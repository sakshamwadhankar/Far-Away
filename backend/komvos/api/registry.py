"""
backend/komvos/api/registry.py

In-memory run registry for the duration of the server process, plus the
endpoint-registry resolution shared by every route that can execute a
pipeline: canvas runs (/pipelines/run), estimates (/pipelines/estimate), and
Phase 3's served deployments.

WHY THIS MODULE AND NOT api/main.py: api/main.py constructs the FastAPI `app`
singleton and, going forward, mounts komvos.serve.routes on it. If the
endpoint-resolution helpers lived in main.py, serve/routes.py would have to
import main.py while main.py imports serve.routes — a circular import. This
module has no dependency on either, so both import from here safely.

`bind_app` is a light form of dependency injection: main.py calls it once,
right after constructing `app`, so `get_endpoint_registry_override` and
`get_state_manager` can read `app.state` (where tests inject overrides)
without importing the `app` object itself.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import HTTPException

from komvos.secrets import get_secret

#: Maximum events buffered for a run before the producer starts dropping new
#: ones instead of enqueueing them. Generous enough that an attached, draining
#: consumer is never affected; small enough that a run nobody consumes cannot
#: accumulate memory without bound.
RUN_QUEUE_MAX_EVENTS = 10_000

#: How long a finished run stays registered after its driving task completes,
#: so a WebSocket attaching slightly late still finds it — the /ws/run/{id}
#: handler waits up to ~4 s for a run to be registered.
REGISTRY_GRACE_SECONDS = 5.0

if TYPE_CHECKING:
    from fastapi import FastAPI

    from komvos.compiler.dag import CompiledDAG
    from komvos.endpoints.base import ModelEndpoint
    from komvos.scheduler.runner import PipelineRunner
    from komvos.state.sqlite import StateManager

logger = logging.getLogger(__name__)

#: Opt-in that allows executing pipelines containing mock endpoints. The old
#: NEURALFLOW_-prefixed name is accepted for one release with a warning.
MOCK_GATE_ENV_VAR = "KOMVOS_ALLOW_MOCK_ENDPOINT"
_LEGACY_MOCK_GATE_ENV_VAR = "NEURALFLOW_ALLOW_MOCK_ENDPOINT"


def _mock_gate_enabled() -> bool:
    """True when mock endpoints are explicitly allowed in this environment."""
    if os.environ.get(MOCK_GATE_ENV_VAR) == "1":
        return True
    # One-release compatibility with the pre-rename variable name.
    if os.environ.get(_LEGACY_MOCK_GATE_ENV_VAR) == "1":
        logger.warning(
            "Environment variable %s is deprecated and will be removed in a "
            "future release; set %s instead.",
            _LEGACY_MOCK_GATE_ENV_VAR,
            MOCK_GATE_ENV_VAR,
        )
        return True
    return False


class RunRegistry:
    """Thread-safe (asyncio-safe) in-memory store for active runs."""

    def __init__(self) -> None:
        self._runs: dict[str, PipelineRunner] = {}
        self._queues: dict[str, asyncio.Queue] = {}  # type: ignore[type-arg]

    def create(
        self,
        run_id: str,
        runner: PipelineRunner,
        queue: asyncio.Queue,  # type: ignore[type-arg]
    ) -> None:
        self._runs[run_id] = runner
        self._queues[run_id] = queue

    def get_runner(self, run_id: str) -> PipelineRunner | None:
        return self._runs.get(run_id)

    def get_queue(self, run_id: str) -> asyncio.Queue | None:  # type: ignore[type-arg]
        return self._queues.get(run_id)

    def remove(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
        self._queues.pop(run_id, None)

    def active_run_ids(self) -> list[str]:
        return list(self._runs.keys())


# Process-level singleton — imported directly by main.py
run_registry = RunRegistry()


# ---------------------------------------------------------------------------
# App binding — see module docstring for why this indirection exists.
# ---------------------------------------------------------------------------

_app: FastAPI | None = None


def bind_app(app: FastAPI) -> None:
    """Called once from main.py, immediately after `app = FastAPI(...)`."""
    global _app
    _app = app


def _get_app() -> FastAPI:
    if _app is None:  # pragma: no cover — programming error, not a runtime path
        raise RuntimeError(
            "komvos.api.registry.bind_app() was not called. "
            "It must run once, right after the FastAPI app is constructed."
        )
    return _app


def get_endpoint_registry_override() -> dict[str, ModelEndpoint]:
    """Test override endpoint registry, or empty if none was injected."""
    app = _get_app()
    if hasattr(app.state, "endpoint_registry"):
        # Starlette's State is untyped (Any); assert the contract explicitly.
        return cast("dict[str, ModelEndpoint]", app.state.endpoint_registry)
    return {}


_default_state_manager: StateManager | None = None


def build_default_state_manager() -> StateManager:
    """
    Construct the default process-wide StateManager.

    This runs table creation, the durability pragmas, the column-migration
    probe, and the legacy "~/.neuralflow" -> "~/.komvos" data migration. All of
    that must happen exactly once per process, so only two callers are allowed:
    the application lifespan (eagerly, at startup) and get_state_manager's
    lazy fallback (for ASGI transports that never run lifespan events, i.e.
    tests).
    """
    from komvos.state.sqlite import StateManager

    old_db_dir = Path(os.path.expanduser("~/.neuralflow"))
    db_dir = Path(os.path.expanduser("~/.komvos"))

    if old_db_dir.exists() and not db_dir.exists():
        try:
            old_db_dir.rename(db_dir)
        except OSError:
            db_dir.mkdir(parents=True, exist_ok=True)
    else:
        db_dir.mkdir(parents=True, exist_ok=True)

    old_db_file = db_dir / "neuralflow.db"
    if old_db_file.exists():
        old_db_file.rename(db_dir / "komvos.db")

    return StateManager(str(db_dir / "komvos.db"))


def ensure_default_state_manager() -> StateManager:
    """Return the cached default StateManager, building it exactly once."""
    global _default_state_manager
    if _default_state_manager is None:
        _default_state_manager = build_default_state_manager()
    return _default_state_manager


def get_state_manager() -> StateManager:
    """The process-level StateManager, or a test override."""
    app = _get_app()
    if hasattr(app.state, "state_manager"):
        # Test override (tests inject here directly) wins over everything.
        return cast("StateManager", app.state.state_manager)

    # Built once by the lifespan at startup, or lazily here on first use under
    # transports that do not run lifespan events. Never rebuilt per request.
    return ensure_default_state_manager()


# ---------------------------------------------------------------------------
# Endpoint resolution — descriptor -> live ModelEndpoint
# ---------------------------------------------------------------------------


async def resolve_ollama_base(model_name: str, descriptor_base: str | None) -> str:
    """
    Resolve the correct base URL for an Ollama execution.
    If a custom ngrok URL is saved, we still want local models (like qwen) to run
    against localhost:11434 if they exist locally.
    """
    if descriptor_base:
        return f"{descriptor_base.rstrip('/')}/v1"

    saved_base = get_secret("ollama_base_url")
    if not saved_base or not saved_base.startswith("http"):
        return "http://127.0.0.1:11434/v1"

    # We have a custom ngrok URL. Let's see if the requested model exists on localhost.
    try:
        # trust_env=False prevents local proxies from intercepting localhost requests
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            resp = await client.get("http://127.0.0.1:11434/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                for m in data.get("models", []):
                    # Check exact or prefix match just in case
                    if m.get("name") == model_name or m.get("name", "").startswith(
                        model_name + ":"
                    ):
                        return "http://127.0.0.1:11434/v1"
    except Exception as e:
        logger.warning(f"Failed to check local ollama tags for {model_name}: {e}")

    # Fallback to custom URL
    return f"{saved_base.rstrip('/')}/v1"


async def build_endpoint_registry(
    dag: CompiledDAG, *, enforce_mock_gate: bool = True
) -> dict[str, ModelEndpoint]:
    """
    Resolve every endpoint descriptor in `dag.pipeline.endpoints` to a live
    ModelEndpoint instance.

    Shared by /pipelines/run, /pipelines/estimate, and the serve routes so
    there is exactly one place that knows how to turn a descriptor into an
    endpoint. `enforce_mock_gate` is off for /pipelines/estimate, which never
    calls generate() on the result — only routes that might actually execute a
    request need the mock-endpoint gate check.
    """
    from komvos.endpoints.cloud import CloudEndpoint

    global_ep = get_endpoint_registry_override()
    run_endpoints: dict[str, ModelEndpoint] = {}

    for ref, descriptor in dag.pipeline.endpoints.items():
        if ref in global_ep:
            # Test override takes priority
            run_endpoints[ref] = global_ep[ref]
        elif descriptor.kind in (
            "openai",
            "anthropic",
            "google",
            "openai_compatible",
            "groq",
            "openrouter",
            "zhipu",
            "nvidia",
        ):
            run_endpoints[ref] = CloudEndpoint(
                provider=descriptor.kind,
                model_name=descriptor.model or "gpt-4o-mini",
                base_url=descriptor.base_url,
            )
        elif descriptor.kind == "mock":
            if enforce_mock_gate and not _mock_gate_enabled():
                raise HTTPException(
                    status_code=403,
                    detail="Mock endpoints are disabled in this environment.",
                )
            from komvos.endpoints.mock import MockEndpoint

            run_endpoints[ref] = MockEndpoint(id=descriptor.model or "mock-model")
        elif descriptor.kind == "ollama":
            from komvos.endpoints.ollama import OllamaEndpoint

            ollama_model = descriptor.model or "qwen2.5:3b"
            ollama_base = await resolve_ollama_base(ollama_model, descriptor.base_url)

            run_endpoints[ref] = OllamaEndpoint(
                id=f"ollama:{descriptor.model or 'default'}",
                base_url=ollama_base,
                model=ollama_model,
            )
        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported endpoint kind '{descriptor.kind}' "
                    f"for ref '{ref}'. Supported: openai, anthropic, "
                    "google, openai_compatible, ollama."
                ),
            )

    return run_endpoints


# ---------------------------------------------------------------------------
# Background task wrapper
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------

class _DropOnFullQueue:
    """
    Producer-side view of a run's event queue that drops events when full.

    The scheduler awaits ``queue.put`` once per streamed token. For an
    abandoned run — one whose client never attached a WebSocket consumer — a
    plain unbounded queue grows one event per token for the entire run, and a
    plain bounded queue would block ``put`` forever once full, stalling the
    driving task so its own cleanup could never run. Dropping when full bounds
    memory and keeps the task moving; a run with a live consumer never
    approaches the cap in practice.

    This wraps (never replaces) the queue registered in RunRegistry, so
    consumers keep reading from the same object they were handed.
    """

    def __init__(self, queue: asyncio.Queue[Any]) -> None:
        self._queue = queue

    async def put(self, item: Any) -> None:
        if self._queue.qsize() >= RUN_QUEUE_MAX_EVENTS:
            logger.warning(
                "Run event queue at capacity (%d); dropping event.",
                RUN_QUEUE_MAX_EVENTS,
            )
            return
        await self._queue.put(item)


async def run_pipeline_task(
    run_id: str,
    runner: PipelineRunner,
    queue: asyncio.Queue,  # type: ignore[type-arg]
) -> None:
    """
    Drive a PipelineRunner to completion as a background task.

    Catches any exception PipelineRunner.run() itself doesn't handle, reports
    it as a run_error event, and puts the sentinel so whatever is draining the
    queue (the /ws/run/{id} handler, or Phase 3's SSE stream) knows to stop.
    Shared by canvas runs and served requests — one place that guarantees a
    queue consumer is never left waiting forever after an unhandled error.

    This task also owns the run's registry lifecycle: because it is the only
    code guaranteed to execute for every run — including runs whose client
    never attaches a WebSocket — cleanup happens here on every path. A finished
    run lingers for REGISTRY_GRACE_SECONDS first so a slightly late WebSocket
    attach still finds it.
    """
    from komvos.scheduler.events import WsRunErrorEvent

    producer_queue = _DropOnFullQueue(queue)
    try:
        await runner.run(producer_queue)  # type: ignore[arg-type]
    except Exception as exc:
        logger.exception("Unhandled error in run %s", run_id)
        await producer_queue.put(WsRunErrorEvent(run_id=run_id, error=str(exc)))
        await producer_queue.put(None)
    finally:
        # A consumer that drained to the sentinel (WebSocket handler or served
        # SSE stream) removes the entry itself; in that case there is nothing
        # left to do and no reason to linger. Otherwise hold the entry for a
        # short grace period so a slightly late WebSocket attach still finds
        # the run, then remove it — this is the path that used to leak.
        if run_registry.get_runner(run_id) is not None:
            deadline = time.monotonic() + REGISTRY_GRACE_SECONDS
            while (
                run_registry.get_runner(run_id) is not None
                and time.monotonic() < deadline
            ):
                await asyncio.sleep(0.05)
            run_registry.remove(run_id)
