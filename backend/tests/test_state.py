"""
backend/tests/test_state.py

Phase 3 — Tests for SQLite StateManager and resume logic.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
from pathlib import Path
from typing import Any

import pytest

from komvos.compiler.dag import compile
from komvos.endpoints.mock import MockEndpoint
from komvos.scheduler.engine import EndpointRegistry, Scheduler
from komvos.scheduler.runner import PipelineRunner
from komvos.state.sqlite import StateManager
from tests.test_scheduler import LINEAR_PIPELINE


@pytest.fixture
def temp_db() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        path = Path(f.name)
    yield path
    with contextlib.suppress(PermissionError):
        path.unlink(missing_ok=True)


def test_state_manager_init(temp_db: Path) -> None:
    sm = StateManager(temp_db)
    # Check tables
    with sm._get_conn() as conn:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        assert "runs" in tables
        assert "node_executions" in tables
        assert "loop_iterations" in tables


def test_state_manager_crud(temp_db: Path) -> None:
    sm = StateManager(temp_db)
    sm.save_run("run1", "pipe1", "running")

    # Save node
    sm.save_node_execution("run1", "nodeA", outputs={"result": 42})
    sm.save_node_execution("run1", "nodeB", error="failed")

    state = sm.load_run_state("run1")
    assert "nodeA" in state
    assert state["nodeA"] == {"result": 42}

    # nodeB had an error, shouldn't be in loaded state for resume
    assert "nodeB" not in state


@pytest.mark.asyncio
async def test_scheduler_resume_skips_nodes() -> None:
    """Test that engine skips nodes that are already in resume_state."""
    endpoint = MockEndpoint(id="mock:model", predefined_text="New text")
    registry = EndpointRegistry({"mock:model": endpoint})
    dag = compile(LINEAR_PIPELINE)

    resume_state = {"model": {"output": "Old cached text"}}

    scheduler = Scheduler(dag, registry)
    result = await scheduler.run({"in": {"prompt": "Hi"}}, resume_state=resume_state)

    assert result.completed is True
    # The 'out' node should receive 'Old cached text' from 'model' instead of 'New text'
    assert result.node_results["model"].outputs["output"] == "Old cached text"
    assert result.node_results["out"].outputs["result"] == "Old cached text"


@pytest.mark.asyncio
async def test_runner_records_and_resumes(temp_db: Path) -> None:
    """Test PipelineRunner with StateManager end-to-end."""
    sm = StateManager(temp_db)

    endpoint = MockEndpoint(id="mock:model", predefined_text="Text")
    registry = EndpointRegistry({"mock:model": endpoint})
    dag = compile(LINEAR_PIPELINE)

    runner = PipelineRunner("run_xyz", dag, registry, state_manager=sm)
    queue: asyncio.Queue[Any] = asyncio.Queue()
    await runner.run(queue)

    # verify DB
    state = sm.load_run_state("run_xyz")
    assert "in" in state
    assert "model" in state
    assert state["model"]["output"] == "Text"
    assert "out" in state

    with sm._get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM runs WHERE run_id = 'run_xyz'"
        ).fetchone()
        assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_runner_halt_saves_trace(temp_db: Path) -> None:
    """Test that a halted run saves partial trace."""
    sm = StateManager(temp_db)
    endpoint = MockEndpoint(id="mock:model", predefined_text="Text", token_delay=0.1)
    registry = EndpointRegistry({"mock:model": endpoint})
    dag = compile(LINEAR_PIPELINE)

    runner = PipelineRunner("run_halt", dag, registry, state_manager=sm)
    queue: asyncio.Queue[Any] = asyncio.Queue()

    task = asyncio.create_task(runner.run(queue))
    await asyncio.sleep(0.05)
    runner.stop()
    await task

    with sm._get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM runs WHERE run_id = 'run_halt'"
        ).fetchone()
        assert row["status"] == "stopped"

        cursor = conn.execute(
            "SELECT node_id, error FROM node_executions WHERE run_id = 'run_halt'"
        )
        nodes = {r["node_id"]: r["error"] for r in cursor}

        assert "in" in nodes
        assert nodes["in"] is None
        assert "model" in nodes
        assert nodes["model"] is not None
