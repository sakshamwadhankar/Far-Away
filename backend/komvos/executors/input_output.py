"""
backend/komvos/executors/input_output.py

Executors for 'input' and 'output' nodes.
"""

from typing import Any

from komvos.executors.base import BaseExecutor, ExecutorContext


class InputExecutor(BaseExecutor):
    """
    Input node executor.
    Input nodes don't compute anything themselves during standard execution;
    their values are seeded from initial_inputs before execution starts.
    However, if an input node is reached, it just passes its outputs.
    Wait, the engine treats input nodes specially (it verifies they are seeded).
    If we delegate input nodes here, we just return the inputs we were given
    (or rather, the engine should just not call execute() on input nodes,
    or we return empty dict and let engine handle it).
    Actually, engine passes 'inputs' which are the gathered values.
    For an input node, its inputs are already seeded.
    We will just return the gathered inputs as outputs.
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        from komvos.scheduler.engine import EventKind, SchedulerEvent

        ctx.check_cancel()
        await ctx.emit(
            SchedulerEvent(
                kind=EventKind.NODE_DONE,
                node_id=ctx.node.id,
                data={
                    "inputs": {},
                    "outputs": ctx.inputs,
                },
            )
        )
        return ctx.inputs


class OutputExecutor(BaseExecutor):
    """
    Output node executor.
    Output nodes simply pass their inputs through to their outputs.
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        from komvos.scheduler.engine import EventKind, SchedulerEvent

        ctx.check_cancel()
        await ctx.emit(
            SchedulerEvent(
                kind=EventKind.NODE_DONE,
                node_id=ctx.node.id,
                data={
                    "inputs": ctx.inputs,
                    "outputs": ctx.inputs,
                },
            )
        )
        return ctx.inputs
