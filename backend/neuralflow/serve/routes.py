"""
backend/neuralflow/serve/routes.py

The FastAPI router for Phase 3: deploying pipelines and calling them.

Management routes (session-token auth, same as the rest of the app):
    POST   /deployments                    deploy a pipeline
    GET    /deployments                    list deployments (no key material)
    DELETE /deployments/{id}                undeploy
    POST   /deployments/{id}/rotate-key     new key, old one dies immediately

Public routes (deployment-key auth, Authorization: Bearer kv_...):
    POST   /v1/chat/completions             OpenAI-compatible, supports stream=true
    GET    /v1/models                       lists this key's deployment, OpenAI format
    POST   /v1/deployments/{id}/run         native JSON in/out

Built as a FACTORY (`create_serve_router`) rather than importing `app` from
api/main.py: main.py will mount this router, so this module must not import
main.py in return — that would be circular. Everything it needs from main.py's
world (session-token auth, pipeline compilation, endpoint resolution, run
tracking) is either passed in as a callable or imported from api/registry.py,
which — like this module — has no dependency on api/main.py.

Every served run goes through the SAME PipelineRunner + Scheduler event queue
as a canvas run (api/registry.run_pipeline_task, api/registry.run_registry).
There is no second execution or event pipeline here — only the HTTP-shaped
translation of the same WsEvent stream the WebSocket handler already speaks.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from neuralflow.compiler.dag import CompiledDAG
from neuralflow.compiler.validation import (
    PipelineValidationError,
    PipelineValidationErrors,
)
from neuralflow.scheduler.engine import EndpointRegistry
from neuralflow.scheduler.events import (
    WS_TERMINAL_EVENTS,
    WsAccessDeniedEvent,
    WsBudgetExceededEvent,
    WsNodeDoneEvent,
    WsNodeErrorEvent,
    WsRunCompletedEvent,
    WsRunErrorEvent,
    WsRunHaltedEvent,
    WsRunStoppedEvent,
    WsTokenEvent,
)
from neuralflow.scheduler.runner import PipelineRunner
from neuralflow.serve.keys import generate_key
from neuralflow.serve.models import (
    ChatCompletionRequest,
    ChatMessage,
    Deployment,
    DeploymentCreateRequest,
    DeploymentCreateResponse,
    DeploymentListResponse,
    DeploymentMappingError,
    DeploymentSummary,
    NativeRunResponse,
    RotateKeyResponse,
    UndeployResponse,
    native_input_fields,
    native_output_fields,
    resolve_chat_io,
)
from neuralflow.serve.ratelimit import RateLimiter
from neuralflow.serve.store import DeploymentStore
from neuralflow.state.sqlite import StateManager

#: Served requests get a wall-clock ceiling that canvas runs don't: a canvas
#: run is watched by a human who can hit Stop, a served HTTP request is not.
#: Not user-configurable in this phase — see README.md "Known limitations".
SERVED_WALL_CLOCK_BUDGET_SECONDS = 300.0

# One rate limiter for the process's lifetime — see serve/ratelimit.py for why
# this is intentionally in-memory and not persisted.
_rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# Deployment store access — mirrors api/registry.py's get_state_manager
# pattern: a test override via app.state, or a default instance opened
# against the same ~/.neuralflow/neuralflow.db file StateManager uses.
# ---------------------------------------------------------------------------


def get_deployment_store(request: Request) -> DeploymentStore:
    if hasattr(request.app.state, "deployment_store"):
        return cast("DeploymentStore", request.app.state.deployment_store)
    db_dir = Path(os.path.expanduser("~/.neuralflow"))
    db_dir.mkdir(parents=True, exist_ok=True)
    return DeploymentStore(str(db_dir / "neuralflow.db"))


def _to_summary(deployment: Deployment) -> DeploymentSummary:
    return DeploymentSummary(
        id=deployment.id,
        name=deployment.name,
        expose_lan=deployment.expose_lan,
        rate_limit_per_minute=deployment.rate_limit_per_minute,
        chat_input_node=deployment.chat_input_node,
        chat_output_node=deployment.chat_output_node,
        created_at=deployment.created_at,
        request_count=deployment.request_count,
        error_count=deployment.error_count,
        last_request_at=deployment.last_request_at,
    )


# ---------------------------------------------------------------------------
# Deployment-key auth + rate limiting (public routes)
# ---------------------------------------------------------------------------


def _make_verify_deployment_key() -> Callable[..., Awaitable[Deployment]]:
    """
    Returns the deployment-key auth dependency.

    A factory (rather than a bare module-level function) only so it closes
    over nothing surprising — kept symmetrical with create_serve_router below.
    """

    async def verify_deployment_key(
        request: Request,
        store: DeploymentStore = Depends(get_deployment_store),
    ) -> Deployment:
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            raise HTTPException(
                status_code=401,
                detail=(
                    "Missing Authorization header. "
                    "Expected: Authorization: Bearer kv_..."
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )
        provided = auth_header[len("bearer ") :].strip()
        if not provided:
            raise HTTPException(
                status_code=401,
                detail="Empty bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        deployment = store.find_by_key(provided)
        if deployment is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or revoked deployment key.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not _rate_limiter.check(deployment.id, deployment.rate_limit_per_minute):
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded for this deployment "
                    f"({deployment.rate_limit_per_minute} req/min)."
                ),
            )

        return deployment

    return verify_deployment_key


def _is_loopback(host: str | None) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


def _enforce_lan_policy(deployment: Deployment, request: Request) -> None:
    """
    Reject a non-loopback caller unless this deployment opted in to LAN access.

    The backend process itself is bound to 127.0.0.1 (Phase 1), so in normal
    operation a non-loopback request can never physically arrive. This check
    is defense in depth for the case where it does — a manual `--host
    0.0.0.0` launch, or a future packaging change — so a deployment that never
    opted in stays inert even then, rather than silently trusting the process
    bind to do the whole job.
    """
    client_host = request.client.host if request.client else None
    if not deployment.expose_lan and not _is_loopback(client_host):
        raise HTTPException(
            status_code=403,
            detail=(
                "This deployment is not exposed beyond 127.0.0.1. Enable LAN "
                "access on the deployment to allow non-local requests."
            ),
        )


# ---------------------------------------------------------------------------
# Chat message <-> pipeline value mapping
# ---------------------------------------------------------------------------


def _messages_to_prompt(messages: list[ChatMessage]) -> str:
    """
    Collapse an OpenAI `messages` array into the single text value a
    pipeline's input node receives.

    A single message (the common case — most tools built against a Komvos
    deployment send one user turn) is passed through as-is. Multiple messages
    are joined into a "role: content" transcript, since the pipeline's input
    node has no native concept of a message list.
    """
    if len(messages) == 1:
        return messages[0].content
    return "\n".join(f"{m.role}: {m.content}" for m in messages)


def _extract_node_value(dag: CompiledDAG, node_id: str, outputs: dict[str, Any]) -> Any:
    """
    Pull "the" value out of a node's final outputs dict.

    Output nodes' outputs are keyed by their declared INPUT port names (see
    executors/input_output.py — OutputExecutor passes its inputs straight
    through). We take the first declared port, which is what every template
    and the UI-created access/output nodes use; a node with no ports at all
    (shouldn't happen for output nodes) falls back to the first value present.
    """
    node = next((n for n in dag.pipeline.nodes if n.id == node_id), None)
    if node is not None and node.inputs:
        return outputs.get(node.inputs[0].name)
    return next(iter(outputs.values()), None)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _direct_model_source(dag: CompiledDAG, output_node_id: str) -> str | None:
    """
    The model node id feeding `output_node_id`, if — and only if — there is
    exactly one, and it connects directly.

    Token-level SSE streaming only makes sense for this direct topology
    (input -> model -> output): a transform or router between the model and
    the output operates on the whole finished string, not token by token. Any
    other shape falls back to a single buffered delta chunk in
    _sse_chat_stream — always correct, just not incrementally streamed.
    """
    preds = dag.reverse_adj.get(output_node_id, [])
    if len(preds) != 1:
        return None
    node = next((n for n in dag.pipeline.nodes if n.id == preds[0]), None)
    return preds[0] if node is not None and node.type == "model" else None


# ---------------------------------------------------------------------------
# Draining a run to completion (non-streaming chat + native paths)
# ---------------------------------------------------------------------------


class _RunOutcome:
    __slots__ = ("node_outputs", "error", "tokens_in", "tokens_out")

    def __init__(self) -> None:
        self.node_outputs: dict[str, dict[str, Any]] = {}
        self.error: str | None = None
        self.tokens_in = 0
        self.tokens_out = 0


async def _drain_to_completion(queue: asyncio.Queue) -> _RunOutcome:  # type: ignore[type-arg]
    """
    Consume a run's event queue until it terminates, collecting every node's
    final outputs. Mirrors the /ws/run/{id} handler's termination rule
    (None sentinel or a WS_TERMINAL_EVENTS member) exactly — this is the same
    stream, just read to the end instead of forwarded frame by frame.
    """
    outcome = _RunOutcome()
    while True:
        event = await queue.get()
        if event is None:
            break
        if isinstance(event, WsNodeDoneEvent):
            outcome.node_outputs[event.node_id] = event.outputs
        elif isinstance(event, WsRunCompletedEvent):
            outcome.tokens_in = event.total_tokens_in
            outcome.tokens_out = event.total_tokens_out
        elif isinstance(event, WsAccessDeniedEvent):
            outcome.error = f"Node '{event.node_id}' denied: {event.reason}"
        elif isinstance(event, WsNodeErrorEvent):
            outcome.error = f"Node '{event.node_id}' failed: {event.error}"
        elif isinstance(event, WsRunErrorEvent):
            outcome.error = event.error
        elif isinstance(event, WsRunHaltedEvent):
            outcome.error = outcome.error or f"Run halted: {event.reason}"
        elif isinstance(event, WsBudgetExceededEvent):
            outcome.error = outcome.error or "Budget exceeded."
        elif isinstance(event, WsRunStoppedEvent):
            outcome.error = outcome.error or "Run stopped."
        if isinstance(event, WS_TERMINAL_EVENTS):
            break
    return outcome


# ---------------------------------------------------------------------------
# OpenAI wire-format helpers
# ---------------------------------------------------------------------------


def _sse_frame(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _chat_chunk(
    chunk_id: str,
    created: int,
    model: str,
    *,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _chat_response(
    deployment_id: str, content: str, *, tokens_in: int, tokens_out: int
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": deployment_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": tokens_in,
            "completion_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
    }


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_serve_router(
    *,
    verify_token_dep: Callable[..., Any],
    compile_pipeline_fn: Callable[..., CompiledDAG],
    build_endpoint_registry_fn: Callable[[CompiledDAG], Awaitable[dict[str, Any]]],
    get_state_manager_fn: Callable[[], StateManager],
    run_registry: Any,
    run_task_fn: Callable[
        [str, PipelineRunner, asyncio.Queue[Any]], Coroutine[Any, Any, None]
    ],
) -> APIRouter:
    """
    Build the serve router. All shared machinery is injected rather than
    imported from api/main.py — see the module docstring for why.
    """
    router = APIRouter()
    verify_deployment_key = _make_verify_deployment_key()

    def _compile_or_422(pipeline: dict[str, Any], *, mode: str) -> CompiledDAG:
        try:
            return compile_pipeline_fn(pipeline, mode=mode)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        except PipelineValidationErrors as exc:
            raise HTTPException(status_code=422, detail=exc.errors) from exc
        except PipelineValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def _start_run(
        dag: CompiledDAG,
        deployment: Deployment,
        mapped_inputs: dict[str, dict[str, Any]],
    ) -> tuple[str, asyncio.Queue[Any]]:
        endpoints = await build_endpoint_registry_fn(dag)
        registry = EndpointRegistry(endpoints)
        run_id = str(uuid.uuid4())
        queue: asyncio.Queue[Any] = asyncio.Queue()
        runner = PipelineRunner(
            run_id=run_id,
            dag=dag,
            registry=registry,
            state_manager=get_state_manager_fn(),
            deployment_id=deployment.id,
            initial_inputs=mapped_inputs,
            budget_wall_clock_seconds=SERVED_WALL_CLOCK_BUDGET_SECONDS,
        )
        run_registry.create(run_id, runner, queue)
        asyncio.create_task(run_task_fn(run_id, runner, queue), name=f"run-{run_id}")
        return run_id, queue

    # -- Management routes (session-token auth) -------------------------

    @router.post(
        "/deployments",
        response_model=DeploymentCreateResponse,
        status_code=201,
        dependencies=[Depends(verify_token_dep)],
    )
    async def create_deployment(
        body: DeploymentCreateRequest,
        request: Request,
        store: DeploymentStore = Depends(get_deployment_store),
    ) -> DeploymentCreateResponse:
        dag = _compile_or_422(body.pipeline, mode="served")

        try:
            input_id, output_id = resolve_chat_io(dag.pipeline)
        except DeploymentMappingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        deployment_id = str(uuid.uuid4())
        plaintext_key, key_hash = generate_key()
        deployment = Deployment(
            id=deployment_id,
            name=body.name or dag.pipeline.name,
            pipeline=body.pipeline,
            key_hash=key_hash,
            expose_lan=body.expose_lan,
            rate_limit_per_minute=body.rate_limit_per_minute,
            chat_input_node=input_id,
            chat_output_node=output_id,
            created_at=int(time.time() * 1000),
        )
        store.create(deployment)

        base_url = f"{request.url.scheme}://{request.url.netloc}/v1"
        return DeploymentCreateResponse(
            deployment_id=deployment_id, key=plaintext_key, base_url=base_url
        )

    @router.get(
        "/deployments",
        response_model=DeploymentListResponse,
        dependencies=[Depends(verify_token_dep)],
    )
    async def list_deployments(
        store: DeploymentStore = Depends(get_deployment_store),
    ) -> DeploymentListResponse:
        return DeploymentListResponse(
            deployments=[_to_summary(d) for d in store.list()]
        )

    @router.delete(
        "/deployments/{deployment_id}",
        response_model=UndeployResponse,
        dependencies=[Depends(verify_token_dep)],
    )
    async def undeploy(
        deployment_id: str,
        store: DeploymentStore = Depends(get_deployment_store),
    ) -> UndeployResponse:
        deleted = store.delete(deployment_id)
        _rate_limiter.reset(deployment_id)
        return UndeployResponse(deployment_id=deployment_id, deleted=deleted)

    @router.post(
        "/deployments/{deployment_id}/rotate-key",
        response_model=RotateKeyResponse,
        dependencies=[Depends(verify_token_dep)],
    )
    async def rotate_key(
        deployment_id: str,
        store: DeploymentStore = Depends(get_deployment_store),
    ) -> RotateKeyResponse:
        if store.get(deployment_id) is None:
            raise HTTPException(status_code=404, detail="Deployment not found.")
        plaintext_key, key_hash = generate_key()
        store.rotate_key(deployment_id, key_hash)
        return RotateKeyResponse(deployment_id=deployment_id, key=plaintext_key)

    # -- Public routes (deployment-key auth) -----------------------------

    @router.get("/v1/models")
    async def list_models(
        deployment: Deployment = Depends(verify_deployment_key),
    ) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": deployment.id,
                    "object": "model",
                    "created": deployment.created_at // 1000,
                    "owned_by": "komvos",
                }
            ],
        }

    @router.post("/v1/chat/completions")
    async def chat_completions(
        body: ChatCompletionRequest,
        request: Request,
        deployment: Deployment = Depends(verify_deployment_key),
        store: DeploymentStore = Depends(get_deployment_store),
    ) -> Response:
        if body.model and body.model != deployment.id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"model '{body.model}' does not match this deployment "
                    f"key's deployment ('{deployment.id}')."
                ),
            )
        _enforce_lan_policy(deployment, request)

        dag = _compile_or_422(deployment.pipeline, mode="served")
        input_node = next(
            n for n in dag.pipeline.nodes if n.id == deployment.chat_input_node
        )
        prompt = _messages_to_prompt(body.messages)
        mapped_inputs = {
            deployment.chat_input_node: {
                port.name: prompt for port in input_node.outputs
            }
        }

        if body.stream:
            return StreamingResponse(
                _stream_chat(dag, deployment, mapped_inputs, store),
                media_type="text/event-stream",
            )

        run_id, queue = await _start_run(dag, deployment, mapped_inputs)
        try:
            outcome = await _drain_to_completion(queue)
        finally:
            run_registry.remove(run_id)

        if outcome.error:
            store.record_request(deployment.id, success=False)
            raise HTTPException(status_code=502, detail=outcome.error)

        store.record_request(deployment.id, success=True)
        content = _as_text(
            _extract_node_value(
                dag,
                deployment.chat_output_node,
                outcome.node_outputs.get(deployment.chat_output_node, {}),
            )
        )
        return JSONResponse(
            _chat_response(
                deployment.id,
                content,
                tokens_in=outcome.tokens_in,
                tokens_out=outcome.tokens_out,
            )
        )

    async def _stream_chat(
        dag: CompiledDAG,
        deployment: Deployment,
        mapped_inputs: dict[str, dict[str, Any]],
        store: DeploymentStore,
    ) -> AsyncIterator[str]:
        run_id, queue = await _start_run(dag, deployment, mapped_inputs)
        chunk_id = f"chatcmpl-{run_id}"
        created = int(time.time())
        stream_source = _direct_model_source(dag, deployment.chat_output_node)

        outcome = _RunOutcome()
        try:
            yield _sse_frame(
                _chat_chunk(
                    chunk_id, created, deployment.id, delta={"role": "assistant"}
                )
            )
            while True:
                event = await queue.get()
                if event is None:
                    break
                if (
                    isinstance(event, WsTokenEvent)
                    and stream_source
                    and event.node_id == stream_source
                ):
                    yield _sse_frame(
                        _chat_chunk(
                            chunk_id,
                            created,
                            deployment.id,
                            delta={"content": event.text},
                        )
                    )
                elif isinstance(event, WsNodeDoneEvent):
                    outcome.node_outputs[event.node_id] = event.outputs
                elif isinstance(event, WsRunCompletedEvent):
                    outcome.tokens_in = event.total_tokens_in
                    outcome.tokens_out = event.total_tokens_out
                elif isinstance(event, WsAccessDeniedEvent):
                    outcome.error = f"Node '{event.node_id}' denied: {event.reason}"
                elif isinstance(event, WsNodeErrorEvent):
                    outcome.error = f"Node '{event.node_id}' failed: {event.error}"
                elif isinstance(event, WsRunErrorEvent):
                    outcome.error = event.error
                elif isinstance(event, WsRunHaltedEvent):
                    outcome.error = outcome.error or f"Run halted: {event.reason}"
                elif isinstance(event, WsBudgetExceededEvent):
                    outcome.error = outcome.error or "Budget exceeded."
                elif isinstance(event, WsRunStoppedEvent):
                    outcome.error = outcome.error or "Run stopped."
                if isinstance(event, WS_TERMINAL_EVENTS):
                    break
        finally:
            run_registry.remove(run_id)

        if outcome.error:
            store.record_request(deployment.id, success=False)
            yield _sse_frame(
                {"error": {"message": outcome.error, "type": "komvos_error"}}
            )
            yield "data: [DONE]\n\n"
            return

        if not stream_source:
            # No direct model -> output edge: token-level deltas were never
            # possible for this topology, so send the whole result as one
            # buffered delta instead of nothing. See _direct_model_source.
            content = _as_text(
                _extract_node_value(
                    dag,
                    deployment.chat_output_node,
                    outcome.node_outputs.get(deployment.chat_output_node, {}),
                )
            )
            yield _sse_frame(
                _chat_chunk(
                    chunk_id, created, deployment.id, delta={"content": content}
                )
            )

        store.record_request(deployment.id, success=True)
        yield _sse_frame(
            _chat_chunk(
                chunk_id, created, deployment.id, delta={}, finish_reason="stop"
            )
        )
        yield "data: [DONE]\n\n"

    @router.post(
        "/v1/deployments/{deployment_id}/run", response_model=NativeRunResponse
    )
    async def native_run(
        deployment_id: str,
        body: dict[str, Any],
        request: Request,
        deployment: Deployment = Depends(verify_deployment_key),
        store: DeploymentStore = Depends(get_deployment_store),
    ) -> NativeRunResponse:
        if deployment_id != deployment.id:
            # The key only ever resolves to its own deployment; a mismatched
            # path id is treated as "not found" rather than leaking that some
            # OTHER id exists.
            raise HTTPException(status_code=404, detail="Deployment not found.")
        _enforce_lan_policy(deployment, request)

        dag = _compile_or_422(deployment.pipeline, mode="served")
        nodes_by_id = {n.id: n for n in dag.pipeline.nodes}

        mapped_inputs: dict[str, dict[str, Any]] = {}
        for node_id, field in native_input_fields(dag.pipeline).items():
            if field not in body:
                continue  # not provided — keep the node's default "" seed
            node = nodes_by_id[node_id]
            mapped_inputs[node_id] = {port.name: body[field] for port in node.outputs}

        run_id, queue = await _start_run(dag, deployment, mapped_inputs)
        try:
            outcome = await _drain_to_completion(queue)
        finally:
            run_registry.remove(run_id)

        if outcome.error:
            store.record_request(deployment.id, success=False)
            raise HTTPException(status_code=502, detail=outcome.error)

        store.record_request(deployment.id, success=True)
        result: dict[str, Any] = {}
        for node_id, field in native_output_fields(dag.pipeline).items():
            result[field] = _extract_node_value(
                dag, node_id, outcome.node_outputs.get(node_id, {})
            )

        return NativeRunResponse(outputs=result)

    return router
