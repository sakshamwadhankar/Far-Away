"""
backend/komvos/api/main.py

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
import contextlib
import json
import logging
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import keyring
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from komvos.api.auth import check_token, is_dev_mode, verify_token
from komvos.api.models import (
    ApiKeysResponse,
    ApiKeysUpdateRequest,
    CustomNodeResponse,
    EstimateResponse,
    HealthResponse,
    LibraryTemplateResponse,
    ModelInfo,
    ModelsResponse,
    NodeEstimate,
    PublishTemplateRequest,
    PublishTemplateResponse,
    RunRequest,
    RunResponse,
    SaveCustomNodeRequest,
    SaveCustomNodeResponse,
    StopResponse,
)
from komvos.api.registry import (
    bind_app,
    build_endpoint_registry,
    run_pipeline_task,
    run_registry,
)
from komvos.api.registry import (
    get_endpoint_registry_override as _global_registry,
)
from komvos.api.registry import (
    get_state_manager as _global_state_manager,
)
from komvos.compiler.dag import compile as compile_pipeline
from komvos.compiler.models import Pipeline
from komvos.compiler.validation import (
    PipelineValidationError,
    PipelineValidationErrors,
)
from komvos.scheduler.engine import EndpointRegistry
from komvos.scheduler.events import WS_TERMINAL_EVENTS
from komvos.scheduler.runner import PipelineRunner
from komvos.secrets import get_secret

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CORS allowlist
#
# The renderer is an Electron window, not a website. In a packaged build it is
# served over the custom "komvos" app protocol (registered in
# apps/desktop/src/main.ts), so its requests carry the real origin
# "komvos://bundle". That origin is forgeable by no one: a web page — including
# one embedded in a sandboxed iframe, which sends the opaque origin "null" —
# cannot make its browser produce it. The old "null"/"file://" entries were
# removed for exactly that reason.
#
# The Vite dev server origins are added ONLY under KOMVOS_DEV=1. Without that
# opt-in no http(s) origin is allowed, so a site the user happens to be visiting
# cannot drive their pipelines or spend their API credits.
# ---------------------------------------------------------------------------

_ELECTRON_RENDERER_ORIGINS = ["komvos://bundle"]

_DEV_SERVER_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _allowed_origins() -> list[str]:
    """Build the CORS allowlist for this process."""
    origins = list(_ELECTRON_RENDERER_ORIGINS)
    if is_dev_mode():
        origins.extend(_DEV_SERVER_ORIGINS)
    return origins


_DEV_MODE = is_dev_mode()

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application startup/shutdown.

    Builds the process-wide StateManager exactly once, eagerly: table
    creation, the durability pragmas, the column-migration probe and the
    legacy-directory migration are startup work, not per-request work. The
    instance is cached in api/registry; get_state_manager still honours a test
    override injected into app.state first.

    With the StateManager in place, applies the active governance profile's
    retention window. Order matters: the sweep needs the manager to exist.
    """
    from komvos.api.registry import ensure_default_state_manager

    ensure_default_state_manager()

    try:
        sm = _global_state_manager()
        from komvos.governance.profiles import (
            get_active_profile_name,
            load_profile,
        )

        active_name = get_active_profile_name(sm)
        profile = load_profile(active_name, sm)
        if profile and profile.retention_window:
            sm.sweep_retention(profile.retention_window)
    except Exception as exc:
        logger.warning(f"Startup retention sweep skipped/failed: {exc}")
    yield


app = FastAPI(
    title="Komvos Backend",
    version="0.1.0",
    description="Local execution backend for NeuralFlow — bound to 127.0.0.1.",
    # The interactive docs enumerate the entire API surface, so they are a
    # developer convenience only.
    docs_url="/docs" if _DEV_MODE else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _DEV_MODE else None,
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# `_global_registry`, `_global_state_manager`, and `build_endpoint_registry`
# live in api/registry.py — see that module's docstring for why. `bind_app`
# below is what lets them reach this process's `app.state`.
bind_app(app)


# ---------------------------------------------------------------------------
# GET /health  (no auth — liveness probe used by Electron after spawn)
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=app.version)


