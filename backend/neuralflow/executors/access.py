"""
backend/neuralflow/executors/access.py

Executor for `access` nodes (schema 2.1).

An access node is a scope marker, not a transform: it declares what the part of
the graph downstream of it is permitted to reach. All of its meaning is
consumed at compile time, where the ancestor walk in compiler/dag.py turns it
into a per-node effective policy, and at call time, where the endpoints refuse
anything that policy withholds.

By the time the scheduler reaches one there is nothing left to do, so this
executor produces no outputs. It exists because the node is a real vertex in
the DAG and the scheduler must be able to visit it.
"""

from __future__ import annotations

from typing import Any

from neuralflow.executors.base import BaseExecutor, ExecutorContext


class AccessExecutor(BaseExecutor):
    """No-op executor for access nodes. They carry policy, not data."""

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        ctx.check_cancel()
        return {}
