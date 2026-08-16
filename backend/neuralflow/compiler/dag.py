"""
backend/neuralflow/compiler/dag.py

Pipeline compiler: raw JSON → typed, validated CompiledDAG.

This module is the single gate between a pipeline document and the scheduler.
It enforces ALL five TRD §4 validation rules:
  1. Acyclicity (excluding loop subgraphs)  — via validation.validate_pipeline
  2. Port-type compatibility                — via validation.validate_pipeline
  3. endpoint_ref resolution                — via Pydantic model_validator
  4. Structured stop_when (no eval)         — via Pydantic StopCondition model
  5. Finite max_iterations + on_max policy  — via Pydantic Loop model

BREAKING CHANGE: CompiledDAG is a shared contract consumed by the scheduler.
Announce before modifying its fields.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from neuralflow.compiler.models import (
    ENDPOINT_KINDS,
    AccessPolicy,
    Loop,
    Node,
    Pipeline,
    PortType,
)
from neuralflow.compiler.validation import (
    PipelineValidationError,
    PipelineValidationErrors,
    _loop_body_edges,
    check_effective_policies,
    validate_pipeline,
)

#: Compile modes.
#:
#: "local"  — a canvas run. A pipeline with no access node is permissive, which
#:            is what keeps every pre-2.1 pipeline working unchanged.
#: "served" — the pipeline is about to be reachable over HTTP (Phase 3). An
#:            explicit access policy is mandatory; "what can this thing touch"
#:            stops being an inspector and becomes a security boundary.
CompileMode = Literal["local", "served"]

# ---------------------------------------------------------------------------
# CompiledDAG — the compiler's output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledDAG:
    """
    Immutable output of the pipeline compiler.

    Contains everything the scheduler needs to execute the pipeline:
    the validated model, topological order, adjacency structures,
    loop metadata, and a port-type registry.
    """

    pipeline: Pipeline
    """Fully validated Pydantic Pipeline model."""

    topo_order: list[str]
    """
    Topological order of node IDs in the main graph.
    Loop-body-internal edges are excluded from the sort so that
    loop bodies don't create false cycles.
    """

    adjacency: dict[str, list[str]]
    """Forward adjacency: node_id → [successor node IDs]."""

    reverse_adj: dict[str, list[str]]
    """Reverse adjacency: node_id → [predecessor node IDs]."""

    loop_map: dict[str, Loop]
    """loop_id → Loop for quick lookup."""

    node_to_loop: dict[str, str]
    """node_id → loop_id for every node that is inside a loop body."""

    port_registry: dict[str, PortType]
    """
    Flattened port registry: "nodeId.portName" → PortType.
    Includes both input and output ports.
    """

    effective_policies: dict[str, AccessPolicy]
    """
    node_id → the AccessPolicy actually in force for that node.

    The intersection of every access node upstream of it, or the permissive
    policy when none governs it. Every node in the pipeline has an entry,
    including the access nodes themselves.
    """

    policy_sources: dict[str, tuple[str, ...]]
    """
    node_id → IDs of the access nodes whose policies were intersected to
    produce its effective policy, in topological order. Empty when the node is
    ungoverned.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_topo_order(pipeline: Pipeline) -> list[str]:
    """
    Compute topological order via Kahn's algorithm.

    Loop-internal edges (both endpoints in the same loop body) are excluded
    so that loop subgraphs don't prevent the sort. This mirrors the logic
    in validation._check_acyclic but returns the sorted order instead of
    just checking for cycles.

    Pre-condition: validate_pipeline() has already confirmed acyclicity.
    """
    node_ids = {n.id for n in pipeline.nodes}
    loop_internal = _loop_body_edges(pipeline)

    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = dict.fromkeys(node_ids, 0)

    for edge in pipeline.edges:
        src = edge.source_node()
        dst = edge.target_node()
        if (src, dst) in loop_internal:
            continue
        if src not in node_ids or dst not in node_ids:
            continue
        adjacency[src].append(dst)
        in_degree[dst] += 1

    queue: deque[str] = deque(sorted(nid for nid, deg in in_degree.items() if deg == 0))
    order: list[str] = []

    while queue:
        current = queue.popleft()
        order.append(current)
        for neighbour in sorted(adjacency[current]):
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)

    return order


