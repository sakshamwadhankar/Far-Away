"""
backend/neuralflow/scheduler/__init__.py

Public API for the scheduler module.
"""

from neuralflow.scheduler.engine import (
    CancelToken,
    EndpointRegistry,
    EventCallback,
    EventKind,
    LoopIterationRecord,
    NodeResult,
    PipelineCancelled,
    Scheduler,
    SchedulerEvent,
    SchedulerResult,
)
from neuralflow.scheduler.events import (
    WS_TERMINAL_EVENTS,
    WsBudgetExceededEvent,
    WsEvent,
    WsLoopIterationEvent,
    WsNodeDoneEvent,
    WsNodeStartedEvent,
    WsRunCompletedEvent,
    WsRunErrorEvent,
    WsRunHaltedEvent,
    WsRunStoppedEvent,
    WsTokenEvent,
)
from neuralflow.scheduler.runner import PipelineRunner
from neuralflow.scheduler.stop_eval import (
    StopConditionTypeError,
    StopFieldResolutionError,
    evaluate_stop_condition,
)

__all__ = [
    # Engine
    "CancelToken",
    "EndpointRegistry",
    "EventCallback",
    "EventKind",
    "LoopIterationRecord",
    "NodeResult",
    "PipelineCancelled",
    "Scheduler",
    "SchedulerEvent",
    "SchedulerResult",
    # Runner
    "PipelineRunner",
    # WS Events
    "WS_TERMINAL_EVENTS",
    "WsBudgetExceededEvent",
    "WsEvent",
    "WsLoopIterationEvent",
    "WsNodeDoneEvent",
    "WsNodeStartedEvent",
    "WsRunCompletedEvent",
    "WsRunErrorEvent",
    "WsRunHaltedEvent",
    "WsRunStoppedEvent",
    "WsTokenEvent",
    # Stop eval
    "StopConditionTypeError",
    "StopFieldResolutionError",
    "evaluate_stop_condition",
]
