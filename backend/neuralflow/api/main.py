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
import json
from pathlib import Path
import httpx
import keyring
from neuralflow.compiler.models import Pipeline

from neuralflow.api.auth import verify_token
from neuralflow.api.models import (
    HealthResponse,
    ModelInfo,
    ModelsResponse,
    RunRequest,
    RunResponse,
    StopResponse,
    EstimateResponse,
    NodeEstimate,
    PublishTemplateRequest,
    LibraryTemplateResponse,
    PublishTemplateResponse,
    SaveCustomNodeRequest,
    CustomNodeResponse,
    SaveCustomNodeResponse,
    ApiKeysResponse,
    ApiKeysUpdateRequest,
)
from neuralflow.api.registry import run_registry
from neuralflow.compiler.dag import compile as compile_pipeline
from neuralflow.compiler.validation import PipelineValidationError, PipelineValidationErrors
from neuralflow.endpoints.base import ModelEndpoint
from neuralflow.endpoints.cloud import CloudEndpoint
from neuralflow.scheduler.engine import EndpointRegistry
from neuralflow.scheduler.events import WS_TERMINAL_EVENTS
from neuralflow.scheduler.runner import PipelineRunner
from neuralflow.state.sqlite import StateManager

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
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
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


def _global_state_manager() -> StateManager:
    """Return the global StateManager or test override."""
    if hasattr(app.state, "state_manager"):
        return app.state.state_manager
    import os
    from pathlib import Path
    db_dir = Path(os.path.expanduser("~/.neuralflow"))
    db_dir.mkdir(parents=True, exist_ok=True)
    return StateManager(str(db_dir / "neuralflow.db"))

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
# GET /pipelines/templates  (auth required)
# ---------------------------------------------------------------------------

@app.get("/pipelines/templates", dependencies=[Depends(verify_token)])
async def get_templates() -> list[dict[str, Any]]:
    templates_dir = Path(__file__).parent.parent.parent.parent / "templates"
    templates = []
    if not templates_dir.exists():
        return []
    
    for file in templates_dir.glob("*.json"):
        try:
            with open(file, "r", encoding="utf-8") as f:
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
async def publish_library_template(body: PublishTemplateRequest) -> PublishTemplateResponse:
    """Validate a pipeline and publish it to the community library."""
    # Validate pipeline schema
    try:
        Pipeline.model_validate(body.pipeline)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid pipeline: {exc}")

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
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
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
        raise HTTPException(status_code=404, detail=f"Custom node '{node_id}' not found.")
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
        raise HTTPException(status_code=404, detail=f"Custom node '{node_id}' not found.")

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


@app.get("/settings/api-keys", response_model=ApiKeysResponse, dependencies=[Depends(verify_token)])
async def get_api_keys_status() -> ApiKeysResponse:
    """Return which API keys are set (boolean status only)."""
    providers = ["openai", "anthropic", "google", "groq", "openrouter", "zhipu", "nvidia", "ollama_base_url"]
    status = {}
    for p in providers:
        status[p] = bool(keyring.get_password("neuralflow", p))
    return ApiKeysResponse(keys=status)


