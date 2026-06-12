"""
backend/neuralflow/executors/logic.py

Executors for logic and data transformations (Judge, Router, Transform).
"""

import json
from typing import Any

from jinja2 import Template

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

        best_candidate: Any = None
        best_score = float("-inf")

        for port_name, value in ctx.inputs.items():
            if isinstance(value, dict) and "score" in value:
                try:
                    score = float(value["score"])
                    if score > best_score:
                        best_score = score
                        best_candidate = value
                except (ValueError, TypeError):
                    pass

        if best_candidate is None:
            # Fallback if no scores found: just take the first input
            if ctx.inputs:
                best_candidate = next(iter(ctx.inputs.values()))
            else:
                best_candidate = {}

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

        outputs: dict[str, Any] = {}
        for port in ctx.node.outputs:
            if str(condition_val).lower() in port.name.lower():
                outputs[port.name] = text_val
            else:
                outputs[port.name] = None  # Route not taken

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

        template = Template(template_str)
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
