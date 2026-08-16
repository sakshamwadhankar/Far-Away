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
        # `synchronous` is a per-connection setting and this class opens a fresh
        # connection per operation, so it has to be re-applied here — unlike
        # `journal_mode`, which is persisted in the database file by _init_db.
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist, and set the durability pragmas."""
        conn = self._get_conn()
        try:
            # WAL lets readers proceed while a write is in flight. Without it,
            # a live run's trace writes and a concurrent /runs/{id}/trace read
            # contend on a single global lock, and `timeout=5.0` in _get_conn
            # turns that contention into multi-second stalls.
            #
            # journal_mode is persisted in the database file, so this only has
            # to be asserted once. synchronous is per-connection and is set in
            # _get_conn instead.
            conn.execute("PRAGMA journal_mode=WAL")

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
                        updated_at INTEGER NOT NULL,
                        deployment_id TEXT
                    )
                    """
                )
                self._migrate_runs_deployment_id(conn)
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
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS library_templates (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        author TEXT NOT NULL DEFAULT 'Anonymous',
                        tags TEXT NOT NULL DEFAULT '',
                        pipeline_json TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        downloads INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS custom_nodes (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        author TEXT NOT NULL DEFAULT 'Anonymous',
                        icon_color TEXT NOT NULL DEFAULT '#6B3AB8',
                        inputs_json TEXT NOT NULL DEFAULT '[]',
                        outputs_json TEXT NOT NULL DEFAULT '[]',
                        template TEXT NOT NULL DEFAULT '',
                        tags TEXT NOT NULL DEFAULT '',
                        created_at INTEGER NOT NULL
                    )
                    """
                )
        finally:
            conn.close()

    @staticmethod
    def _migrate_runs_deployment_id(conn: sqlite3.Connection) -> None:
        """
        Add `runs.deployment_id` for databases created before Phase 3.

        The CREATE TABLE above only takes effect for a brand-new file; an
        existing ~/.neuralflow/neuralflow.db predates the column, and SQLite
        has no `ADD COLUMN IF NOT EXISTS`. Check PRAGMA table_info first so
        this is idempotent across every startup, not just the first one after
        upgrading.
        """
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        if "deployment_id" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN deployment_id TEXT")

    def save_run(
        self,
        run_id: str,
        pipeline_id: str,
        status: str = "running",
        cost: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        deployment_id: str | None = None,
    ) -> None:
        """
        Create or update a run record.

        `deployment_id` is set once, at creation, for a run started by a
        served request (Phase 3); it is NULL for ordinary canvas runs. Left
        out of the ON CONFLICT UPDATE SET on purpose — a run's origin does not
        change after it starts, so a later status update must not overwrite it
        (callers other than the initial save_run pass deployment_id=None).
        """
        now = int(time.time() * 1000)
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, pipeline_id, status, cost, tokens_in, tokens_out,
                        started_at, updated_at, deployment_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        status=excluded.status,
                        cost=excluded.cost,
                        tokens_in=excluded.tokens_in,
                        tokens_out=excluded.tokens_out,
                        updated_at=excluded.updated_at
                    """,
                    (
                        run_id,
                        pipeline_id,
                        status,
                        cost,
                        tokens_in,
                        tokens_out,
                        now,
                        now,
                        deployment_id,
                    ),
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
                    SET status = ?, cost = ?, tokens_in = ?,
                        tokens_out = ?, updated_at = ?
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
                    INSERT INTO node_executions
                        (run_id, node_id, inputs_json, outputs_json,
                         cost, tokens_in, tokens_out, error)
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
                    INSERT INTO loop_iterations
                        (run_id, loop_id, iteration, inputs_json, outputs_json)
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
                "SELECT node_id, outputs_json FROM node_executions "
                "WHERE run_id = ? AND error IS NULL",
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

    def get_full_trace(self, run_id: str) -> dict[str, Any] | None:
        """Fetch the full trace for a run."""
        conn = self._get_conn()
        try:
            run = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not run:
                return None

            nodes = conn.execute(
                "SELECT * FROM node_executions WHERE run_id = ?", (run_id,)
            ).fetchall()
            loops = conn.execute(
                "SELECT * FROM loop_iterations WHERE run_id = ?", (run_id,)
            ).fetchall()

            # Helper to parse JSON fields safely
            def _parse_json(val: str | None) -> Any:
                if val is None:
                    return None
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    return val

            parsed_nodes = []
            for n in nodes:
                d = dict(n)
                d["inputs"] = _parse_json(d.pop("inputs_json", None))
                d["outputs"] = _parse_json(d.pop("outputs_json", None))
                parsed_nodes.append(d)

            parsed_loops = []
            for loop_row in loops:
                d = dict(loop_row)
                d["inputs"] = _parse_json(d.pop("inputs_json", None))
                d["outputs"] = _parse_json(d.pop("outputs_json", None))
                parsed_loops.append(d)

            return {
                "run": dict(run),
                "nodes": parsed_nodes,
                "loops": parsed_loops,
            }
        finally:
            conn.close()

    # -------------------------------------------------------------------
    # Library Templates (community sharing)
    # -------------------------------------------------------------------

    def publish_template(
        self,
        template_id: str,
        name: str,
        description: str,
        author: str,
        tags: str,
        pipeline_json: str,
    ) -> None:
        """Publish a pipeline to the community library."""
        now = int(time.time() * 1000)
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO library_templates
                        (id, name, description, author, tags,
                         pipeline_json, created_at, downloads)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        author=excluded.author,
                        tags=excluded.tags,
                        pipeline_json=excluded.pipeline_json
                    """,
                    (template_id, name, description, author, tags, pipeline_json, now),
                )
        finally:
            conn.close()

    def list_library_templates(self) -> list[dict[str, Any]]:
        """Return all library templates ordered by newest first."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT id, name, description, author, tags, "
                "pipeline_json, created_at, downloads "
                "FROM library_templates ORDER BY created_at DESC"
            )
            results: list[dict[str, Any]] = []
            for row in cursor:
                d = dict(row)
                try:
                    d["pipeline"] = json.loads(d.pop("pipeline_json"))
                except json.JSONDecodeError:
                    d["pipeline"] = {}
                    d.pop("pipeline_json", None)
                results.append(d)
            return results
        finally:
            conn.close()

    def get_library_template(self, template_id: str) -> dict[str, Any] | None:
        """Fetch a single library template by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id, name, description, author, tags, "
                "pipeline_json, created_at, downloads "
                "FROM library_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            try:
                d["pipeline"] = json.loads(d.pop("pipeline_json"))
            except json.JSONDecodeError:
                d["pipeline"] = {}
                d.pop("pipeline_json", None)
            return d
        finally:
            conn.close()

    def delete_library_template(self, template_id: str) -> bool:
        """Delete a library template. Returns True if a row was deleted."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM library_templates WHERE id = ?",
                    (template_id,),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def increment_template_downloads(self, template_id: str) -> None:
        """Bump the download counter for a library template."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    "UPDATE library_templates SET downloads = downloads + 1 "
                    "WHERE id = ?",
                    (template_id,),
                )
        finally:
            conn.close()

    # -------------------------------------------------------------------
    # Custom Nodes (user-defined node definitions)
    # -------------------------------------------------------------------

    def save_custom_node(
        self,
        node_id: str,
        name: str,
        description: str,
        author: str,
        icon_color: str,
        inputs_json: str,
        outputs_json: str,
        template: str,
        tags: str,
    ) -> None:
        """Save a user-defined custom node definition."""
        now = int(time.time() * 1000)
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO custom_nodes
                        (id, name, description, author, icon_color,
                         inputs_json, outputs_json, template, tags, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        author=excluded.author,
                        icon_color=excluded.icon_color,
                        inputs_json=excluded.inputs_json,
                        outputs_json=excluded.outputs_json,
                        template=excluded.template,
                        tags=excluded.tags
                    """,
                    (
                        node_id,
                        name,
                        description,
                        author,
                        icon_color,
                        inputs_json,
                        outputs_json,
                        template,
                        tags,
                        now,
                    ),
                )
        finally:
            conn.close()

    def list_custom_nodes(self) -> list[dict[str, Any]]:
        """Return all custom node definitions ordered by newest first."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT id, name, description, author, icon_color, "
                "inputs_json, outputs_json, template, tags, created_at "
                "FROM custom_nodes ORDER BY created_at DESC"
            )
            results: list[dict[str, Any]] = []
            for row in cursor:
                d = dict(row)
                try:
                    d["inputs"] = json.loads(d.pop("inputs_json"))
                except json.JSONDecodeError:
                    d["inputs"] = []
                    d.pop("inputs_json", None)
                try:
                    d["outputs"] = json.loads(d.pop("outputs_json"))
                except json.JSONDecodeError:
                    d["outputs"] = []
                    d.pop("outputs_json", None)
                results.append(d)
            return results
        finally:
            conn.close()

    def get_custom_node(self, node_id: str) -> dict[str, Any] | None:
        """Fetch a single custom node definition by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id, name, description, author, icon_color, "
                "inputs_json, outputs_json, template, tags, created_at "
                "FROM custom_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            try:
                d["inputs"] = json.loads(d.pop("inputs_json"))
            except json.JSONDecodeError:
                d["inputs"] = []
                d.pop("inputs_json", None)
            try:
                d["outputs"] = json.loads(d.pop("outputs_json"))
            except json.JSONDecodeError:
                d["outputs"] = []
                d.pop("outputs_json", None)
            return d
        finally:
            conn.close()

    def delete_custom_node(self, node_id: str) -> bool:
        """Delete a custom node definition. Returns True if a row was deleted."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM custom_nodes WHERE id = ?",
                    (node_id,),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()
