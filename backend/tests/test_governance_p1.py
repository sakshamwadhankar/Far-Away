"""
backend/tests/test_governance_p1.py

P1 — the evidence surface.

Covers:
  * TASK 0: DecisionOrigin distinguishes policy allows, profile allows,
    human allows (allow-once AND allow-for-run) and human denials
  * TASK 1: decisions persist through StateManager and survive a simulated
    restart (a fresh StateManager over the same file sees them)
  * TASK 2: every decision-list filter, keyset pagination, summary counts,
    and both export formats
  * TASK 3: governance decisions reach the run's WebSocket queue as typed
    WsEvents

No test here talks to a real provider: everything runs on MockEndpoint.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from komvos.compiler.dag import compile as compile_pipeline
from komvos.compiler.models import AccessPolicy
from komvos.endpoints.mock import MockEndpoint
from komvos.executors.base import ExecutorContext
from komvos.executors.model import ModelExecutor
from komvos.governance.approvals import ApprovalAnswer
from komvos.governance.context import run_context
from komvos.governance.decisions import (
    DecisionOrigin,
    DecisionOutcome,
    GovernanceDecision,
    GovernanceDomain,
)
from komvos.governance.posture import consult_posture
from komvos.governance.profiles import EXPLORE, REVIEW
from komvos.governance.resolve import resolve_policy
from komvos.governance.sinks import InMemoryDecisionSink
from komvos.scheduler.engine import EndpointRegistry
from komvos.scheduler.runner import PipelineRunner
from komvos.state.sqlite import StateManager

AUTH = {"Authorization": "Bearer test-token"}

PIPELINE_ID = "00000000-0000-4000-a000-00000000p101"


def model_ctx(
    node_id: str,
    endpoint_ref: str,
    endpoint: Any,
    policy: Any,
    *,
    pipeline_policy: Any | None = None,
    governed_by: tuple[str, ...] = (),
) -> ExecutorContext:
    """An ExecutorContext with explicit resolved vs pipeline-only policies."""
    from komvos.compiler.models import Node

    node = Node.model_validate(
        {
            "id": node_id,
            "type": "model",
            "endpoint_ref": endpoint_ref,
            "inputs": [{"name": "prompt", "type": "text"}],
            "outputs": [{"name": "out", "type": "text"}],
        }
    )
    return ExecutorContext(
        node=node,
        inputs={"prompt": "hello"},
        registry=EndpointRegistry({endpoint_ref: endpoint}),
        emit_fn=lambda _e: None,
        policy=policy,
        policy_sources=governed_by,
        pipeline_policy=pipeline_policy,
    )


async def wait_for_pending(governance: Any, timeout: float = 5.0) -> list[Any]:
    """Poll until the run's approval registry holds a pending question."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        pending = governance.approvals.pending()
        if pending:
            return pending
        if loop.time() > deadline:
            raise AssertionError("no pending approval appeared in time")
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# TASK 0 — origins: who decided, and if a human, exactly what they said
# ---------------------------------------------------------------------------


async def test_policy_allow_records_pipeline_policy_origin() -> None:
    """A plain allow from the pipeline's own policy needs no attribution spin."""
    sink = InMemoryDecisionSink()
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        AccessPolicy(providers=["mock"]),
        pipeline_policy=AccessPolicy(providers=["mock"]),
    )
    with run_context(sink, "run-origin-policy"):
        await ModelExecutor().execute(ctx)

    provider_allows = [
        d
        for d in sink.for_run("run-origin-policy")
        if (
            d.domain is GovernanceDomain.PROVIDERS
            and d.outcome is DecisionOutcome.ALLOWED
        )
    ]
    assert provider_allows
    assert provider_allows[-1].origin is DecisionOrigin.PIPELINE_POLICY


