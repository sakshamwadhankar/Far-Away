"""
backend/neuralflow/executors/logic.py

Executors for logic and data transformations (Judge, Router, Transform).
"""

import json
from typing import Any

from jinja2.sandbox import SandboxedEnvironment

_SANDBOX = SandboxedEnvironment()

from neuralflow.executors.base import BaseExecutor, ExecutorContext
from neuralflow.scheduler.engine import EventKind, SchedulerEvent


class JudgeExecutor(BaseExecutor):
    """
    Judge node executor.
    Takes N inputs (assumed to be JSON objects with a 'score' field),
    and selects the one with the highest score.
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        ctx.check_cancel()

        score_field = ctx.node.config.score_field if ctx.node.config and ctx.node.config.score_field else "score"
        strategy = ctx.node.config.strategy if ctx.node.config and ctx.node.config.strategy else "max_numeric"

        best_candidate: Any = None
        best_score = float("-inf")

        for port_name, value in ctx.inputs.items():
            if isinstance(value, dict) and score_field in value:
                if strategy == "max_numeric":
                    try:
                        score = float(value[score_field])
                        if score > best_score:
                            best_score = score
                            best_candidate = value
                    except (ValueError, TypeError):
                        pass
                elif strategy == "truthy":
                    if bool(value[score_field]):
                        best_candidate = value
                        break

        if best_candidate is None:
            raise ValueError(f"Judge found no candidate matching score_field '{score_field}' with strategy '{strategy}'.")

        outputs: dict[str, Any] = {}
        for port in ctx.node.outputs:
            outputs[port.name] = best_candidate

        await ctx.emit(
            SchedulerEvent(
                kind=EventKind.NODE_DONE,
                node_id=ctx.node.id,
                data={"inputs": ctx.inputs, "outputs": outputs},
            )
        )
        return outputs


class RouterExecutor(BaseExecutor):
    """
    Router node executor.
    Reads a 'condition' input port, and routes the 'text' input port
    to the corresponding output port (e.g. branch_true).
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        ctx.check_cancel()

        condition_val = str(ctx.inputs.get("condition", ""))
        text_val = ctx.inputs.get("text", "")

        routing_map = ctx.node.config.routing_map if ctx.node.config and ctx.node.config.routing_map else None
        
        matched_port = None
        if routing_map:
            matched_port = routing_map.get(str(condition_val))
        else:
            for port in ctx.node.outputs:
                if str(condition_val) == port.name:
                    matched_port = port.name
                    break
        
        if not matched_port or matched_port not in [p.name for p in ctx.node.outputs]:
            raise ValueError(f"Router condition '{condition_val}' matched no valid output port.")

        outputs: dict[str, Any] = {}
        for port in ctx.node.outputs:
            if port.name == matched_port:
                outputs[port.name] = text_val
            else:
                outputs[port.name] = None

        await ctx.emit(
            SchedulerEvent(
                kind=EventKind.NODE_DONE,
                node_id=ctx.node.id,
                data={"inputs": ctx.inputs, "outputs": outputs},
            )
        )
        return outputs


class TransformExecutor(BaseExecutor):
    """
    Transform node executor.
    Uses Jinja2 to template inputs into an output using node.config.system_prompt
    as the template string.
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        ctx.check_cancel()

        template_str = (
            ctx.node.config.system_prompt
            if ctx.node.config and ctx.node.config.system_prompt
            else ""
        )

        template = _SANDBOX.from_string(template_str)
        rendered = template.render(**ctx.inputs)

        outputs: dict[str, Any] = {}
        for port in ctx.node.outputs:
            if port.type == "json":
                try:
                    outputs[port.name] = json.loads(rendered)
                except json.JSONDecodeError:
                    outputs[port.name] = rendered
            else:
                outputs[port.name] = rendered

        await ctx.emit(
            SchedulerEvent(
                kind=EventKind.NODE_DONE,
                node_id=ctx.node.id,
                data={"inputs": ctx.inputs, "outputs": outputs},
            )
        )
        return outputs


class CompareExecutor(BaseExecutor):
    """
    Compare node executor.
    Takes 'input1' and 'input2' and compares them.
    Outputs 'diff' (a string showing differences) and 'is_different' (boolean).
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        ctx.check_cancel()
        
        import difflib

        val1 = ctx.inputs.get("input1")
        val2 = ctx.inputs.get("input2")

        str1 = json.dumps(val1, indent=2) if isinstance(val1, (dict, list)) else str(val1)
        str2 = json.dumps(val2, indent=2) if isinstance(val2, (dict, list)) else str(val2)

        is_different = str1 != str2

        if is_different:
            diff_lines = list(difflib.unified_diff(
                str1.splitlines(),
                str2.splitlines(),
                fromfile="input1",
                tofile="input2",
                lineterm=""
            ))
            diff_text = "\n".join(diff_lines)
        else:
            diff_text = ""

        outputs: dict[str, Any] = {}
        for port in ctx.node.outputs:
            if port.name == "is_different":
                outputs[port.name] = is_different
            elif port.name == "diff":
                outputs[port.name] = diff_text
            else:
                outputs[port.name] = None

        await ctx.emit(
            SchedulerEvent(
                kind=EventKind.NODE_DONE,
                node_id=ctx.node.id,
                data={"inputs": ctx.inputs, "outputs": outputs},
            )
        )
        return outputs
