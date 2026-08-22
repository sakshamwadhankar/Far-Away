"""
backend/komvos/state/sqlite.py

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
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS governance_profiles (
                        name TEXT PRIMARY KEY,
                        spec_json TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                self._init_governance_decisions(conn)
        finally:
            conn.close()

    def _init_governance_decisions(self, conn: sqlite3.Connection) -> None:
        """
        Governance decision log (P1) — purely additive.

        `seq` is an AUTOINCREMENT primary key so every insert is monotonic
        even under concurrent writers; it doubles as the keyset-pagination
        cursor, which is why every index leads with its filter column and
        ends with `seq`. `decision_id` exists so an exported line can be
        referenced without exposing internal row ids.
        """
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS governance_decisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    governed_by_json TEXT NOT NULL DEFAULT '[]',
                    policy_json TEXT NOT NULL DEFAULT '{}',
                    when_utc TEXT NOT NULL,
                    when_ms INTEGER NOT NULL
                )
                """
            )
            # One index per filterable equality column, each ending in `seq`
            # so a filtered keyset scan walks the index instead of sorting.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_gdec_run "
                "ON governance_decisions (run_id, seq)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_gdec_node "
                "ON governance_decisions (node_id, seq)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_gdec_domain "
                "ON governance_decisions (domain, seq)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_gdec_outcome "
                "ON governance_decisions (outcome, seq)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_gdec_origin "
                "ON governance_decisions (origin, seq)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_gdec_when "
                "ON governance_decisions (when_ms)"
            )

    @staticmethod
    def _migrate_runs_deployment_id(conn: sqlite3.Connection) -> None:
        """
        Add `runs.deployment_id` for databases created before Phase 3.

        The CREATE TABLE above only takes effect for a brand-new file; an
        existing ~/.komvos/komvos.db predates the column, and SQLite
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
        from komvos.governance.context import current_governance
        from komvos.governance.profiles import RetentionMode

        gov = current_governance()
        if (
            gov is not None
            and gov.profile is not None
            and gov.profile.retention == RetentionMode.METADATA
        ):
            # Metadata recording mode: strip raw payload data
            inputs_json = "{}" if inputs is not None else None
            outputs_json = "{}" if outputs is not None else None
        else:
            inputs_json = json.dumps(inputs) if inputs is not None else None
            outputs_json = json.dumps(outputs) if outputs is not None else None

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
                        inputs_json,
                        outputs_json,
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
        from komvos.governance.context import current_governance
        from komvos.governance.profiles import RetentionMode

        gov = current_governance()
        if (
            gov is not None
            and gov.profile is not None
            and gov.profile.retention == RetentionMode.METADATA
        ):
            inputs_json = "{}" if inputs is not None else None
            outputs_json = "{}" if outputs is not None else None
        else:
            inputs_json = json.dumps(inputs) if inputs is not None else None
            outputs_json = json.dumps(outputs) if outputs is not None else None

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
                        inputs_json,
                        outputs_json,
                    ),
                )
        finally:
            conn.close()

    def delete_run(self, run_id: str) -> bool:
        """
        Delete a single run and all associated telemetry rows.
        Records a governance decision under the retention domain.
        """
        conn = self._get_conn()
        try:
            with conn:
                row = conn.execute(
                    "SELECT run_id FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if not row:
                    return False
                conn.execute("DELETE FROM node_executions WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM loop_iterations WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

                logger.info(
                    "Retention decision: deleted run '%s' and telemetry rows.",
                    run_id,
                )
                return True
        finally:
            conn.close()

    def sweep_retention(self, retention_str: str | None) -> int:
        """
        Delete runs older than the retention window specified by retention_str.
        Supported formats: '1d', '7d', '30d', '90d', '24h', 'forever', 'none'.
        If retention is None, 'forever', or 'none', no runs are deleted (preserving
        history across upgrades). Records a governance decision under the
        retention domain.
        """
        if not retention_str or retention_str.lower() in (
            "forever",
            "none",
            "unlimited",
        ):
            return 0

        s = retention_str.strip().lower()
        duration_ms = 0
        if s.endswith("d"):
            try:
                duration_ms = int(s[:-1]) * 24 * 3600 * 1000
            except ValueError:
                return 0
        elif s.endswith("h"):
            try:
                duration_ms = int(s[:-1]) * 3600 * 1000
            except ValueError:
                return 0
        elif s.endswith("m"):
            try:
                duration_ms = int(s[:-1]) * 60 * 1000
            except ValueError:
                return 0
        elif s.endswith("s"):
            try:
                duration_ms = int(s[:-1]) * 1000
            except ValueError:
                return 0
        else:
            try:
                duration_ms = int(s) * 24 * 3600 * 1000
            except ValueError:
                return 0

        if duration_ms <= 0:
            return 0

        cutoff = int(time.time() * 1000) - duration_ms
        conn = self._get_conn()
        try:
            with conn:
                old_runs = conn.execute(
                    "SELECT run_id FROM runs WHERE started_at < ?", (cutoff,)
                ).fetchall()
                if not old_runs:
                    return 0

                run_ids = [r["run_id"] for r in old_runs]
                placeholders = ",".join("?" for _ in run_ids)
                conn.execute(
                    f"DELETE FROM node_executions WHERE run_id IN ({placeholders})",
                    run_ids,
                )
                conn.execute(
                    f"DELETE FROM loop_iterations WHERE run_id IN ({placeholders})",
                    run_ids,
                )
                conn.execute(
                    f"DELETE FROM runs WHERE run_id IN ({placeholders})",
                    run_ids,
                )
                pruned_count = len(run_ids)

                logger.info(
                    "Retention sweep: pruned %d runs older than %s (cutoff %d).",
                    pruned_count,
                    retention_str,
                    cutoff,
                )
                return pruned_count
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
                    "DELETE FROM custom_nodes WHERE id = ?", (node_id,)
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    # -------------------------------------------------------------------
    # Governance profiles + small app settings (Gov-2)
    #
    # Custom profiles are stored as full JSON specs; the ACTIVE selection is
    # a single row in app_settings. Built-in profiles are NOT stored — they
    # live in code (governance.profiles) and are not editable, so persisting
    # them would only create a second copy to drift.
    # -------------------------------------------------------------------

    def save_governance_profile(self, name: str, spec_json: str) -> None:
        """Insert or replace a custom profile spec."""
        now = int(time.time() * 1000)
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO governance_profiles (name, spec_json, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        spec_json=excluded.spec_json
                    """,
                    (name, spec_json, now),
                )
        finally:
            conn.close()

    def list_governance_profiles(self) -> list[dict[str, Any]]:
        """All custom profiles as {name, spec} dicts; corrupt rows skipped."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT name, spec_json FROM governance_profiles"
            ).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                try:
                    spec = json.loads(row["spec_json"])
                    results.append({"name": row["name"], "spec": spec})
                except json.JSONDecodeError:
                    logger.warning(
                        "Skipping corrupt governance profile %r", row["name"]
                    )
            return results
        finally:
            conn.close()

    def get_governance_profile(self, name: str) -> dict[str, Any] | None:
        """One custom profile's spec, or None."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT spec_json FROM governance_profiles WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return None
            try:
                return {"name": name, "spec": json.loads(row["spec_json"])}
            except json.JSONDecodeError:
                logger.warning("Corrupt governance profile %r treated as absent", name)
                return None
        finally:
            conn.close()

    def delete_governance_profile(self, name: str) -> bool:
        """Delete a custom profile. Returns True if a row was deleted."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM governance_profiles WHERE name = ?", (name,)
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def get_setting(self, key: str) -> str | None:
        """One app setting value, or None when unset."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()

    def set_setting(self, key: str, value: str) -> None:
        """Insert or update one app setting."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (key, value),
                )
        finally:
            conn.close()

    # -------------------------------------------------------------------
    # Governance decision log (P1)
    #
    # Append-only: every enforcement point's ALLOW and DENY alike land
    # here so history survives a restart. No deletion path on purpose —
    # retention/recording-level enforcement is a later phase. Reads go
    # through query_governance_decisions (keyset-paginated) and
    # summarize_governance_decisions; callers off the event loop wrap them
    # in asyncio.to_thread exactly like the trace writes.
    # -------------------------------------------------------------------

    def save_governance_decision(
        self,
        *,
        decision_id: str,
        run_id: str,
        node_id: str,
        domain: str,
        capability: str,
        outcome: str,
        origin: str,
        reason: str,
        governed_by_json: str,
        policy_json: str,
        when_utc: str,
        when_ms: int,
    ) -> None:
        """Append one governance decision. Never updated or deleted."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO governance_decisions (
                        decision_id, run_id, node_id, domain, capability,
                        outcome, origin, reason, governed_by_json,
                        policy_json, when_utc, when_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        run_id,
                        node_id,
                        domain,
                        capability,
                        outcome,
                        origin,
                        reason,
                        governed_by_json,
                        policy_json,
                        when_utc,
                        when_ms,
                    ),
                )
        finally:
            conn.close()

    @staticmethod
    def _decision_where(
        *,
        run_id: str | None,
        node_id: str | None,
        domain: str | None,
        outcome: str | None,
        origin: str | None,
        since_ms: int | None,
        until_ms: int | None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if node_id is not None:
            clauses.append("node_id = ?")
            params.append(node_id)
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        if outcome is not None:
            clauses.append("outcome = ?")
            params.append(outcome)
        if origin is not None:
            clauses.append("origin = ?")
            params.append(origin)
        if since_ms is not None:
            clauses.append("when_ms >= ?")
            params.append(since_ms)
        if until_ms is not None:
            clauses.append("when_ms <= ?")
            params.append(until_ms)
        return (" AND ".join(clauses)) if clauses else "1=1", params

    @staticmethod
    def _decision_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        try:
            d["governed_by"] = json.loads(d.pop("governed_by_json"))
        except json.JSONDecodeError:
            d["governed_by"] = []
            d.pop("governed_by_json", None)
        try:
            d["effective_policy"] = json.loads(d.pop("policy_json"))
        except json.JSONDecodeError:
            d["effective_policy"] = {}
            d.pop("policy_json", None)
        return d

    def query_governance_decisions(
        self,
        *,
        run_id: str | None = None,
        node_id: str | None = None,
        domain: str | None = None,
        outcome: str | None = None,
        origin: str | None = None,
        since_ms: int | None = None,
        until_ms: int | None = None,
        cursor: int | None = None,
        limit: int = 50,
        newest_first: bool = True,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """
        One keyset page of decisions.

        Pagination walks `seq` — monotonic by construction — never OFFSET,
        so page N costs the same as page 1 no matter how large the log
        grows. Returns (rows, next_cursor); next_cursor is None when there
        are no further rows in this order.
        """
        where, params = self._decision_where(
            run_id=run_id,
            node_id=node_id,
            domain=domain,
            outcome=outcome,
            origin=origin,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        if newest_first:
            comparison = "seq < ?"
            ordering = "DESC"
        else:
            comparison = "seq > ?"
            ordering = "ASC"

        fetch_limit = max(1, min(limit, 1000))
        sql = (
            "SELECT seq, decision_id, run_id, node_id, domain, capability, "
            "outcome, origin, reason, governed_by_json, policy_json, "
            "when_utc, when_ms FROM governance_decisions "
            f"WHERE {where}"
        )
        query_params = list(params)
        if cursor is not None:
            sql += f" AND {comparison}"
            query_params.append(cursor)
        sql += f" ORDER BY seq {ordering} LIMIT ?"
        query_params.append(fetch_limit + 1)

        conn = self._get_conn()
        try:
            rows = conn.execute(sql, tuple(query_params)).fetchall()
        finally:
            conn.close()

        has_more = len(rows) > fetch_limit
        rows = rows[:fetch_limit]
        results = [self._decision_row_to_dict(r) for r in rows]
        next_cursor: int | None = None
        if has_more and results:
            next_cursor = int(results[-1]["seq"])
        return results, next_cursor

    def summarize_governance_decisions(
        self,
        *,
        run_id: str | None = None,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> dict[str, Any]:
        """Counts by outcome and by domain for a run, or overall."""
        where, params = self._decision_where(
            run_id=run_id,
            node_id=None,
            domain=None,
            outcome=None,
            origin=None,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        conn = self._get_conn()
        try:
            by_outcome_rows = conn.execute(
                f"SELECT outcome, COUNT(*) AS n FROM governance_decisions "
                f"WHERE {where} GROUP BY outcome",
                tuple(params),
            ).fetchall()
            by_domain_rows = conn.execute(
                f"SELECT domain, COUNT(*) AS n FROM governance_decisions "
                f"WHERE {where} GROUP BY domain",
                tuple(params),
            ).fetchall()
        finally:
            conn.close()
        by_outcome = {r["outcome"]: r["n"] for r in by_outcome_rows}
        by_domain = {r["domain"]: r["n"] for r in by_domain_rows}
        return {
            "total": sum(by_outcome.values()),
            "by_outcome": by_outcome,
            "by_domain": by_domain,
        }
