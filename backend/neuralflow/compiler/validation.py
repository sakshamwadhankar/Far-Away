"""
backend/neuralflow/compiler/validation.py

Semantic validation for a parsed Pipeline model.

This module enforces the five validation rules from TRD §4 that cannot be
expressed in JSON Schema (which is structural) or Pydantic (which is
field-level). It operates on already-parsed Pipeline objects.

Rules implemented here:
  1. Main graph (excluding loop subgraphs) must be ACYCLIC.
  2. Every edge must connect TYPE-COMPATIBLE ports.
  6. Access nodes are scope markers: no data ports, and every edge touching
     one uses the reserved scope port and carries no payload (schema 2.1).
  (Rules 3, 4, 5 — endpoint_ref resolution, stop_when structure, finite
   max_iterations — are enforced at the Pydantic parse stage in models.py.)

Capability enforcement itself — which node may reach which provider under the
effective access policy — lives in `check_effective_policies` below, and is
driven by the ancestor walk in dag.py.

BREAKING CHANGE: this is a shared contract. Announce before modifying.
No dummy data, no app logic beyond validation.
"""

from __future__ import annotations

from collections import defaultdict, deque

from neuralflow.compiler.models import (
    ACCESS_SCOPE_PORT,
    AccessPolicy,
    Node,
    Pipeline,
    PortType,
)

# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------


class PipelineValidationError(Exception):
    """Base class for all pipeline semantic validation errors."""


