"""
backend/neuralflow/api/registry.py

In-memory run registry for the duration of the server process.

Stores active PipelineRunner instances by run_id so that the /stop endpoint
and the WebSocket handler can look them up.

Runs are removed from the registry once their event queue is drained and
the WebSocket connection closes.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuralflow.scheduler.runner import PipelineRunner


class RunRegistry:
    """Thread-safe (asyncio-safe) in-memory store for active runs."""

    def __init__(self) -> None:
        self._runs: dict[str, "PipelineRunner"] = {}
        self._queues: dict[str, asyncio.Queue] = {}  # type: ignore[type-arg]

    def create(
        self,
        run_id: str,
        runner: "PipelineRunner",
        queue: asyncio.Queue,  # type: ignore[type-arg]
    ) -> None:
        self._runs[run_id] = runner
        self._queues[run_id] = queue

    def get_runner(self, run_id: str) -> "PipelineRunner | None":
        return self._runs.get(run_id)

    def get_queue(self, run_id: str) -> "asyncio.Queue | None":  # type: ignore[type-arg]
        return self._queues.get(run_id)

    def remove(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
        self._queues.pop(run_id, None)

    def active_run_ids(self) -> list[str]:
        return list(self._runs.keys())


# Process-level singleton — imported directly by main.py
run_registry = RunRegistry()