# ---------------------------------------------------------------------------
# GET /health/ollama  (no auth — used for onboarding)
# ---------------------------------------------------------------------------


@app.get("/health/ollama")
async def health_ollama() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://127.0.0.1:11434/")
            if resp.status_code == 200:
                return {"status": "ok", "message": "Ollama is running"}
    except Exception:
        pass
    return {"status": "error", "message": "Ollama not reachable"}


# ---------------------------------------------------------------------------
# GET /health/hermes  (no auth — used for Hermes Agent detection)
# ---------------------------------------------------------------------------


@app.get("/health/hermes")
async def health_hermes() -> dict[str, Any]:
    from komvos.endpoints.hermes import probe_hermes_server

    return await probe_hermes_server()


# ---------------------------------------------------------------------------
# GET /health/desktop  (no auth — used for desktop server detection)
# ---------------------------------------------------------------------------


@app.get("/health/desktop")
async def health_desktop() -> dict[str, Any]:
    from komvos.desktop.detection import probe_computer_server

    return await probe_computer_server()



# ---------------------------------------------------------------------------
# GET /pipelines/templates  (auth required)
# ---------------------------------------------------------------------------


@app.get("/pipelines/templates", dependencies=[Depends(verify_token)])
async def get_templates() -> list[dict[str, Any]]:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        templates_dir = Path(sys._MEIPASS) / "templates"
    else:
        templates_dir = Path(__file__).parent.parent.parent.parent / "templates"
    templates = []
    if not templates_dir.exists():
        return []

    for file in templates_dir.glob("*.json"):
        try:
            with open(file, encoding="utf-8") as f:
                data = json.load(f)
                pipeline = Pipeline.model_validate(data)
                templates.append(pipeline.model_dump(exclude_none=True, by_alias=True))
        except Exception as e:
            logger.warning("Failed to load template %s: %s", file.name, e)

    return templates


# ---------------------------------------------------------------------------
# POST /library/publish  (auth required)
# ---------------------------------------------------------------------------


@app.post(
    "/library/publish",
    response_model=PublishTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_token)],
)
async def publish_library_template(
    body: PublishTemplateRequest,
) -> PublishTemplateResponse:
    """Validate a pipeline and publish it to the community library."""
    # Validate pipeline schema
    try:
        Pipeline.model_validate(body.pipeline)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid pipeline: {exc}") from exc

    template_id = str(uuid.uuid4())
    sm = _global_state_manager()
    sm.publish_template(
        template_id=template_id,
        name=body.name,
        description=body.description,
        author=body.author,
        tags=body.tags,
        pipeline_json=json.dumps(body.pipeline),
    )
    return PublishTemplateResponse(id=template_id)


# ---------------------------------------------------------------------------
# GET /library/templates  (auth required)
# ---------------------------------------------------------------------------


@app.get(
    "/library/templates",
    response_model=list[LibraryTemplateResponse],
    dependencies=[Depends(verify_token)],
)
async def list_library_templates() -> list[LibraryTemplateResponse]:
    """Return all community-published templates."""
    sm = _global_state_manager()
    rows = sm.list_library_templates()
    return [LibraryTemplateResponse(**r) for r in rows]


# ---------------------------------------------------------------------------
# DELETE /library/templates/{template_id}  (auth required)
# ---------------------------------------------------------------------------


@app.delete(
    "/library/templates/{template_id}",
    dependencies=[Depends(verify_token)],
)
async def delete_library_template(template_id: str) -> dict[str, Any]:
    """Remove a template from the community library."""
    sm = _global_state_manager()
    deleted = sm.delete_library_template(template_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Template '{template_id}' not found."
        )
    return {"deleted": True, "id": template_id}


# ---------------------------------------------------------------------------
# POST /custom-nodes  (auth required)
# ---------------------------------------------------------------------------