class PipelineValidationErrors(PipelineValidationError):
    """Raised when one or more pipeline validation errors occur."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_port_index(nodes: list[Node]) -> dict[str, dict[str, PortType]]:
    """
    Build a mapping: node_id -> {port_name -> port_type} for all output ports.
    Used to look up the type of an edge's source port.
    """
    index: dict[str, dict[str, PortType]] = {}
    for node in nodes:
        index[node.id] = {port.name: port.type for port in node.outputs}
    return index


def _build_input_port_index(nodes: list[Node]) -> dict[str, dict[str, PortType]]:
    """Build mapping: node_id -> {port_name -> port_type} for all INPUT ports."""
    index: dict[str, dict[str, PortType]] = {}
    for node in nodes:
        index[node.id] = {port.name: port.type for port in node.inputs}
    return index


def _build_node_index(nodes: list[Node]) -> dict[str, Node]:
    return {n.id: n for n in nodes}


def _loop_body_edges(pipeline: Pipeline) -> frozenset[tuple[str, str]]:
    """
    Return the set of (from_node, to_node) pairs that are INSIDE loop bodies.
    These edges are excluded from the acyclicity check on the main graph
    (loops are subgraphs, not back-edges — TRD §4 rule 1).
    """
    loop_node_sets: list[frozenset[str]] = [frozenset(lp.body) for lp in pipeline.loops]
    # An edge is a "loop-internal" edge if BOTH endpoints are in the same loop body.
    internal: set[tuple[str, str]] = set()
    for edge in pipeline.edges:
        src = edge.source_node()
        dst = edge.target_node()
        for body in loop_node_sets:
            if src in body and dst in body:
                internal.add((src, dst))
                break
    return frozenset(internal)


# ---------------------------------------------------------------------------
# Rule 1: Acyclicity (Kahn's algorithm — topological sort)
# ---------------------------------------------------------------------------


def _check_acyclic(pipeline: Pipeline, errors: list[str]) -> None:
    """
    Enforce TRD §4 rule 1: main graph must be acyclic.

    Loop subgraph edges (both endpoints within the same loop body) are excluded
    from this check — they form bounded subgraphs, not true back-edges.
    """
    node_ids = {n.id for n in pipeline.nodes}
    loop_internal = _loop_body_edges(pipeline)

    # Build adjacency and in-degree, skipping loop-internal edges.
    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = dict.fromkeys(node_ids, 0)

    for edge in pipeline.edges:
        src = edge.source_node()
        dst = edge.target_node()
        if (src, dst) in loop_internal:
            continue
        if src not in node_ids or dst not in node_ids:
            continue  # Unknown nodes caught separately.
        adjacency[src].append(dst)
        in_degree[dst] += 1

    # Kahn's BFS topological sort.
    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for neighbour in adjacency[current]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)

    if visited != len(node_ids):
        errors.append(
            f"[Graph Cycle] Pipeline '{pipeline.name}' contains a cycle "
            "in the main graph. "
            f"Only {visited} of {len(node_ids)} nodes could be topologically sorted. "
            "Loops must be declared as subgraphs in 'loops[]', not as back-edges."
        )


# ---------------------------------------------------------------------------
# Rule 2: Port-type compatibility
# ---------------------------------------------------------------------------


def _check_port_type_compatibility(pipeline: Pipeline, errors: list[str]) -> None:
    """
    Enforce TRD §4 rule 2: every edge must connect type-compatible ports.

    Two ports are compatible if and only if their types are identical.
    (Implicit type coercion is intentionally not supported — Transform nodes
    exist for that purpose.)
    """
    node_index = _build_node_index(pipeline.nodes)
    output_index = _build_port_index(pipeline.nodes)
    input_index = _build_input_port_index(pipeline.nodes)

    for edge in pipeline.edges:
        src_node_id = edge.source_node()
        src_port_name = edge.source_port()
        dst_node_id = edge.target_node()
        dst_port_name = edge.target_port()

        if src_node_id not in node_index:
            errors.append(
                f"[Unknown Node] Edge '{edge.from_}' -> '{edge.to}': "
                f"source node '{src_node_id}' not found."
            )
            continue
        if dst_node_id not in node_index:
            errors.append(
                f"[Unknown Node] Edge '{edge.from_}' -> '{edge.to}': "
                f"target node '{dst_node_id}' not found."
            )
            continue

        # Scope edges carry no payload, so there is nothing to type-check.
        # Their port names are validated by _check_access_nodes instead.
        if (
            node_index[src_node_id].type == "access"
            or node_index[dst_node_id].type == "access"
        ):
            continue

        src_ports = output_index.get(src_node_id, {})
        if src_port_name not in src_ports:
            errors.append(
                f"[Unknown Port] Edge '{edge.from_}' -> '{edge.to}': "
                f"node '{src_node_id}' has no output port named '{src_port_name}'. "
                f"Available output ports: {list(src_ports.keys()) or '(none)'}."
            )
            continue

        dst_ports = input_index.get(dst_node_id, {})
        if dst_port_name not in dst_ports:
            errors.append(
                f"[Unknown Port] Edge '{edge.from_}' -> '{edge.to}': "
                f"node '{dst_node_id}' has no input port named '{dst_port_name}'. "
                f"Available input ports: {list(dst_ports.keys()) or '(none)'}."
            )
            continue

        src_type = src_ports[src_port_name]
        dst_type = dst_ports[dst_port_name]
        if src_type != dst_type:
            errors.append(
                f"[Port Type Mismatch] Edge '{edge.from_}' -> '{edge.to}': "
                f"source port type '{src_type}' is incompatible with "
                f"target port type '{dst_type}'. "
                "Use a Transform node to convert between types."
            )


# ---------------------------------------------------------------------------
# Rule 3 (additional): Loop body node validation
# ---------------------------------------------------------------------------


def _check_loop_bodies(pipeline: Pipeline, errors: list[str]) -> None:
    """
    Validate that every node ID in every loop's body list exists in the
    pipeline's nodes. Catches typos at compile time.
    """
    node_ids = {n.id for n in pipeline.nodes}
    for loop in pipeline.loops:
        for body_node_id in loop.body:
            if body_node_id not in node_ids:
                errors.append(
                    f"[Invalid Loop Body] Loop '{loop.id}' references "
                    f"node '{body_node_id}' "
                    f"in its body, but no node with that ID exists. "
                    f"Available node IDs: {sorted(node_ids)}."
                )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Rule 6: Access nodes are scope markers
# ---------------------------------------------------------------------------


def _check_access_nodes(pipeline: Pipeline, errors: list[str]) -> None:
    """
    An access node grants capabilities to the part of the graph downstream of
    it. It is not a transform: nothing flows through it, so every edge that
    touches one must use the reserved scope port.

    (The "no data ports" and "must have a policy" rules are enforced earlier,
    at the Pydantic parse stage in models.Node.)
    """
    access_ids = {n.id for n in pipeline.nodes if n.type == "access"}
    if not access_ids:
        return

    connected: set[str] = set()

    for edge in pipeline.edges:
        for node_id, port_name, side in (
            (edge.source_node(), edge.source_port(), "from"),
            (edge.target_node(), edge.target_port(), "to"),
        ):
            if node_id not in access_ids:
                continue
            connected.add(node_id)
            if port_name != ACCESS_SCOPE_PORT:
                errors.append(
                    f"[Invalid Access Edge] Edge '{edge.from_}' -> '{edge.to}': "
                    f"access node '{node_id}' carries no data, so its '{side}' "
                    f"endpoint must be '{node_id}.{ACCESS_SCOPE_PORT}', "
                    f"not '{node_id}.{port_name}'."
                )

    for node_id in sorted(access_ids - connected):
        errors.append(
            f"[Orphan Access Node] Access node '{node_id}' governs nothing: "
            "connect it to the nodes whose capabilities it should limit, or "
            "remove it."
        )


# ---------------------------------------------------------------------------
# Capability enforcement (driven by dag.compute_effective_policies)
# ---------------------------------------------------------------------------


def check_effective_policies(
    pipeline: Pipeline,
    policies: dict[str, AccessPolicy],
    denied_by: dict[str, dict[str, str]],
) -> None:
    """
    Fail compilation when a node requests a capability its effective policy
    does not grant.

    `policies` maps node_id → effective AccessPolicy, and `denied_by` maps
    node_id → {capability: access_node_id}, naming which access node is
    responsible for each missing capability so the message can point at it.

    Raises PipelineValidationErrors listing every violation.
    """
    errors: list[str] = []
    endpoints = pipeline.endpoints

    for node in pipeline.nodes:
        if node.type != "model" or node.endpoint_ref is None:
            continue

        descriptor = endpoints.get(node.endpoint_ref)
        if descriptor is None:
            # Already reported by the Pydantic endpoint_ref resolution rule.
            continue

        policy = policies[node.id]
        kind = descriptor.kind

        if kind == "ollama":
            if not policy.allow_local_models:
                gate = denied_by.get(node.id, {}).get("allow_local_models", "?")
                errors.append(
                    f"[Access Denied] Node '{node.id}' (model:{kind}) requires "
                    f"local models, denied by access node '{gate}' which does "
                    "not grant 'allow_local_models'."
                )
            continue

        if kind not in policy.providers:
            gate = denied_by.get(node.id, {}).get(f"provider:{kind}", "?")
            granted = ", ".join(policy.providers) if policy.providers else "(none)"
            errors.append(
                f"[Access Denied] Node '{node.id}' (model:{kind}) requires "
                f"provider '{kind}', denied by access node '{gate}' which "
                f"grants: [{granted}]."
            )

    if errors:
        raise PipelineValidationErrors(errors)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_pipeline(pipeline: Pipeline) -> None:
    """
    Run all semantic validation rules on a parsed Pipeline.

    Raises PipelineValidationErrors on rule violation.
    Pydantic structural validation (field types, required fields, endpoint_ref
    resolution) must have already passed before calling this function.

    Rules:
      1. Main graph is acyclic.
      2. All edge port types are compatible.
      3. All loop body node IDs exist in the pipeline.
      6. Access nodes are wired as scope markers.

    Capability enforcement is NOT run here — it needs the ancestor walk, so
    compile() calls check_effective_policies after building adjacency.
    """
    errors: list[str] = []
    _check_acyclic(pipeline, errors)
    _check_port_type_compatibility(pipeline, errors)
    _check_loop_bodies(pipeline, errors)
    _check_access_nodes(pipeline, errors)

    if errors:
        raise PipelineValidationErrors(errors)
