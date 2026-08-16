"""
backend/tests/test_serve.py

Phase 3 — serving pipelines as an OpenAI-compatible HTTP API.

Covers: key hashing/verification, rejection of wrong/revoked keys, rate
limiting, deployment refused without an access node, access policy enforced
on served requests, the OpenAI-compatibility acceptance criterion (a real
`openai` SDK client completing a chat call), and well-formed/terminating SSE
streaming.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import tempfile
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from neuralflow.api.main import app
from neuralflow.endpoints.mock import MockEndpoint
from neuralflow.serve.keys import generate_key, hash_key, verify_key
from neuralflow.serve.store import DeploymentStore
from neuralflow.state.sqlite import StateManager

AUTH = {"Authorization": "Bearer test-token"}


def build_pipeline(
    *,
    provider: str = "mock",
    granted_providers: list[str] | None = None,
    input_nodes: list[dict[str, Any]] | None = None,
    output_nodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    input -> model -> output, governed by an access node.

    `granted_providers` defaults to [provider] (the happy path); pass a
    mismatched list to exercise the "policy doesn't grant what the model
    needs" rejection. `input_nodes`/`output_nodes` override the default
    single-node shape to exercise ambiguous-mapping rejections.
    """
    nodes: list[dict[str, Any]] = list(
        input_nodes
        or [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            }
        ]
    )
    nodes.append(
        {
            "id": "bot",
            "type": "model",
            "endpoint_ref": f"{provider}:default",
            "inputs": [{"name": "prompt", "type": "text"}],
            "outputs": [{"name": "reply", "type": "text"}],
        }
    )
    nodes.extend(
        output_nodes
        or [
            {
                "id": "out",
                "type": "output",
                "inputs": [{"name": "result", "type": "text"}],
            }
        ]
    )
    nodes.append(
        {
            "id": "gate-1",
            "type": "access",
            "config": {"access_policy": {"providers": granted_providers or [provider]}},
        }
    )

    edges = [
        {"from": n["id"] + ".prompt", "to": "bot.prompt"}
        for n in nodes
        if n["type"] == "input"
    ]
    edges.append(
        {
            "from": "bot.reply",
            "to": (output_nodes or [{"id": "out"}])[0]["id"] + ".result",
        }
    )
    edges.append({"from": "gate-1.scope", "to": "bot.prompt"})

    return {
        "schema_version": "2.1",
        "id": "00000000-0000-4000-a000-00000000se01",
        "name": "Serve test pipeline",
        "version": "1.0.0",
        "nodes": nodes,
        "edges": edges,
        "endpoints": {f"{provider}:default": {"kind": provider}},
    }


