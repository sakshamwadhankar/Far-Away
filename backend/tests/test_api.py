"""
backend/tests/test_api.py

P2 Phase 2 API layer tests.

All tests use MockEndpoint — no real API keys required.

WebSocket tests use httpx-ws.aconnect_ws() with ASGIWebSocketTransport
created locally per-connection. HTTP tests use httpx.AsyncClient with
ASGITransport. This avoids AnyIO cancel scope bugs across pytest fixtures
while preventing the thread deadlocks caused by starlette.TestClient.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from neuralflow.api.main import app
from neuralflow.endpoints.mock import MockEndpoint

# ---------------------------------------------------------------------------
# Pipeline fixture
# ---------------------------------------------------------------------------

PIPELINE: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000099",
    "name": "API Test Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "model_node",
            "type": "model",
            "endpoint_ref": "mock:default",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
            "config": {"temperature": 0.7, "max_tokens": 20},
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
    ],
    "loops": [],
    "edges": [
        {"from": "in.prompt", "to": "model_node.input"},
        {"from": "model_node.output", "to": "out.result"},
    ],
    "endpoints": {
        "mock:default": {"kind": "openai", "model": "gpt-4o-mini"},
    },
}

AUTH = {"Authorization": "Bearer test-token"}
TERMINAL = {"run_completed", "run_stopped", "budget_exceeded", "run_error", "run_halted"}


# ---------------------------------------------------------------------------
# WS Helper
# ---------------------------------------------------------------------------


async def _ws_events(run_id: str, token: str = "test-token") -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    # Create the WS transport + client dynamically per WS connection
    # to avoid AnyIO fixture cancel scope leakage
    async with ASGIWebSocketTransport(app=app) as transport:
        async with AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as ws_client:
            async with aconnect_ws(
                f"ws://127.0.0.1/ws/run/{run_id}?token={token}",
                ws_client,
            ) as ws:
                while True:
                    msg = await ws.receive_json()
                    events.append(msg)
                    if msg.get("event") in TERMINAL:
                        break
    return events


# ---------------------------------------------------------------------------
# Fixtures (HTTP only)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    app.state.endpoint_registry = {
        "mock:default": MockEndpoint(
            id="mock:default",
            token_delay=0.0,
            predefined_text="hello world test response",
        )
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as ac:
        yield ac
    if hasattr(app.state, "endpoint_registry"):
        del app.state.endpoint_registry


@pytest_asyncio.fixture
async def slow_client():
    app.state.endpoint_registry = {
        "mock:default": MockEndpoint(
            id="mock:default",
            token_delay=0.06,
            predefined_text="one two three four five six seven eight",
        )
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as ac:
        yield ac
    if hasattr(app.state, "endpoint_registry"):
        del app.state.endpoint_registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_auth_rejected_no_header(client: AsyncClient) -> None:
    resp = await client.post("/pipelines/run", json={"pipeline": PIPELINE})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_accepted_dev_mode(client: AsyncClient) -> None:
    saved = os.environ.pop("NEURALFLOW_SESSION_TOKEN", None)
    try:
        resp = await client.post(
            "/pipelines/run",
            json={"pipeline": PIPELINE},
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code == 202
    finally:
        if saved is not None:
            os.environ["NEURALFLOW_SESSION_TOKEN"] = saved


@pytest.mark.asyncio
async def test_auth_rejected_wrong_token(client: AsyncClient) -> None:
    os.environ["NEURALFLOW_SESSION_TOKEN"] = "correct"
    try:
        resp = await client.post(
            "/pipelines/run",
            json={"pipeline": PIPELINE},
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401
    finally:
        del os.environ["NEURALFLOW_SESSION_TOKEN"]


@pytest.mark.asyncio
async def test_run_and_stream(client: AsyncClient) -> None:
    run_resp = await client.post(
        "/pipelines/run", json={"pipeline": PIPELINE}, headers=AUTH
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]

    events = await _ws_events(run_id)
    types = [e["event"] for e in events]

    assert "node_started" in types
    assert "token" in types
    assert "node_done" in types
    assert types[-1] == "run_completed"

    model_start_idx = next(
        (i for i, e in enumerate(events)
         if e["event"] == "node_started" and e.get("node_id") == "model_node"),
        None,
    )
    first_token_idx = next((i for i, e in enumerate(events) if e["event"] == "token"), None)
    
    assert model_start_idx is not None
    assert first_token_idx is not None
    assert model_start_idx < first_token_idx
    
    final = events[-1]
    assert "total_cost_usd" in final
    assert "elapsed_ms" in final


@pytest.mark.asyncio
async def test_budget_breach_halts_run(client: AsyncClient) -> None:
    run_resp = await client.post(
        "/pipelines/run",
        json={"pipeline": PIPELINE, "budget_usd": 0.0},
        headers=AUTH,
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]

    events = await _ws_events(run_id)
    types = [e["event"] for e in events]

    assert "budget_exceeded" in types
    assert "token" not in types

    breach = next(e for e in events if e["event"] == "budget_exceeded")
    assert breach["budget_usd"] == 0.0
    assert "cumulative_cost_usd" in breach


@pytest.mark.asyncio
async def test_stop_endpoint_halts_run(slow_client: AsyncClient) -> None:
    run_resp = await slow_client.post(
        "/pipelines/run", json={"pipeline": PIPELINE}, headers=AUTH
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]

    # Give the background task time to start streaming
    await asyncio.sleep(0.05)

    stop_resp = await slow_client.post(f"/runs/{run_id}/stop", headers=AUTH)
    assert stop_resp.status_code == 200
    assert stop_resp.json()["halted"] is True

    events = await _ws_events(run_id)
    types = [e["event"] for e in events]
    assert "run_stopped" in types


@pytest.mark.asyncio
async def test_invalid_pipeline_422(client: AsyncClient) -> None:
    bad = {"schema_version": "2.0", "id": "bad", "name": "x"}
    resp = await client.post(
        "/pipelines/run", json={"pipeline": bad}, headers=AUTH
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_models_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/models", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "models" in body
    assert len(body["models"]) >= 1
    m = body["models"][0]
    assert "endpoint_id" in m
    assert "max_context" in m
    assert "json_mode" in m
