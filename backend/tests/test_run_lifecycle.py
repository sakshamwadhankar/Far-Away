"""
Phase 3 — abandoned-run lifecycle regression tests.

A run started via POST /pipelines/run whose client never attaches the
WebSocket used to leak its registry entry forever, with an unbounded event
queue accumulating one event per streamed token. run_pipeline_task now owns
cleanup on every path: after REGISTRY_GRACE_SECONDS the registry entry must be
gone even with no consumer ever attached.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import komvos.api.registry as api_registry
from komvos.api.main import app
from komvos.endpoints.mock import MockEndpoint

AUTH = {"Authorization": "Bearer test-session-token"}

PIPELINE: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-0000000000ab",
    "name": "Abandoned Run Lifecycle Test",
    "version": "1.0.0",
    "nodes": [
        {"id": "in", "type": "input", "outputs": [{"name": "prompt", "type": "text"}]},
        {
            "id": "model_node",
            "type": "model",
            "endpoint_ref": "mock:default",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
            "config": {"temperature": 0.7, "max_tokens": 20},
        },
        {"id": "out", "type": "output", "inputs": [{"name": "result", "type": "text"}]},
    ],
    "loops": [],
    "edges": [
        {"from": "in.prompt", "to": "model_node.input"},
        {"from": "model_node.output", "to": "out.result"},
    ],
    "endpoints": {
        "mock:default": {"kind": "mock", "model": "mock-model"},
    },
}


@pytest.mark.asyncio
async def test_abandoned_run_leaves_registry_empty(monkeypatch) -> None:
    # Shrink the grace period so the test does not have to wait 5 s.
    monkeypatch.setattr(api_registry, "REGISTRY_GRACE_SECONDS", 0.05)
    app.state.endpoint_registry = {
        "mock:default": MockEndpoint(
            id="mock:default",
            token_delay=0.0,
            predefined_text="hello world test response",
        )
    }
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            resp = await client.post(
                "/pipelines/run", json={"pipeline": PIPELINE}, headers=AUTH
            )
            assert resp.status_code == 202
            run_id = resp.json()["run_id"]

            # The run registers immediately...
            assert run_id in api_registry.run_registry.active_run_ids()

            # ...and no WebSocket is ever attached. The driving task must
            # still remove the registry entry once the grace period passes.
            for _ in range(200):  # up to 10 s of polling
                if run_id not in api_registry.run_registry.active_run_ids():
                    break
                await asyncio.sleep(0.05)

            assert run_id not in api_registry.run_registry.active_run_ids()
    finally:
        if hasattr(app.state, "endpoint_registry"):
            del app.state.endpoint_registry
