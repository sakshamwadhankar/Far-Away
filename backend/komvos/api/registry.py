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
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx
from fastapi import HTTPException

from komvos.secrets import get_secret

if TYPE_CHECKING:
    from fastapi import FastAPI

    from komvos.compiler.dag import CompiledDAG
    from komvos.endpoints.base import ModelEndpoint
    from komvos.scheduler.runner import PipelineRunner
    from komvos.state.sqlite import StateManager

logger = logging.getLogger(__name__)


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


def get_state_manager() -> StateManager:
    """The process-level StateManager, or a test override."""
    from komvos.state.sqlite import StateManager

    app = _get_app()
    if hasattr(app.state, "state_manager"):
        return cast("StateManager", app.state.state_manager)

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
    request need the NEURALFLOW_ALLOW_MOCK_ENDPOINT check.
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
            if (
                enforce_mock_gate
                and os.environ.get("NEURALFLOW_ALLOW_MOCK_ENDPOINT") != "1"
            ):
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
    """
    from komvos.scheduler.events import WsRunErrorEvent

    try:
        await runner.run(queue)
    except Exception as exc:
        logger.exception("Unhandled error in run %s", run_id)
        await queue.put(WsRunErrorEvent(run_id=run_id, error=str(exc)))
        await queue.put(None)