@app.post(
    "/custom-nodes",
    response_model=SaveCustomNodeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_token)],
)
async def save_custom_node(body: SaveCustomNodeRequest) -> SaveCustomNodeResponse:
    """Save a user-defined custom node definition."""
    node_id = str(uuid.uuid4())
    sm = _global_state_manager()
    sm.save_custom_node(
        node_id=node_id,
        name=body.name,
        description=body.description,
        author=body.author,
        icon_color=body.icon_color,
        inputs_json=json.dumps([p.model_dump() for p in body.inputs]),
        outputs_json=json.dumps([p.model_dump() for p in body.outputs]),
        template=body.template,
        tags=body.tags,
    )
    return SaveCustomNodeResponse(id=node_id)


# ---------------------------------------------------------------------------
# GET /custom-nodes  (auth required)
# ---------------------------------------------------------------------------


@app.get(
    "/custom-nodes",
    response_model=list[CustomNodeResponse],
    dependencies=[Depends(verify_token)],
)
async def list_custom_nodes() -> list[CustomNodeResponse]:
    """Return all user-defined custom node definitions."""
    sm = _global_state_manager()
    rows = sm.list_custom_nodes()
    return [CustomNodeResponse(**r) for r in rows]


# ---------------------------------------------------------------------------
# DELETE /custom-nodes/{node_id}  (auth required)
# ---------------------------------------------------------------------------


@app.delete(
    "/custom-nodes/{node_id}",
    dependencies=[Depends(verify_token)],
)
async def delete_custom_node(node_id: str) -> dict[str, Any]:
    """Remove a custom node definition."""
    sm = _global_state_manager()
    deleted = sm.delete_custom_node(node_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Custom node '{node_id}' not found."
        )
    return {"deleted": True, "id": node_id}


# ---------------------------------------------------------------------------
# POST /custom-nodes/{node_id}/publish  (auth required)
# ---------------------------------------------------------------------------


@app.post(
    "/custom-nodes/{node_id}/publish",
    response_model=PublishTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_token)],
)
async def publish_custom_node(node_id: str) -> PublishTemplateResponse:
    """Publish a custom node to the library as a single-node pipeline template."""
    sm = _global_state_manager()
    cn = sm.get_custom_node(node_id)
    if cn is None:
        raise HTTPException(
            status_code=404, detail=f"Custom node '{node_id}' not found."
        )

    # Build a single-node pipeline from the custom node definition
    pipeline = {
        "schema_version": "2.0",
        "id": str(uuid.uuid4()),
        "name": f"Custom: {cn['name']}",
        "version": "1.0.0",
        "description": cn.get("description", ""),
        "endpoints": {},
        "nodes": [
            {
                "id": "custom-node",
                "type": "transform",
                "inputs": cn.get("inputs", []),
                "outputs": cn.get("outputs", []),
                "config": {
                    "system_prompt": cn.get("template", ""),
                    "custom_node_id": node_id,
                    "custom_label": cn["name"],
                    "custom_color": cn.get("icon_color", "#6B3AB8"),
                },
            }
        ],
        "edges": [],
    }

    template_id = str(uuid.uuid4())
    sm.publish_template(
        template_id=template_id,
        name=f"Custom Node: {cn['name']}",
        description=cn.get("description", ""),
        author=cn.get("author", "Anonymous"),
        tags=f"custom-node,{cn.get('tags', '')}".rstrip(","),
        pipeline_json=json.dumps(pipeline),
    )
    return PublishTemplateResponse(id=template_id)


# ---------------------------------------------------------------------------
# /settings/api-keys  (auth required)
# ---------------------------------------------------------------------------


@app.get(
    "/settings/api-keys",
    response_model=ApiKeysResponse,
    dependencies=[Depends(verify_token)],
)
async def get_api_keys_status() -> ApiKeysResponse:
    """Return which API keys are set (boolean status only)."""
    providers = [
        "openai",
        "anthropic",
        "google",
        "groq",
        "openrouter",
        "zhipu",
        "nvidia",
        "ollama_base_url",
    ]
    status = {}
    for p in providers:
        status[p] = bool(get_secret(p))
    return ApiKeysResponse(keys=status)