@app.post("/settings/api-keys", response_model=ApiKeysResponse, dependencies=[Depends(verify_token)])
async def update_api_keys(req: ApiKeysUpdateRequest) -> ApiKeysResponse:
    """Update API keys in OS keychain."""
    for provider, key in req.keys.items():
        if key.strip() == "":
            continue # Leave blank to keep
        elif key.strip() == "__DELETE__":
            try:
                keyring.delete_password("neuralflow", provider)
            except Exception:
                pass
        else:
            keyring.set_password("neuralflow", provider, key.strip())
            
    # Return updated status
    providers = ["openai", "anthropic", "google", "groq", "openrouter", "zhipu", "nvidia", "ollama_base_url"]
    status = {}
    for p in providers:
        status[p] = bool(keyring.get_password("neuralflow", p))
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
        ollama_base = keyring.get_password("neuralflow", "ollama_base_url")
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
                    headers={"ngrok-skip-browser-warning": "true"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("models", []):
                        name = m.get("name")
                        eid = f"ollama:{name}"
                        if name and eid not in seen_ollama_ids:
                            seen_ollama_ids.add(eid)
                            infos.append(ModelInfo(
                                endpoint_id=eid,
                                provider="ollama",
                                model_name=name,
                                max_context=8192,
                                json_mode=True,
                                tools=False,
                                vision=False
                            ))
            except Exception:
                pass

        # 2. OpenAI
        openai_key = keyring.get_password("neuralflow", "openai")
        if openai_key:
            try:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {openai_key}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        name = m.get("id")
                        if name and ("gpt" in name or "o1" in name or "o3" in name):
                            infos.append(ModelInfo(
                                endpoint_id=f"openai:{name}",
                                provider="openai",
                                model_name=name,
                                max_context=128000,
                                json_mode=True,
                                tools=True,
                                vision=True
                            ))
            except Exception:
                pass

        # 3. Anthropic
        anthropic_key = keyring.get_password("neuralflow", "anthropic")
        if anthropic_key:
            try:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        name = m.get("id")
                        if name:
                            infos.append(ModelInfo(
                                endpoint_id=f"anthropic:{name}",
                                provider="anthropic",
                                model_name=name,
                                max_context=200000,
                                json_mode=True,
                                tools=True,
                                vision=True
                            ))
            except Exception:
                pass

        # 4. Google
        google_key = keyring.get_password("neuralflow", "google")
        if google_key:
            try:
                resp = await client.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={google_key}")
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("models", []):
                        name = m.get("name", "").replace("models/", "")
                        if "gemini" in name:
                            infos.append(ModelInfo(
                                endpoint_id=f"google:{name}",
                                provider="google",
                                model_name=name,
                                max_context=1048576,
                                json_mode=True,
                                tools=True,
                                vision=True
                            ))
            except Exception:
                pass

        # 5. Groq
        groq_key = keyring.get_password("neuralflow", "groq")
        if groq_key:
            try:
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {groq_key}"}
                )
                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        name = m.get("id")
                        if name:
                            infos.append(ModelInfo(
                                endpoint_id=f"groq:{name}", provider="groq", model_name=name,
                                max_context=8192, json_mode=True, tools=True, vision=False
                            ))
            except Exception: pass

        # 6. OpenRouter
        openrouter_key = keyring.get_password("neuralflow", "openrouter")
        if openrouter_key:
            try:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {openrouter_key}"}
                )
                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        name = m.get("id")
                        if name:
                            infos.append(ModelInfo(
                                endpoint_id=f"openrouter:{name}", provider="openrouter", model_name=name,
                                max_context=128000, json_mode=True, tools=True, vision=True
                            ))
            except Exception: pass

        # 7. Nvidia
        nvidia_key = keyring.get_password("neuralflow", "nvidia")
        if nvidia_key:
            try:
                resp = await client.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {nvidia_key}"}
                )
                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        name = m.get("id")
                        if name:
                            infos.append(ModelInfo(
                                endpoint_id=f"nvidia:{name}", provider="nvidia", model_name=name,
                                max_context=128000, json_mode=True, tools=True, vision=True
                            ))
            except Exception: pass

        # 8. Zhipu (GLM)
        zhipu_key = keyring.get_password("neuralflow", "zhipu")
        if zhipu_key:
            for name in ["glm-4", "glm-4v", "glm-4-plus", "glm-3-turbo"]:
                infos.append(ModelInfo(
                    endpoint_id=f"zhipu:{name}", provider="zhipu", model_name=name,
                    max_context=128000, json_mode=True, tools=True, vision=(name=="glm-4v")
                ))

    return ModelsResponse(models=infos)


# ---------------------------------------------------------------------------
# POST /pipelines/run  (auth required)
# ---------------------------------------------------------------------------