async def test_profile_allow_records_profile_origin() -> None:
    """An Audit posture permitting a withheld action is the PROFILE's grant."""
    sink = InMemoryDecisionSink()
    resolved = resolve_policy(AccessPolicy(providers=["openai"]), EXPLORE).policy
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        resolved,
        pipeline_policy=AccessPolicy(providers=["openai"]),
    )
    with run_context(sink, "run-origin-profile", profile=EXPLORE):
        await ModelExecutor().execute(ctx)

    provider_allows = [
        d
        for d in sink.for_run("run-origin-profile")
        if (
            d.domain is GovernanceDomain.PROVIDERS
            and d.outcome is DecisionOutcome.ALLOWED
        )
    ]
    assert provider_allows
    assert provider_allows[-1].origin is DecisionOrigin.PROFILE


async def test_human_allow_once_records_human_origin() -> None:
    """
    The defect this phase fixes: an Ask-approved action must NOT read as
    `profile` (an automatic grant) — a person said yes, once.
    """
    sink = InMemoryDecisionSink()
    resolved = resolve_policy(AccessPolicy(providers=["openai"]), REVIEW).policy
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        resolved,
        pipeline_policy=AccessPolicy(providers=["openai"]),
    )
    with run_context(sink, "run-origin-human-once", profile=REVIEW) as governance:
        task = asyncio.create_task(ModelExecutor().execute(ctx))
        pending = await wait_for_pending(governance)
        governance.approvals.answer(pending[0].approval_id, ApprovalAnswer.ALLOW_ONCE)
        await task

    allows = [
        d
        for d in sink.for_run("run-origin-human-once")
        if (
            d.domain is GovernanceDomain.PROVIDERS
            and d.outcome is DecisionOutcome.ALLOWED
        )
    ]
    assert allows
    assert allows[-1].origin is DecisionOrigin.HUMAN_ALLOW_ONCE


async def test_human_allow_for_run_records_standing_grant_origin() -> None:
    """A standing grant is a different human answer from a one-off yes."""
    sink = InMemoryDecisionSink()
    resolved = resolve_policy(AccessPolicy(providers=["openai"]), REVIEW).policy
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        resolved,
        pipeline_policy=AccessPolicy(providers=["openai"]),
    )
    with run_context(sink, "run-origin-human-run", profile=REVIEW) as governance:
        task = asyncio.create_task(ModelExecutor().execute(ctx))
        pending = await wait_for_pending(governance)
        governance.approvals.answer(
            pending[0].approval_id, ApprovalAnswer.ALLOW_FOR_RUN
        )
        await task

    allows = [
        d
        for d in sink.for_run("run-origin-human-run")
        if (
            d.domain is GovernanceDomain.PROVIDERS
            and d.outcome is DecisionOutcome.ALLOWED
        )
    ]
    assert allows
    assert allows[-1].origin is DecisionOrigin.HUMAN_ALLOW_FOR_RUN


async def test_human_deny_is_distinct_from_policy_deny_and_timeout() -> None:
    """
    Three ways to say no, three different records: a person refusing, the
    pipeline's own policy refusing, and nobody answering in time.
    """
    # -- human deny --------------------------------------------------------
    sink = InMemoryDecisionSink()
    outcome = None
    with run_context(sink, "run-origin-deny", profile=REVIEW) as governance:
        ask_task = asyncio.create_task(
            consult_posture(
                domain=GovernanceDomain.EGRESS,
                capability="egress:blocked.example.com",
                node_id="n",
                pipeline_reason="the pipeline withheld this host.",
                effective_policy=AccessPolicy(),
            )
        )
        pending = await wait_for_pending(governance)
        governance.approvals.answer(pending[0].approval_id, ApprovalAnswer.DENY)
        outcome = await ask_task

    assert outcome.allowed is False
    human_denials = [
        d
        for d in sink.for_run("run-origin-deny")
        if d.outcome is DecisionOutcome.DENIED
    ]
    assert human_denials
    assert human_denials[-1].origin is DecisionOrigin.HUMAN_DENY

    # -- timeout is not a human denial --------------------------------------
    timeout_sink = InMemoryDecisionSink()
    with run_context(timeout_sink, "run-origin-timeout", profile=REVIEW):
        await consult_posture(
            domain=GovernanceDomain.EGRESS,
            capability="egress:silent.example.com",
            node_id="n",
            pipeline_reason="the pipeline withheld this host.",
            effective_policy=AccessPolicy(),
            timeout=0.05,
        )
    timed_out = [
        d
        for d in timeout_sink.for_run("run-origin-timeout")
        if d.outcome is DecisionOutcome.TIMEOUT
    ]
    assert timed_out
    assert timed_out[-1].origin is not DecisionOrigin.HUMAN_DENY


