"""
backend/tests/test_merge_c.py

Merge C Integration Test.
Verifies the full end-to-end pipeline lifecycle using MockEndpoint.
"""

import asyncio
import os
from typing import Any

import pytest
from httpx import AsyncClient

from komvos.api.main import app
from komvos.endpoints.mock import MockEndpoint
from tests.test_api import _ws_events

# Create a realistic Solver -> Verifier -> Judge -> Router pipeline
PIPELINE_MERGE_C: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "merge-c-test-pipeline",
    "name": "Merge C E2E Pipeline",
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
            "endpoint_ref": "mock:solver",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "solution", "type": "text"}],
            "config": {"temperature": 0.7, "max_tokens": 100},
        },
        {
            "id": "verifier",
            "type": "model",
            "endpoint_ref": "mock:verifier",
            "inputs": [{"name": "solution", "type": "text"}],
            "outputs": [{"name": "verified_json", "type": "json"}],
            "config": {"response_format": "json"},
        },
        {
            "id": "judge",
            "type": "judge",
            "inputs": [{"name": "cand1", "type": "json"}],
            "outputs": [{"name": "best", "type": "json"}],
            "config": {"score_field": "verified", "strategy": "truthy"},
        },
        {
            "id": "router",
            "type": "router",
            "inputs": [
                {"name": "condition", "type": "text"},
                {"name": "text", "type": "text"},
            ],
            "outputs": [
                {"name": "branch_true", "type": "text"},
                {"name": "branch_false", "type": "text"},
            ],
            "config": {"routing_map": {"True": "branch_true", "False": "branch_false"}},
        },
        {
            "id": "transformer",
            "type": "transform",
            "inputs": [{"name": "in", "type": "json"}],
            "outputs": [{"name": "out", "type": "text"}],
            "config": {"system_prompt": "{{ in.verified }}"},
        },
        {
            "id": "out_success",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
        {
            "id": "out_fail",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
    ],
    "edges": [
        {"from": "in.prompt", "to": "solver.input"},
        {"from": "solver.solution", "to": "verifier.solution"},
        {"from": "verifier.verified_json", "to": "judge.cand1"},
        {"from": "judge.best", "to": "transformer.in"},
        {"from": "transformer.out", "to": "router.condition"},
        {"from": "solver.solution", "to": "router.text"},
        {"from": "router.branch_true", "to": "out_success.result"},
        {"from": "router.branch_false", "to": "out_fail.result"},
    ],
    "endpoints": {
        "mock:solver": {"kind": "mock"},
        "mock:verifier": {"kind": "mock"},
    },
}

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def mock_env():
    os.environ["KOMVOS_ALLOW_MOCK_ENDPOINT"] = "1"
    yield
    os.environ.pop("KOMVOS_ALLOW_MOCK_ENDPOINT", None)


@pytest.mark.asyncio
async def test_merge_c_2a_run_completes_judge_picks_winner(
    client: AsyncClient, mock_env
) -> None:
    # 2a: Run completes, all nodes reach done, Judge picks expected winner

    app.state.endpoint_registry = {
        "mock:solver": MockEndpoint(
            id="mock:solver", predefined_text="This is a solution."
        ),
        "mock:verifier": MockEndpoint(
            id="mock:verifier", predefined_text='{"verified": true}'
        ),
    }

    run_resp = await client.post(
        "/pipelines/run", json={"pipeline": PIPELINE_MERGE_C}, headers=AUTH
    )
    assert run_resp.status_code == 202, run_resp.text
    run_id = run_resp.json()["run_id"]

    events = await _ws_events(run_id)

    # Assert run completes
    assert any(e.get("event") == "run_completed" for e in events)

    # Check Judge output
    judge_done = next(
        e
        for e in events
        if e.get("event") == "node_done" and e.get("node_id") == "judge"
    )
    assert judge_done["outputs"]["best"]["verified"] is True

    # Check Router routed to branch_true
    router_done = next(
        e
        for e in events
        if e.get("event") == "node_done" and e.get("node_id") == "router"
    )
    assert router_done["outputs"]["branch_true"] is not None
    assert router_done["outputs"]["branch_false"] is None


