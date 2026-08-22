"""
backend/komvos/api/models.py

Pydantic request / response models for the Komvos API.

These are the shapes of JSON bodies the API accepts and returns.
Do NOT put execution logic here — pure data models only.

BREAKING CHANGE: changing field names/types here impacts the P3 desktop client.
Announce before modifying.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


# ---------------------------------------------------------------------------
# /models
# ---------------------------------------------------------------------------


class ModelInfo(BaseModel):
    endpoint_id: str
    provider: str
    model_name: str
    max_context: int
    json_mode: bool
    tools: bool
    vision: bool


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


# ---------------------------------------------------------------------------
# /settings/api-keys
# ---------------------------------------------------------------------------


class ApiKeysResponse(BaseModel):
    keys: dict[str, bool]


class ApiKeysUpdateRequest(BaseModel):
    keys: dict[str, str]


# ---------------------------------------------------------------------------
# POST /pipelines/run
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """
    Request body for POST /pipelines/run.

    `pipeline` must be a valid pipeline schema v2 JSON object.
    Budget fields are optional; omit to run without a cap.
    """

    pipeline: dict[str, Any] = Field(
        description=(
            "Pipeline schema v2 JSON object "
            "(will be parsed + validated server-side)."
        )
    )
    budget_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Maximum spend in USD. Run halts when exceeded.",
    )
    budget_wall_clock_seconds: float | None = Field(
        default=None,
        ge=1.0,
        description="Maximum wall-clock time in seconds. Run halts when exceeded.",
    )


class RunResponse(BaseModel):
    run_id: str


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/stop
# ---------------------------------------------------------------------------


class StopResponse(BaseModel):
    run_id: str
    halted: bool


# ---------------------------------------------------------------------------
# POST /pipelines/estimate
# ---------------------------------------------------------------------------


class NodeEstimate(BaseModel):
    usd: float
    latency_ms: int
    is_local: bool


class EstimateResponse(BaseModel):
    nodes: dict[str, NodeEstimate]
    total_usd: float
    total_latency_ms: int
    loop_multiplier: int = 1


# ---------------------------------------------------------------------------
# Library Templates (community sharing)
# ---------------------------------------------------------------------------


class PublishTemplateRequest(BaseModel):
    """Request body for POST /library/publish."""

    name: str = Field(min_length=1, description="Human-friendly template name.")
    description: str = Field(default="", description="Optional description.")
    author: str = Field(
        default="Anonymous", min_length=1, description="Author display name."
    )
    tags: str = Field(
        default="", description="Comma-separated tags, e.g. 'rag,chat,multi-agent'."
    )
    pipeline: dict[str, Any] = Field(
        description="Pipeline schema v2 JSON object (will be validated server-side)."
    )


class LibraryTemplateResponse(BaseModel):
    """Single library template returned in lists and detail views."""

    id: str
    name: str
    description: str
    author: str
    tags: str
    pipeline: dict[str, Any]
    created_at: int
    downloads: int


class PublishTemplateResponse(BaseModel):
    """Response body for POST /library/publish."""

    id: str


# ---------------------------------------------------------------------------
# Custom Nodes (user-defined node definitions)
# ---------------------------------------------------------------------------


class PortDefinition(BaseModel):
    """A single port definition for a custom node."""

    name: str = Field(min_length=1)
    type: str = Field(
        description="Port type: text, number, boolean, json, image, audio."
    )


class SaveCustomNodeRequest(BaseModel):
    """Request body for POST /custom-nodes."""

    name: str = Field(min_length=1, description="Display name for the custom node.")
    description: str = Field(default="", description="What this node does.")
    author: str = Field(default="Anonymous", min_length=1)
    icon_color: str = Field(
        default="#6B3AB8", description="Hex color for the node accent."
    )
    inputs: list[PortDefinition] = Field(default_factory=list)
    outputs: list[PortDefinition] = Field(default_factory=list)
    template: str = Field(
        default="", description="Jinja2 template for transform logic."
    )
    tags: str = Field(default="", description="Comma-separated tags.")


class CustomNodeResponse(BaseModel):
    """A custom node definition returned by GET /custom-nodes."""

    id: str
    name: str
    description: str
    author: str
    icon_color: str
    inputs: list[PortDefinition]
    outputs: list[PortDefinition]
    template: str
    tags: str
    created_at: int


class SaveCustomNodeResponse(BaseModel):
    """Response body for POST /custom-nodes."""

    id: str