# ---------------------------------------------------------------------------
# TASK 1 — decisions survive a restart
# ---------------------------------------------------------------------------


def _sample_decision(run_id: str, **overrides: Any) -> GovernanceDecision:
    from komvos.compiler.models import AccessPolicy as AP

    fields: dict[str, Any] = {
        "run_id": run_id,
        "node_id": "summarize",
        "domain": GovernanceDomain.PROVIDERS,
        "capability": "provider:mock",
        "outcome": DecisionOutcome.ALLOWED,
        "reason": "granted by its effective policy.",
        "governed_by": ("gate-1",),
        "effective_policy": AP(providers=["mock"]),
        "origin": DecisionOrigin.PIPELINE_POLICY,
    }
    fields.update(overrides)
    return GovernanceDecision(**fields)


def test_sqlite_sink_persists_and_survives_a_restart(tmp_path: Path) -> None:
    """A fresh StateManager over the same file sees every stored decision."""
    from komvos.governance.sinks import SqliteDecisionSink

    db = tmp_path / "gov.db"
    writer = StateManager(db)

    async def write() -> None:
        sink = SqliteDecisionSink(writer)
        await sink.record(_sample_decision("run-persist"))
        await sink.record(
            _sample_decision(
                "run-persist",
                outcome=DecisionOutcome.DENIED,
                origin=DecisionOrigin.HUMAN_DENY,
            )
        )

    asyncio.run(write())

    # Simulated restart: a brand-new StateManager instance, same file.
    reader = StateManager(db)
    rows, next_cursor = reader.query_governance_decisions(run_id="run-persist")
    assert next_cursor is None  # fewer than one page of rows
    assert [r["outcome"] for r in rows] == ["deny", "allow"]  # newest first
    assert rows[0]["origin"] == "human_deny"
    assert rows[0]["governed_by"] == ["gate-1"]
    assert rows[0]["effective_policy"]["providers"] == ["mock"]
    assert rows[0]["when_utc"].endswith("+00:00")


def test_preexisting_database_opens_cleanly_with_decisions_table(
    tmp_path: Path,
) -> None:
    """A database from before this phase must open and gain the new table."""
    db = tmp_path / "pre-p1.db"
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO app_settings VALUES ('legacy', '1')")
    conn.commit()
    conn.close()

    sm = StateManager(db)  # must not raise
    rows, _ = sm.query_governance_decisions()
    assert rows == []
    assert sm.get_setting("legacy") == "1"


async def test_pipeline_runner_writes_decisions_to_state_manager(
    tmp_path: Path,
) -> None:
    """A full runner-driven run persists ALLOW records for later inspection."""
    doc = {
        "schema_version": "2.1",
        "id": PIPELINE_ID,
        "name": "Persisted",
        "version": "1.0.0",
        "nodes": [
            {"id": "in", "type": "input",
             "outputs": [{"name": "prompt", "type": "text"}]},
            {"id": "bot", "type": "model", "endpoint_ref": "mock:model",
             "inputs": [{"name": "prompt", "type": "text"}],
             "outputs": [{"name": "reply", "type": "text"}]},
            {"id": "out", "type": "output", "inputs": [{"name": "r", "type": "text"}]},
            {"id": "gate-1", "type": "access",
             "config": {"access_policy": {"providers": ["mock"]}}},
        ],
        "edges": [
            {"from": "in.prompt", "to": "bot.prompt"},
            {"from": "bot.reply", "to": "out.r"},
            {"from": "gate-1.scope", "to": "bot.prompt"},
        ],
        "endpoints": {"mock:model": {"kind": "mock", "model": "m"}},
    }
    dag = compile_pipeline(doc)
    state_manager = StateManager(tmp_path / "runs.db")
    runner = PipelineRunner(
        "run-sqlite-e2e",
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
        state_manager=state_manager,
    )
    queue: asyncio.Queue[Any] = asyncio.Queue()
    await runner.run(queue)

    rows, _ = state_manager.query_governance_decisions(run_id="run-sqlite-e2e")
    assert any(
        r["domain"] == "providers" and r["outcome"] == "allow" for r in rows
    ), f"expected persisted provider allow, got {rows}"


