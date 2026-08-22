"""
backend/komvos/serve/store.py

SQLite persistence for deployments.

Shares the same database FILE as komvos.state.sqlite.StateManager (both
default to ~/.komvos/komvos.db) so that a served run's trace rows
(runs/node_executions/loop_iterations, tagged with deployment_id — see
StateManager.save_run) live alongside canvas-run traces in one place, per
upgrade.md 3.4.6. This class owns its own connections and its own table
rather than subclassing StateManager, so the two can be constructed and
tested independently; `_init_db` is additive (CREATE TABLE IF NOT EXISTS)
so opening both against the same file in either order is safe.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from komvos.serve.keys import verify_key
from komvos.serve.models import Deployment


class DeploymentStore:
    """Manages the `deployments` table."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS deployments (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        pipeline_json TEXT NOT NULL,
                        key_hash TEXT NOT NULL,
                        expose_lan INTEGER NOT NULL DEFAULT 0,
                        rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
                        chat_input_node TEXT NOT NULL,
                        chat_output_node TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        request_count INTEGER NOT NULL DEFAULT 0,
                        error_count INTEGER NOT NULL DEFAULT 0,
                        last_request_at INTEGER
                    )
                    """
                )
        finally:
            conn.close()

    # -- writes ---------------------------------------------------------

    def create(self, deployment: Deployment) -> None:
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO deployments (
                        id, name, pipeline_json, key_hash, expose_lan,
                        rate_limit_per_minute, chat_input_node, chat_output_node,
                        created_at, request_count, error_count, last_request_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        deployment.id,
                        deployment.name,
                        _dump_pipeline(deployment.pipeline),
                        deployment.key_hash,
                        int(deployment.expose_lan),
                        deployment.rate_limit_per_minute,
                        deployment.chat_input_node,
                        deployment.chat_output_node,
                        deployment.created_at,
                        deployment.request_count,
                        deployment.error_count,
                        deployment.last_request_at,
                    ),
                )
        finally:
            conn.close()

    def rotate_key(self, deployment_id: str, new_key_hash: str) -> bool:
        """Replace a deployment's key hash. Returns True if a row was updated."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE deployments SET key_hash = ? WHERE id = ?",
                    (new_key_hash, deployment_id),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def delete(self, deployment_id: str) -> bool:
        """Returns True if a row was deleted."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM deployments WHERE id = ?", (deployment_id,)
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def record_request(self, deployment_id: str, *, success: bool) -> None:
        """Bump request/error counters and last_request_at for a served call."""
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE deployments
                    SET request_count = request_count + 1,
                        error_count = error_count + ?,
                        last_request_at = ?
                    WHERE id = ?
                    """,
                    (0 if success else 1, int(time.time() * 1000), deployment_id),
                )
        finally:
            conn.close()

    # -- reads ------------------------------------------------------------

    def get(self, deployment_id: str) -> Deployment | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM deployments WHERE id = ?", (deployment_id,)
            ).fetchone()
            return _row_to_deployment(row) if row else None
        finally:
            conn.close()

    def list(self) -> list[Deployment]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM deployments ORDER BY created_at DESC"
            ).fetchall()
            return [_row_to_deployment(row) for row in rows]
        finally:
            conn.close()

    def find_by_key(self, plaintext_key: str) -> Deployment | None:
        """
        Resolve a presented deployment key to its Deployment.

        O(n) over all deployments rather than an indexed lookup: hashes are
        one-way by design, and a local desktop install has at most a handful
        of deployments, so a full scan comparing hmac.compare_digest against
        each stored hash is both simple and fast enough. It also avoids
        storing any partial-key index that would leak a few bytes of the key.
        """
        for deployment in self.list():
            if verify_key(plaintext_key, deployment.key_hash):
                return deployment
        return None


def _dump_pipeline(pipeline: dict[str, Any]) -> str:
    return json.dumps(pipeline)


def _row_to_deployment(row: sqlite3.Row) -> Deployment:
    d = dict(row)
    d["pipeline"] = json.loads(d.pop("pipeline_json"))
    d["expose_lan"] = bool(d["expose_lan"])
    return Deployment.model_validate(d)
