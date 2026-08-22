"""
Phase 4 — provider resilience tests.

Covers the shared retry policy in endpoints/cloud.py (bounded exponential
backoff with jitter for rate-limit/server-error responses), the per-process
client caches in cloud.py and ollama.py, and a mock-endpoint pipeline run
proving the refactor leaves execution behaviour unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

import komvos.endpoints.cloud as cloud_mod
import komvos.endpoints.ollama as ollama_mod
from komvos.endpoints.cloud import _is_retryable, _retry_with_backoff


class _ProviderError(Exception):
    """Stands in for an SDK error carrying an HTTP status."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider error {status_code}")
        self.status_code = status_code


class _GenaiError(Exception):
    """google-genai shapes its errors with ``code`` instead."""

    def __init__(self, code: int) -> None:
        super().__init__(f"genai error {code}")
        self.code = code


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, True), (500, True), (502, True), (503, True), (400, False), (401, False)],
)
def test_is_retryable_by_status(status: int, expected: bool) -> None:
    assert _is_retryable(_ProviderError(status)) is expected


def test_is_retryable_genai_code_attribute() -> None:
    assert _is_retryable(_GenaiError(429)) is True
    assert _is_retryable(_GenaiError(503)) is True
    assert _is_retryable(_GenaiError(403)) is False


def test_is_retryable_plain_exception_is_false() -> None:
    assert _is_retryable(ValueError("nope")) is False


# ---------------------------------------------------------------------------
# Bounded exponential backoff with jitter
# ---------------------------------------------------------------------------


def test_retry_succeeds_after_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(cloud_mod.asyncio, "sleep", _fake_sleep)

    calls = {"n": 0}

    async def attempt() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _ProviderError(429)
        return "ok"

    result = asyncio.run(_retry_with_backoff(attempt, "test op"))

    assert result == "ok"
    assert calls["n"] == 3
    # Backoff doubles per attempt and stays under the cap even with jitter.
    assert len(delays) == 2
    assert all(0 < d <= cloud_mod.RETRY_MAX_DELAY_S for d in delays)
    assert delays[1] > delays[0]


def test_retry_gives_up_after_attempt_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr(cloud_mod.asyncio, "sleep", _fake_sleep)

    calls = {"n": 0}

    async def attempt() -> str:
        calls["n"] += 1
        raise _ProviderError(503)

    with pytest.raises(_ProviderError):
        asyncio.run(_retry_with_backoff(attempt, "test op"))

    assert calls["n"] == cloud_mod.RETRY_ATTEMPTS


def test_retry_does_not_swallow_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_sleep(seconds: float) -> None:
        raise AssertionError("must not back off for non-retryable errors")

    monkeypatch.setattr(cloud_mod.asyncio, "sleep", _fake_sleep)

    async def attempt() -> str:
        raise _ProviderError(401)

    with pytest.raises(_ProviderError):
        asyncio.run(_retry_with_backoff(attempt, "test op"))


# ---------------------------------------------------------------------------
# Client reuse
# ---------------------------------------------------------------------------


def test_cloud_clients_are_cached_per_provider_base_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same provider/base/key reuses one client; anything else builds anew."""
    monkeypatch.setenv("KOMVOS_ALLOW_MOCK_ENDPOINT", "1")

    # Drive the cache directly so no real SDK call is made.
    built: list[str] = []

    def factory(name: str) -> Any:
        built.append(name)
        return object()

    def make(label: str, name: str, base: str, key: str) -> Any:
        return cloud_mod._get_cached_client(
            f"openai:{name}", base, key, lambda: factory(label)
        )

    a = make("a", "test", "https://x/v1", "key1")
    b = make("b", "test", "https://x/v1", "key1")
    c = make("c", "test", "https://y/v1", "key1")
    d = make("d", "test", "https://x/v1", "key2")

    assert a is b          # identical coordinates -> reused
    assert a is not c      # different base URL
    assert a is not d      # rotated API key must not be masked by the cache
    assert built == ["a", "c", "d"]


def test_ollama_clients_are_cached_per_base_url_with_explicit_timeouts() -> None:
    e1 = ollama_mod.OllamaEndpoint(id="ollama:m", base_url="http://127.0.0.1:11434/v1")
    e2 = ollama_mod.OllamaEndpoint(id="ollama:m", base_url="http://127.0.0.1:11434/v1")

    client = ollama_mod._get_client(e1._base_url)  # noqa: SLF001 - test access
    assert ollama_mod._get_client(e2._base_url) is client

    assert isinstance(client, httpx.AsyncClient)
    assert client.timeout.connect == ollama_mod.CONNECT_TIMEOUT_S
    assert client.timeout.read == ollama_mod.READ_TIMEOUT_S
    assert client.timeout.write == ollama_mod.WRITE_TIMEOUT_S


# ---------------------------------------------------------------------------
# Mock-endpoint regression: pipeline execution is unchanged by the refactor
# ---------------------------------------------------------------------------


async def test_mock_pipeline_still_completes_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from komvos.api.main import app
    from komvos.endpoints.mock import MockEndpoint

    monkeypatch.setenv("KOMVOS_ALLOW_MOCK_ENDPOINT", "1")
    app.state.endpoint_registry = {
        "mock:default": MockEndpoint(
            id="mock:default",
            token_delay=0.0,
            predefined_text="hello world test response",
        )
    }
    try:
        pipeline: dict[str, Any] = {
            "schema_version": "2.0",
            "id": "00000000-0000-4000-a000-0000000000cd",
            "name": "Resilience Regression",
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
            "endpoints": {"mock:default": {"kind": "mock", "model": "mock-model"}},
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            resp = await client.post(
                "/pipelines/run",
                json={"pipeline": pipeline},
                headers={"Authorization": "Bearer t"},
            )
            assert resp.status_code == 202
            run_id = resp.json()["run_id"]

            deadline = asyncio.get_event_loop().time() + 10
            while asyncio.get_event_loop().time() < deadline:
                trace_resp = await client.get(
                    f"/runs/{run_id}/trace", headers={"Authorization": "Bearer t"}
                )
                if trace_resp.status_code == 200:
                    status = (trace_resp.json().get("run") or {}).get("status")
                    if status in {"completed", "error", "stopped"}:
                        assert status == "completed"
                        return
                await asyncio.sleep(0.05)
            pytest.fail("mock pipeline did not reach a terminal state in time")
    finally:
        if hasattr(app.state, "endpoint_registry"):
            del app.state.endpoint_registry
