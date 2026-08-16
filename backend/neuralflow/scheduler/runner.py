"""
backend/neuralflow/scheduler/runner.py

PipelineRunner — P2-owned execution bridge.

Wraps P1's Scheduler to:
  1. Drive execution in a background asyncio task.
  2. Translate SchedulerEvents → typed WsEvents for WebSocket streaming.
  3. Enforce budget (USD cap) and wall-clock cap via CancelToken.
  4. Expose stop() for the kill-switch endpoint.

Design:
  - The Scheduler is injected with an event_callback. The callback appends
    WsEvent objects to an asyncio.Queue consumed by the WS handler.
  - Budget is tracked by summing estimate_cost() before each model node via
    a pre-execution hook injected as part of the event_callback.
  - Wall-clock is checked once at task startup and again on each
    node_started event. If exceeded, CancelToken.cancel() is called.

NOTE: The Scheduler does NOT check budget itself — that is P2's
responsibility. P1's CancelToken is the shared cancellation primitive.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuralflow.state.sqlite import StateManager

from neuralflow.compiler.dag import CompiledDAG
from neuralflow.endpoints.base import (
    Caps,
    Cost,
    GenRequest,
    Health,
    ModelEndpoint,
    Token,
)
from neuralflow.scheduler.engine import (
    CancelToken,
    EndpointRegistry,
    EventKind,
    Scheduler,
    SchedulerEvent,
)
from neuralflow.scheduler.events import (
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

logger = logging.getLogger(__name__)


class PipelineRunner:
    """
    Wraps P1's Scheduler for the API layer.

    Usage::
        runner = PipelineRunner(run_id, dag, registry,
                                budget_usd=1.0, budget_wall_clock_seconds=60)
        queue: asyncio.Queue[WsEvent | None] = asyncio.Queue()
        task = asyncio.create_task(runner.run(queue))
        # later from the /stop endpoint:
        runner.stop()
    """

    def __init__(
        self,
        run_id: str,
        dag: CompiledDAG,
        registry: EndpointRegistry,
        *,
        budget_usd: float | None = None,
        budget_wall_clock_seconds: float | None = None,
        state_manager: StateManager | None = None,
    ) -> None:
        self.run_id = run_id
        self._dag = dag
        self._registry = registry
        self._budget_usd = budget_usd
        self._budget_wall_clock_ms = (
            int(budget_wall_clock_seconds * 1000) if budget_wall_clock_seconds else None
        )
        self._state_manager = state_manager
        self._cancel = CancelToken()
        self._cumulative_cost: float = 0.0
        self._total_tokens_in: int = 0
        self._total_tokens_out: int = 0
        self._stopped_by_user: bool = False
        self._start_ms: int = 0

    def stop(self) -> None:
        """Signal the pipeline to halt at the next checkpoint."""
        self._stopped_by_user = True
        self._cancel.cancel("Run stopped by user.")

    async def run(self, queue: asyncio.Queue) -> None:  # type: ignore[type-arg]
        """
        Execute the pipeline in the background.

        Puts WsEvent objects into queue. Always terminates by putting None
        (sentinel) so the WS handler knows the task finished.
        """
        self._start_ms = int(time.time() * 1000)

        resume_state = None
        if self._state_manager:
            resume_state = self._state_manager.load_run_state(self.run_id)
            self._state_manager.save_run(self.run_id, self._dag.pipeline.id, "running")

        # Pre-budget check for each model node: wrap registry endpoints
        # to call estimate_cost() before generate() starts.
        budget_registry = _BudgetEnforcingRegistry(
            inner=self._registry,
            cancel_token=self._cancel,
            budget_usd=self._budget_usd,
            run_id=self.run_id,
            queue=queue,
            runner=self,
        )

        async def _event_callback(event: SchedulerEvent) -> None:
            if self._state_manager:
                if event.kind == EventKind.NODE_DONE:
                    self._state_manager.save_node_execution(
                        self.run_id,
                        event.node_id or "",
                        inputs=event.data.get("inputs"),
                        outputs=event.data.get("outputs"),
                        cost=event.data.get("cost_usd"),
                        tokens_in=event.data.get("tokens_in"),
                        tokens_out=event.data.get("tokens_out"),
                    )
                elif event.kind == EventKind.NODE_ERROR:
                    self._state_manager.save_node_execution(
                        self.run_id,
                        event.node_id or "",
                        error=event.data.get("error"),
                    )
                elif event.kind == EventKind.LOOP_ITERATION:
                    self._state_manager.save_loop_iteration(
                        self.run_id,
                        event.data.get("loop_id", ""),
                        event.data.get("iteration", 0),
                        outputs=event.data.get("outputs"),
                    )

            ws_event = self._translate(event)
            if ws_event is not None:
                await queue.put(ws_event)
            # Wall-clock check on every node_started
            if event.kind == EventKind.NODE_STARTED and self._budget_wall_clock_ms:
                elapsed = int(time.time() * 1000) - self._start_ms
                if elapsed >= self._budget_wall_clock_ms:
                    self._cancel.cancel(
                        f"Wall-clock budget exceeded: {elapsed}ms > "
                        f"{self._budget_wall_clock_ms}ms."
                    )

        scheduler = Scheduler(
            self._dag,
            budget_registry,
            event_callback=_event_callback,
            cancel_token=self._cancel,
        )

        try:
            result = await scheduler.run(
                {
                    node.id: {
                        port.name: (
                            getattr(node.config, "default_value", "")
                            if getattr(node, "config", None)
                            and getattr(node.config, "default_value", None)
                            else ""
                        )
                        for port in node.outputs
                    }
                    for node in self._dag.pipeline.nodes
                    if node.type == "input"
                },
                resume_state=resume_state,
            )
        except Exception as exc:
            logger.exception("Unhandled error in pipeline run %s", self.run_id)
            if self._state_manager:
                self._state_manager.update_run_status(
                    self.run_id,
                    "error",
                    self._cumulative_cost,
                    self._total_tokens_in,
                    self._total_tokens_out,
                )
            await queue.put(WsRunErrorEvent(run_id=self.run_id, error=str(exc)))
            await queue.put(None)
            return

        elapsed_ms = int(time.time() * 1000) - self._start_ms

        if result.completed:
            if self._state_manager:
                self._state_manager.update_run_status(
                    self.run_id,
                    "completed",
                    self._cumulative_cost,
                    self._total_tokens_in,
                    self._total_tokens_out,
                )
            await queue.put(
                WsRunCompletedEvent(
                    run_id=self.run_id,
                    total_cost_usd=self._cumulative_cost,
                    total_tokens_in=self._total_tokens_in,
                    total_tokens_out=self._total_tokens_out,
                    elapsed_ms=elapsed_ms,
                )
            )
        else:
            # Cancelled: determine cause
            if self._stopped_by_user:
                if self._state_manager:
                    self._state_manager.update_run_status(
                        self.run_id,
                        "stopped",
                        self._cumulative_cost,
                        self._total_tokens_in,
                        self._total_tokens_out,
                    )
                await queue.put(WsRunStoppedEvent(run_id=self.run_id))
            elif budget_registry.budget_exceeded:
                if self._state_manager:
                    self._state_manager.update_run_status(
                        self.run_id,
                        "budget_exceeded",
                        self._cumulative_cost,
                        self._total_tokens_in,
                        self._total_tokens_out,
                    )
                await queue.put(
                    WsBudgetExceededEvent(
                        run_id=self.run_id,
                        cumulative_cost_usd=self._cumulative_cost,
                        budget_usd=self._budget_usd or 0.0,
                        node_id=budget_registry.exceeded_at_node or "",
                    )
                )
            else:
                if self._state_manager:
                    self._state_manager.update_run_status(
                        self.run_id,
                        "halted",
                        self._cumulative_cost,
                        self._total_tokens_in,
                        self._total_tokens_out,
                    )
                await queue.put(
                    WsRunHaltedEvent(
                        run_id=self.run_id,
                        reason=self._cancel.reason,
                    )
                )

        await queue.put(None)  # sentinel

    def _translate(self, event: SchedulerEvent) -> WsEvent | None:
        """Map a P1 SchedulerEvent → a P2 WsEvent for the WebSocket client."""
        node_id = event.node_id or ""
        d = event.data

        if event.kind == EventKind.NODE_STARTED:
            return WsNodeStartedEvent(
                run_id=self.run_id,
                node_id=node_id,
                node_type=d.get("type", "unknown"),
            )
        if event.kind == EventKind.NODE_DONE:
            # Track token counts from node done outputs
            return WsNodeDoneEvent(
                run_id=self.run_id,
                node_id=node_id,
                inputs=d.get("inputs", {}),
                outputs=d.get("outputs", {}),
                cost_usd=d.get("cost_usd"),
                tokens_in=d.get("tokens_in"),
                tokens_out=d.get("tokens_out"),
            )
        if event.kind == EventKind.NODE_ERROR:
            from neuralflow.scheduler.events import WsNodeErrorEvent

            return WsNodeErrorEvent(
                run_id=self.run_id,
                node_id=node_id,
                error=d.get("error", "Unknown error"),
            )
        if event.kind == EventKind.TOKEN:
            self._total_tokens_out += 1
            return WsTokenEvent(
                run_id=self.run_id,
                node_id=node_id,
                text=d.get("text", ""),
                index=d.get("index", 0),
            )
        if event.kind == EventKind.LOOP_ITERATION:
            return WsLoopIterationEvent(
                run_id=self.run_id,
                loop_id=d.get("loop_id", ""),
                iteration=d.get("iteration", 0),
                max_iterations=d.get("max_iterations", 0),
            )
        if event.kind == EventKind.RUN_HALTED:
            # Will emit appropriate terminal event at the end of run()
            return None

        return None


class _BudgetEnforcingRegistry(EndpointRegistry):
    """
    EndpointRegistry that wraps each endpoint's generate() call
    with a pre-flight estimate_cost() check.

    If the cumulative cost would exceed budget_usd, it cancels the token
    and sets budget_exceeded=True so PipelineRunner can emit the right event.
    """

    def __init__(
        self,
        inner: EndpointRegistry,
        cancel_token: CancelToken,
        budget_usd: float | None,
        run_id: str,
        queue: asyncio.Queue,  # type: ignore[type-arg]
        runner: PipelineRunner,
    ) -> None:
        # Pass an empty dict — we override resolve()
        super().__init__({})
        self._inner = inner
        self._cancel = cancel_token
        self._budget_usd = budget_usd
        self._run_id = run_id
        self._queue = queue
        self._runner = runner
        self.budget_exceeded: bool = False
        self.exceeded_at_node: str | None = None

    def resolve(self, ref: str) -> ModelEndpoint:
        endpoint = self._inner.resolve(ref)
        return _BudgetCheckingEndpoint(
            wrapped=endpoint,
            cancel_token=self._cancel,
            budget_usd=self._budget_usd,
            registry=self,
        )


class _BudgetCheckingEndpoint:
    """
    Wraps a ModelEndpoint to intercept generate() with a pre-flight
    estimate_cost() check before streaming begins.
    """

    def __init__(
        self,
        wrapped: ModelEndpoint,
        cancel_token: CancelToken,
        budget_usd: float | None,
        registry: _BudgetEnforcingRegistry,
    ) -> None:
        self._wrapped = wrapped
        self._cancel = cancel_token
        self._budget_usd = budget_usd
        self._registry = registry
        self.id = wrapped.id

    async def generate(self, req: GenRequest) -> AsyncIterator[Token]:
        runner = self._registry._runner
        estimated = self._wrapped.estimate_cost(req)
        runner._total_tokens_in += estimated.tokens_in

        if (
            self._budget_usd is not None
            and runner._cumulative_cost + estimated.usd > self._budget_usd
        ):
            self._registry.budget_exceeded = True
            self._registry.exceeded_at_node = self.id
            self._cancel.cancel(
                f"Budget exceeded: ${runner._cumulative_cost + estimated.usd:.6f} "
                f"> ${self._budget_usd:.6f}"
            )
            # Raise so the scheduler stops — will be caught as PipelineCancelled
            from neuralflow.scheduler.engine import PipelineCancelled

            raise PipelineCancelled(self._cancel.reason)

        runner._cumulative_cost += estimated.usd

        async for token in self._wrapped.generate(req):
            yield token

    async def health(self) -> Health:
        return await self._wrapped.health()

    def capabilities(self) -> Caps:
        return self._wrapped.capabilities()

    def estimate_cost(self, req: GenRequest) -> Cost:
        return self._wrapped.estimate_cost(req)
