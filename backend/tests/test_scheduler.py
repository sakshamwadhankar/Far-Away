"""
backend/tests/test_scheduler.py

Phase 2 — Tests for the pipeline scheduler.

Tests:
  1. test_parallel_branches — Diamond DAG: input → [A, B] → output.
     Verifies A and B run concurrently (both start before either finishes).
  2. test_loop_stops_on_condition — Loop with stop_when, MockEndpoint returns
     {"verified": true} on iteration 3. Assert loop ran exactly 3 iterations.
  3. test_loop_hits_max_iterations — MockEndpoint always returns
     {"verified": false}. max_iterations=3. Assert loop ran exactly 3.
  4. test_stop_eval_operators — Unit tests for all 7 stop_when operators.
  5. test_loop_on_max_fail — Loop with on_max="fail" raises RuntimeError.

Run with:
    pytest backend/tests/test_scheduler.py -v

No live services, no API keys. All endpoints are MockEndpoint (AGENT.md rule 1).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from neuralflow.compiler.dag import compile
from neuralflow.compiler.models import StopCondition
from neuralflow.endpoints.mock import MockEndpoint
from neuralflow.scheduler.engine import (
    CancelToken,
    EndpointRegistry,
    EventKind,
    PipelineCancelled,
    Scheduler,
    SchedulerEvent,
    SchedulerResult,
)
from neuralflow.scheduler.stop_eval import (
    StopConditionTypeError,
    StopFieldResolutionError,
    evaluate_stop_condition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(**endpoints: MockEndpoint) -> EndpointRegistry:
    """Build an EndpointRegistry from named MockEndpoints."""
    return EndpointRegistry(endpoints)


# ---------------------------------------------------------------------------
# Pipeline fixtures
# ---------------------------------------------------------------------------


DIAMOND_PIPELINE: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000020",
    "name": "Diamond Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "branch_a",
            "type": "model",
            "endpoint_ref": "mock:a",
            "config": {"temperature": 0.5},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "branch_b",
            "type": "model",
            "endpoint_ref": "mock:b",
            "config": {"temperature": 0.5},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [
                {"name": "result_a", "type": "text"},
                {"name": "result_b", "type": "text"},
            ],
        },
    ],
    "edges": [
        {"from": "in.prompt", "to": "branch_a.input"},
        {"from": "in.prompt", "to": "branch_b.input"},
        {"from": "branch_a.output", "to": "out.result_a"},
        {"from": "branch_b.output", "to": "out.result_b"},
    ],
    "endpoints": {
        "mock:a": {"kind": "openai"},
        "mock:b": {"kind": "openai"},
    },
}


LOOP_PIPELINE: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000021",
    "name": "Loop Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "solver",
            "type": "model",
            "endpoint_ref": "mock:solver",
            "config": {"temperature": 0.7},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "verify",
            "type": "model",
            "endpoint_ref": "mock:verify",
            "config": {"temperature": 0.2, "response_format": "json"},
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "json"}],
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
    ],
    "loops": [
        {
            "id": "refine",
            "body": ["solver", "verify"],
            "max_iterations": 5,
            "stop_when": {
                "field": "verify.output.verified",
                "op": "==",
                "value": True,
            },
            "on_max": "return_last",
        }
    ],
    "edges": [
        {"from": "in.prompt", "to": "solver.input"},
        {"from": "solver.output", "to": "verify.input"},
        {"from": "solver.output", "to": "out.result"},
    ],
    "endpoints": {
        "mock:solver": {"kind": "openai"},
        "mock:verify": {"kind": "openai"},
    },
}


def _make_loop_pipeline_fail() -> dict[str, Any]:
    """Same loop pipeline but with on_max='fail'."""
    pipe = json.loads(json.dumps(LOOP_PIPELINE))
    pipe["id"] = "00000000-0000-4000-a000-000000000022"
    pipe["name"] = "Loop Fail Pipeline"
    pipe["loops"][0]["max_iterations"] = 3
    pipe["loops"][0]["on_max"] = "fail"
    return pipe


# ---------------------------------------------------------------------------
# Test 1: Parallel branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_branches() -> None:
    """
    Diamond DAG: in → [branch_a, branch_b] → out.

    Concurrency proof (CI-safe, no wall-clock flakiness):
    We track event ordering — both branches must emit node_started
    before either emits node_done. If the scheduler ran them
    sequentially, A would start AND finish before B starts.

    Secondary: timing sanity check with very generous tolerance.
    """
    delay = 0.05  # 50ms per token, 3 tokens each

    # Collect events in order
    events: list[SchedulerEvent] = []

    async def collect_events(event: SchedulerEvent) -> None:
        events.append(event)

    endpoint_a = MockEndpoint(
        id="mock:a",
        token_delay=delay,
        predefined_text="Response from A",
    )
    endpoint_b = MockEndpoint(
        id="mock:b",
        token_delay=delay,
        predefined_text="Response from B",
    )

    registry = EndpointRegistry({
        "mock:a": endpoint_a,
        "mock:b": endpoint_b,
    })

    dag = compile(DIAMOND_PIPELINE)
    scheduler = Scheduler(
        dag, registry, event_callback=collect_events
    )

    start = time.monotonic()
    result = await scheduler.run({"in": {"prompt": "test input"}})
    elapsed = time.monotonic() - start

    # Both branches completed with correct outputs
    assert result.completed is True
    assert result.node_results["branch_a"].outputs["output"] == (
        "Response from A"
    )
    assert result.node_results["branch_b"].outputs["output"] == (
        "Response from B"
    )

    # --- Primary assertion: event ordering proves concurrency ---
    # Extract node_started / node_done events for the two branches
    branch_events = [
        (e.kind, e.node_id)
        for e in events
        if e.node_id in ("branch_a", "branch_b")
        and e.kind in (EventKind.NODE_STARTED, EventKind.NODE_DONE)
    ]

    # Both node_started must appear before any node_done.
    # If sequential: [started_a, done_a, started_b, done_b]
    # If parallel:   [started_a, started_b, ..., done_a, done_b]
    #                  (or started_b, started_a, ...)
    started_indices = [
        i for i, (kind, _) in enumerate(branch_events)
        if kind == EventKind.NODE_STARTED
    ]
    done_indices = [
        i for i, (kind, _) in enumerate(branch_events)
        if kind == EventKind.NODE_DONE
    ]

    assert len(started_indices) == 2, (
        f"Expected 2 node_started events, got {len(started_indices)}"
    )
    assert len(done_indices) == 2, (
        f"Expected 2 node_done events, got {len(done_indices)}"
    )

    # Both starts must happen before EITHER finish
    max_start_idx = max(started_indices)
    min_done_idx = min(done_indices)
    assert max_start_idx < min_done_idx, (
        "Parallelism violation: a branch finished before both "
        "branches started. Event order: "
        f"{branch_events}"
    )

    # --- Secondary: timing sanity (very generous tolerance) ---
    sequential_time = 2 * (3 * delay)
    assert elapsed < sequential_time * 0.95, (
        f"elapsed={elapsed:.3f}s exceeds 95% of sequential "
        f"estimate ({sequential_time * 0.95:.3f}s)"
    )


# ---------------------------------------------------------------------------
# Test 2: Loop stops on condition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_stops_on_condition() -> None:
    """
    Loop with stop_when: verify.output.verified == true.
    MockEndpoint returns {"verified": false} for iterations 1–2,
    then {"verified": true} for iteration 3. Loop must run exactly 3 times.
    """
    call_count = 0

    def verify_response_fn(req: Any) -> str:
        nonlocal call_count
        call_count += 1
        # Iterations 1 and 2: not verified
        # Iteration 3: verified
        if call_count >= 3:
            return json.dumps({"verified": True, "score": 0.95})
        return json.dumps({"verified": False, "score": 0.3})

    solver_endpoint = MockEndpoint(
        id="mock:solver",
        predefined_text="Solver output iteration",
    )
    verify_endpoint = MockEndpoint(
        id="mock:verify",
        response_fn=verify_response_fn,
    )

    registry = EndpointRegistry({
        "mock:solver": solver_endpoint,
        "mock:verify": verify_endpoint,
    })

    dag = compile(LOOP_PIPELINE)
    scheduler = Scheduler(dag, registry)

    result = await scheduler.run({"in": {"prompt": "Solve this problem"}})

    assert result.completed is True
    assert "refine" in result.loop_histories

    history = result.loop_histories["refine"]
    assert len(history) == 3, (
        f"Expected loop to stop at iteration 3, but ran {len(history)} iterations."
    )

    # Verify per-iteration records exist
    assert history[0].iteration == 1
    assert history[1].iteration == 2
    assert history[2].iteration == 3

    # Verify the last iteration had the verified output
    last_outputs = history[2].outputs
    assert "verify" in last_outputs
    assert last_outputs["verify"]["output"]["verified"] is True


# ---------------------------------------------------------------------------
# Test 3: Loop hits max iterations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_hits_max_iterations() -> None:
    """
    Loop with max_iterations=5. MockEndpoint always returns
    {"verified": false}. Loop must run exactly 5 times and return
    gracefully (on_max="return_last").
    """
    verify_endpoint = MockEndpoint(
        id="mock:verify",
        json_response={"verified": False, "score": 0.1},
    )
    solver_endpoint = MockEndpoint(
        id="mock:solver",
        predefined_text="Solver attempt",
    )

    registry = EndpointRegistry({
        "mock:solver": solver_endpoint,
        "mock:verify": verify_endpoint,
    })

    dag = compile(LOOP_PIPELINE)
    scheduler = Scheduler(dag, registry)

    result = await scheduler.run({"in": {"prompt": "Unsolvable problem"}})

    assert result.completed is True
    assert "refine" in result.loop_histories

    history = result.loop_histories["refine"]
    assert len(history) == 5, (
        f"Expected loop to run max_iterations=5 times, but ran {len(history)}."
    )

    # All iterations should have verified=False
    for record in history:
        assert record.outputs["verify"]["output"]["verified"] is False


# ---------------------------------------------------------------------------
# Test 4: Loop on_max="fail" raises RuntimeError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_on_max_fail() -> None:
    """
    Loop with on_max="fail" and max_iterations=3. MockEndpoint always
    returns {"verified": false}. Must raise RuntimeError.
    """
    verify_endpoint = MockEndpoint(
        id="mock:verify",
        json_response={"verified": False},
    )
    solver_endpoint = MockEndpoint(
        id="mock:solver",
        predefined_text="Solver attempt",
    )

    registry = EndpointRegistry({
        "mock:solver": solver_endpoint,
        "mock:verify": verify_endpoint,
    })

    pipeline_data = _make_loop_pipeline_fail()
    dag = compile(pipeline_data)
    scheduler = Scheduler(dag, registry)

    with pytest.raises(RuntimeError, match="fail"):
        await scheduler.run({"in": {"prompt": "Will fail"}})


# ---------------------------------------------------------------------------
# Test 5: Stop evaluator — all 7 operators
# ---------------------------------------------------------------------------


class TestStopEvalOperators:
    """Unit tests for each stop_when operator."""

    def _make_state(self, value: Any) -> dict[str, dict[str, Any]]:
        return {"node": {"port": value}}

    def _cond(self, op: str, target: Any) -> StopCondition:
        return StopCondition(field="node.port", op=op, value=target)  # type: ignore[arg-type]

    def test_eq_true(self) -> None:
        assert evaluate_stop_condition(
            self._cond("==", True), self._make_state(True)
        ) is True

    def test_eq_false(self) -> None:
        assert evaluate_stop_condition(
            self._cond("==", True), self._make_state(False)
        ) is False

    def test_ne(self) -> None:
        assert evaluate_stop_condition(
            self._cond("!=", "bad"), self._make_state("good")
        ) is True

    def test_gt(self) -> None:
        assert evaluate_stop_condition(
            self._cond(">", 0.5), self._make_state(0.9)
        ) is True

    def test_gt_false(self) -> None:
        assert evaluate_stop_condition(
            self._cond(">", 0.5), self._make_state(0.3)
        ) is False

    def test_lt(self) -> None:
        assert evaluate_stop_condition(
            self._cond("<", 10.0), self._make_state(5.0)
        ) is True

    def test_ge(self) -> None:
        assert evaluate_stop_condition(
            self._cond(">=", 0.5), self._make_state(0.5)
        ) is True

    def test_le(self) -> None:
        assert evaluate_stop_condition(
            self._cond("<=", 0.5), self._make_state(0.5)
        ) is True

    def test_contains(self) -> None:
        assert evaluate_stop_condition(
            self._cond("contains", "success"), self._make_state("task success!")
        ) is True

    def test_contains_false(self) -> None:
        assert evaluate_stop_condition(
            self._cond("contains", "fail"), self._make_state("task success!")
        ) is False


# ---------------------------------------------------------------------------
# Test 6: Stop evaluator — nested JSON field traversal
# ---------------------------------------------------------------------------


def test_stop_eval_nested_json_field() -> None:
    """
    Field path "verify.output.result.verified" traverses:
    state["verify"]["output"]["result"]["verified"]
    """
    state: dict[str, dict[str, Any]] = {
        "verify": {
            "output": {"result": {"verified": True, "score": 0.9}},
        }
    }
    cond = StopCondition(
        field="verify.output.result.verified", op="==", value=True
    )
    assert evaluate_stop_condition(cond, state) is True


def test_stop_eval_json_string_auto_parse() -> None:
    """
    If the port value is a JSON string, the evaluator should auto-parse it
    for deeper traversal.
    """
    state: dict[str, dict[str, Any]] = {
        "verify": {
            "output": '{"verified": true, "score": 0.9}',
        }
    }
    cond = StopCondition(
        field="verify.output.verified", op="==", value=True
    )
    assert evaluate_stop_condition(cond, state) is True


# ---------------------------------------------------------------------------
# Test 7: Stop evaluator — error cases
# ---------------------------------------------------------------------------


def test_stop_eval_missing_node_raises() -> None:
    """Missing node in state raises StopFieldResolutionError."""
    state: dict[str, dict[str, Any]] = {}
    cond = StopCondition(field="missing.port", op="==", value=True)
    with pytest.raises(StopFieldResolutionError, match="missing"):
        evaluate_stop_condition(cond, state)


def test_stop_eval_missing_port_raises() -> None:
    """Missing port in node raises StopFieldResolutionError."""
    state: dict[str, dict[str, Any]] = {"node": {}}
    cond = StopCondition(field="node.missing_port", op="==", value=True)
    with pytest.raises(StopFieldResolutionError, match="missing_port"):
        evaluate_stop_condition(cond, state)


def test_stop_eval_contains_on_non_string_raises() -> None:
    """'contains' on a non-string value raises StopConditionTypeError."""
    state: dict[str, dict[str, Any]] = {"node": {"port": 42}}
    cond = StopCondition(field="node.port", op="contains", value="x")
    with pytest.raises(StopConditionTypeError, match="contains"):
        evaluate_stop_condition(cond, state)


# ---------------------------------------------------------------------------
# Test 8: EndpointRegistry rejects unknown refs
# ---------------------------------------------------------------------------


def test_endpoint_registry_unknown_ref() -> None:
    """EndpointRegistry.resolve() raises KeyError for unknown refs."""
    registry = EndpointRegistry({})
    with pytest.raises(KeyError, match="unknown:ref"):
        registry.resolve("unknown:ref")


# ---------------------------------------------------------------------------
# Test 9: Simple linear pipeline runs end-to-end
# ---------------------------------------------------------------------------

LINEAR_PIPELINE: dict[str, Any] = {
    "schema_version": "2.0",
    "id": "00000000-0000-4000-a000-000000000023",
    "name": "Simple Linear",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "model",
            "type": "model",
            "endpoint_ref": "mock:model",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
    ],
    "edges": [
        {"from": "in.prompt", "to": "model.input"},
        {"from": "model.output", "to": "out.result"},
    ],
    "endpoints": {
        "mock:model": {"kind": "openai"},
    },
}


@pytest.mark.asyncio
async def test_linear_pipeline_end_to_end() -> None:
    """Simple in→model→out pipeline runs and produces expected output."""
    endpoint = MockEndpoint(
        id="mock:model",
        predefined_text="Hello from mock",
    )
    registry = EndpointRegistry({"mock:model": endpoint})

    dag = compile(LINEAR_PIPELINE)
    scheduler = Scheduler(dag, registry)
    result = await scheduler.run({"in": {"prompt": "Hi"}})

    assert result.completed is True
    assert result.node_results["model"].outputs["output"] == (
        "Hello from mock"
    )
    assert result.node_results["out"].outputs["result"] == (
        "Hello from mock"
    )


# ---------------------------------------------------------------------------
# Test 10: CancelToken halts pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_token_halts_pipeline() -> None:
    """
    CancelToken.cancel() called before run starts.
    Pipeline should return completed=False with a run_halted event.
    """
    events: list[SchedulerEvent] = []

    async def collect(event: SchedulerEvent) -> None:
        events.append(event)

    endpoint = MockEndpoint(
        id="mock:model",
        predefined_text="Should not appear",
    )
    registry = EndpointRegistry({"mock:model": endpoint})

    dag = compile(LINEAR_PIPELINE)
    token = CancelToken()
    token.cancel("Budget exceeded $5.00")

    scheduler = Scheduler(
        dag, registry,
        event_callback=collect,
        cancel_token=token,
    )
    result = await scheduler.run({"in": {"prompt": "Hi"}})

    assert result.completed is False

    halt_events = [
        e for e in events
        if e.kind == EventKind.RUN_HALTED
    ]
    assert len(halt_events) == 1
    assert "Budget exceeded" in halt_events[0].data["reason"]


# ---------------------------------------------------------------------------
# Test 11: Event stream for a linear pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_stream_linear_pipeline() -> None:
    """
    Verify event ordering for in→model→out:
      node_started(in) → node_done(in) →
      node_started(model) → token* → node_done(model) →
      node_started(out) → node_done(out)
    """
    events: list[SchedulerEvent] = []

    async def collect(event: SchedulerEvent) -> None:
        events.append(event)

    endpoint = MockEndpoint(
        id="mock:model",
        predefined_text="Hello world",
    )
    registry = EndpointRegistry({"mock:model": endpoint})

    dag = compile(LINEAR_PIPELINE)
    scheduler = Scheduler(
        dag, registry, event_callback=collect
    )
    result = await scheduler.run({"in": {"prompt": "Hi"}})

    assert result.completed is True

    # Extract kinds in order
    kinds = [e.kind for e in events]

    # Must contain node lifecycle events for all 3 nodes
    assert kinds.count(EventKind.NODE_STARTED) == 3
    assert kinds.count(EventKind.NODE_DONE) == 3

    # Must contain token events (2 words = 2 tokens)
    assert kinds.count(EventKind.TOKEN) == 2

    # Model's token events must be between its started and done
    model_events = [
        (e.kind, e.node_id) for e in events
        if e.node_id == "model"
    ]
    assert model_events[0] == (EventKind.NODE_STARTED, "model")
    assert model_events[-1] == (EventKind.NODE_DONE, "model")
    # All middle events should be tokens
    for kind, _ in model_events[1:-1]:
        assert kind == EventKind.TOKEN


# ---------------------------------------------------------------------------
# Test 12: CancelToken unit tests
# ---------------------------------------------------------------------------


def test_cancel_token_initially_not_cancelled() -> None:
    token = CancelToken()
    assert token.is_cancelled is False
    token.check()  # should not raise


def test_cancel_token_raises_after_cancel() -> None:
    token = CancelToken()
    token.cancel("test reason")
    assert token.is_cancelled is True
    assert token.reason == "test reason"
    with pytest.raises(PipelineCancelled, match="test reason"):
        token.check()


# ---------------------------------------------------------------------------
# Test 13: Budget Cap Verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_cap_halts_pipeline() -> None:
    """
    Verify that PipelineRunner enforcing a strict USD budget cap halts execution
    and emits WsBudgetExceededEvent when the estimate_cost exceeds the cap.
    """
    from neuralflow.scheduler.runner import PipelineRunner
    from neuralflow.endpoints.base import Cost
    from neuralflow.scheduler.events import WsBudgetExceededEvent

    class ExpensiveMockEndpoint(MockEndpoint):
        def estimate_cost(self, req: Any) -> Cost:
            # Each call costs $10.00
            return Cost(usd=10.0, tokens_in=1000, tokens_out=10)

    endpoint = ExpensiveMockEndpoint(
        id="mock:expensive",
        predefined_text="I am too expensive",
    )
    registry = EndpointRegistry({"mock:expensive": endpoint})

    expensive_pipeline = {
        "schema_version": "2.0",
        "id": "budget-test-pipe",
        "name": "Budget Pipe",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "model_1",
                "type": "model",
                "endpoint_ref": "mock:expensive",
                "inputs": [{"name": "input", "type": "text"}],
                "outputs": [{"name": "output", "type": "text"}],
            },
            {
                "id": "model_2",
                "type": "model",
                "endpoint_ref": "mock:expensive",
                "inputs": [{"name": "input", "type": "text"}],
                "outputs": [{"name": "output", "type": "text"}],
            },
            {
                "id": "out",
                "type": "output",
                "inputs": [{"name": "result", "type": "text"}],
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "model_1.input"},
            {"from": "model_1.output", "to": "model_2.input"},
            {"from": "model_2.output", "to": "out.result"},
        ],
        "endpoints": {
            "mock:expensive": {"kind": "openai"},
        },
    }

    dag = compile(expensive_pipeline)
    
    runner = PipelineRunner(
        run_id="run-budget-123",
        dag=dag,
        registry=registry,
        budget_usd=15.0,  # Cap at $15
    )
    queue: asyncio.Queue = asyncio.Queue()
    
    await runner.run(queue)
    
    events = []
    while not queue.empty():
        evt = await queue.get()
        if evt is not None:
            events.append(evt)
            
    budget_events = [e for e in events if isinstance(e, WsBudgetExceededEvent)]
    assert len(budget_events) == 1
    
    # model_1 costs $10 (passes, cumulative $10)
    # model_2 costs $10 (fails, $20 > $15)
    assert budget_events[0].cumulative_cost_usd == 10.0
    assert budget_events[0].node_id == "mock:expensive"
    assert runner._cancel.is_cancelled is True
    assert "Budget exceeded" in runner._cancel.reason
