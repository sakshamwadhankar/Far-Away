"""
backend/komvos/executors/logic.py

Executors for logic and data transformations (Judge, Router, Transform).
"""

import difflib
import json
import threading
from asyncio import to_thread as asyncio_to_thread
from typing import Any

from jinja2.sandbox import SandboxedEnvironment

from komvos.executors.base import BaseExecutor, ExecutorContext
from komvos.scheduler.engine import EventKind, SchedulerEvent

_SANDBOX = SandboxedEnvironment()

#: A Transform template's render is aborted if it exceeds this many seconds.
#: The render runs in a worker thread so a runaway loop cannot stall the
#: event loop while the bound waits.
MAX_RENDER_SECONDS = 5.0

#: A Transform template's rendered output is rejected above this size.
MAX_RENDER_OUTPUT_CHARS = 1_000_000


class JudgeExecutor(BaseExecutor):
    """
    Judge node executor.
    Takes N inputs (assumed to be JSON objects with a 'score' field),
    and selects the one with the highest score.
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        ctx.check_cancel()

        score_field = (
            ctx.node.config.score_field
            if ctx.node.config and ctx.node.config.score_field
            else "score"
        )
        strategy = (
            ctx.node.config.strategy
            if ctx.node.config and ctx.node.config.strategy
            else "max_numeric"
        )

        best_candidate: Any = None
        best_score = float("-inf")

        for _port_name, value in ctx.inputs.items():
            if isinstance(value, dict) and score_field in value:
                if strategy == "max_numeric":
                    try:
                        score = float(value[score_field])
                        if score > best_score:
                            best_score = score
                            best_candidate = value
                    except (ValueError, TypeError):
                        pass
                elif strategy == "truthy" and bool(value[score_field]):
                    best_candidate = value
                    break

        if best_candidate is None:
            raise ValueError(
                f"Judge found no candidate matching score_field "
                f"'{score_field}' with strategy '{strategy}'."
            )

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

        routing_map = (
            ctx.node.config.routing_map
            if ctx.node.config and ctx.node.config.routing_map
            else None
        )

        matched_port = None
        if routing_map:
            matched_port = routing_map.get(str(condition_val))
        else:
            for port in ctx.node.outputs:
                if str(condition_val) == port.name:
                    matched_port = port.name
                    break

        if not matched_port or matched_port not in [p.name for p in ctx.node.outputs]:
            raise ValueError(
                f"Router condition '{condition_val}' matched no valid output port."
            )

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

        # Bounded render: a user-supplied template can loop a huge range or
        # concatenate without limit. The (synchronous) render runs on a daemon
        # worker thread with a hard time budget, then the output is size-
        # capped. If the budget lapses the worker is abandoned — it is a
        # daemon, so it can never block interpreter shutdown; Jinja renders
        # are not interruptible, so the abandoned thread's CPU cost until it
        # finishes is accepted (documented limitation).
        render_result: list[str] = []
        render_error: list[BaseException] = []

        def _run_render() -> None:
            try:
                render_result.append(template.render(**ctx.inputs))
            except BaseException as exc:  # noqa: BLE001 - relayed below
                render_error.append(exc)

        def _bounded_render() -> str:
            worker = threading.Thread(
                target=_run_render, name="jinja-bounded-render", daemon=True
            )
            worker.start()
            worker.join(timeout=MAX_RENDER_SECONDS)
            if worker.is_alive():
                raise ValueError(
                    f"Transform template exceeded its render time limit of "
                    f"{MAX_RENDER_SECONDS:.0f}s. Check for unbounded loops "
                    f"(e.g. large range() iterations) in the template."
                )
            if render_error:
                raise render_error[0]
            return render_result[0] if render_result else ""

        rendered = await asyncio_to_thread(_bounded_render)

        if len(rendered) > MAX_RENDER_OUTPUT_CHARS:
            raise ValueError(
                f"Transform template output exceeded the size limit: rendered "
                f"{len(rendered)} characters, limit is "
                f"{MAX_RENDER_OUTPUT_CHARS}."
            )

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

        val1 = ctx.inputs.get("input1")
        val2 = ctx.inputs.get("input2")

        str1 = (
            json.dumps(val1, indent=2) if isinstance(val1, dict | list) else str(val1)
        )
        str2 = (
            json.dumps(val2, indent=2) if isinstance(val2, dict | list) else str(val2)
        )

        is_different = str1 != str2

        if is_different:
            diff_lines = list(
                difflib.unified_diff(
                    str1.splitlines(),
                    str2.splitlines(),
                    fromfile="input1",
                    tofile="input2",
                    lineterm="",
                )
            )
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
