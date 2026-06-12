"""
backend/neuralflow/state/sqlite.py

Phase 3 — Durable SQLite storage for pipeline runs and checkpoints.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StateManager:
    """
    Manages SQLite database for pipeline runs, checkpoints, and loop history.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        pipeline_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        cost REAL DEFAULT 0.0,
                        tokens_in INTEGER DEFAULT 0,
                        tokens_out INTEGER DEFAULT 0,
                        started_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS node_executions (
                        run_id TEXT NOT NULL,
                        node_id TEXT NOT NULL,
                        inputs_json TEXT,
                        outputs_json TEXT,
                        cost REAL DEFAULT 0.0,
                        tokens_in INTEGER DEFAULT 0,
                        tokens_out INTEGER DEFAULT 0,
                        error TEXT,
                        PRIMARY KEY (run_id, node_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS loop_iterations (
                        run_id TEXT NOT NULL,
                        loop_id TEXT NOT NULL,
                        iteration INTEGER NOT NULL,
                        inputs_json TEXT,
                        outputs_json TEXT,
                        PRIMARY KEY (run_id, loop_id, iteration)
                    )
                    """
                )
        finally:
            conn.close()

    def save_run(
        self,
        run_id: str,
        pipeline_id: str,
        status: str = "running",
        cost: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Create or update a run record."""
        now = int(time.time() * 1000)
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, pipeline_id, status, cost, tokens_in, tokens_out,
                        started_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        status=excluded.status,
                        cost=excluded.cost,
                        tokens_in=excluded.tokens_in,
                        tokens_out=excluded.tokens_out,
                        updated_at=excluded.updated_at
                    """,
                    (run_id, pipeline_id, status, cost, tokens_in, tokens_out, now, now),
                )
        finally:
            conn.close()

    def update_run_status(
        self,
        run_id: str,
        status: str,
        cost: float,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        """Update just the run status and totals."""
        now = int(time.time() * 1000)
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE runs
                    SET status = ?, cost = ?, tokens_in = ?, tokens_out = ?, updated_at = ?
                    WHERE run_id = ?
                    """,
                    (status, cost, tokens_in, tokens_out, now, run_id),
                )
        finally:
            conn.close()

    def save_node_execution(
        self,
        run_id: str,
        node_id: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        cost: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        error: str | None = None,
    ) -> None:
        """Save a checkpoint for a node."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO node_executions (run_id, node_id, inputs_json, outputs_json, cost, tokens_in, tokens_out, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, node_id) DO UPDATE SET
                        inputs_json=excluded.inputs_json,
                        outputs_json=excluded.outputs_json,
                        cost=excluded.cost,
                        tokens_in=excluded.tokens_in,
                        tokens_out=excluded.tokens_out,
                        error=excluded.error
                    """,
                    (
                        run_id,
                        node_id,
                        json.dumps(inputs) if inputs is not None else None,
                        json.dumps(outputs) if outputs is not None else None,
                        cost,
                        tokens_in,
                        tokens_out,
                        error,
                    ),
                )
        finally:
            conn.close()

    def save_loop_iteration(
        self,
        run_id: str,
        loop_id: str,
        iteration: int,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> None:
        """Save history for a single loop iteration."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO loop_iterations (run_id, loop_id, iteration, inputs_json, outputs_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, loop_id, iteration) DO UPDATE SET
                        inputs_json=excluded.inputs_json,
                        outputs_json=excluded.outputs_json
                    """,
                    (
                        run_id,
                        loop_id,
                        iteration,
                        json.dumps(inputs) if inputs is not None else None,
                        json.dumps(outputs) if outputs is not None else None,
                    ),
                )
        finally:
            conn.close()

    def load_run_state(self, run_id: str) -> dict[str, dict[str, Any]]:
        """
        Load successfully executed nodes and their outputs from a run.
        Returns: { node_id: outputs_dict }
        """
        state: dict[str, dict[str, Any]] = {}
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT node_id, outputs_json FROM node_executions WHERE run_id = ? AND error IS NULL",
                (run_id,),
            )
            for row in cursor:
                node_id = row["node_id"]
                outputs_json = row["outputs_json"]
                if outputs_json:
                    try:
                        state[node_id] = json.loads(outputs_json)
                    except json.JSONDecodeError:
                        state[node_id] = {}
                else:
                    state[node_id] = {}
        finally:
            conn.close()
        return state