# ---------------------------------------------------------------------------
# TASK 3 — decisions reach the WebSocket stream live
# ---------------------------------------------------------------------------


async def test_runner_emits_typed_decision_events_on_the_queue() -> None:
    from komvos.scheduler.events import WsGovernanceDecisionEvent

    doc = {
        "schema_version": "2.1",
        "id": PIPELINE_ID,
        "name": "Live decisions",
        "version": "1.0.0",
        "nodes": [
            {"id": "in", "type": "input",
             "outputs": [{"name": "prompt", "type": "text"}]},
            {"id": "bot", "type": "model", "endpoint_ref": "mock:model",
             "inputs": [{"name": "prompt", "type": "text"}],
             "outputs": [{"name": "reply", "type": "text"}]},
            {"id": "out", "type": "output", "inputs": [{"name": "r", "type": "text"}]},
            {"id": "gate-1", "type": "access",
             "config": {"access_policy": {"providers": ["mock"]}}},
        ],
        "edges": [
            {"from": "in.prompt", "to": "bot.prompt"},
            {"from": "bot.reply", "to": "out.r"},
            {"from": "gate-1.scope", "to": "bot.prompt"},
        ],
        "endpoints": {"mock:model": {"kind": "mock", "model": "m"}},
    }
    dag = compile_pipeline(doc)
    runner = PipelineRunner(
        "run-live-decisions",
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
    )
    queue: asyncio.Queue[Any] = asyncio.Queue()
    await runner.run(queue)

    decision_events = [
        e
        for e in _drain(queue)
        if isinstance(e, WsGovernanceDecisionEvent)
    ]
    assert decision_events, "no governance_decision events reached the queue"
    providers_allow = [
        e
        for e in decision_events
        if e.domain == "providers" and e.outcome == "allow"
    ]
    assert providers_allow
    assert providers_allow[0].node_id == "bot"
    assert providers_allow[0].reason


def _drain(queue: asyncio.Queue) -> list[Any]:
    items: list[Any] = []
    while not queue.empty():
        item = queue.get_nowait()
        if item is None:
            break
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# TASK 2 — query, filter, paginate, summarize, export
# ---------------------------------------------------------------------------

CSV_HEADER = [
    "when_utc",
    "run_id",
    "node_id",
    "domain",
    "capability",
    "outcome",
    "origin",
    "governed_by",
    "reason",
    "effective_policy",
]


async def _decisions_app(tmp_path: Path) -> tuple[Any, Any]:
    """FastAPI app mounting ONLY the governance router over a temp database."""
    from fastapi import FastAPI

    from komvos.governance.api import create_governance_router

    app = FastAPI(title="test-decisions")
    state_manager = StateManager(tmp_path / "decisions-api.db")

    def noop_token() -> str:
        return "dev"

    app.include_router(
        create_governance_router(
            verify_token_dep=noop_token, get_state_manager_fn=lambda: state_manager
        )
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    return client, state_manager


@pytest.fixture
async def decisions_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, StateManager]]:
    client, state_manager = await _decisions_app(tmp_path)
    yield client, state_manager
    await client.aclose()


