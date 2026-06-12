"""
backend/neuralflow/executors/input_output.py

Executors for 'input' and 'output' nodes.
"""

from typing import Any

from neuralflow.executors.base import BaseExecutor, ExecutorContext


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
        ctx.check_cancel()
        # Input nodes pass their existing seeded state.
        # But wait, if engine calls gather_inputs, it will get nothing because input nodes have no incoming edges.
        # So we should actually return what was seeded.
        # The engine handles input seeding specially. 
        # But to be safe, if we get called, we just return ctx.inputs.
        return ctx.inputs


class OutputExecutor(BaseExecutor):
    """
    Output node executor.
    Output nodes simply pass their inputs through to their outputs.
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        ctx.check_cancel()
        return ctx.inputs
