"""
backend/tests/test_security.py

Phase 1 — security hardening.

Covers the three boundaries that keep a locally-bound backend from being driven
by whatever page the user happens to have open:

  1. CORS is an explicit allowlist, not `.*`.
  2. Auth fails closed — an unset session token is not a bypass.
  3. The interactive docs are a dev-only surface.

Plus the event-loop guarantee for SQLite trace writes (1.4).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from httpx import AsyncClient

from komvos.api import main as api_main
from komvos.api.auth import (
    DEV_MODE_ENV_VAR,
    SESSION_TOKEN_ENV_VAR,
    check_token,
    is_dev_mode,
)
from komvos.state.sqlite import StateManager
from tests.test_api import PIPELINE

AUTH = {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# 1.1 — CORS allowlist
# ---------------------------------------------------------------------------


def test_cors_allowlist_excludes_web_origins_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without KOMVOS_DEV=1 the allowlist contains no http(s) origin at all."""
    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)
    origins = api_main._allowed_origins()

    assert origins == ["komvos://bundle"]
    assert not any(o.startswith("http") for o in origins)


def test_cors_allowlist_adds_dev_server_only_in_dev_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    origins = api_main._allowed_origins()

    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins
    # The Electron renderer origin is still present.
    assert "komvos://bundle" in origins


def test_cors_allowlist_is_not_a_wildcard() -> None:
    """Regression guard for `allow_origin_regex='.*'` + allow_credentials."""
    cors = next(m for m in api_main.app.user_middleware if "CORS" in m.cls.__name__)
    assert cors.kwargs.get("allow_origin_regex") is None
    assert "*" not in cors.kwargs["allow_origins"]
    assert cors.kwargs["allow_credentials"] is True


@pytest.mark.asyncio
async def test_cors_rejects_arbitrary_web_origin(client: AsyncClient) -> None:
    """
    A page on the public web must not receive an Access-Control-Allow-Origin
    header, so the browser refuses to hand it the response.
    """
    resp = await client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_cors_preflight_rejects_arbitrary_web_origin(
    client: AsyncClient,
) -> None:
    resp = await client.request(
        "OPTIONS",
        "/pipelines/run",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_cors_allows_electron_renderer_origin(client: AsyncClient) -> None:
    """
    The packaged renderer loads over the custom komvos:// app protocol, so its
    requests carry the real origin "komvos://bundle" — an origin no web page,
    including a sandboxed iframe (origin "null"), can produce.
    """
    resp = await client.get("/health", headers={"Origin": "komvos://bundle"})
    assert resp.headers.get("access-control-allow-origin") == "komvos://bundle"


@pytest.mark.asyncio
async def test_cors_rejects_opaque_null_origin(client: AsyncClient) -> None:
    """
    Regression guard for the Phase 3 hardening: "null" is the origin every
    sandboxed iframe on the public internet sends, so it must never be
    admitted even though a file://-loaded window used to send it.
    """
    resp = await client.get("/health", headers={"Origin": "null"})
    assert "access-control-allow-origin" not in resp.headers


# ---------------------------------------------------------------------------
# 1.1 — /docs is dev-only
# ---------------------------------------------------------------------------


def test_docs_are_gated_on_dev_mode() -> None:
    """
    docs_url/openapi_url are wired to the dev flag as read at import time.

    Asserting the relationship rather than a fixed value keeps this honest for
    a developer who runs pytest with KOMVOS_DEV=1 already exported.
    """
    assert (api_main.app.docs_url is not None) == api_main._DEV_MODE
    assert (api_main.app.openapi_url is not None) == api_main._DEV_MODE
    # ReDoc is off unconditionally.
    assert api_main.app.redoc_url is None


@pytest.mark.asyncio
async def test_docs_not_served_outside_dev_mode(client: AsyncClient) -> None:
    if api_main._DEV_MODE:
        pytest.skip("KOMVOS_DEV=1 was set when komvos.api.main was imported")
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404


# ---------------------------------------------------------------------------
# 1.2 — auth fails closed
# ---------------------------------------------------------------------------


def test_check_token_rejects_when_no_token_and_no_dev_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bypass this phase closes: unset token used to accept anything."""
    monkeypatch.delenv(SESSION_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)

    assert not is_dev_mode()
    assert check_token("anything") is False
    assert check_token("") is False
    assert check_token(None) is False


def test_check_token_accepts_any_value_only_under_explicit_dev_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SESSION_TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")

    assert check_token("anything") is True
    # An empty token is still not a token.
    assert check_token("") is False


@pytest.mark.parametrize("value", ["0", "true", "yes", "", "TRUE"])
def test_dev_mode_requires_exactly_one(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Only the literal "1" opts in — no truthy-string guessing."""
    monkeypatch.setenv(DEV_MODE_ENV_VAR, value)
    assert is_dev_mode() is False


def test_check_token_compares_against_configured_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_TOKEN_ENV_VAR, "correct-horse")
    # Dev mode must not weaken a configured token.
    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")

    assert check_token("correct-horse") is True
    assert check_token("wrong") is False
    assert check_token("") is False