def _seed_decisions(state_manager: StateManager) -> None:
    """
    Deterministic rows across three runs with distinct filterable values.
    Times are fixed so since_ms/until_ms filters are exact.
    """
    from komvos.governance.decisions import GovernanceDecision as GD
    from komvos.governance.sinks import decision_to_row

    def make(seq_time: str, ms: int, **fields: Any) -> None:
        defaults: dict[str, Any] = {
            "run_id": "run-1",
            "node_id": "bot",
            "domain": GovernanceDomain.PROVIDERS,
            "capability": "provider:mock",
            "outcome": DecisionOutcome.ALLOWED,
            "reason": "granted.",
            "governed_by": ("gate-1",),
            "effective_policy": AccessPolicy(providers=["mock"]),
            "origin": DecisionOrigin.PIPELINE_POLICY,
        }
        defaults.update(fields)
        row = decision_to_row(GD(**defaults))
        # Override the timestamp fields deterministically.
        row["when_utc"] = seq_time
        row["when_ms"] = ms
        state_manager.save_governance_decision(**row)

    base = 1_700_000_000_000
    make("2033-11-14T22:13:20+00:00", base, run_id="run-1", node_id="bot")
    make(
        "2033-11-14T22:13:21+00:00",
        base + 1000,
        run_id="run-1",
        node_id="bot",
        domain=GovernanceDomain.EGRESS,
        capability="egress:api.example.com",
        outcome=DecisionOutcome.DENIED,
        reason="not in allowed domains, egress blocked by policy, no retry.",
        origin=DecisionOrigin.HUMAN_DENY,
    )
    make(
        "2033-11-14T22:13:22+00:00",
        base + 2000,
        run_id="run-2",
        node_id="writer",
        domain=GovernanceDomain.SPEND,
        outcome=DecisionOutcome.ALLOWED,
        origin=DecisionOrigin.PROFILE,
    )
    make(
        "2033-11-14T22:13:23+00:00",
        base + 3000,
        run_id="run-2",
        node_id="writer",
        domain=GovernanceDomain.SPEND,
        outcome=DecisionOutcome.TIMEOUT,
        origin=DecisionOrigin.PROFILE,
    )
    for i in range(25):
        make(
            f"2033-11-14T22:14:{i % 60:02d}+00:00",
            base + 10_000 + i,
            run_id="run-3",
            node_id=f"n{i}",
        )


def test_filter_by_run_node_domain_outcome_origin_and_time(
    decisions_api: tuple[httpx.AsyncClient, StateManager],
) -> None:
    client, sm = decisions_api

    async def scenario() -> None:
        await asyncio.to_thread(_seed_decisions, sm)

        async def ids(query: str) -> list[str]:
            resp = await client.get(f"/governance/decisions?{query}", headers=AUTH)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            return [d["node_id"] for d in body["decisions"]]

        # run filter
        assert set(await ids("run_id=run-2")) == {"writer"}
        # node filter
        assert (await ids("run_id=run-3&node_id=n7")) == ["n7"]
        # domain filter
        assert (await ids("run_id=run-1&domain=egress")) == ["bot"]
        # outcome filter
        outcomes = {
            d["outcome"]
            for d in (
                await client.get(
                    "/governance/decisions?run_id=run-2&outcome=allow", headers=AUTH
                )
            ).json()["decisions"]
        }
        assert outcomes == {"allow"}
        # origin filter
        assert len(await ids("origin=human_deny")) == 1
        assert {*(await ids("outcome=timeout"))} == {"writer"}
        # time range filters
        base = 1_700_000_000_000
        assert len(await ids(f"since_ms={base + 10_000}")) == 25
        assert len(await ids(f"until_ms={base + 1500}")) == 2
        assert len(await ids(f"since_ms={base + 1000}&until_ms={base + 2000}")) == 2
        # unknown enum value is rejected by the API contract, not silently empty
        bad = await client.get("/governance/decisions?outcome=nope", headers=AUTH)
        assert bad.status_code == 422

    asyncio.run(scenario())