def _build_adjacency(
    pipeline: Pipeline,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build forward and reverse adjacency from all edges (including loop-internal)."""
    forward: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)

    for edge in pipeline.edges:
        src = edge.source_node()
        dst = edge.target_node()
        forward[src].append(dst)
        reverse[dst].append(src)

    return dict(forward), dict(reverse)


def _build_loop_maps(
    pipeline: Pipeline,
) -> tuple[dict[str, Loop], dict[str, str]]:
    """Build loop_id → Loop and node_id → loop_id maps."""
    loop_map: dict[str, Loop] = {}
    node_to_loop: dict[str, str] = {}

    for lp in pipeline.loops:
        loop_map[lp.id] = lp
        for node_id in lp.body:
            node_to_loop[node_id] = lp.id

    return loop_map, node_to_loop


def _build_port_registry(pipeline: Pipeline) -> dict[str, PortType]:
    """
    Build a flat "nodeId.portName" → PortType registry
    covering both input and output ports.
    """
    registry: dict[str, PortType] = {}
    for node in pipeline.nodes:
        for port in node.inputs:
            registry[f"{node.id}.{port.name}"] = port.type
        for port in node.outputs:
            registry[f"{node.id}.{port.name}"] = port.type
    return registry


def compute_effective_policies(
    pipeline: Pipeline,
    topo_order: list[str],
    reverse_adj: dict[str, list[str]],
) -> tuple[dict[str, AccessPolicy], dict[str, tuple[str, ...]]]:
    """
    Work out which AccessPolicy is actually in force for every node.

    An access node applies its policy to every node downstream of it. A node's
    governing set is therefore every access node among its ancestors, and its
    effective policy is the INTERSECTION of their policies — the most
    restrictive wins, never the union. Moving a node further downstream can
    only ever take capabilities away.

    Implemented as a single sweep in topological order: a node inherits the
    union of its predecessors' governing sets, plus the predecessor itself when
    that predecessor is an access node. Because predecessors are always visited
    first, one pass is enough.

    Returns (effective_policies, policy_sources). A node governed by nothing
    gets AccessPolicy.permissive() and an empty source tuple.

    See backend/neuralflow/compiler/README.md for the rule and its rationale.
    """
    nodes = {n.id: n for n in pipeline.nodes}
    # Access nodes in topological order, so intersections and error messages
    # are deterministic.
    rank = {node_id: i for i, node_id in enumerate(topo_order)}

    governing: dict[str, set[str]] = {n.id: set() for n in pipeline.nodes}

    for node_id in topo_order:
        inherited: set[str] = set()
        for pred_id in reverse_adj.get(node_id, []):
            inherited |= governing.get(pred_id, set())
            if nodes[pred_id].type == "access":
                inherited.add(pred_id)
        governing[node_id] = inherited

    policies: dict[str, AccessPolicy] = {}
    sources: dict[str, tuple[str, ...]] = {}

    for node_id, gate_ids in governing.items():
        ordered = tuple(sorted(gate_ids, key=lambda g: rank.get(g, 0)))
        sources[node_id] = ordered

        if not ordered:
            policies[node_id] = AccessPolicy.permissive()
            continue

        effective = _policy_of(nodes[ordered[0]])
        for gate_id in ordered[1:]:
            effective = effective.intersect(_policy_of(nodes[gate_id]))
        policies[node_id] = effective

    return policies, sources


def _policy_of(access_node: Node) -> AccessPolicy:
    """Read the policy off an access node. Presence is guaranteed by models.Node."""
    config = access_node.config
    if config is None or config.access_policy is None:  # pragma: no cover
        raise PipelineValidationError(
            f"[Missing Access Policy] Access node '{access_node.id}' has no policy."
        )
    return config.access_policy


def _attribute_denials(
    pipeline: Pipeline,
    sources: dict[str, tuple[str, ...]],
    nodes: dict[str, Node],
) -> dict[str, dict[str, str]]:
    """
    For each node, name the access node responsible for each missing capability.

    The effective policy says *what* is denied; this says *who* denied it, so
    the compiler error can point the user at the node to edit. When several
    gates deny the same capability the earliest one in topological order is
    reported — that is the outermost scope, and widening it is the first thing
    the user would have to do.
    """
    denied: dict[str, dict[str, str]] = {}

    for node_id, gate_ids in sources.items():
        if not gate_ids:
            continue
        reasons: dict[str, str] = {}
        for gate_id in gate_ids:
            policy = _policy_of(nodes[gate_id])
            if not policy.allow_local_models:
                reasons.setdefault("allow_local_models", gate_id)
            if not policy.allow_network:
                reasons.setdefault("allow_network", gate_id)
            for kind in ENDPOINT_KINDS:
                if kind not in policy.providers:
                    reasons.setdefault(f"provider:{kind}", gate_id)
        denied[node_id] = reasons

    return denied


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compile(raw_json: dict[str, Any], mode: CompileMode = "local") -> CompiledDAG:
    """
    Compile a raw pipeline JSON dict into a validated, executable DAG.

    Steps:
      1. Parse via Pydantic → enforces structural rules (3, 4, 5).
      2. Run semantic validation → enforces rules (1, 2, 6) plus loop bodies.
      3. Compute topological order, adjacency, loop maps, port registry.
      4. Compute the effective access policy for every node and reject any
         node that reaches for a capability it was not granted.
      5. Return frozen CompiledDAG.

    Args:
        raw_json: the pipeline document.
        mode: "local" for a canvas run — a pipeline with no access node is
            permissive, so every pre-2.1 pipeline keeps working. "served" for
            a pipeline about to be exposed over HTTP, where an explicit access
            policy is mandatory.

    Raises:
        PipelineValidationErrors  — structural, semantic, or access issues
    """
    # Step 1: Parse and structurally validate
    try:
        pipeline = Pipeline.model_validate(raw_json)
    except ValidationError as e:
        errors: list[str] = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            msg = err["msg"]
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, ") :]
            errors.append(f"[Structural] Field '{loc}': {msg}")
        raise PipelineValidationErrors(errors) from e

    # Step 2: Semantic validation (acyclicity, port compatibility, loop bodies)
    # This will raise PipelineValidationErrors if any rules are violated.
    validate_pipeline(pipeline)

    # Step 3: Build execution metadata
    topo_order = _compute_topo_order(pipeline)
    forward_adj, reverse_adj = _build_adjacency(pipeline)
    loop_map, node_to_loop = _build_loop_maps(pipeline)
    port_registry = _build_port_registry(pipeline)

    # Step 4: Access control
    has_access_node = any(n.type == "access" for n in pipeline.nodes)

    if mode == "served" and not has_access_node:
        raise PipelineValidationErrors(
            [
                "[Access Required] This pipeline has no access node, so there "
                "is no statement of what it is allowed to reach. Deploying it "
                "would expose an unbounded capability set over HTTP. Add an "
                "access node and connect it to the nodes it should govern."
            ]
        )

    policies, sources = compute_effective_policies(pipeline, topo_order, reverse_adj)
    if has_access_node:
        nodes_by_id = {n.id: n for n in pipeline.nodes}
        check_effective_policies(
            pipeline, policies, _attribute_denials(pipeline, sources, nodes_by_id)
        )

    # Step 5: Return frozen DAG
    return CompiledDAG(
        pipeline=pipeline,
        topo_order=topo_order,
        adjacency=forward_adj,
        reverse_adj=reverse_adj,
        loop_map=loop_map,
        node_to_loop=node_to_loop,
        port_registry=port_registry,
        effective_policies=policies,
        policy_sources=sources,
    )
