"""
backend/komvos/scheduler/events.py

Typed WebSocket event models bridging the Scheduler's internal SchedulerEvent
format to the JSON frames streamed to the P3 desktop client.

These are what the WebSocket handler at /ws/run/{run_id} sends — not the same
as SchedulerEvent (P1's internal type). This is P2's WS contract.

BREAKING CHANGE: changing field names/types here impacts the P3 desktop UI.
Announce before modifying.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now_ms() -> int:
    return int(time.time() * 1000)


class WsNodeStartedEvent(BaseModel):
    event: Literal["node_started"] = "node_started"
    run_id: str
    node_id: str
    node_type: str
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsTokenEvent(BaseModel):
    event: Literal["token"] = "token"
    run_id: str
    node_id: str
    text: str
    index: int
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsNodeDoneEvent(BaseModel):
    event: Literal["node_done"] = "node_done"
    run_id: str
    node_id: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    cost_usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsLoopIterationEvent(BaseModel):
    event: Literal["loop_iteration"] = "loop_iteration"
    run_id: str
    loop_id: str
    iteration: int
    max_iterations: int
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsRunHaltedEvent(BaseModel):
    event: Literal["run_halted"] = "run_halted"
    run_id: str
    reason: str
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsRunCompletedEvent(BaseModel):
    event: Literal["run_completed"] = "run_completed"
    run_id: str
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    elapsed_ms: int
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsRunErrorEvent(BaseModel):
    event: Literal["run_error"] = "run_error"
    run_id: str
    error: str
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsBudgetExceededEvent(BaseModel):
    event: Literal["budget_exceeded"] = "budget_exceeded"
    run_id: str
    cumulative_cost_usd: float
    budget_usd: float
    node_id: str
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsRunStoppedEvent(BaseModel):
    event: Literal["run_stopped"] = "run_stopped"
    run_id: str
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsNodeErrorEvent(BaseModel):
    event: Literal["node_error"] = "node_error"
    run_id: str
    node_id: str
    error: str
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsAccessDeniedEvent(BaseModel):
    """
    A node was blocked by its effective access policy before it could run.

    Distinct from node_error so the UI can show *which* capability was withheld
    and offer to grant it on the governing access node, rather than surfacing
    a generic failure. Added in schema 2.1.
    """

    event: Literal["access_denied"] = "access_denied"
    run_id: str
    node_id: str
    capability: str
    """e.g. "provider:anthropic" or "allow_local_models"."""
    reason: str
    timestamp_ms: int = Field(default_factory=_now_ms)


class WsApprovalPendingEvent(BaseModel):
    """
    A node under the Ask posture is suspended waiting for a human.

    Carries everything a UI needs to render the question and what each
    possible answer will do. The run keeps executing every OTHER node while
    this one waits; answering happens over the governance HTTP API. Not a
    terminal event — the run resumes (or fails) when the approval resolves,
    times out, or the run is cancelled.
    """

    event: Literal["approval_pending"] = "approval_pending"
    run_id: str
    node_id: str
    approval_id: str
    domain: str
    """One of the GovernanceDomain values: providers|egress|spend|retention."""
    capability: str
    reason: str
    allow_once_effect: str
    allow_for_run_effect: str
    deny_effect: str
    timeout_seconds: float
    timestamp_ms: int = Field(default_factory=_now_ms)


WsEvent = (
    WsNodeStartedEvent
    | WsTokenEvent
    | WsNodeDoneEvent
    | WsNodeErrorEvent
    | WsAccessDeniedEvent
    | WsApprovalPendingEvent
    | WsLoopIterationEvent
    | WsRunHaltedEvent
    | WsRunCompletedEvent
    | WsRunErrorEvent
    | WsBudgetExceededEvent
    | WsRunStoppedEvent
)

# Terminal event types — WS handler stops streaming after these
WS_TERMINAL_EVENTS = (
    WsRunCompletedEvent,
    WsRunHaltedEvent,
    WsRunErrorEvent,
    WsBudgetExceededEvent,
    WsRunStoppedEvent,
)