@app.post(
    "/settings/api-keys",
    response_model=ApiKeysResponse,
    dependencies=[Depends(verify_token)],
)
async def update_api_keys(req: ApiKeysUpdateRequest) -> ApiKeysResponse:
    """Update API keys in OS keychain."""
    for provider, key in req.keys.items():
        if key.strip() == "":
            continue  # Leave blank to keep
        elif key.strip() == "__DELETE__":
            with contextlib.suppress(Exception):
                keyring.delete_password("komvos", provider)
        else:
            keyring.set_password("komvos", provider, key.strip())

    # Return updated status
    providers = [
        "openai",
        "anthropic",
        "google",
        "groq",
        "openrouter",
        "zhipu",
        "nvidia",
        "ollama_base_url",
    ]
    status = {}
    for p in providers:
        status[p] = bool(get_secret(p))
    return ApiKeysResponse(keys=status)


# ---------------------------------------------------------------------------
# GET /models  (auth required)
# ---------------------------------------------------------------------------


@app.get("/models", response_model=ModelsResponse, dependencies=[Depends(verify_token)])
async def list_models() -> ModelsResponse:
    """
    Fetch live model lists from each provider dynamically.
    """
    infos: list[ModelInfo] = []

    # Keep mock endpoints if they are in the test registry override
    registry = _global_registry()
    for eid, ep in registry.items():
        if eid.startswith("mock:"):
            caps = ep.capabilities()
            infos.append(
                ModelInfo(
                    endpoint_id=eid,
                    provider="mock",
                    model_name=eid.split(":", 1)[1],
                    max_context=caps.max_context,
                    json_mode=caps.json_mode,
                    tools=caps.tools,
                    vision=caps.vision,
                )
            )

    async with httpx.AsyncClient(timeout=3.0) as client:
        # 1. Ollama — always check localhost AND custom URL (e.g. ngrok)
        ollama_base = get_secret("ollama_base_url")
        if not ollama_base or not ollama_base.startswith("http"):
            ollama_base = None

        # Build list of Ollama URLs to probe (dedup)
        ollama_urls: list[str] = ["http://127.0.0.1:11434"]
        if ollama_base:
            normalized = ollama_base.rstrip("/")
            if normalized not in ollama_urls:
                ollama_urls.append(normalized)

        seen_ollama_ids: set[str] = set()
        for base_url in ollama_urls:
            try:
                resp = await client.get(
                    f"{base_url}/api/tags",
                    headers={"ngrok-skip-browser-warning": "true"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("models", []):
                        name = m.get("name")
                        eid = f"ollama:{name}"
                        if name and eid not in seen_ollama_ids:
                            seen_ollama_ids.add(eid)
                            is_vision = any(
                                tag in name.lower()
                                for tag in (
                                    "vision",
                                    "llava",
                                    "vl",
                                    "bakllava",
                                    "minicpm",
                                    "moondream",
                                )
                            )
                            infos.append(
                                ModelInfo(
                                    endpoint_id=eid,
                                    provider="ollama",
                                    model_name=name,
                                    max_context=8192,
                                    json_mode=True,
                                    tools=False,
                                    vision=is_vision,
                                )
                            )
            except Exception:
                pass

        # 2. OpenAI
        openai_key = get_secret("openai")
        if openai_key:
            try:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {openai_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        name = m.get("id")
                        if name and ("gpt" in name or "o1" in name or "o3" in name):
                            infos.append(
                                ModelInfo(
                                    endpoint_id=f"openai:{name}",
                                    provider="openai",
                                    model_name=name,
                                    max_context=128000,
                                    json_mode=True,
                                    tools=True,
                                    vision=True,
                                )
                            )
            except Exception:
                pass

        # 3. Anthropic
        anthropic_key = get_secret("anthropic")
        if anthropic_key:
            try:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        name = m.get("id")
                        if name:
                            infos.append(
                                ModelInfo(
                                    endpoint_id=f"anthropic:{name}",
                                    provider="anthropic",
                                    model_name=name,
                                    max_context=200000,
                                    json_mode=True,
                                    tools=True,
                                    vision=True,
                                )
                            )
            except Exception:
                pass

        # 4. Google
        google_key = get_secret("google")
        if google_key:
            try:
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={google_key}"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("models", []):
                        name = m.get("name", "").replace("models/", "")
                        methods = m.get("supportedGenerationMethods")
                        if "gemini" in name and (
                            methods is None or "generateContent" in methods
                        ):
                            infos.append(
                                ModelInfo(
                                    endpoint_id=f"google:{name}",
                                    provider="google",
                                    model_name=name,
                                    max_context=1048576,
                                    json_mode=True,
                                    tools=True,
                                    vision=True,
                                )
                            )
            except Exception:
                pass

        # 5. Groq
        groq_key = get_secret("groq")
        if groq_key:
            try:
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {groq_key}"},
                )
                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        name = m.get("id")
                        if name:
                            infos.append(
                                ModelInfo(
                                    endpoint_id=f"groq:{name}",
                                    provider="groq",
                                    model_name=name,
                                    max_context=8192,
                                    json_mode=True,
                                    tools=True,
                                    vision=False,
                                )
                            )
            except Exception:
                pass

        # 6. OpenRouter
        openrouter_key = get_secret("openrouter")
        if openrouter_key:
            try:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {openrouter_key}"},
                )
                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        name = m.get("id")
                        if name:
                            infos.append(
                                ModelInfo(
                                    endpoint_id=f"openrouter:{name}",
                                    provider="openrouter",
                                    model_name=name,
                                    max_context=128000,
                                    json_mode=True,
                                    tools=True,
                                    vision=True,
                                )
                            )
            except Exception:
                pass

        # 7. Nvidia
        nvidia_key = get_secret("nvidia")
        if nvidia_key:
            nvidia_added = False
            try:
                resp = await client.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {nvidia_key}"},
                )
                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        name = m.get("id")
                        if name:
                            infos.append(
                                ModelInfo(
                                    endpoint_id=f"nvidia:{name}",
                                    provider="nvidia",
                                    model_name=name,
                                    max_context=128000,
                                    json_mode=True,
                                    tools=True,
                                    vision=True,
                                )
                            )
                            nvidia_added = True
            except Exception:
                pass
            if not nvidia_added:
                for name in [
                    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                    "meta/llama-3.2-11b-vision-instruct",
                    "meta/llama-3.1-70b-instruct",
                    "nvidia/llama-3.1-nemotron-70b-instruct",
                ]:
                    infos.append(
                        ModelInfo(
                            endpoint_id=f"nvidia:{name}",
                            provider="nvidia",
                            model_name=name,
                            max_context=128000,
                            json_mode=True,
                            tools=True,
                            vision=True,
                        )
                    )

        # 8. Zhipu (GLM)
        zhipu_key = get_secret("zhipu")
        if zhipu_key:
            for name in ["glm-4", "glm-4v", "glm-4-plus", "glm-3-turbo"]:
                infos.append(
                    ModelInfo(
                        endpoint_id=f"zhipu:{name}",
                        provider="zhipu",
                        model_name=name,
                        max_context=128000,
                        json_mode=True,
                        tools=True,
                        vision=(name == "glm-4v"),
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
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except PipelineValidationErrors as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except PipelineValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ── 2. Build endpoint registry for this run ───────────────────────────────
    run_endpoints = await build_endpoint_registry(dag)
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
        state_manager=_global_state_manager(),
    )

    run_registry.create(run_id, runner, queue)

    # ── 4. Launch background task ────────────────────────────────────────────
    asyncio.create_task(
        run_pipeline_task(run_id, runner, queue),
        name=f"run-{run_id}",
    )

    return RunResponse(run_id=run_id)


# ---------------------------------------------------------------------------
# POST /pipelines/estimate  (auth required)
# ---------------------------------------------------------------------------


@app.post(
    "/pipelines/estimate",
    response_model=EstimateResponse,
    dependencies=[Depends(verify_token)],
)
async def estimate_pipeline(body: RunRequest) -> EstimateResponse:
    """
    Returns cost and latency estimates for model nodes in the pipeline.
    """
    try:
        dag = compile_pipeline(body.pipeline)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except PipelineValidationErrors as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except PipelineValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_endpoints = await build_endpoint_registry(dag, enforce_mock_gate=False)

    from komvos.endpoints.base import GenRequest, Message

    dummy_req = GenRequest(
        messages=[Message(role="user", content="Test " * 100)]
    )  # ~100 tokens input

    nodes_est: dict[str, NodeEstimate] = {}
    total_usd = 0.0
    total_latency = 0
    loop_multiplier = 1

    for node in dag.pipeline.nodes:
        if node.type == "model":
            ep_ref = node.endpoint_ref
            if ep_ref and ep_ref in run_endpoints:
                ep = run_endpoints[ep_ref]

                req = dummy_req.model_copy(update={})
                if node.config and node.config.max_tokens is not None:
                    req.max_tokens = node.config.max_tokens

                cost = ep.estimate_cost(req)
                is_local = ep_ref.startswith("ollama:") or ep_ref.startswith("mock:")
                lat = 2000 if is_local else 5000

                nodes_est[node.id] = NodeEstimate(
                    usd=cost.usd, latency_ms=lat, is_local=is_local
                )
                total_usd += cost.usd
                total_latency += lat

    # Loop bounds live on the pipeline's `loops[]` declarations, not on the
    # loop node's config. Use the widest declared bound as the multiplier.
    for loop in dag.pipeline.loops or []:
        loop_multiplier = max(loop_multiplier, loop.max_iterations)

    total_usd *= loop_multiplier
    total_latency *= loop_multiplier

    return EstimateResponse(
        nodes=nodes_est,
        total_usd=total_usd,
        total_latency_ms=total_latency,
        loop_multiplier=loop_multiplier,
    )


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
# GET /runs/{run_id}/trace  (auth required)
# ---------------------------------------------------------------------------


@app.get(
    "/runs/{run_id}/trace",
    dependencies=[Depends(verify_token)],
)
async def get_run_trace(run_id: str) -> dict[str, Any]:
    """Return the full execution trace from SQLite."""
    sm = _global_state_manager()
    # Unbounded work: three queries plus a JSON parse of every node's inputs and
    # outputs. Off the event loop, so pulling a large trace cannot stall the
    # WebSocket pump of a run that is still streaming.
    trace = await asyncio.to_thread(sm.get_full_trace, run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Run not found in trace database.")
    return trace


# ---------------------------------------------------------------------------
# DELETE /runs/{run_id}  (auth required)
# ---------------------------------------------------------------------------


@app.delete(
    "/runs/{run_id}",
    dependencies=[Depends(verify_token)],
)
async def delete_run(run_id: str) -> dict[str, Any]:
    """Delete a single run and all associated telemetry rows."""
    sm = _global_state_manager()
    deleted = sm.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"run_id": run_id, "deleted": True}



# ---------------------------------------------------------------------------
# WebSocket /ws/run/{run_id}
# ---------------------------------------------------------------------------


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
    # Same fail-closed rule as the HTTP routes: an unset session token is only
    # a pass under an explicit KOMVOS_DEV=1, never on its own.
    if not check_token(token):
        await websocket.close(code=4001, reason="Invalid or missing session token.")
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
        with contextlib.suppress(Exception):
            await websocket.close()


# ---------------------------------------------------------------------------
# Phase 3 — serve pipelines as an OpenAI-compatible HTTP API
#
# Mounted last, after everything create_serve_router depends on is already
# defined, and via the factory (not a module-level import of `app`) so
# komvos.serve.routes never has to import this module — see that
# module's docstring for the circular-import reasoning.
# ---------------------------------------------------------------------------

from komvos.serve.routes import create_serve_router  # noqa: E402

app.include_router(
    create_serve_router(
        verify_token_dep=verify_token,
        compile_pipeline_fn=compile_pipeline,
        build_endpoint_registry_fn=build_endpoint_registry,
        get_state_manager_fn=_global_state_manager,
        run_registry=run_registry,
        run_task_fn=run_pipeline_task,
    )
)


# ---------------------------------------------------------------------------
# Gov-2 — governance profiles + approvals
#
# Mounted last, same factory pattern as the serve router above: this module
# never gets imported by komvos.governance.api, so no circular import.
# ---------------------------------------------------------------------------

from komvos.governance.api import create_governance_router  # noqa: E402

app.include_router(
    create_governance_router(
        verify_token_dep=verify_token,
        get_state_manager_fn=_global_state_manager,
    )
)
