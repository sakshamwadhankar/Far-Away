"""
backend/neuralflow/scheduler/engine.py

Async execution engine for compiled NeuralFlow pipelines.

Responsibilities:
  - Topological execution order (from CompiledDAG)
  - Parallel branch execution via asyncio.gather
  - Bounded loop subgraph iteration with per-iteration IO recording
  - Stop condition evaluation (structured, no eval)
  - Injected EndpointRegistry — never hardcodes or imports real endpoints
  - Live event streaming via injected callback (for WebSocket)
  - Cooperative cancellation via CancelToken (for kill switch / budget)

The scheduler is ENDPOINT-AGNOSTIC (TRD §2):
  "The scheduler is endpoint-agnostic: it never knows whether a node is
   cloud, local, or sharded. This is the single most important design
   constraint."

BREAKING CHANGE: EndpointRegistry, SchedulerResult, SchedulerEvent,
and CancelToken are shared contracts.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from neuralflow.compiler.dag import CompiledDAG
from neuralflow.compiler.models import StopCondition
from neuralflow.endpoints.base import GenRequest, Message, ModelEndpoint
from neuralflow.scheduler.stop_eval import (
    StopFieldResolutionError,
    evaluate_stop_condition,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EndpointRegistry — injected, never hardcoded
# ---------------------------------------------------------------------------


class EndpointRegistry:
    """
    Maps endpoint_ref strings to ModelEndpoint instances.

    This is the ONLY way the scheduler resolves endpoints.
    In tests, inject MockEndpoint instances. In production, inject
    CloudEndpoint / OllamaEndpoint instances resolved from the pipeline's
    endpoints map + OS keychain.
    """

    def __init__(self, endpoints: dict[str, ModelEndpoint]) -> None:
        self._endpoints: dict[str, ModelEndpoint] = dict(endpoints)

    def resolve(self, ref: str) -> ModelEndpoint:
        """
        Resolve an endpoint_ref to a ModelEndpoint.

        Raises KeyError if the ref is not registered.
        """
        if ref not in self._endpoints:
            raise KeyError(
                f"Endpoint ref '{ref}' not found in registry. "
                f"Available: {list(self._endpoints.keys())}."
            )
        return self._endpoints[ref]


# ---------------------------------------------------------------------------
# CancelToken — cooperative cancellation for kill switch / budget
# ---------------------------------------------------------------------------


class PipelineCancelled(Exception):
    """Raised when a pipeline run is cancelled via CancelToken."""


class CancelToken:
    """
    Cooperative cancellation token.

    The API layer / budget enforcer calls cancel() to halt a running
    pipeline. The scheduler checks is_cancelled before each node
    execution and each loop iteration.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._reason: str = "Pipeline cancelled."

    def cancel(self, reason: str = "Pipeline cancelled.") -> None:
        """Signal cancellation. Thread-safe (simple bool flip)."""
        self._reason = reason
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    def check(self) -> None:
        """Raise PipelineCancelled if the token has been cancelled."""
        if self._cancelled:
            raise PipelineCancelled(self._reason)


# ---------------------------------------------------------------------------
# Event types — for WebSocket streaming
# ---------------------------------------------------------------------------


class EventKind(StrEnum):
    """Discriminator for scheduler events."""

    NODE_STARTED = "node_started"
    NODE_DONE = "node_done"
    NODE_ERROR = "node_error"
    TOKEN = "token"
    LOOP_ITERATION = "loop_iteration"
    RUN_HALTED = "run_halted"


class SchedulerEvent(BaseModel):
    """
    Event emitted during pipeline execution.

    The API layer converts these to WebSocket frames:
      - node_started → show spinner on the node
      - token        → stream partial text in the panel
      - node_done    → show final result + cost
      - loop_iteration → update loop counter in the UI
      - run_halted   → show error banner
    """

    kind: EventKind
    node_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


# Callback type: can be sync or async
EventCallback = Callable[[SchedulerEvent], Awaitable[None] | None]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class NodeResult(BaseModel):
    """Output of a single node execution."""

    node_id: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    """port_name → value"""


