"""
backend/tests/test_schema.py

Phase 1 — P1 tests for pipeline schema v2.

Tests:
  1. A valid Solver→Verifier→Judge pipeline loads against pipeline.schema.json
     AND parses into the Pydantic Pipeline model without errors.
  2. A pipeline with a cyclic edge is rejected by the compiler's cycle check.
  3. A pipeline with a type-mismatched edge (json → number) is rejected.

Run with:
    pytest backend/tests/test_schema.py -v

No live services, no API keys, no dummy data in production code.
MockEndpoint lives in tests only (AGENT.md rule 1).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from neuralflow.compiler.models import Pipeline
from neuralflow.compiler.validation import (
    CyclicGraphError,
    PortTypeMismatchError,
    validate_pipeline,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_repo_root() -> pathlib.Path:
    current = pathlib.Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "shared" / "pipeline.schema.json").exists():
            return parent
    raise RuntimeError("Could not find repository root containing shared/pipeline.schema.json")

SCHEMA_PATH = _get_repo_root() / "shared" / "pipeline.schema.json"

def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _assert_json_schema_valid(data: dict[str, Any]) -> None:
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    assert errors == [], f"JSON Schema errors: {[e.message for e in errors]}"


def _assert_json_schema_invalid(data: dict[str, Any]) -> None:
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(data))
    assert errors != [], "Expected JSON Schema validation to fail, but it passed."


# ---------------------------------------------------------------------------
# Fixtures — inline pipeline documents (no secrets, no dummy production data)
# ---------------------------------------------------------------------------

VALID_SOLVER_VERIFIER_JUDGE: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000001",
    "name": "Solver → Verifier → Judge",
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
            "role": "solver",
            "config": {"temperature": 0.7, "max_tokens": 2048},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "verifier",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "role": "verifier",
            "config": {"temperature": 0.2, "response_format": "json"},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "json"}],
        },
        {
            "id": "judge",
            "type": "judge",
            "inputs": [
                {"name": "candidate", "type": "text"},
                {"name": "verdict", "type": "json"},
            ],
            "outputs": [{"name": "output", "type": "text"}],
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
            "body": ["solver", "verifier"],
            "max_iterations": 5,
            "stop_when": {"field": "verifier.output.verified", "op": "==", "value": True},
            "on_max": "return_best",
        }
    ],
    "edges": [
        {"from": "in.prompt", "to": "solver.input"},
        {"from": "solver.output", "to": "verifier.input"},
        {"from": "solver.output", "to": "judge.candidate"},
        {"from": "verifier.output", "to": "judge.verdict"},
        {"from": "judge.output", "to": "out.result"},
    ],
    "endpoints": {
        "cloud:gpt-4o": {"kind": "openai", "model": "gpt-4o"},
    },
}

# Cyclic: solver → verifier → solver (back-edge)
INVALID_CYCLIC: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000002",
    "name": "Cyclic Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "solver",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "verifier",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
    ],
    "edges": [
        {"from": "solver.output", "to": "verifier.input"},
        # back-edge: creates a cycle
        {"from": "verifier.output", "to": "solver.input"},
    ],
    "endpoints": {
        "cloud:gpt-4o": {"kind": "openai", "model": "gpt-4o"},
    },
}

# Type mismatch: solver outputs json but verifier expects number
INVALID_TYPE_MISMATCH: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000003",
    "name": "Type-Mismatch Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "solver",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "json"}],  # produces json
        },
        {
            "id": "consumer",
            "type": "model",
            "endpoint_ref": "cloud:gpt-4o",
            "inputs": [{"name": "score", "type": "number"}],  # expects number — mismatch!
            "outputs": [{"name": "result", "type": "text"}],
        },
    ],
    "edges": [
        {"from": "solver.output", "to": "consumer.score"},  # json → number: invalid
    ],
    "endpoints": {
        "cloud:gpt-4o": {"kind": "openai", "model": "gpt-4o"},
    },
}


# ---------------------------------------------------------------------------
# Test 1 — Valid pipeline loads against JSON Schema and Pydantic model
# ---------------------------------------------------------------------------


def test_valid_pipeline_passes_json_schema() -> None:
    """Valid Solver→Verifier→Judge pipeline must satisfy the JSON Schema."""
    _assert_json_schema_valid(VALID_SOLVER_VERIFIER_JUDGE)


def test_valid_pipeline_parses_into_pydantic() -> None:
    """Valid pipeline must parse into Pipeline without ValidationError."""
    pipeline = Pipeline.model_validate(VALID_SOLVER_VERIFIER_JUDGE)
    assert pipeline.schema_version == "2.0"
    assert pipeline.name == "Solver → Verifier → Judge"
    assert len(pipeline.nodes) == 5
    assert len(pipeline.loops) == 1
    assert len(pipeline.edges) == 5
    assert pipeline.loops[0].max_iterations == 5
    assert pipeline.loops[0].stop_when.op == "=="


def test_valid_pipeline_endpoint_refs_resolve() -> None:
    """All endpoint_refs in the valid pipeline must resolve in the endpoints map."""
    pipeline = Pipeline.model_validate(VALID_SOLVER_VERIFIER_JUDGE)
    endpoint_keys = set(pipeline.endpoints.keys())
    for node in pipeline.nodes:
        if node.endpoint_ref is not None:
            assert node.endpoint_ref in endpoint_keys, (
                f"Node '{node.id}' endpoint_ref '{node.endpoint_ref}' not in endpoints map."
            )


# ---------------------------------------------------------------------------
# Test 2 — Cyclic pipeline is rejected
# ---------------------------------------------------------------------------


def test_cyclic_pipeline_fails_json_schema() -> None:
    """Cyclic pipeline must still be structurally valid JSON Schema — cycles are a semantic error."""
    # JSON Schema cannot detect cycles; this confirms the document is otherwise valid.
    # The cycle is caught by validate_pipeline() (compiler), tested below.
    _assert_json_schema_valid(INVALID_CYCLIC)


def test_cyclic_pipeline_rejected_by_compiler() -> None:
    """validate_pipeline() must raise CyclicGraphError for a graph with a back-edge."""
    pipeline = Pipeline.model_validate(INVALID_CYCLIC)
    with pytest.raises(CyclicGraphError):
        validate_pipeline(pipeline)


# ---------------------------------------------------------------------------
# Test 3 — Type-mismatch edge is rejected
# ---------------------------------------------------------------------------


def test_type_mismatch_pipeline_fails_json_schema() -> None:
    """Type-mismatch pipeline must also be structurally valid JSON Schema — port types are semantic."""
    _assert_json_schema_valid(INVALID_TYPE_MISMATCH)


def test_type_mismatch_rejected_by_compiler() -> None:
    """validate_pipeline() must raise PortTypeMismatchError for json→number edge."""
    pipeline = Pipeline.model_validate(INVALID_TYPE_MISMATCH)
    with pytest.raises(PortTypeMismatchError):
        validate_pipeline(pipeline)


# ---------------------------------------------------------------------------
# Test 4 — Pydantic rejects structurally invalid documents
# ---------------------------------------------------------------------------


def test_missing_schema_version_rejected() -> None:
    bad = dict(VALID_SOLVER_VERIFIER_JUDGE)
    del bad["schema_version"]
    with pytest.raises(ValidationError):
        Pipeline.model_validate(bad)


def test_wrong_schema_version_rejected() -> None:
    bad = {**VALID_SOLVER_VERIFIER_JUDGE, "schema_version": "1.0"}
    with pytest.raises(ValidationError):
        Pipeline.model_validate(bad)


def test_model_node_without_endpoint_ref_rejected() -> None:
    bad = dict(VALID_SOLVER_VERIFIER_JUDGE)
    bad_nodes = [
        {**n, "endpoint_ref": None} if n["type"] == "model" else n
        for n in bad["nodes"]
    ]
    # Remove endpoint_ref key entirely from model nodes
    cleaned = []
    for n in bad_nodes:
        nc = dict(n)
        if nc.get("type") == "model":
            nc.pop("endpoint_ref", None)
        cleaned.append(nc)
    bad["nodes"] = cleaned
    with pytest.raises(ValidationError):
        Pipeline.model_validate(bad)


def test_unresolved_endpoint_ref_rejected() -> None:
    bad = dict(VALID_SOLVER_VERIFIER_JUDGE)
    bad["endpoints"] = {}  # wipe endpoints map
    with pytest.raises(ValidationError):
        Pipeline.model_validate(bad)


def test_loop_max_iterations_zero_rejected() -> None:
    bad = dict(VALID_SOLVER_VERIFIER_JUDGE)
    bad["loops"] = [{**VALID_SOLVER_VERIFIER_JUDGE["loops"][0], "max_iterations": 0}]
    with pytest.raises(ValidationError):
        Pipeline.model_validate(bad)
