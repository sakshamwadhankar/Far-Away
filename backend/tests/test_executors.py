"""
backend/tests/test_executors.py

Unit tests for node executors including JSON repair.
"""

import json
from typing import Any

import pytest

from neuralflow.compiler.models import Node, NodeConfig, Port
from neuralflow.endpoints.base import GenRequest
from neuralflow.endpoints.mock import MockEndpoint
from neuralflow.executors.base import ExecutorContext
from neuralflow.executors.input_output import InputExecutor, OutputExecutor
from neuralflow.executors.logic import JudgeExecutor, RouterExecutor, TransformExecutor
from neuralflow.executors.model import ModelExecutor
from neuralflow.scheduler.engine import CancelToken, EndpointRegistry, EventKind, SchedulerEvent


class MockEmitter:
    def __init__(self):
        self.events: list[SchedulerEvent] = []

    async def emit(self, event: SchedulerEvent) -> None:
        self.events.append(event)


@pytest.fixture
def mock_emitter() -> MockEmitter:
    return MockEmitter()


@pytest.fixture
def registry() -> EndpointRegistry:
    return EndpointRegistry({})


def make_ctx(
    node: Node,
    inputs: dict[str, Any],
    registry: EndpointRegistry,
    emitter: MockEmitter,
) -> ExecutorContext:
    return ExecutorContext(
        node=node,
        inputs=inputs,
        registry=registry,
        emit_fn=emitter.emit,
        cancel_token=CancelToken(),
    )


async def test_input_executor(registry: EndpointRegistry, mock_emitter: MockEmitter):
    node = Node(id="in1", type="input", outputs=[Port(name="val", type="text")])
    ctx = make_ctx(node, {"val": "hello"}, registry, mock_emitter)
    
    executor = InputExecutor()
    outputs = await executor.execute(ctx)
    
    assert outputs == {"val": "hello"}
    assert len(mock_emitter.events) == 1
    assert mock_emitter.events[0].kind == EventKind.NODE_DONE


async def test_output_executor(registry: EndpointRegistry, mock_emitter: MockEmitter):
    node = Node(id="out1", type="output", inputs=[Port(name="in", type="text")])
    ctx = make_ctx(node, {"in": "world"}, registry, mock_emitter)
    
    executor = OutputExecutor()
    outputs = await executor.execute(ctx)
    
    assert outputs == {"in": "world"}
    assert len(mock_emitter.events) == 1
    assert mock_emitter.events[0].kind == EventKind.NODE_DONE


async def test_judge_executor(registry: EndpointRegistry, mock_emitter: MockEmitter):
    node = Node(id="judge1", type="judge", outputs=[Port(name="best", type="json")])
    inputs = {
        "cand1": {"text": "A", "score": 0.5},
        "cand2": {"text": "B", "score": 0.9},
        "cand3": {"text": "C", "score": 0.2},
    }
    ctx = make_ctx(node, inputs, registry, mock_emitter)
    
    executor = JudgeExecutor()
    outputs = await executor.execute(ctx)
    
    assert outputs["best"]["text"] == "B"
    assert outputs["best"]["score"] == 0.9


async def test_router_executor(registry: EndpointRegistry, mock_emitter: MockEmitter):
    node = Node(
        id="router1", 
        type="router", 
        outputs=[
            Port(name="branch_true", type="text"),
            Port(name="branch_false", type="text"),
        ]
    )
    inputs = {"condition": "true", "text": "payload"}
    ctx = make_ctx(node, inputs, registry, mock_emitter)
    
    executor = RouterExecutor()
    outputs = await executor.execute(ctx)
    
    assert outputs["branch_true"] == "payload"
    assert outputs["branch_false"] is None


async def test_transform_executor(registry: EndpointRegistry, mock_emitter: MockEmitter):
    node = Node(
        id="transform1", 
        type="transform", 
        config=NodeConfig(system_prompt="Result is: {{ val1 }} + {{ val2 }}"),
        outputs=[Port(name="out", type="text")]
    )
    inputs = {"val1": "foo", "val2": "bar"}
    ctx = make_ctx(node, inputs, registry, mock_emitter)
    
    executor = TransformExecutor()
    outputs = await executor.execute(ctx)
    
    assert outputs["out"] == "Result is: foo + bar"


async def test_model_executor_text_mode(mock_emitter: MockEmitter):
    endpoint = MockEndpoint(id="mock1", predefined_text="Model response text")
    registry = EndpointRegistry({"mock1": endpoint})
    
    node = Node(
        id="model1", 
        type="model", 
        endpoint_ref="mock1",
        outputs=[Port(name="out", type="text")]
    )
    inputs = {"prompt": "Hello"}
    ctx = make_ctx(node, inputs, registry, mock_emitter)
    
    executor = ModelExecutor()
    outputs = await executor.execute(ctx)
    
    assert outputs["out"] == "Model response text"
    
    # Check events
    tokens = [e for e in mock_emitter.events if e.kind == EventKind.TOKEN]
    assert len(tokens) > 0
    done = [e for e in mock_emitter.events if e.kind == EventKind.NODE_DONE]
    assert len(done) == 1
    assert done[0].data["cost_usd"] > 0


async def test_model_executor_json_repair(mock_emitter: MockEmitter):
    call_count = 0

    def dynamic_response(req: GenRequest) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "This is prose, not json."
        else:
            return '{"key": "value"}'

    endpoint = MockEndpoint(id="mock_json", response_fn=dynamic_response)
    registry = EndpointRegistry({"mock_json": endpoint})
    
    node = Node(
        id="model1", 
        type="model", 
        endpoint_ref="mock_json",
        config=NodeConfig(response_format="json"),
        outputs=[Port(name="out", type="json")]
    )
    ctx = make_ctx(node, {"prompt": "json me"}, registry, mock_emitter)
    
    executor = ModelExecutor()
    outputs = await executor.execute(ctx)
    
    # Output should be the repaired JSON
    assert outputs["out"] == {"key": "value"}
    assert call_count == 2
    
    # Ensure cost is accumulated across both attempts
    done = [e for e in mock_emitter.events if e.kind == EventKind.NODE_DONE]
    assert len(done) == 1
    # Cost should be approx 2 * 0.001 (based on mock.py estimate_cost logic)
    assert done[0].data["cost_usd"] >= 0.002
    assert done[0].data["tokens_out"] > 0


async def test_model_executor_json_repair_failure(mock_emitter: MockEmitter):
    # Endpoint always returns prose
    endpoint = MockEndpoint(id="mock_fail", predefined_text="Still not JSON.")
    registry = EndpointRegistry({"mock_fail": endpoint})
    
    node = Node(
        id="model1", 
        type="model", 
        endpoint_ref="mock_fail",
        config=NodeConfig(response_format="json"),
        outputs=[Port(name="out", type="json")]
    )
    ctx = make_ctx(node, {"prompt": "fail me"}, registry, mock_emitter)
    
    executor = ModelExecutor()
    
    # Should raise after 3 attempts
    with pytest.raises(ValueError, match="Failed to generate valid JSON"):
        await executor.execute(ctx)