class LoopIterationRecord(BaseModel):
    """Per-iteration IO for one loop iteration."""

    iteration: int
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class SchedulerResult(BaseModel):
    """Full execution result for a pipeline run."""

    node_results: dict[str, NodeResult] = Field(default_factory=dict)
    """node_id → NodeResult"""

    loop_histories: dict[str, list[LoopIterationRecord]] = Field(
        default_factory=dict
    )
    """loop_id → list of per-iteration records"""

    completed: bool = True
    """False if the run was halted (budget, kill switch, loop failure)."""


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class Scheduler:
    """
    Async pipeline execution engine.

    Consumes a CompiledDAG and an injected EndpointRegistry.
    Executes nodes in topological order, runs independent branches in
    parallel, and handles loop subgraphs as bounded iterations.
    """

    def __init__(
        self,
        dag: CompiledDAG,
        registry: EndpointRegistry,
        *,
        event_callback: EventCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> None:
        self._dag = dag
        self._registry = registry
        self._event_callback = event_callback
        self._cancel = cancel_token
        self._state: dict[str, dict[str, Any]] = {}
        self._resume_state: dict[str, dict[str, Any]] = {}
        """State loaded from previous checkpoints."""

    async def run(
        self,
        initial_inputs: dict[str, Any],
        resume_state: dict[str, dict[str, Any]] | None = None,
    ) -> SchedulerResult:
        """
        Execute the pipeline.

        Args:
            initial_inputs: Values for input nodes' output ports.
                Example: {"in": {"prompt": "Hello world"}}

        Returns:
            SchedulerResult with all node outputs and loop histories.
        """
        self._state = {}
        self._resume_state = {}
        loop_histories: dict[str, list[LoopIterationRecord]] = {}

        if resume_state:
            self._resume_state = dict(resume_state)
            for node_id, outputs in resume_state.items():
                self._state[node_id] = dict(outputs)

        # Seed input nodes
        for node_id, ports in initial_inputs.items():
            self._state[node_id] = dict(ports)

        # Build execution tiers: groups of nodes that can run in parallel.
        tiers = self._build_execution_tiers()

        try:
            for tier in tiers:
                # Check cancellation before each tier
                self._check_cancel()

                # Filter out loop body nodes
                regular_nodes = [
                    nid for nid in tier
                    if nid not in self._dag.node_to_loop
                ]

                # Check if any node in this tier is a loop entry
                loop_entries = self._find_loop_entries_in_tier(tier)

                # Execute regular nodes in parallel
                if len(regular_nodes) > 1:
                    tasks = [
                        self._execute_node(nid)
                        for nid in regular_nodes
                    ]
                    await asyncio.gather(*tasks)
                elif len(regular_nodes) == 1:
                    await self._execute_node(regular_nodes[0])

                # Execute any loops that are ready
                for loop_id in loop_entries:
                    history = await self._execute_loop(loop_id)
                    loop_histories[loop_id] = history

        except PipelineCancelled as exc:
            await self._emit(SchedulerEvent(
                kind=EventKind.RUN_HALTED,
                data={"reason": str(exc)},
            ))
            return SchedulerResult(
                node_results=self._build_node_results(),
                loop_histories=loop_histories,
                completed=False,
            )

        return SchedulerResult(
            node_results=self._build_node_results(),
            loop_histories=loop_histories,
            completed=True,
        )

    def _build_node_results(self) -> dict[str, NodeResult]:
        """Build NodeResult dict from current state."""
        return {
            node_id: NodeResult(node_id=node_id, outputs=outputs)
            for node_id, outputs in self._state.items()
        }

    def _check_cancel(self) -> None:
        """Raise PipelineCancelled if the cancel token is set."""
        if self._cancel is not None:
            self._cancel.check()

    async def _emit(self, event: SchedulerEvent) -> None:
        """Emit an event to the registered callback, if any."""
        if self._event_callback is not None:
            result = self._event_callback(event)
            if asyncio.iscoroutine(result):
                await result

    # ------------------------------------------------------------------
    # Tier computation
    # ------------------------------------------------------------------

    def _build_execution_tiers(self) -> list[list[str]]:
        """
        Group topo_order into tiers of parallelizable nodes.

        Nodes in the same tier have no edges between them —
        they can safely run concurrently.
        """
        topo = self._dag.topo_order
        if not topo:
            return []

        # Compute tier index: max(tier of predecessors) + 1
        # Nodes with no predecessors (in main graph) get tier 0
        tier_of: dict[str, int] = {}

        for nid in topo:
            preds = self._dag.reverse_adj.get(nid, [])
            # Only consider predecessors that are in topo_order
            # (loop-internal edges may reference nodes not in main topo)
            pred_tiers = [
                tier_of[p]
                for p in preds
                if p in tier_of
            ]
            tier_of[nid] = (max(pred_tiers) + 1) if pred_tiers else 0

        # Group by tier
        max_tier = max(tier_of.values()) if tier_of else 0
        tiers: list[list[str]] = [[] for _ in range(max_tier + 1)]
        for nid in topo:
            tiers[tier_of[nid]].append(nid)

        return tiers

    def _find_loop_entries_in_tier(self, tier: list[str]) -> list[str]:
        """
        Find loop IDs whose first body node is in this tier.

        A loop is "ready" when its entry node's predecessors (outside the
        loop) have been completed.
        """
        seen_loops: set[str] = set()
        loop_entries: list[str] = []

        for nid in tier:
            if nid in self._dag.node_to_loop:
                loop_id = self._dag.node_to_loop[nid]
                loop = self._dag.loop_map[loop_id]
                # Only trigger on the FIRST body node
                if loop.body[0] == nid and loop_id not in seen_loops:
                    seen_loops.add(loop_id)
                    loop_entries.append(loop_id)

        return loop_entries

    # ------------------------------------------------------------------
    # Node execution
    # ------------------------------------------------------------------

    async def _execute_node(self, node_id: str) -> None:
        """
        Execute a single node using its registered executor.
        """
        from neuralflow.executors import EXECUTOR_REGISTRY, ExecutorContext

        try:
            self._check_cancel()

            node = self._get_node(node_id)

            if node_id in self._resume_state and node.type != "input":
                # Node was resumed from a previous checkpoint
                # Remove it so loop iterations will run normally
                del self._resume_state[node_id]
                
                await self._emit(SchedulerEvent(
                    kind=EventKind.NODE_DONE,
                    node_id=node_id,
                    data={"outputs": self._state[node_id]},
                ))
                return

            await self._emit(SchedulerEvent(
                kind=EventKind.NODE_STARTED,
                node_id=node_id,
                data={"type": node.type},
            ))

            if node.type == "input" and node_id not in self._state:
                raise RuntimeError(
                    f"Input node '{node_id}' has no initial "
                    "values in state. Provide them in "
                    "initial_inputs."
                )

            if node.type not in EXECUTOR_REGISTRY:
                raise NotImplementedError(
                    f"Node type '{node.type}' is not supported. "
                    f"Available executors: {list(EXECUTOR_REGISTRY.keys())}"
                )

            executor_cls = EXECUTOR_REGISTRY[node.type]
            executor = executor_cls()

            # Gather inputs
            if node.type != "input":
                input_values = self._gather_inputs_for_node(node_id)
            else:
                input_values = self._state[node_id]

            # Build context
            ctx = ExecutorContext(
                node=node,
                inputs=input_values,
                registry=self._registry,
                emit_fn=self._emit,
                cancel_token=self._cancel,
            )

            # Execute
            outputs = await executor.execute(ctx)
            
            # Store outputs
            self._state[node_id] = outputs

        except Exception as exc:
            await self._emit(SchedulerEvent(
                kind=EventKind.NODE_ERROR,
                node_id=node_id,
                data={"error": str(exc)},
            ))
            raise

    def _gather_inputs_for_node(self, node_id: str) -> dict[str, Any]:
        """
        Collect input values for a node from the execution state,
        following the edge definitions.
        """
        inputs: dict[str, Any] = {}
        for edge in self._dag.pipeline.edges:
            if edge.target_node() == node_id:
                src_node = edge.source_node()
                src_port = edge.source_port()
                dst_port = edge.target_port()

                if src_node in self._state:
                    src_outputs = self._state[src_node]
                    if src_port in src_outputs:
                        inputs[dst_port] = src_outputs[src_port]

        return inputs

    def _get_node(self, node_id: str) -> Any:
        """Look up a node by ID in the pipeline."""
        for node in self._dag.pipeline.nodes:
            if node.id == node_id:
                return node
        raise RuntimeError(
            f"Node '{node_id}' not found in pipeline. This should never "
            "happen after compilation — possible compiler bug."
        )

    # ------------------------------------------------------------------
    # Loop execution
    # ------------------------------------------------------------------

    async def _execute_loop(
        self, loop_id: str
    ) -> list[LoopIterationRecord]:
        """
        Execute a loop subgraph as bounded iterations.

        For each iteration:
          1. Execute body nodes sequentially (in declared order).
          2. Record per-iteration IO.
          3. Evaluate stop_when condition.
          4. If stop_when is True → break.
          5. If max_iterations reached → apply on_max policy.
        """
        loop = self._dag.loop_map[loop_id]
        history: list[LoopIterationRecord] = []

        for iteration in range(1, loop.max_iterations + 1):
            # Check cancellation before each iteration
            self._check_cancel()

            # Capture inputs for this iteration
            iter_inputs: dict[str, Any] = {}
            for body_node_id in loop.body:
                gathered = self._gather_inputs_for_node(
                    body_node_id
                )
                if gathered:
                    iter_inputs[body_node_id] = gathered

            # Execute body nodes sequentially
            for body_node_id in loop.body:
                await self._execute_node(body_node_id)

            # Capture outputs for this iteration
            iter_outputs: dict[str, Any] = {}
            for body_node_id in loop.body:
                if body_node_id in self._state:
                    iter_outputs[body_node_id] = dict(
                        self._state[body_node_id]
                    )

            # Record iteration
            record = LoopIterationRecord(
                iteration=iteration,
                inputs=iter_inputs,
                outputs=iter_outputs,
            )
            history.append(record)

            await self._emit(SchedulerEvent(
                kind=EventKind.LOOP_ITERATION,
                data={
                    "loop_id": loop_id,
                    "iteration": iteration,
                    "max_iterations": loop.max_iterations,
                    "outputs": iter_outputs,
                },
            ))

            logger.debug(
                "Loop '%s' iteration %d/%d completed",
                loop_id,
                iteration,
                loop.max_iterations,
            )

            # Evaluate stop condition
            if self._check_stop_condition(loop.stop_when):
                logger.info(
                    "Loop '%s' stopped at iteration %d: condition met.",
                    loop_id,
                    iteration,
                )
                break
        else:
            # max_iterations reached without stop condition
            logger.info(
                "Loop '%s' reached max_iterations=%d. Policy: %s",
                loop_id,
                loop.max_iterations,
                loop.on_max,
            )
            if loop.on_max == "fail":
                raise RuntimeError(
                    f"Loop '{loop_id}' exhausted {loop.max_iterations} "
                    f"iterations without meeting stop condition. "
                    f"Policy 'fail' triggered."
                )
            # return_best and return_last both return the last state
            # (return_best requires scorer integration — Phase 3)

        return history

    def _check_stop_condition(self, condition: StopCondition) -> bool:
        """
        Evaluate a stop condition against current execution state.
        Returns False (instead of raising) if the field doesn't exist yet.
        """
        try:
            return evaluate_stop_condition(condition, self._state)
        except StopFieldResolutionError:
            # Field not yet available — condition not met
            return False
