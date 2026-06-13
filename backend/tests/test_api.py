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
import httpx
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


from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_models_endpoint_dynamic_fetching(client: AsyncClient) -> None:
    class MockResponse:
        def __init__(self, status_code, json_data):
            self.status_code = status_code
            self._json_data = json_data
        def json(self):
            return self._json_data

    original_get = httpx.AsyncClient.get

    async def mock_get(self, url, *args, **kwargs):
        url_str = str(url)
        if "11434" in url_str:
            return MockResponse(200, {"models": [{"name": "qwen2.5:3b"}]})
        elif "openai" in url_str:
            return MockResponse(200, {"data": [{"id": "gpt-4o-mini"}]})
        elif "anthropic" in url_str:
            return MockResponse(401, {}) # simulate error
        elif "google" in url_str:
            return MockResponse(200, {"models": [{"name": "models/gemini-1.5-flash"}]})
        return await original_get(self, url, *args, **kwargs)

    def mock_keyring_get(service, username):
        if username == "openai": return "sk-open"
        if username == "anthropic": return "sk-anth"
        if username == "google": return "sk-goog"
        return None

    with patch("httpx.AsyncClient.get", new=mock_get), \
         patch("keyring.get_password", side_effect=mock_keyring_get):
        resp = await client.get("/models", headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert "models" in body
        
        models = body["models"]
        endpoint_ids = [m["endpoint_id"] for m in models]
        
        # Test mock provider override
        assert "mock:default" in endpoint_ids
        
        # Test local ollama
        assert "ollama:qwen2.5:3b" in endpoint_ids
        
        # Test openai (key present, 200 OK)
        assert "openai:gpt-4o-mini" in endpoint_ids
        
        # Test anthropic (key present, but 401 error, skips cleanly)
        assert not any(eid.startswith("anthropic:") for eid in endpoint_ids)
        
        # Test google (key present, 200 OK, stripped models/)
        assert "google:gemini-1.5-flash" in endpoint_ids


@pytest.mark.asyncio
async def test_models_endpoint_all_offline(client: AsyncClient) -> None:
    original_get = httpx.AsyncClient.get

    async def mock_get(self, url, *args, **kwargs):
        url_str = str(url)
        if "11434" not in url_str and ("/models" in url_str or "127.0.0.1" in url_str):
            return await original_get(self, url, *args, **kwargs)
        raise Exception("Network error")

    def mock_keyring_get(service, username):
        return None  # No keys

    with patch("httpx.AsyncClient.get", new=mock_get), \
         patch("keyring.get_password", side_effect=mock_keyring_get):
        resp = await client.get("/models", headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        
        # Should only contain mock:default
        models = body["models"]
        assert len(models) == 1
        assert models[0]["endpoint_id"] == "mock:default"


@pytest.mark.asyncio
async def test_get_trace_after_completion(client: AsyncClient) -> None:
    # 1. Start run
    run_resp = await client.post(
        "/pipelines/run", json={"pipeline": PIPELINE}, headers=AUTH
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]

    # 2. Wait for completion via WS
    events = await _ws_events(run_id)
    types = [e["event"] for e in events]
    assert "run_completed" in types

    # 3. Fetch trace
    trace_resp = await client.get(f"/runs/{run_id}/trace", headers=AUTH)
    assert trace_resp.status_code == 200
    trace = trace_resp.json()
    
    assert "run" in trace
    assert trace["run"]["status"] == "completed"
    assert trace["run"]["run_id"] == run_id
    
    assert "nodes" in trace
    assert len(trace["nodes"]) > 0
    
    model_node = next((n for n in trace["nodes"] if n["node_id"] == "model_node"), None)
    assert model_node is not None
    assert "outputs" in model_node
    
    assert "loops" in trace


def test_default_db_path() -> None:
    from neuralflow.api.main import _global_state_manager, app
    import os
    from pathlib import Path
    
    # Ensure no override
    if hasattr(app.state, "state_manager"):
        del app.state.state_manager
        
    sm = _global_state_manager()
    expected_dir = Path(os.path.expanduser("~/.neuralflow"))
    assert sm.db_path == expected_dir / "neuralflow.db"


@pytest.mark.asyncio
async def test_cost_divergence_on_retries(client: AsyncClient) -> None:
    call_count = 0

    def dynamic_response(req) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "This is prose, not json."
        else:
            return '{"key": "value"}'

    from neuralflow.api.main import app
    from neuralflow.endpoints.mock import MockEndpoint
    
    app.state.endpoint_registry = {
        "mock:json_repair": MockEndpoint(id="mock:json_repair", response_fn=dynamic_response)
    }
    
    import copy
    pipeline = copy.deepcopy(PIPELINE)
    pipeline["nodes"][1]["endpoint_ref"] = "mock:json_repair"
    pipeline["nodes"][1]["config"]["response_format"] = "json"
    pipeline["endpoints"]["mock:json_repair"] = {"kind": "mock"}

    run_resp = await client.post("/pipelines/run", json={"pipeline": pipeline}, headers=AUTH)
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]

    events = await _ws_events(run_id)
    
    node_done_events = [e for e in events if e.get("event") == "node_done" and e.get("node_id") == "model_node"]
    assert len(node_done_events) == 1
    node_cost = node_done_events[0]["cost_usd"]
    
    # Should reflect two attempts of approx 0.001 each
    assert node_cost >= 0.002

    run_completed = next((e for e in events if e.get("event") == "run_completed"), None)
    assert run_completed is not None
    assert run_completed["total_cost_usd"] == node_cost

    trace_resp = await client.get(f"/runs/{run_id}/trace", headers=AUTH)
    trace = trace_resp.json()
    model_node = next(n for n in trace["nodes"] if n["node_id"] == "model_node")
    
    assert model_node["cost"] == node_cost
    assert trace["run"]["cost"] == node_cost

@pytest.mark.asyncio
async def test_estimate_pipeline(client: AsyncClient) -> None:
    resp = await client.post(
        "/pipelines/estimate",
        json={"pipeline": PIPELINE},
        headers=AUTH,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "total_usd" in data
    assert "total_latency_ms" in data
    assert "model_node" in data["nodes"]
    est = data["nodes"]["model_node"]
    assert "usd" in est
    assert "latency_ms" in est
    assert "is_local" in est
    # In mock:default, is_local should be true
    assert est["is_local"] is True