async def _resolve_ollama_base(model_name: str, descriptor_base: str | None) -> str:
    """
    Resolve the correct base URL for an Ollama execution.
    If a custom ngrok URL is saved, we still want local models (like qwen) to run
    against localhost:11434 if they exist locally.
    """
    if descriptor_base:
        return f"{descriptor_base.rstrip('/')}/v1"
        
    saved_base = keyring.get_password("neuralflow", "ollama_base_url")
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
                    if m.get("name") == model_name or m.get("name", "").startswith(model_name + ":"):
                        return "http://127.0.0.1:11434/v1"
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to check local ollama tags for {model_name}: {e}")
        
    # Fallback to custom URL
    return f"{saved_base.rstrip('/')}/v1"


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
    except PipelineValidationErrors as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
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
            if descriptor.kind in ("openai", "anthropic", "google", "openai_compatible", "groq", "openrouter", "zhipu", "nvidia"):
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
            elif descriptor.kind == "ollama":
                from neuralflow.endpoints.ollama import OllamaEndpoint
                ollama_model = descriptor.model or "qwen2.5:3b"
                ollama_base = await _resolve_ollama_base(ollama_model, descriptor.base_url)

                run_endpoints[ref] = OllamaEndpoint(
                    id=f"ollama:{descriptor.model or 'default'}",
                    base_url=ollama_base,
                    model=ollama_model,
                )
            else:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Unsupported endpoint kind '{descriptor.kind}' for ref '{ref}'. "
                        "Supported: openai, anthropic, google, openai_compatible, ollama."
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
        state_manager=_global_state_manager(),
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
        raise HTTPException(status_code=422, detail=exc.errors())
    except PipelineValidationErrors as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    except PipelineValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    global_ep = _global_registry()
    run_endpoints: dict[str, ModelEndpoint] = {}

    for ref, descriptor in dag.pipeline.endpoints.items():
        if ref in global_ep:
            run_endpoints[ref] = global_ep[ref]
        else:
            if descriptor.kind in ("openai", "anthropic", "google", "openai_compatible", "groq", "openrouter", "zhipu", "nvidia"):
                run_endpoints[ref] = CloudEndpoint(
                    provider=descriptor.kind,
                    model_name=descriptor.model or "gpt-4o-mini",
                    base_url=descriptor.base_url,
                )
            elif descriptor.kind == "mock":
                from neuralflow.endpoints.mock import MockEndpoint
                run_endpoints[ref] = MockEndpoint(id=descriptor.model or "mock-model")
            elif descriptor.kind == "ollama":
                from neuralflow.endpoints.ollama import OllamaEndpoint
                ollama_model = descriptor.model or "qwen2.5:3b"
                ollama_base = await _resolve_ollama_base(ollama_model, descriptor.base_url)

                run_endpoints[ref] = OllamaEndpoint(
                    id=f"ollama:{descriptor.model or 'default'}",
                    base_url=ollama_base,
                    model=ollama_model,
                )

    from neuralflow.endpoints.base import GenRequest, Message
    dummy_req = GenRequest(messages=[Message(role="user", content="Test " * 100)]) # ~100 tokens input
    
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
                if hasattr(node, "config") and node.config and "max_tokens" in node.config:
                    req.max_tokens = node.config["max_tokens"]
                
                cost = ep.estimate_cost(req)
                is_local = (ep_ref.startswith("ollama:") or ep_ref.startswith("mock:"))
                lat = 2000 if is_local else 5000
                
                nodes_est[node.id] = NodeEstimate(usd=cost.usd, latency_ms=lat, is_local=is_local)
                total_usd += cost.usd
                total_latency += lat
        
        elif node.type == "loop":
            iters = node.config.get("max_iterations", 1) if getattr(node, "config", None) else 1
            if isinstance(iters, int) and iters > 1:
                loop_multiplier = max(loop_multiplier, iters)
                
    total_usd *= loop_multiplier
    total_latency *= loop_multiplier

    return EstimateResponse(
        nodes=nodes_est,
        total_usd=total_usd,
        total_latency_ms=total_latency,
        loop_multiplier=loop_multiplier
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
    trace = sm.get_full_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Run not found in trace database.")
    return trace


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