@pytest.mark.asyncio
async def test_http_route_401s_when_failing_closed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SESSION_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)

    resp = await client.post(
        "/pipelines/run",
        json={"pipeline": PIPELINE},
        headers={"Authorization": "Bearer anything"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_websocket_rejects_when_failing_closed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The WS handler used to reject a mismatched token only when one was
    configured, so an unset token accepted every connection.
    """
    from httpx_ws import WebSocketDisconnect, aconnect_ws
    from httpx_ws.transport import ASGIWebSocketTransport

    # Start a real run while dev mode is still on, so the run exists.
    run_resp = await client.post(
        "/pipelines/run", json={"pipeline": PIPELINE}, headers=AUTH
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]

    # Now drop the dev-mode opt-in and try to attach to that run's stream.
    monkeypatch.delenv(SESSION_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)

    disconnect: WebSocketDisconnect | None = None
    try:
        async with (
            ASGIWebSocketTransport(app=api_main.app) as transport,
            AsyncClient(transport=transport, base_url="http://127.0.0.1") as ws_client,
            aconnect_ws(
                f"ws://127.0.0.1/ws/run/{run_id}?token=anything", ws_client
            ) as ws,
        ):
            await ws.receive_json()
    except WebSocketDisconnect as exc:  # pragma: no cover — depends on anyio version
        disconnect = exc
    except BaseExceptionGroup as group:
        # anyio wraps the handshake failure in a task group.
        matched, _ = group.split(WebSocketDisconnect)
        assert matched is not None, f"unexpected failure: {group!r}"
        disconnect = matched.exceptions[0]  # type: ignore[assignment]

    assert disconnect is not None, "WebSocket accepted an unauthenticated client"
    assert disconnect.code == 4001


# ---------------------------------------------------------------------------
# 1.4 — SQLite writes stay off the event loop
# ---------------------------------------------------------------------------


def test_sqlite_uses_wal_and_normal_sync(tmp_path: Any) -> None:
    db = tmp_path / "trace.db"
    sm = StateManager(db)

    conn = sm._get_conn()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        # synchronous=NORMAL is 1.
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()


class _SlowStateManager(StateManager):
    """StateManager whose writes block the calling thread for `delay` seconds."""

    def __init__(self, db_path: Any, delay: float) -> None:
        super().__init__(db_path)
        self.delay = delay

    def save_node_execution(self, *args: Any, **kwargs: Any) -> None:
        time.sleep(self.delay)
        super().save_node_execution(*args, **kwargs)

    def update_run_status(self, *args: Any, **kwargs: Any) -> None:
        time.sleep(self.delay)
        super().update_run_status(*args, **kwargs)

    def save_run(self, *args: Any, **kwargs: Any) -> None:
        time.sleep(self.delay)
        super().save_run(*args, **kwargs)


#: Heartbeat period. Kept comfortably above the ~15.6ms timer granularity of
#: the Windows event loop so that scheduling jitter is not mistaken for
#: blocking.
TICK_INTERVAL = 0.02

#: A blocking write in these tests holds the thread this long.
WRITE_DELAY = 0.3


async def _measure_max_loop_gap(body: Any) -> tuple[float, float]:
    """
    Await `body()` while a heartbeat ticks every TICK_INTERVAL seconds.

    Returns (elapsed_seconds, max_gap_seconds), where max_gap is the longest
    interval between consecutive heartbeat wakeups. This measures event-loop
    starvation directly and is independent of the platform's timer resolution:
    a loop blocked inside a C call for D seconds shows a gap of ~D, while a
    healthy loop stays near TICK_INTERVAL plus jitter.
    """
    gaps: list[float] = []
    stop = asyncio.Event()

    async def heartbeat() -> None:
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(TICK_INTERVAL)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    started = time.perf_counter()
    try:
        await body()
    finally:
        elapsed = time.perf_counter() - started
        stop.set()
        await beat

    return elapsed, max(gaps) if gaps else elapsed


def _mock_registry() -> Any:
    from komvos.endpoints.mock import MockEndpoint
    from komvos.scheduler.engine import EndpointRegistry

    return EndpointRegistry(
        {
            "mock:default": MockEndpoint(
                id="mock:default", token_delay=0.0, predefined_text="alpha beta"
            )
        }
    )


@pytest.mark.asyncio
async def test_blocking_write_on_the_loop_starves_it(tmp_path: Any) -> None:
    """
    Calibration for the test below.

    Proves the harness can actually detect a blocked event loop: calling the
    same slow write directly (the pre-1.4 behaviour) drives responsiveness to
    near zero. Without this, a passing responsiveness assertion would prove
    nothing.
    """
    sm = _SlowStateManager(tmp_path / "blocking.db", delay=WRITE_DELAY)

    async def body() -> None:
        sm.save_run("run-blocking", "pipeline-1", "running")

    elapsed, max_gap = await _measure_max_loop_gap(body)

    assert elapsed >= WRITE_DELAY
    assert (
        max_gap >= WRITE_DELAY * 0.8
    ), f"harness cannot detect a blocked loop (max gap {max_gap * 1000:.0f}ms)"


@pytest.mark.asyncio
async def test_run_stays_responsive_while_trace_writes_are_slow(
    tmp_path: Any,
) -> None:
    """
    The real assertion: PipelineRunner drives a full run whose every trace
    write blocks for 0.3s, and the event loop keeps servicing other coroutines
    throughout. Reverting any asyncio.to_thread in runner.py fails this.
    """
    from komvos.compiler.dag import compile as compile_pipeline
    from komvos.scheduler.runner import PipelineRunner

    sm = _SlowStateManager(tmp_path / "run.db", delay=WRITE_DELAY)
    runner = PipelineRunner(
        "run-slow-db",
        compile_pipeline(PIPELINE),
        _mock_registry(),
        state_manager=sm,
    )
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def body() -> None:
        await asyncio.wait_for(runner.run(queue), timeout=30.0)

    elapsed, max_gap = await _measure_max_loop_gap(body)

    events: list[Any] = []
    while not queue.empty():
        item = queue.get_nowait()
        if item is None:
            break
        events.append(item)

    assert events, "run produced no events"
    # The run spent most of its wall time inside blocking writes...
    assert (
        elapsed >= 2 * WRITE_DELAY
    ), f"expected the slow writes to dominate, got {elapsed:.2f}s"
    # ...yet the loop was never held for anything like one write's duration.
    assert (
        max_gap < WRITE_DELAY / 2
    ), f"event loop was starved for {max_gap * 1000:.0f}ms during the run"
