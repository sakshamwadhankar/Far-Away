"""
backend/neuralflow/api/main.py

NeuralFlow FastAPI application — P2 Phase 2.

SECURITY:
  - Bound to 127.0.0.1 only (enforced via uvicorn launch args, not here).
  - Every HTTP route requires Authorization: Bearer <token>.
  - WebSocket /ws/run/{run_id} authenticates via ?token=<token> query param
    (browsers cannot set arbitrary headers on WS upgrade requests).

ROUTES:
  GET  /health                   — liveness probe, no auth
  GET  /models                   — list configured endpoints + capabilities
  POST /pipelines/run            — validate pipeline, start run, return run_id
  POST /runs/{run_id}/stop       — kill-switch for an active run
  WS   /ws/run/{run_id}          — stream WsEvent JSON frames until run ends
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError

from neuralflow.api.auth import verify_token
from neuralflow.api.models import (
    HealthResponse,
    ModelInfo,
    ModelsResponse,
    RunRequest,
    RunResponse,
    StopResponse,
)
from neuralflow.api.registry import run_registry
from neuralflow.compiler.dag import compile as compile_pipeline
from neuralflow.compiler.validation import PipelineValidationError
from neuralflow.endpoints.base import ModelEndpoint
from neuralflow.endpoints.cloud import CloudEndpoint
from neuralflow.scheduler.engine import EndpointRegistry
from neuralflow.scheduler.events import WS_TERMINAL_EVENTS
from neuralflow.scheduler.runner import PipelineRunner

logger = logging.getLogger(__name__)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="NeuralFlow Backend",
    version="0.1.0",
    description="Local execution backend for NeuralFlow — bound to 127.0.0.1.",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global endpoint registry — injected via app.state in tests;
# built from pipeline descriptors at run-time in production.
# ---------------------------------------------------------------------------


def _global_registry() -> dict[str, ModelEndpoint]:
    """Return the process-level endpoint registry or test override."""
    if hasattr(app.state, "endpoint_registry"):
        return app.state.endpoint_registry  # type: ignore[return-value]
    return {}


# ---------------------------------------------------------------------------
# GET /health  (no auth — liveness probe used by Electron after spawn)
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=app.version)


# ---------------------------------------------------------------------------
# GET /models  (auth required)
# ---------------------------------------------------------------------------


@app.get("/models", response_model=ModelsResponse, dependencies=[Depends(verify_token)])
async def list_models() -> ModelsResponse:
    """
    Return capabilities for all registered endpoints.
    Phase 4 will fetch live model lists from each provider dynamically.
    """
    registry = _global_registry()
    infos: list[ModelInfo] = []
    for eid, ep in registry.items():
        caps = ep.capabilities()
        parts = eid.split(":", 1)
        provider = parts[0] if len(parts) == 2 else "unknown"
        model_name = parts[1] if len(parts) == 2 else eid
        infos.append(
            ModelInfo(
                endpoint_id=eid,
                provider=provider,
                model_name=model_name,
                max_context=caps.max_context,
                json_mode=caps.json_mode,
                tools=caps.tools,
                vision=caps.vision,
            )
        )
    return ModelsResponse(models=infos)


# ---------------------------------------------------------------------------
# POST /pipelines/run  (auth required)
# ---------------------------------------------------------------------------


@app.post(
    "/pipelines/run",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_token)],
)
async def start_run(body: RunRequest) -> RunResponse:
    """
    1. Parse + semantically validate the pipeline JSON via compiler.compile().
    2. Build an EndpointRegistry for this run (from app.state override or
       CloudEndpoint instances derived from pipeline.endpoints descriptors).
    3. Create a PipelineRunner with budget caps, register it, launch background task.
    4. Return the run_id immediately — client connects via WebSocket for events.
    """
    # ── 1. Compile (parse + validate) ────────────────────────────────────────
    try:
        dag = compile_pipeline(body.pipeline)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())
    except PipelineValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # ── 2. Build endpoint registry for this run ───────────────────────────────
    global_ep = _global_registry()
    run_endpoints: dict[str, ModelEndpoint] = {}

    for ref, descriptor in dag.pipeline.endpoints.items():
        if ref in global_ep:
            # Test override takes priority
            run_endpoints[ref] = global_ep[ref]
        else:
            if descriptor.kind in ("openai", "anthropic", "google", "openai_compatible"):
                run_endpoints[ref] = CloudEndpoint(
                    provider=descriptor.kind,
                    model_name=descriptor.model or "gpt-4o-mini",
                    base_url=descriptor.base_url,
                )
            elif descriptor.kind == "mock":
                if os.environ.get("NEURALFLOW_ALLOW_MOCK_ENDPOINT") != "1":
                    raise HTTPException(
                        status_code=403,
                        detail="Mock endpoints are disabled in this environment.",
                    )
                from neuralflow.endpoints.mock import MockEndpoint
                run_endpoints[ref] = MockEndpoint(id=descriptor.model or "mock-model")
            else:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Unsupported endpoint kind '{descriptor.kind}' for ref '{ref}'. "
                        "Supported: openai, anthropic, google, openai_compatible."
                    ),
                )

    endpoint_registry = EndpointRegistry(run_endpoints)

    # ── 3. Create runner + queue ──────────────────────────────────────────────
    run_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]

    runner = PipelineRunner(
        run_id=run_id,
        dag=dag,
        registry=endpoint_registry,
        budget_usd=body.budget_usd,
        budget_wall_clock_seconds=body.budget_wall_clock_seconds,
    )

    run_registry.create(run_id, runner, queue)

    # ── 4. Launch background task ────────────────────────────────────────────
    asyncio.create_task(
        _run_task(run_id, runner, queue),
        name=f"run-{run_id}",
    )

    return RunResponse(run_id=run_id)


async def _run_task(
    run_id: str,
    runner: PipelineRunner,
    queue: asyncio.Queue,  # type: ignore[type-arg]
) -> None:
    """Wrapper: catches any uncaught exception and puts sentinel None."""
    try:
        await runner.run(queue)
    except Exception as exc:
        logger.exception("Unhandled error in run %s", run_id)
        from neuralflow.scheduler.events import WsRunErrorEvent
        await queue.put(WsRunErrorEvent(run_id=run_id, error=str(exc)))
        await queue.put(None)


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/stop  (auth required)
# ---------------------------------------------------------------------------


@app.post(
    "/runs/{run_id}/stop",
    response_model=StopResponse,
    dependencies=[Depends(verify_token)],
)
async def stop_run(run_id: str) -> StopResponse:
    """Kill-switch: cancel an active run. Returns 404 if already finished."""
    runner = run_registry.get_runner(run_id)
    if runner is None:
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found or already completed.",
        )
    runner.stop()
    return StopResponse(run_id=run_id, halted=True)


# ---------------------------------------------------------------------------
# WebSocket /ws/run/{run_id}
# ---------------------------------------------------------------------------

_SESSION_TOKEN = os.environ.get("NEURALFLOW_SESSION_TOKEN")


@app.websocket("/ws/run/{run_id}")
async def ws_run(
    websocket: WebSocket,
    run_id: str,
    token: str = Query(..., description="Session auth token"),
) -> None:
    """
    Stream WsEvent JSON frames until the run terminates.
    Authenticated via ?token= query parameter.
    """
    # ── Auth ──────────────────────────────────────────────────────────────────
    session_token = os.environ.get("NEURALFLOW_SESSION_TOKEN")
    if session_token and token != session_token:
        await websocket.close(code=4001, reason="Invalid session token.")
        return
    if not token:
        await websocket.close(code=4001, reason="Missing token.")
        return

    # ── Wait for run to be registered (POST may still be returning) ───────────
    for _ in range(40):  # up to 4 s
        queue = run_registry.get_queue(run_id)
        if queue is not None:
            break
        await asyncio.sleep(0.1)
    else:
        await websocket.close(code=4004, reason=f"Run '{run_id}' not found.")
        return

    await websocket.accept()

    try:
        while True:
            event = await queue.get()
            if event is None:
                break  # sentinel — task finished
            payload = event.model_dump_json()
            try:
                await websocket.send_text(payload)
            except WebSocketDisconnect:
                runner = run_registry.get_runner(run_id)
                if runner:
                    runner.stop()
                break
            if isinstance(event, WS_TERMINAL_EVENTS):
                break
    finally:
        run_registry.remove(run_id)
        try:
            await websocket.close()
        except Exception:
            pass
