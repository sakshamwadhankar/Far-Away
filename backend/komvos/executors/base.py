"""
backend/komvos/executors/base.py

Base interfaces for node executors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from komvos.compiler.models import AccessPolicy

if TYPE_CHECKING:
    from komvos.compiler.models import Node
    from komvos.scheduler.engine import (
        CancelToken,
        EndpointRegistry,
        SchedulerEvent,
    )

EventCallback = Callable[["SchedulerEvent"], Awaitable[None] | None]


@dataclass
class ExecutorContext:
    """Context passed to every node executor."""

    node: Node
    inputs: dict[str, Any]
    registry: EndpointRegistry
    emit_fn: EventCallback
    cancel_token: CancelToken | None = None
    policy: AccessPolicy = field(default_factory=AccessPolicy.permissive)
    """
    The effective access policy for this node, from
    CompiledDAG.effective_policies. Defaults to permissive so that a context
    built without one (tests, non-model executors) behaves as it did before
    schema 2.1.
    """
    policy_sources: tuple[str, ...] = ()
    """
    IDs of the access nodes whose intersection produced `policy`, from
    CompiledDAG.policy_sources. Empty when the node is ungoverned. Carried so
    governance decisions can name which access node constrained them.
    """
    pipeline_policy: AccessPolicy | None = None
    """
    The pipeline-only view of this node's policy — before profile resolution.
    None means "same as `policy`" (no profile was in force at compile time).
    The Ask/Audit posture layer fires only when THIS policy denies and the
    resolved one permits: that difference is exactly the profile's grant.
    """

    def check_cancel(self) -> None:
        """Raise PipelineCancelled if the cancel token is set."""
        if self.cancel_token is not None:
            self.cancel_token.check()

    async def emit(self, event: SchedulerEvent) -> None:
        """Emit an event via the callback."""
        import asyncio

        if self.emit_fn is not None:
            result = self.emit_fn(event)
            if asyncio.iscoroutine(result):
                await result


class BaseExecutor(ABC):
    """
    Abstract base class for all node executors.
    """

    @abstractmethod
    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        """
        Execute the node logic.

        Args:
            ctx: Execution context containing node config, inputs, and utilities.

        Returns:
            A dictionary mapping output port names to their computed values.
        """
        pass
