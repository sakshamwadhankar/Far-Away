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
from typing import Any

from pydantic import ValidationError

from neuralflow.compiler.models import Loop, Pipeline, PortType
from neuralflow.compiler.validation import (
    PipelineValidationErrors,
    _loop_body_edges,
    validate_pipeline,
)

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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compile(raw_json: dict[str, Any]) -> CompiledDAG:
    """
    Compile a raw pipeline JSON dict into a validated, executable DAG.

    Steps:
      1. Parse via Pydantic → enforces structural rules (3, 4, 5).
      2. Run semantic validation → enforces rules (1, 2) plus loop body checks.
      3. Compute topological order, adjacency, loop maps, port registry.
      4. Return frozen CompiledDAG.

    Raises:
        PipelineValidationErrors  — structural or semantic issues
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

    # Step 4: Return frozen DAG
    return CompiledDAG(
        pipeline=pipeline,
        topo_order=topo_order,
        adjacency=forward_adj,
        reverse_adj=reverse_adj,
        loop_map=loop_map,
        node_to_loop=node_to_loop,
        port_registry=port_registry,
    )