@pytest_asyncio.fixture
async def serve_client():
    """
    A client with its own temp SQLite file backing both StateManager and
    DeploymentStore (same file, per serve/store.py's design), and a mock
    endpoint pre-registered so deployed pipelines execute without any real
    network call.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    app.state.state_manager = StateManager(db_path)
    app.state.deployment_store = DeploymentStore(db_path)
    app.state.endpoint_registry = {
        "mock:default": MockEndpoint(
            id="mock:default", token_delay=0.0, predefined_text="hello world"
        )
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as ac:
        yield ac, db_path

    for attr in ("state_manager", "deployment_store", "endpoint_registry"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
    with contextlib.suppress(OSError):
        os.unlink(db_path)


async def _deploy(
    client: AsyncClient, pipeline: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    resp = await client.post(
        "/deployments", json={"pipeline": pipeline, **extra}, headers=AUTH
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Key hashing / verification (serve/keys.py)
# ---------------------------------------------------------------------------


def test_generate_key_roundtrips_through_verify() -> None:
    plaintext, digest = generate_key()
    assert plaintext.startswith("kv_")
    assert verify_key(plaintext, digest) is True


def test_verify_key_rejects_wrong_plaintext() -> None:
    _plaintext, digest = generate_key()
    assert verify_key("kv_totally-different-value", digest) is False


def test_verify_key_rejects_missing_prefix_before_hashing() -> None:
    """A value shaped nothing like a deployment key is rejected outright."""
    assert verify_key("session-token-not-a-deployment-key", hash_key("x")) is False


def test_hash_key_is_sha256_hex() -> None:
    plaintext = "kv_example"
    digest = hash_key(plaintext)
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex


# ---------------------------------------------------------------------------
# Deployment refused without an access node (3.4.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deploy_refused_without_access_node(serve_client) -> None:
    client, _db = serve_client
    pipeline = build_pipeline()
    pipeline["nodes"] = [n for n in pipeline["nodes"] if n["type"] != "access"]
    pipeline["edges"] = [e for e in pipeline["edges"] if "gate" not in e["from"]]

    resp = await client.post("/deployments", json={"pipeline": pipeline}, headers=AUTH)

    assert resp.status_code == 422
    assert "access node" in json.dumps(resp.json()).lower()


@pytest.mark.asyncio
async def test_deploy_refused_when_policy_does_not_grant_the_model(
    serve_client,
) -> None:
    """
    Access policy enforced BEFORE a deployment can even exist: a model asking
    for 'mock' behind a gate that only grants 'openai' never becomes callable.
    """
    client, _db = serve_client
    pipeline = build_pipeline(provider="mock", granted_providers=["openai"])

    resp = await client.post("/deployments", json={"pipeline": pipeline}, headers=AUTH)

    assert resp.status_code == 422
    detail = json.dumps(resp.json())
    assert "mock" in detail
    assert "gate-1" in detail


@pytest.mark.asyncio
async def test_deploy_refused_on_ambiguous_chat_input(serve_client) -> None:
    client, _db = serve_client
    pipeline = build_pipeline(
        input_nodes=[
            {
                "id": "a",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "b",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
        ]
    )
    # Route only 'a' to the model so the pipeline is otherwise valid; the
    # ambiguity is what deployment must reject.
    pipeline["edges"] = [e for e in pipeline["edges"] if not e["from"].startswith("b.")]

    resp = await client.post("/deployments", json={"pipeline": pipeline}, headers=AUTH)

    assert resp.status_code == 422
    detail = json.dumps(resp.json())
    assert "'a'" in detail and "'b'" in detail


# ---------------------------------------------------------------------------
# Deploy, list, keys shown once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deploy_returns_key_once_and_it_is_never_listed(serve_client) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())

    assert data["key"].startswith("kv_")
    assert "deployment_id" in data
    assert "base_url" in data

    resp = await client.get("/deployments", headers=AUTH)
    assert resp.status_code == 200
    assert data["key"] not in resp.text
    assert "key" not in resp.json()["deployments"][0]


@pytest.mark.asyncio
async def test_undeploy_removes_it_from_the_list(serve_client) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())

    resp = await client.delete(f"/deployments/{data['deployment_id']}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"deployment_id": data["deployment_id"], "deleted": True}

    listed = await client.get("/deployments", headers=AUTH)
    assert data["deployment_id"] not in [d["id"] for d in listed.json()["deployments"]]


# ---------------------------------------------------------------------------
# Auth: wrong / revoked keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_authorization_header_rejected(serve_client) -> None:
    client, _db = serve_client
    await _deploy(client, build_pipeline())

    resp = await client.get("/v1/models")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_deployment_key_rejected(serve_client) -> None:
    client, _db = serve_client
    await _deploy(client, build_pipeline())

    resp = await client.get(
        "/v1/models", headers={"Authorization": "Bearer kv_not-the-right-key"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_rotated_key_dies_immediately(serve_client) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())
    old_key = data["key"]

    rotate = await client.post(
        f"/deployments/{data['deployment_id']}/rotate-key", headers=AUTH
    )
    assert rotate.status_code == 200
    new_key = rotate.json()["key"]
    assert new_key != old_key

    old_resp = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {old_key}"}
    )
    assert old_resp.status_code == 401

    new_resp = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {new_key}"}
    )
    assert new_resp.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_returns_429_once_exceeded(serve_client) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline(), rate_limit_per_minute=2)
    headers = {"Authorization": f"Bearer {data['key']}"}

    codes = [
        (await client.get("/v1/models", headers=headers)).status_code for _ in range(3)
    ]

    assert codes[:2] == [200, 200]
    assert codes[2] == 429


# ---------------------------------------------------------------------------
# Chat completions — non-streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completions_happy_path(serve_client) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())
    headers = {"Authorization": f"Bearer {data['key']}"}

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": data["deployment_id"],
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == data["deployment_id"]
    assert body["choices"][0]["message"]["content"] == "hello world"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] > 0


@pytest.mark.asyncio
async def test_chat_completions_rejects_mismatched_model(serve_client) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())
    headers = {"Authorization": f"Bearer {data['key']}"}

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "some-other-deployment",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers=headers,
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_chat_completions_increments_request_count(serve_client) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())
    headers = {"Authorization": f"Bearer {data['key']}"}

    await client.post(
        "/v1/chat/completions",
        json={
            "model": data["deployment_id"],
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers=headers,
    )

    listed = await client.get("/deployments", headers=AUTH)
    entry = listed.json()["deployments"][0]
    assert entry["request_count"] == 1
    assert entry["error_count"] == 0
    assert entry["last_request_at"] is not None


# ---------------------------------------------------------------------------
# Trace persistence (3.4.6): served runs land in the shared trace tables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_served_run_is_tagged_with_deployment_id_in_trace_tables(
    serve_client,
) -> None:
    client, db_path = serve_client
    data = await _deploy(client, build_pipeline())
    headers = {"Authorization": f"Bearer {data['key']}"}

    await client.post(
        "/v1/chat/completions",
        json={
            "model": data["deployment_id"],
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers=headers,
    )

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT deployment_id, status FROM runs WHERE deployment_id = ?",
            (data["deployment_id"],),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0][1] == "completed"


# ---------------------------------------------------------------------------
# Native run path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_native_run_maps_fields_by_node_id(serve_client) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())
    headers = {"Authorization": f"Bearer {data['key']}"}

    resp = await client.post(
        f"/v1/deployments/{data['deployment_id']}/run",
        json={"in": "native hello"},
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"outputs": {"out": "hello world"}}


@pytest.mark.asyncio
async def test_native_run_rejects_mismatched_deployment_id_in_path(
    serve_client,
) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())
    headers = {"Authorization": f"Bearer {data['key']}"}

    resp = await client.post(
        "/v1/deployments/not-this-deployment/run",
        json={"in": "hi"},
        headers=headers,
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Streaming: well-formed, terminating SSE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_chat_completions_emits_well_formed_openai_deltas(
    serve_client,
) -> None:
    client, _db = serve_client
    data = await _deploy(client, build_pipeline())
    headers = {"Authorization": f"Bearer {data['key']}"}

    frames: list[str] = []
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": data["deployment_id"],
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        headers=headers,
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                frames.append(line[len("data: ") :])

    assert frames, "no SSE frames received"
    assert frames[-1] == "[DONE]"

    parsed = [json.loads(f) for f in frames[:-1]]
    for chunk in parsed:
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["model"] == data["deployment_id"]
        assert "delta" in chunk["choices"][0]

    # First chunk announces the assistant role, matching OpenAI's convention.
    assert parsed[0]["choices"][0]["delta"].get("role") == "assistant"
    # Exactly one terminal chunk, carrying finish_reason.
    finishes = [c for c in parsed if c["choices"][0]["finish_reason"] == "stop"]
    assert len(finishes) == 1
    assert finishes[0] is parsed[-1]

    # The streamed content, reassembled, is the model's full output.
    content = "".join(c["choices"][0]["delta"].get("content", "") for c in parsed)
    assert content == "hello world"


@pytest.mark.asyncio
async def test_stale_stored_policy_is_rejected_before_streaming_starts(
    serve_client,
) -> None:
    """
    Every request recompiles the deployment's stored pipeline (serve/README's
    "recompiled per request" design) rather than trusting a cached DAG. Write
    a pipeline straight into the store whose access node no longer grants the
    provider its model node needs — bypassing POST /deployments' own
    compile-time check the way stored data could drift in principle — and
    confirm the request 422s with the same access-denial message the compiler
    produces, instead of streaming an empty or hung response.
    """
    client, db_path = serve_client
    store = DeploymentStore(db_path)
    from neuralflow.serve.models import Deployment

    pipeline = build_pipeline(provider="mock", granted_providers=["mock"])
    for node in pipeline["nodes"]:
        if node["type"] == "access":
            node["config"]["access_policy"]["providers"] = ["openai"]

    plaintext, digest = generate_key()
    store.create(
        Deployment(
            id="tampered-deployment",
            name="tampered",
            pipeline=pipeline,
            key_hash=digest,
            chat_input_node="in",
            chat_output_node="out",
            created_at=0,
        )
    )

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "tampered-deployment",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        headers={"Authorization": f"Bearer {plaintext}"},
    )

    assert resp.status_code == 422
    detail = json.dumps(resp.json())
    assert "mock" in detail and "gate-1" in detail


# ---------------------------------------------------------------------------
# Acceptance criterion (3.6): the real `openai` SDK completes a chat call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_openai_sdk_completes_a_chat_call(serve_client) -> None:
    """
    This is the acceptance criterion for the whole phase: an unmodified
    `openai` Python SDK client, pointed at our /v1 routes, completes a normal
    chat call. Uses AsyncOpenAI with its http_client overridden to the same
    in-process ASGI transport the rest of the suite uses — no real socket
    needed, but every byte on the wire is exactly what a real client sends
    and receives.
    """
    from openai import AsyncOpenAI

    client, _db = serve_client
    data = await _deploy(client, build_pipeline())

    sdk_http_client = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1/v1"
    )
    sdk = AsyncOpenAI(
        base_url="http://127.0.0.1/v1",
        api_key=data["key"],
        http_client=sdk_http_client,
    )
    try:
        resp = await sdk.chat.completions.create(
            model=data["deployment_id"],
            messages=[{"role": "user", "content": "hello"}],
        )
    finally:
        await sdk_http_client.aclose()

    assert resp.choices[0].message.content == "hello world"
    assert resp.model == data["deployment_id"]


@pytest.mark.asyncio
async def test_real_openai_sdk_lists_this_deployment_as_a_model(serve_client) -> None:
    from openai import AsyncOpenAI

    client, _db = serve_client
    data = await _deploy(client, build_pipeline())

    sdk_http_client = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1/v1"
    )
    sdk = AsyncOpenAI(
        base_url="http://127.0.0.1/v1",
        api_key=data["key"],
        http_client=sdk_http_client,
    )
    try:
        models = await sdk.models.list()
    finally:
        await sdk_http_client.aclose()

    assert [m.id for m in models.data] == [data["deployment_id"]]


# ---------------------------------------------------------------------------
# LAN policy predicate
# ---------------------------------------------------------------------------


def test_is_loopback_recognizes_local_hosts() -> None:
    from neuralflow.serve.routes import _is_loopback

    assert _is_loopback("127.0.0.1") is True
    assert _is_loopback("::1") is True
    assert _is_loopback("localhost") is True
    assert _is_loopback("192.168.1.50") is False
    assert _is_loopback(None) is False