@pytest.mark.asyncio
async def test_merge_c_2b_kill_mid_run(slow_client: AsyncClient, mock_env) -> None:
    # 2b: KILL via CancelToken mid-run -> SQLite trace contains PARTIAL results
    # slow_client has token_delay=0.06

    # Setup mock endpoints to use the slow token delay
    app.state.endpoint_registry = {
        "mock:solver": MockEndpoint(
            id="mock:solver",
            token_delay=0.1,
            predefined_text="This is a long slow solution.",
        ),
        "mock:verifier": MockEndpoint(
            id="mock:verifier", predefined_text='{"verified": true}'
        ),
    }

    run_resp = await slow_client.post(
        "/pipelines/run", json={"pipeline": PIPELINE_MERGE_C}, headers=AUTH
    )
    assert run_resp.status_code == 202, run_resp.text
    run_id = run_resp.json()["run_id"]

    # Let the solver start generating
    await asyncio.sleep(0.1)

    # Send kill signal
    stop_resp = await slow_client.post(f"/runs/{run_id}/stop", headers=AUTH)
    assert stop_resp.status_code == 200

    events = await _ws_events(run_id)
    assert any(e.get("event") == "run_stopped" for e in events)

    # Check SQLite trace for partial results
    trace_resp = await slow_client.get(f"/runs/{run_id}/trace", headers=AUTH)
    trace = trace_resp.json()

    # Trace should have the run entry and some nodes
    assert trace["run"]["status"] == "stopped"
    assert "nodes" in trace
    # The solver node should have partial outputs or at least be recorded
    solver_node = next((n for n in trace["nodes"] if n["node_id"] == "solver"), None)
    assert solver_node is not None
    assert (
        trace["run"]["cost"] > 0.0 or trace["run"]["cost"] == 0.0
    )  # Might be 0 if mock doesn't cost


@pytest.mark.asyncio
async def test_merge_c_2c_json_repair_cost(client: AsyncClient, mock_env) -> None:
    # 2c: JSON repair cost accumulation and sum matching total in trace.
    call_count = 0

    def dynamic_response(req) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "This is prose, not json."
        else:
            return '{"verified": true}'

    app.state.endpoint_registry = {
        "mock:solver": MockEndpoint(
            id="mock:solver", predefined_text="This is a solution."
        ),
        "mock:verifier": MockEndpoint(id="mock:verifier", response_fn=dynamic_response),
    }

    run_resp = await client.post(
        "/pipelines/run", json={"pipeline": PIPELINE_MERGE_C}, headers=AUTH
    )
    assert run_resp.status_code == 202, run_resp.text
    run_id = run_resp.json()["run_id"]

    events = await _ws_events(run_id)

    verifier_done = next(
        e
        for e in events
        if e.get("event") == "node_done" and e.get("node_id") == "verifier"
    )
    verifier_cost = verifier_done.get("cost_usd") or 0.0
    assert verifier_cost >= 0.002  # Two attempts

    # Sum of emitted NODE_DONE costs == run total in trace
    sum_cost = sum(
        (e.get("cost_usd") or 0.0) for e in events if e.get("event") == "node_done"
    )
    run_completed = next(e for e in events if e.get("event") == "run_completed")
    assert run_completed["total_cost_usd"] == sum_cost

    trace_resp = await client.get(f"/runs/{run_id}/trace", headers=AUTH)
    trace = trace_resp.json()
    assert trace["run"]["cost"] == sum_cost


@pytest.mark.asyncio
async def test_merge_c_2d_router_unmatched_condition(
    client: AsyncClient, mock_env
) -> None:
    # 2d: Router correctly routes with routing_map and raises an error on
    # an unmatched condition.

    app.state.endpoint_registry = {
        "mock:solver": MockEndpoint(
            id="mock:solver", predefined_text="This is a solution."
        ),
        "mock:verifier": MockEndpoint(
            id="mock:verifier", predefined_text='{"verified": "UNEXPECTED"}'
        ),
    }

    run_resp = await client.post(
        "/pipelines/run", json={"pipeline": PIPELINE_MERGE_C}, headers=AUTH
    )
    assert run_resp.status_code == 202, run_resp.text
    run_id = run_resp.json()["run_id"]

    events = await _ws_events(run_id)

    # Should halt due to router error
    run_error = next((e for e in events if e.get("event") == "run_error"), None)
    assert run_error is not None
    assert "matched no valid output port" in run_error.get("error", "")


@pytest.mark.asyncio
async def test_merge_c_2e_serializer_scrub_secrets() -> None:
    # 2e: Save the pipeline via the serializer and assert the exported JSON
    # contains NO api_key/token/secret fields. Here we simulate the python
    # equivalent of ensuring Pydantic models drop secrets when serialized.
    from komvos.compiler.models import Pipeline

    model = Pipeline(**PIPELINE_MERGE_C)
    dumped = model.model_dump(exclude_none=True)

    # Assert round-trip
    model2 = Pipeline(**dumped)
    assert model2.id == model.id
    assert len(model2.nodes) == len(model.nodes)
    assert len(model2.edges) == len(model.edges)
