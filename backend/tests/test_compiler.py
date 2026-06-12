"""
backend/tests/test_compiler.py

Phase 2 — Tests for the pipeline compiler DAG builder.

Tests:
  1. Valid pipeline compiles into a CompiledDAG with correct structure.
  2. Topo order respects edge dependencies.
  3. Cyclic pipeline rejected at compile time.
  4. Type-mismatch edge rejected at compile time.
  5. Bad loop body (nonexistent node) rejected at compile time.

Run with:
    pytest backend/tests/test_compiler.py -v

No live services, no API keys. Uses only inline pipeline fixtures.
"""

from __future__ import annotations

from typing import Any

import pytest

from neuralflow.compiler.dag import CompiledDAG, compile
from neuralflow.compiler.validation import (
    CyclicGraphError,
    InvalidLoopBodyError,
    PortTypeMismatchError,
)


# ---------------------------------------------------------------------------
# Fixtures — inline pipeline documents
# ---------------------------------------------------------------------------


VALID_LINEAR: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000010",
    "name": "Linear Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "solver",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "config": {"temperature": 0.7, "max_tokens": 2048},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
    ],
    "edges": [
        {"from": "in.prompt", "to": "solver.input"},
        {"from": "solver.output", "to": "out.result"},
    ],
    "endpoints": {
        "cloud:gpt-4o": {"kind": "openai", "model": "gpt-4o"},
    },
}


VALID_WITH_LOOP: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000011",
    "name": "Pipeline with Loop",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "solver",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "config": {"temperature": 0.7},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "verify",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "config": {"temperature": 0.2, "response_format": "json"},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "json"}],
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
    ],
    "loops": [
        {
            "id": "refine",
            "body": ["solver", "verify"],
            "max_iterations": 5,
            "stop_when": {
                "field": "verify.output.verified",
                "op": "==",
                "value": True,
            },
            "on_max": "return_best",
        }
    ],
    "edges": [
        {"from": "in.prompt", "to": "solver.input"},
        {"from": "solver.output", "to": "verify.input"},
        {"from": "solver.output", "to": "out.result"},
    ],
    "endpoints": {
        "cloud:gpt-4o": {"kind": "openai", "model": "gpt-4o"},
    },
}


INVALID_CYCLIC: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000012",
    "name": "Cyclic Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "a",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "b",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
    ],
    "edges": [
        {"from": "a.output", "to": "b.input"},
        {"from": "b.output", "to": "a.input"},  # back-edge
    ],
    "endpoints": {
        "cloud:gpt-4o": {"kind": "openai", "model": "gpt-4o"},
    },
}


INVALID_TYPE_MISMATCH: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000013",
    "name": "Type Mismatch",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "src",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "json"}],
        },
        {
            "id": "dst",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "score", "type": "number"}],
            "outputs": [{"name": "result", "type": "text"}],
        },
    ],
    "edges": [
        {"from": "src.output", "to": "dst.score"},  # json → number
    ],
    "endpoints": {
        "cloud:gpt-4o": {"kind": "openai", "model": "gpt-4o"},
    },
}


INVALID_LOOP_BODY: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000014",
    "name": "Bad Loop Body",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "solver",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
    ],
    "loops": [
        {
            "id": "broken",
            "body": ["solver", "nonexistent_node"],  # typo!
            "max_iterations": 3,
            "stop_when": {
                "field": "solver.output.done",
                "op": "==",
                "value": True,
            },
            "on_max": "return_last",
        }
    ],
    "edges": [
        {"from": "in.prompt", "to": "solver.input"},
    ],
    "endpoints": {
        "cloud:gpt-4o": {"kind": "openai", "model": "gpt-4o"},
    },
}


# ---------------------------------------------------------------------------
# Test 1: Valid pipeline compiles into CompiledDAG
# ---------------------------------------------------------------------------


def test_compile_valid_linear_pipeline() -> None:
    """Linear in→solver→out compiles into a CompiledDAG with 3 nodes."""
    dag = compile(VALID_LINEAR)

    assert isinstance(dag, CompiledDAG)
    assert dag.pipeline.name == "Linear Pipeline"
    assert len(dag.topo_order) == 3
    assert set(dag.topo_order) == {"in", "solver", "out"}
    assert dag.loop_map == {}
    assert dag.node_to_loop == {}


def test_compile_valid_pipeline_with_loop() -> None:
    """Pipeline with a loop compiles successfully, with loop metadata."""
    dag = compile(VALID_WITH_LOOP)

    assert isinstance(dag, CompiledDAG)
    assert "refine" in dag.loop_map
    assert dag.node_to_loop["solver"] == "refine"
    assert dag.node_to_loop["verify"] == "refine"
    assert "in" not in dag.node_to_loop
    assert "out" not in dag.node_to_loop


# ---------------------------------------------------------------------------
# Test 2: Topo order respects edge dependencies
# ---------------------------------------------------------------------------


def test_topo_order_respects_edges() -> None:
    """Predecessors must appear before successors in topo_order."""
    dag = compile(VALID_LINEAR)

    idx = {nid: i for i, nid in enumerate(dag.topo_order)}
    # in → solver → out
    assert idx["in"] < idx["solver"]
    assert idx["solver"] < idx["out"]


# ---------------------------------------------------------------------------
# Test 3: Cyclic pipeline rejected
# ---------------------------------------------------------------------------


def test_compile_rejects_cycle() -> None:
    """compile() raises CyclicGraphError for a graph with a back-edge."""
    with pytest.raises(CyclicGraphError):
        compile(INVALID_CYCLIC)


# ---------------------------------------------------------------------------
# Test 4: Type-mismatch edge rejected
# ---------------------------------------------------------------------------


def test_compile_rejects_type_mismatch() -> None:
    """compile() raises PortTypeMismatchError for json→number edge."""
    with pytest.raises(PortTypeMismatchError):
        compile(INVALID_TYPE_MISMATCH)


# ---------------------------------------------------------------------------
# Test 5: Bad loop body rejected
# ---------------------------------------------------------------------------


def test_compile_rejects_bad_loop_body() -> None:
    """compile() raises InvalidLoopBodyError for nonexistent node in body."""
    with pytest.raises(InvalidLoopBodyError, match="nonexistent_node"):
        compile(INVALID_LOOP_BODY)


# ---------------------------------------------------------------------------
# Test 6: Port registry is correctly built
# ---------------------------------------------------------------------------


def test_port_registry_contains_all_ports() -> None:
    """Port registry must have entries for every declared port."""
    dag = compile(VALID_LINEAR)

    assert dag.port_registry["in.prompt"] == "text"
    assert dag.port_registry["solver.input"] == "text"
    assert dag.port_registry["solver.output"] == "text"
    assert dag.port_registry["out.result"] == "text"


# ---------------------------------------------------------------------------
# Test 7: Adjacency is correctly built
# ---------------------------------------------------------------------------


def test_adjacency_reflects_edges() -> None:
    """Forward adjacency must reflect the edge definitions."""
    dag = compile(VALID_LINEAR)

    assert "solver" in dag.adjacency.get("in", [])
    assert "out" in dag.adjacency.get("solver", [])
    assert "in" in dag.reverse_adj.get("solver", [])
    assert "solver" in dag.reverse_adj.get("out", [])