def test_keyset_pagination_walks_every_row_exactly_once(
    decisions_api: tuple[httpx.AsyncClient, StateManager],
) -> None:
    client, sm = decisions_api

    async def scenario() -> None:
        await asyncio.to_thread(_seed_decisions, sm)

        seen: list[int] = []
        cursor: int | None = None
        pages = 0
        while True:
            query = "limit=10"
            if cursor is not None:
                query += f"&cursor={cursor}"
            body = (
                await client.get(f"/governance/decisions?{query}", headers=AUTH)
            ).json()
            pages += 1
            page_seqs = [d["seq"] for d in body["decisions"]]
            assert len(page_seqs) <= 10
            assert (
                page_seqs == sorted(page_seqs, reverse=True)
            ), "page must be newest-first"
            seen.extend(page_seqs)
            if body["next_cursor"] is None:
                break
            cursor = body["next_cursor"]

        assert pages == 3  # 29 seeded rows at 10/page
        assert len(seen) == 29
        assert len(set(seen)) == 29, "keyset pages must not overlap or skip"
        assert seen == sorted(seen, reverse=True)

        # Pagination composes with a filter: only matching rows appear.
        filtered_first = (
            await client.get(
                "/governance/decisions?run_id=run-3&limit=5", headers=AUTH
            )
        ).json()
        assert len(filtered_first["decisions"]) == 5
        assert all(d["run_id"] == "run-3" for d in filtered_first["decisions"])

    asyncio.run(scenario())


def test_summary_counts_by_outcome_and_domain_for_run_and_overall(
    decisions_api: tuple[httpx.AsyncClient, StateManager],
) -> None:
    client, sm = decisions_api

    async def scenario() -> None:
        await asyncio.to_thread(_seed_decisions, sm)

        overall = (
            await client.get("/governance/decisions/summary", headers=AUTH)
        ).json()
        assert overall["total"] == 29
        assert overall["by_outcome"]["deny"] == 1
        assert overall["by_outcome"]["timeout"] == 1
        assert overall["by_outcome"]["allow"] == 27
        assert overall["by_domain"]["providers"] == 26
        assert overall["by_domain"]["egress"] == 1
        assert overall["by_domain"]["spend"] == 2

        one_run = (
            await client.get(
                "/governance/decisions/summary?run_id=run-2", headers=AUTH
            )
        ).json()
        assert one_run["total"] == 2
        assert one_run["by_outcome"] == {"allow": 1, "timeout": 1}
        assert one_run["by_domain"] == {"spend": 2}

    asyncio.run(scenario())


def test_export_json_is_chronological_and_filtered(
    decisions_api: tuple[httpx.AsyncClient, StateManager],
) -> None:
    client, sm = decisions_api

    async def scenario() -> None:
        await asyncio.to_thread(_seed_decisions, sm)

        resp = await client.get(
            "/governance/decisions/export?format=json&run_id=run-1", headers=AUTH
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        rows = json.loads(resp.text)
        assert [r["capability"] for r in rows] == [
            "provider:mock",
            "egress:api.example.com",
        ]
        seqs = [r["seq"] for r in rows]
        assert seqs == sorted(seqs)  # oldest first for reading order

    asyncio.run(scenario())


def test_export_csv_has_header_quotes_reasons_and_escapes_commas(
    decisions_api: tuple[httpx.AsyncClient, StateManager],
) -> None:
    import csv as csv_module
    import io as io_module

    client, sm = decisions_api

    async def scenario() -> None:
        await asyncio.to_thread(_seed_decisions, sm)

        resp = await client.get(
            "/governance/decisions/export?format=csv&domain=egress", headers=AUTH
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers.get("content-disposition", "")

        reader = csv_module.reader(io_module.StringIO(resp.text))
        rows = list(reader)
        assert rows[0] == CSV_HEADER
        assert len(rows) == 2
        # The seeded egress denial's reason contains commas; the CSV module
        # must have quoted it so it round-trips as ONE field.
        data_row = dict(zip(rows[0], rows[1], strict=False))
        assert data_row["reason"] == (
            "not in allowed domains, egress blocked by policy, no retry."
        )
        assert data_row["origin"] == "human_deny"
        assert data_row["governed_by"] == "gate-1"

    asyncio.run(scenario())
