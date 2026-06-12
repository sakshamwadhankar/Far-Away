"""
backend/neuralflow/api/models.py

Pydantic request / response models for the NeuralFlow API.

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
# POST /pipelines/run
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """
    Request body for POST /pipelines/run.

    `pipeline` must be a valid pipeline schema v2 JSON object.
    Budget fields are optional; omit to run without a cap.
    """

    pipeline: dict[str, Any] = Field(
        description="Pipeline schema v2 JSON object (will be parsed + validated server-side)."
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
