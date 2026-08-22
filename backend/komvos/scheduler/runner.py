"""
backend/komvos/scheduler/runner.py

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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from komvos.governance.profiles import GovernanceProfile
    from komvos.state.sqlite import StateManager

from komvos.compiler.dag import CompiledDAG
from komvos.compiler.models import AccessPolicy
from komvos.endpoints.base import (
    Caps,
    Cost,
    GenRequest,
    Health,
    ModelEndpoint,
    Token,
)
from komvos.governance.context import RunGovernance, run_context
from komvos.governance.sinks import (
    CompositeDecisionSink,
    DecisionSink,
    InMemoryDecisionSink,
    QueueDecisionSink,
    SqliteDecisionSink,
)
from komvos.scheduler.engine import (
    CancelToken,
    EndpointRegistry,
    EventKind,
    Scheduler,
    SchedulerEvent,
)
from komvos.scheduler.events import (
    WsAccessDeniedEvent,
    WsApprovalPendingEvent,
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


def _tightest_budget(requested: float | None, dag: CompiledDAG) -> float | None:
    """
    Combine the caller's USD budget with the access policies' cost ceilings.

    Every node's effective policy may carry a `max_cost_usd`. The run must not
    exceed the strictest of them, so the run budget becomes the minimum of the
    requested budget and every policy ceiling. `None` means "no ceiling from
    this source" and never tightens anything.

    This deliberately reuses the existing CancelToken budget path in
    _BudgetEnforcingRegistry instead of adding a parallel enforcement
    mechanism.
    """
    ceilings = [
        policy.max_cost_usd
        for policy in dag.effective_policies.values()
        if policy.max_cost_usd is not None
    ]
    if requested is not None:
        ceilings.append(requested)
    return min(ceilings) if ceilings else None


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
        deployment_id: str | None = None,
        initial_inputs: dict[str, dict[str, Any]] | None = None,
        profile: GovernanceProfile | None = None,
        served: bool = False,
    ) -> None:
        self.run_id = run_id
        self._dag = dag
        self._registry = registry
        # A policy cost ceiling tightens the run's budget through the existing
        # CancelToken path rather than a second budget system: take the lowest
        # ceiling any node is subject to, and the lower of that and whatever
        # the caller asked for.
        self._budget_usd = _tightest_budget(budget_usd, dag)
        self._budget_wall_clock_ms = (
            int(budget_wall_clock_seconds * 1000) if budget_wall_clock_seconds else None
        )
        self._state_manager = state_manager
        # Set when this run was started by a served HTTP request (Phase 3)
        # rather than the canvas, so the trace tables can tell them apart.
        self._deployment_id = deployment_id
        # The governance profile in force for this run. Served runs use the
        # deployment's snapshot; canvas runs pass whatever was resolved at
        # start time. None behaves exactly as before profiles existed.
        self._profile = profile
        # True for runs started by a served HTTP request: Ask degrades to
        # Enforce because there is no human to prompt mid-HTTP-request.
        self._served = served
        # Per-node-id port overrides for input nodes, applied on top of the
        # default "" seed. Phase 3 uses this to inject a served request's
        # mapped body values without touching how canvas runs seed inputs.
        self._initial_inputs = initial_inputs
        self._cancel = CancelToken()
        self._cumulative_cost: float = 0.0
        self._total_tokens_in: int = 0
        self._total_tokens_out: int = 0
        self._stopped_by_user: bool = False
        self._start_ms: int = 0
        # Created fresh per run() and bound into the governance context for
        # the run's duration, so every enforcement point under this runner
        # can record decisions without threading a sink through signatures.
        self.decision_sink: InMemoryDecisionSink | None = None

    def stop(self) -> None:
        """Signal the pipeline to halt at the next checkpoint."""
        self._stopped_by_user = True
        self._cancel.cancel("Run stopped by user.")

    async def _persist_status(self, status: str) -> None:
        """
        Record the run's terminal status and accumulated totals.

        No-op when no StateManager was injected. Runs off the event loop for
        the same reason as the trace writes in `run()`.
        """
        if self._state_manager is None:
            return
        await asyncio.to_thread(
            self._state_manager.update_run_status,
            self.run_id,
            status,
            self._cumulative_cost,
            self._total_tokens_in,
            self._total_tokens_out,
        )

    async def run(self, queue: asyncio.Queue) -> None:  # type: ignore[type-arg]
        """
        Execute the pipeline in the background.

        Puts WsEvent objects into queue. Always terminates by putting None
        (sentinel) so the WS handler knows the task finished.

        Binds this run's governance state — decision sink, active profile,
        served flag, and its per-run approval registry — for the duration of
        the run. The registry is dropped when the binding is released, on
        every exit path including error and cancellation, so an ended run
        cannot leak a pending approval.

        The decision sink composes rather than replaces: every run keeps its
        in-memory sink for in-process queries, and additionally streams each
        decision onto the run's WsEvent queue (live UI) and — when a
        StateManager is injected — into the SQLite decision log (history that
        survives a restart).

        Canvas runs resolve the ACTIVE governance profile here if none was
        passed: the dial the user sets must govern ordinary canvas runs, not
        only served deployments. Served runs keep their deployment's snapshot
        (or None → fail-closed) exactly as G2 defined it.
        """
        if (
            self._profile is None
            and not self._served
            and self._state_manager is not None
        ):
            # Only resolve database profile if active profile has been configured
            active_val = self._state_manager.get_setting("active_governance_profile")
            if active_val is not None:
                from komvos.governance.profiles import active_profile

                self._profile = await asyncio.to_thread(
                    active_profile, self._state_manager
                )

        self.decision_sink = InMemoryDecisionSink()
        sinks: list[DecisionSink] = [QueueDecisionSink(queue), self.decision_sink]
        if self._state_manager is not None:
            sinks.append(SqliteDecisionSink(self._state_manager))
        with run_context(
            CompositeDecisionSink(sinks),
            self.run_id,
            profile=self._profile,
            served=self._served,
        ) as governance:
            assert isinstance(governance, RunGovernance)
            try:
                await self._run(queue)
            finally:
                # Belt and braces: run_context's unbind already removes the
                # approval registry; this also settles anything left pending.
                governance.approvals.close()

    async def _run(self, queue: asyncio.Queue) -> None:  # type: ignore[type-arg]
        """Body of run(), executing under the bound governance context."""
        self._start_ms = int(time.time() * 1000)

        resume_state = None
        if self._state_manager:
            resume_state = await asyncio.to_thread(
                self._state_manager.load_run_state, self.run_id
            )
            await asyncio.to_thread(
                self._state_manager.save_run,
                self.run_id,
                self._dag.pipeline.id,
                "running",
                deployment_id=self._deployment_id,
            )

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
            # Every trace write goes through asyncio.to_thread: sqlite3 is a
            # blocking C extension, and doing these on the event loop stalls the
            # WebSocket pump for the duration of the write. Under a fast
            # multi-node streaming run that shows up as a stuttering monitor.
            if self._state_manager:
                if event.kind == EventKind.NODE_DONE:
                    await asyncio.to_thread(
                        self._state_manager.save_node_execution,
                        self.run_id,
                        event.node_id or "",
                        inputs=event.data.get("inputs"),
                        outputs=event.data.get("outputs"),
                        cost=event.data.get("cost_usd"),
                        tokens_in=event.data.get("tokens_in"),
                        tokens_out=event.data.get("tokens_out"),
                    )
                elif event.kind == EventKind.NODE_ERROR:
                    await asyncio.to_thread(
                        self._state_manager.save_node_execution,
                        self.run_id,
                        event.node_id or "",
                        error=event.data.get("error"),
                    )
                elif event.kind == EventKind.LOOP_ITERATION:
                    await asyncio.to_thread(
                        self._state_manager.save_loop_iteration,
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

        initial_inputs = {
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
        }
        # A served request's mapped body values override the node's own
        # default_value / "" seed, port by port. Canvas runs never set
        # self._initial_inputs, so this is a no-op for them.
        for node_id, port_values in (self._initial_inputs or {}).items():
            initial_inputs.setdefault(node_id, {}).update(port_values)

        try:
            result = await scheduler.run(initial_inputs, resume_state=resume_state)
        except Exception as exc:
            logger.exception("Unhandled error in pipeline run %s", self.run_id)
            await self._persist_status("error")
            await queue.put(WsRunErrorEvent(run_id=self.run_id, error=str(exc)))
            await queue.put(None)
            return

        elapsed_ms = int(time.time() * 1000) - self._start_ms

        if result.completed:
            await self._persist_status("completed")
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
                await self._persist_status("stopped")
                await queue.put(WsRunStoppedEvent(run_id=self.run_id))
            elif budget_registry.budget_exceeded:
                await self._persist_status("budget_exceeded")
                await queue.put(
                    WsBudgetExceededEvent(
                        run_id=self.run_id,
                        cumulative_cost_usd=self._cumulative_cost,
                        budget_usd=self._budget_usd or 0.0,
                        node_id=budget_registry.exceeded_at_node or "",
                    )
                )
            else:
                await self._persist_status("halted")
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
            node_cost = float(d.get("cost_usd", 0.0) or 0.0)
            node_tin = int(d.get("tokens_in", 0) or 0)
            node_tout = int(d.get("tokens_out", 0) or 0)
            self._total_tokens_in += node_tin
            self._total_tokens_out += node_tout
            self._cumulative_cost += node_cost
            return WsNodeDoneEvent(
                run_id=self.run_id,
                node_id=node_id,
                inputs=d.get("inputs", {}),
                outputs=d.get("outputs", {}),
                cost_usd=d.get("cost_usd"),
                tokens_in=d.get("tokens_in"),
                tokens_out=d.get("tokens_out"),
                is_estimate=bool(d.get("is_estimate", False)),
            )
        if event.kind == EventKind.NODE_ERROR:
            from komvos.scheduler.events import WsNodeErrorEvent

            return WsNodeErrorEvent(
                run_id=self.run_id,
                node_id=node_id,
                error=d.get("error", "Unknown error"),
            )
        if event.kind == EventKind.ACCESS_DENIED:
            return WsAccessDeniedEvent(
                run_id=self.run_id,
                node_id=node_id,
                capability=d.get("capability", "unknown"),
                reason=d.get("reason", "Denied by access policy."),
            )
        if event.kind == EventKind.APPROVAL_PENDING:
            return WsApprovalPendingEvent(
                run_id=self.run_id,
                node_id=node_id,
                approval_id=d.get("approval_id", ""),
                domain=d.get("domain", ""),
                capability=d.get("capability", "unknown"),
                reason=d.get("reason", ""),
                allow_once_effect=d.get("allow_once_effect", ""),
                allow_for_run_effect=d.get("allow_for_run_effect", ""),
                deny_effect=d.get("deny_effect", ""),
                timeout_seconds=float(d.get("timeout_seconds", 0.0)),
            )
        if event.kind == EventKind.TOKEN:
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
        self._current_node_id: str | None = None

    def __getattr__(self, name: str) -> Any:
        """
        Delegate unknown attributes to the wrapped endpoint.

        Governance reads `.provider` / `.base_url` / `._base_url` off an
        endpoint to know where its traffic would land; without delegation the
        budget wrapper would hide those and blind the egress gate for every
        runner-driven run.
        """
        return getattr(self._wrapped, name)

    async def generate(self, req: GenRequest) -> AsyncIterator[Token]:
        runner = self._registry._runner
        estimated = self._wrapped.estimate_cost(req)

        if (
            self._budget_usd is not None
            and runner._cumulative_cost + estimated.usd > self._budget_usd
        ):
            self._registry.budget_exceeded = True
            self._registry.exceeded_at_node = (
                self._current_node_id or self.id
            )
            self._cancel.cancel(
                f"Budget exceeded: ${runner._cumulative_cost + estimated.usd:.6f} "
                f"> ${self._budget_usd:.6f}"
            )
            # Raise so the scheduler stops — will be caught as PipelineCancelled
            from komvos.scheduler.engine import PipelineCancelled

            raise PipelineCancelled(self._cancel.reason)

        async for token in self._wrapped.generate(req):
            yield token

    def check_access(self, policy: AccessPolicy, node_id: str) -> None:
        # Delegate: the wrapper only adds budget enforcement, so the wrapped
        # endpoint remains the authority on what its provider is.
        self._current_node_id = node_id
        self._wrapped.check_access(policy, node_id)

    async def health(self) -> Health:
        return await self._wrapped.health()

    def capabilities(self) -> Caps:
        return self._wrapped.capabilities()

    def estimate_cost(self, req: GenRequest) -> Cost:
        return self._wrapped.estimate_cost(req)

    def calculate_cost(
        self, tokens_in: int, tokens_out: int, is_estimate: bool = False
    ) -> Cost:
        if hasattr(self._wrapped, "calculate_cost"):
            return self._wrapped.calculate_cost(
                tokens_in, tokens_out, is_estimate=is_estimate
            )
        return Cost(
            usd=0.0,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            is_estimate=is_estimate,
        )
