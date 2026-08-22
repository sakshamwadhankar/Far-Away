"""
backend/tests/test_governance_g2.py

Gov-2 — posture/profile model, resolution with origin attribution, the Ask
posture's genuine suspension, served-mode degrade, deployment profile
snapshots, migrations, the governance HTTP API, and the G1 drift guard.

No test here calls a real provider: everything runs on MockEndpoint.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from komvos.compiler.dag import compile as compile_pipeline
from komvos.compiler.models import AccessPolicy
from komvos.compiler.validation import PipelineValidationErrors
from komvos.endpoints.base import AccessDeniedError
from komvos.endpoints.mock import MockEndpoint
from komvos.executors.base import ExecutorContext
from komvos.executors.model import ModelExecutor
from komvos.governance.approvals import (
    _REGISTRIES,
    APPROVAL_TIMEOUT_SECONDS,
    ApprovalAnswer,
)
from komvos.governance.context import run_context
from komvos.governance.decisions import (
    DecisionOrigin,
    DecisionOutcome,
    GovernanceDomain,
)
from komvos.governance.posture import consult_posture
from komvos.governance.profiles import (
    BUILT_IN_PROFILES,
    DEFAULT_PROFILE_NAME,
    EXPLORE,
    LOCKED,
    REVIEW,
    GovernanceProfile,
    Posture,
    RetentionMode,
    get_active_profile_name,
    load_profile,
    set_active_profile_name,
)
from komvos.governance.resolve import resolve_policy
from komvos.governance.sinks import InMemoryDecisionSink
from komvos.scheduler.engine import (
    CancelToken,
    EndpointRegistry,
    EventKind,
    PipelineCancelled,
)
from komvos.scheduler.events import WsRunErrorEvent
from komvos.scheduler.runner import PipelineRunner
from komvos.serve.models import Deployment
from komvos.serve.store import DeploymentStore
from komvos.state.sqlite import StateManager

AUTH = {"Authorization": "Bearer test-token"}

PIPELINE_ID = "00000000-0000-4000-a000-00000000g201"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def model_ctx(
    node_id: str,
    endpoint_ref: str,
    endpoint: Any,
    policy: Any,
    *,
    pipeline_policy: Any | None = None,
    governed_by: tuple[str, ...] = (),
    cancel_token: CancelToken | None = None,
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
        cancel_token=cancel_token,
        policy=policy,
        policy_sources=governed_by,
        pipeline_policy=pipeline_policy,
    )


def ask_pipeline() -> dict[str, Any]:
    """
    Two model nodes in the SAME parallel tier.

    gate-a scopes model_a granting ONLY 'openai' — so a mock endpoint is
    withheld by the PIPELINE's own policy, which is what puts the posture in
    charge once a loosening profile resolves the policy upward. gate-b scopes
    model_b granting 'mock' — it runs straight through.
    """
    return {
        "schema_version": "2.1",
        "id": PIPELINE_ID,
        "name": "Ask suspension",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "model_a",
                "type": "model",
                "endpoint_ref": "mock:model",
                "inputs": [{"name": "prompt", "type": "text"}],
                "outputs": [{"name": "out", "type": "text"}],
            },
            {
                "id": "model_b",
                "type": "model",
                "endpoint_ref": "mock:model",
                "inputs": [{"name": "prompt", "type": "text"}],
                "outputs": [{"name": "out", "type": "text"}],
            },
            {
                "id": "out_a",
                "type": "output",
                "inputs": [{"name": "r", "type": "text"}],
            },
            {
                "id": "out_b",
                "type": "output",
                "inputs": [{"name": "r", "type": "text"}],
            },
            {
                "id": "gate-a",
                "type": "access",
                "config": {"access_policy": {"providers": ["openai"]}},
            },
            {
                "id": "gate-b",
                "type": "access",
                "config": {"access_policy": {"providers": ["mock"]}},
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "model_a.prompt"},
            {"from": "model_a.out", "to": "out_a.r"},
            {"from": "in.prompt", "to": "model_b.prompt"},
            {"from": "model_b.out", "to": "out_b.r"},
            {"from": "gate-a.scope", "to": "model_a.prompt"},
            {"from": "gate-b.scope", "to": "model_b.prompt"},
        ],
        "endpoints": {"mock:model": {"kind": "mock", "model": "m"}},
    }


def ungoverned_model_pipeline() -> dict[str, Any]:
    """input -> model -> output where NO access node governs the model."""
    return {
        "schema_version": "2.1",
        "id": PIPELINE_ID,
        "name": "Ungoverned",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "bot",
                "type": "model",
                "endpoint_ref": "mock:model",
                "inputs": [{"name": "prompt", "type": "text"}],
                "outputs": [{"name": "reply", "type": "text"}],
            },
            {"id": "out", "type": "output", "inputs": [{"name": "r", "type": "text"}]},
            {
                "id": "decoy-gate",
                "type": "access",
                "config": {"access_policy": {"providers": ["mock"]}},
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "bot.prompt"},
            {"from": "bot.reply", "to": "out.r"},
            {"from": "decoy-gate.scope", "to": "out.r"},
        ],
        "endpoints": {"mock:model": {"kind": "mock", "model": "m"}},
    }


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


async def drain_queue(queue: asyncio.Queue) -> list[Any]:
    events: list[Any] = []
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=10)
        events.append(event)
        if event is None:
            return events


# ---------------------------------------------------------------------------
# TASK 1 — built-in profile matrix
# ---------------------------------------------------------------------------


def test_builtin_profile_matrix() -> None:
    assert EXPLORE.postures[GovernanceDomain.PROVIDERS] is Posture.AUDIT
    assert EXPLORE.postures[GovernanceDomain.EGRESS] is Posture.AUDIT
    assert EXPLORE.postures[GovernanceDomain.SPEND] is Posture.AUDIT
    assert EXPLORE.retention is RetentionMode.FULL
    assert EXPLORE.spend_cap_usd is None

    assert REVIEW.postures[GovernanceDomain.PROVIDERS] is Posture.ASK
    assert REVIEW.postures[GovernanceDomain.EGRESS] is Posture.ASK
    assert REVIEW.postures[GovernanceDomain.SPEND] is Posture.ASK
    assert REVIEW.spend_ask_threshold_usd is not None
    assert REVIEW.retention is RetentionMode.FULL

    assert LOCKED.postures[GovernanceDomain.PROVIDERS] is Posture.ENFORCE
    assert LOCKED.postures[GovernanceDomain.EGRESS] is Posture.ENFORCE
    assert LOCKED.postures[GovernanceDomain.SPEND] is Posture.ENFORCE
    assert LOCKED.retention is RetentionMode.METADATA

    assert set(BUILT_IN_PROFILES) == {"explore", "review", "locked"}
    assert DEFAULT_PROFILE_NAME == "locked"


# ---------------------------------------------------------------------------
# TASK 2 — resolution in both directions, with origin
# ---------------------------------------------------------------------------


def test_resolution_without_profile_is_identity() -> None:
    policy = AccessPolicy(providers=["mock"], max_cost_usd=3.0)
    resolved = resolve_policy(policy, None)
    assert resolved.policy.providers == ["mock"]
    assert resolved.policy.max_cost_usd == 3.0
    assert resolved.origins == {}
    assert resolved.origin_of("provider:mock") is DecisionOrigin.PIPELINE_POLICY


def test_resolution_loosens_with_profile_origin() -> None:
    policy = AccessPolicy(providers=["mock"], allow_local_models=False)
    resolved = resolve_policy(policy, EXPLORE)

    assert "openai" in resolved.policy.providers
    assert resolved.policy.allow_local_models is True
    assert resolved.origins["provider:openai"] is DecisionOrigin.PROFILE
    assert resolved.origins["allow_local_models"] is DecisionOrigin.PROFILE
    assert resolved.origin_of("provider:mock") is DecisionOrigin.PIPELINE_POLICY


def test_resolution_tightens_with_profile_origin() -> None:
    strict = GovernanceProfile(
        name="strict-custom",
        postures=dict.fromkeys(GovernanceDomain, Posture.ENFORCE),
        spend_cap_usd=2.0,
        retention=RetentionMode.METADATA,
    )
    policy = AccessPolicy(max_cost_usd=5.0)

    resolved = resolve_policy(policy, strict)
    assert resolved.policy.max_cost_usd == 2.0
    assert resolved.origins["max_cost_usd"] is DecisionOrigin.PROFILE


def test_review_threshold_becomes_the_ask_trigger() -> None:
    resolved = resolve_policy(AccessPolicy(), REVIEW)
    assert resolved.policy.max_cost_usd == REVIEW.spend_ask_threshold_usd
    assert resolved.origins["max_cost_usd"] is DecisionOrigin.PROFILE


def test_enforce_profile_leaves_grants_alone() -> None:
    policy = AccessPolicy(providers=["anthropic"], allow_network=True)
    resolved = resolve_policy(policy, LOCKED)
    assert resolved.policy.providers == ["anthropic"]
    assert resolved.policy.allow_network is True
    assert resolved.origins == {}


# ---------------------------------------------------------------------------
# Compile-time / run-time agreement
# ---------------------------------------------------------------------------


def test_compile_without_profile_behaves_identically() -> None:
    """A pipeline that needs no loosening compiles identically either way."""
    governed = {
        "schema_version": "2.1",
        "id": PIPELINE_ID,
        "name": "Governed",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "bot",
                "type": "model",
                "endpoint_ref": "mock:model",
                "inputs": [{"name": "prompt", "type": "text"}],
                "outputs": [{"name": "reply", "type": "text"}],
            },
            {"id": "out", "type": "output", "inputs": [{"name": "r", "type": "text"}]},
            {
                "id": "gate-1",
                "type": "access",
                "config": {"access_policy": {"providers": ["mock"]}},
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "bot.prompt"},
            {"from": "bot.reply", "to": "out.r"},
            {"from": "gate-1.scope", "to": "bot.prompt"},
        ],
        "endpoints": {"mock:model": {"kind": "mock", "model": "m"}},
    }
    dag_default = compile_pipeline(governed)
    dag_none = compile_pipeline(governed, profile=None)
    assert dag_default.effective_policies == dag_none.effective_policies
    # No profile: resolved view and pipeline-only view coincide.
    assert dag_default.pipeline_policies == dag_default.effective_policies


def test_compile_loosening_profile_accepts_otherwise_failing_pipeline() -> None:
    for profile in (EXPLORE, REVIEW):
        dag = compile_pipeline(ask_pipeline(), profile=profile)
        resolved = dag.effective_policies["model_a"]
        pipeline_only = dag.pipeline_policies["model_a"]
        assert "mock" in resolved.providers
        assert "mock" not in pipeline_only.providers


def test_compile_locking_profile_still_rejects() -> None:
    with pytest.raises(PipelineValidationErrors):
        compile_pipeline(ask_pipeline(), profile=LOCKED)


def test_served_structural_rule_holds_under_every_profile() -> None:
    """A profile adjusts grants; it never excuses an ungoverned model node."""
    for profile in BUILT_IN_PROFILES.values():
        with pytest.raises(PipelineValidationErrors) as excinfo:
            compile_pipeline(
                ungoverned_model_pipeline(), mode="served", profile=profile
            )
        message = "\n".join(excinfo.value.errors)
        assert "[Access Required]" in message
        assert "'bot'" in message


# ---------------------------------------------------------------------------
# TASK 3 — posture behaviour through the executor
# ---------------------------------------------------------------------------


async def test_audit_allows_and_attributes_the_profile() -> None:
    from komvos.governance.decisions import GovernanceDomain as GD
    from komvos.governance.sinks import InMemoryDecisionSink

    sink = InMemoryDecisionSink()
    resolved = resolve_policy(
        AccessPolicy(providers=["openai"]), EXPLORE
    ).policy
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        resolved,
        pipeline_policy=AccessPolicy(providers=["openai"]),
    )

    with run_context(sink, "run-audit", profile=EXPLORE):
        outputs = await ModelExecutor().execute(ctx)

    assert outputs["out"]
    provider_allows = [
        d
        for d in sink.for_run("run-audit")
        if d.domain is GD.PROVIDERS and d.outcome is DecisionOutcome.ALLOWED
    ]
    assert provider_allows
    assert provider_allows[-1].origin is DecisionOrigin.PROFILE
    assert "audit posture" in provider_allows[-1].reason


async def test_ask_suspends_and_sibling_in_same_tier_completes() -> None:
    from komvos.governance.sinks import InMemoryDecisionSink

    dag = compile_pipeline(ask_pipeline(), profile=REVIEW)
    events: list[Any] = []

    async def capture(event: Any) -> None:
        events.append(event)

    from komvos.scheduler.engine import Scheduler

    scheduler = Scheduler(
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
        event_callback=capture,
    )

    sink = InMemoryDecisionSink()
    with run_context(sink, "run-tier", profile=REVIEW) as governance:
        task = asyncio.create_task(scheduler.run({"in": {"prompt": "hello"}}))
        pending = await wait_for_pending(governance)

        # The sibling model node finished while model_a was suspended.
        done_nodes = [e.node_id for e in events if e.kind is EventKind.NODE_DONE]
        assert "model_b" in done_nodes
        assert "model_a" not in done_nodes
        # The typed pending-approval announcement went out.
        assert any(e.kind is EventKind.APPROVAL_PENDING for e in events)

        governance.approvals.answer(pending[0].approval_id, ApprovalAnswer.ALLOW_ONCE)
        result = await task

    assert result.completed
    allows = [
        d
        for d in sink.for_run("run-tier")
        if d.domain is GovernanceDomain.PROVIDERS
        and d.outcome is DecisionOutcome.ALLOWED
    ]
    assert allows and "operator" in allows[-1].reason.lower()


async def test_ask_answers_allow_once_then_asks_again() -> None:
    from komvos.governance.sinks import InMemoryDecisionSink

    sink = InMemoryDecisionSink()
    resolved = resolve_policy(AccessPolicy(providers=["openai"]), REVIEW).policy
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        resolved,
        pipeline_policy=AccessPolicy(providers=["openai"]),
    )

    with run_context(sink, "run-once", profile=REVIEW) as governance:
        task = asyncio.create_task(ModelExecutor().execute(ctx))
        pending = await wait_for_pending(governance)
        governance.approvals.answer(pending[0].approval_id, ApprovalAnswer.ALLOW_ONCE)
        outputs = await task

    assert outputs["out"]


async def test_allow_for_run_covers_only_that_capability() -> None:
    with run_context(None, "run-run-grant", profile=REVIEW) as governance:
        registry = governance.approvals
        task = asyncio.create_task(
            registry.request(
                node_id="a",
                domain=GovernanceDomain.PROVIDERS,
                capability="provider:mock",
                reason="why",
            )
        )
        pending = await wait_for_pending(governance)
        registry.answer(pending[0].approval_id, ApprovalAnswer.ALLOW_FOR_RUN)
        resolution = await task

        assert resolution.outcome is DecisionOutcome.ALLOWED
        assert resolution.answer is ApprovalAnswer.ALLOW_FOR_RUN
        assert registry.has_grant(GovernanceDomain.PROVIDERS, "provider:mock")

        # Same domain AND capability: granted immediately, nothing pending.
        second = await registry.request(
            node_id="b",
            domain=GovernanceDomain.PROVIDERS,
            capability="provider:mock",
            reason="again",
        )
        assert second.outcome is DecisionOutcome.ALLOWED
        assert governance.approvals.pending() == []

        # A DIFFERENT domain/capability must NOT ride along.
        other = asyncio.create_task(
            registry.request(
                node_id="c",
                domain=GovernanceDomain.EGRESS,
                capability="egress:api.example.com",
                reason="unrelated",
            )
        )
        pending_other = await wait_for_pending(governance)
        assert pending_other[0].capability.startswith("egress:")
        registry.answer(pending_other[0].approval_id, ApprovalAnswer.DENY)
        denial = await other
        assert denial.outcome is DecisionOutcome.DENIED


async def test_ask_deny_fails_closed_as_denied() -> None:
    from komvos.governance.sinks import InMemoryDecisionSink

    sink = InMemoryDecisionSink()
    resolved = resolve_policy(AccessPolicy(providers=["openai"]), REVIEW).policy
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        resolved,
        pipeline_policy=AccessPolicy(providers=["openai"]),
    )

    with run_context(sink, "run-deny", profile=REVIEW) as governance:
        task = asyncio.create_task(ModelExecutor().execute(ctx))
        pending = await wait_for_pending(governance)
        governance.approvals.answer(pending[0].approval_id, ApprovalAnswer.DENY)
        with pytest.raises(AccessDeniedError):
            await task

    decisions = sink.for_run("run-deny")
    denials = [d for d in decisions if d.outcome is DecisionOutcome.DENIED]
    assert denials and "Denied by operator." in denials[-1].reason


async def test_timeout_fails_closed_and_is_not_a_human_denial() -> None:
    from komvos.governance.sinks import InMemoryDecisionSink

    sink = InMemoryDecisionSink()
    with run_context(sink, "run-timeout", profile=REVIEW):
        outcome = await consult_posture(
            domain=GovernanceDomain.EGRESS,
            capability="egress:silent.example.com",
            node_id="n",
            pipeline_reason="the pipeline withheld this host.",
            effective_policy=AccessPolicy(),
            timeout=0.05,
        )

    assert outcome.allowed is False
    assert outcome.outcome is DecisionOutcome.TIMEOUT
    decision = sink.for_run("run-timeout")[-1]
    assert decision.outcome is DecisionOutcome.TIMEOUT
    assert decision.reason != "Denied by operator."
    assert "failed closed" in decision.reason.lower()


async def test_cancelled_while_suspended_aborts_with_no_leak() -> None:
    resolved = resolve_policy(AccessPolicy(providers=["openai"]), REVIEW).policy
    token = CancelToken()
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        resolved,
        pipeline_policy=AccessPolicy(providers=["openai"]),
        cancel_token=token,
    )

    with run_context(None, "run-cancel", profile=REVIEW) as governance:
        task = asyncio.create_task(ModelExecutor().execute(ctx))
        pending = await wait_for_pending(governance)
        assert len(pending) == 1

        token.cancel("User pressed stop.")
        with pytest.raises(PipelineCancelled):
            await task

        # Nothing left pending after the abort.
        assert governance.approvals.pending() == []


async def test_runner_cleans_up_registry_when_run_ends() -> None:
    """Kill switch during a suspension: run ends, registry gone."""
    dag = compile_pipeline(ask_pipeline(), profile=REVIEW)
    run_id = "run-leak-check"
    runner = PipelineRunner(
        run_id,
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
        profile=REVIEW,
    )
    queue: asyncio.Queue[Any] = asyncio.Queue()

    task = asyncio.create_task(runner.run(queue))
    try:
        deadline = time.monotonic() + 5.0
        while run_id not in _REGISTRIES or not _REGISTRIES[run_id].pending():
            if time.monotonic() > deadline or task.done():
                break
            await asyncio.sleep(0.01)
        assert run_id in _REGISTRIES, "approval never surfaced"

        runner.stop()
        events = await drain_queue(queue)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.wait([task], timeout=5)

    assert run_id not in _REGISTRIES, "ended run leaked its approval registry"
    assert any(isinstance(e, WsRunErrorEvent) or hasattr(e, "reason") for e in events)


async def test_runner_registry_cleaned_up_after_success_too() -> None:
    dag = compile_pipeline(ask_pipeline(), profile=REVIEW)
    run_id = "run-clean-success"
    runner = PipelineRunner(
        run_id,
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
    )
    queue: asyncio.Queue[Any] = asyncio.Queue()
    task = asyncio.create_task(runner.run(queue))

    deadline = time.monotonic() + 5.0
    while run_id not in _REGISTRIES and time.monotonic() < deadline:
        await asyncio.sleep(0.005)
    await task
    assert run_id not in _REGISTRIES


async def test_served_run_under_ask_profile_denies_promptly() -> None:
    """TASK 4: served runs have no human; Ask degrades to Enforce."""
    dag = compile_pipeline(ask_pipeline(), profile=REVIEW)
    runner = PipelineRunner(
        "run-served-ask",
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
        profile=REVIEW,
        served=True,
    )
    queue: asyncio.Queue[Any] = asyncio.Queue()

    started = time.monotonic()
    await runner.run(queue)  # must NOT hang waiting for a person
    elapsed = time.monotonic() - started

    assert elapsed < APPROVAL_TIMEOUT_SECONDS
    assert runner.decision_sink is not None
    degraded = [
        d
        for d in runner.decision_sink.for_run("run-served-ask")
        if "[Ask degraded to Enforce]" in d.reason
    ]
    assert degraded, "the degrade must be visible in the decision record"

    events = []
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=5)
        events.append(event)
        if event is None:
            break
    assert isinstance(events[-2], WsRunErrorEvent)


async def test_no_profile_bound_fails_closed() -> None:
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        AccessPolicy(providers=["openai"]),
    )
    with pytest.raises(AccessDeniedError):
        await ModelExecutor().execute(ctx)


# ---------------------------------------------------------------------------
# TASK 5 — deployment profile snapshots + migrations
# ---------------------------------------------------------------------------


def test_deployment_snapshot_survives_active_change(tmp_path: Path) -> None:
    db = tmp_path / "snap.db"
    state_manager = StateManager(db)
    store = DeploymentStore(db)

    set_active_profile_name(state_manager, "review")
    deployment = Deployment(
        id="d1",
        name="snapshotted",
        pipeline={},
        key_hash="hash",
        chat_input_node="in",
        chat_output_node="out",
        created_at=int(time.time() * 1000),
        profile_name=get_active_profile_name(state_manager),
    )
    store.create(deployment)

    # The user switches the desktop's active profile afterwards...
    set_active_profile_name(state_manager, "locked")

    reloaded = store.get("d1")
    assert reloaded is not None
    assert reloaded.profile_name == "review"
    # ...and the deployment still resolves to ITS OWN snapshot.
    assert load_profile(reloaded.profile_name, state_manager) == load_profile(
        "review", state_manager
    )


def test_preexisting_database_and_deployment_row_load(tmp_path: Path) -> None:
    """A database from before Gov-2 opens cleanly; old rows default safely."""
    db = tmp_path / "pre-gov2.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE deployments (
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
    conn.execute(
        "INSERT INTO deployments VALUES "
        "('dep-old','old','{}','hash',0,60,'in','out',1234,0,0,NULL)"
    )
    conn.commit()
    conn.close()

    store = DeploymentStore(db)
    row = store.get("dep-old")
    assert row is not None
    # Rows predating the column behave exactly as they did pre-profiles:
    assert row.profile_name == "locked"

    state_manager = StateManager(db)
    assert state_manager.get_setting("active_governance_profile") is None
    assert get_active_profile_name(state_manager) == "locked"
    assert load_profile("locked", state_manager) is not None


# ---------------------------------------------------------------------------
# TASK 6 — governance HTTP API
# ---------------------------------------------------------------------------


async def _governance_app(tmp_path: Path) -> tuple[Any, StateManager]:
    from fastapi import FastAPI

    app = FastAPI(title="test")
    state_manager = StateManager(tmp_path / "gov-api.db")
    from komvos.governance.api import create_governance_router

    def noop_token() -> str:
        return "dev"


    app.include_router(
        create_governance_router(
            verify_token_dep=noop_token, get_state_manager_fn=lambda: state_manager
        )
    )
    return app, state_manager


@pytest.fixture
async def gov_client(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, StateManager]]:
    app, state_manager = await _governance_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://t")
    yield client, state_manager
    await client.aclose()


CUSTOM_PROFILE = {
    "name": "my-profile",
    "postures": {
        "providers": "audit",
        "egress": "ask",
        "spend": "enforce",
        "retention": "enforce",
    },
    "retention": "metadata",
}


async def test_profiles_crud_and_active_flow(
    gov_client: tuple[httpx.AsyncClient, StateManager],
) -> None:
    client, _sm = gov_client

    listed = (await client.get("/governance/profiles", headers=AUTH)).json()
    assert {p["profile"]["name"] for p in listed["profiles"]} >= {
        "explore",
        "review",
        "locked",
    }
    assert listed["active_name"] == "locked"

    created = await client.post(
        "/governance/profiles", json=CUSTOM_PROFILE, headers=AUTH
    )
    assert created.status_code == 201, created.text

    duplicate = await client.post(
        "/governance/profiles", json=CUSTOM_PROFILE, headers=AUTH
    )
    assert duplicate.status_code == 409
    builtin = await client.post(
        "/governance/profiles",
        json={**CUSTOM_PROFILE, "name": "review"},
        headers=AUTH,
    )
    assert builtin.status_code == 409
    invalid = await client.post(
        "/governance/profiles",
        json={
            **CUSTOM_PROFILE,
            "name": "invalid-profile",
            # Missing domains: a profile must bind all four.
            "postures": {"providers": "ask"},
        },
        headers=AUTH,
    )
    assert invalid.status_code == 422

    updated = await client.put(
        "/governance/profiles/my-profile",
        json={
            "postures": {
                "providers": "enforce",
                "egress": "enforce",
                "spend": "enforce",
                "retention": "enforce",
            }
        },
        headers=AUTH,
    )
    assert updated.status_code == 200, updated.text

    read_one = await client.get("/governance/profiles/my-profile", headers=AUTH)
    assert read_one.json()["profile"]["postures"]["providers"] == "enforce"

    active_switched = await client.put(
        "/governance/active", json={"name": "my-profile"}, headers=AUTH
    )
    assert active_switched.status_code == 200, active_switched.text
    active_read = await client.get("/governance/active", headers=AUTH)
    assert active_read.json()["name"] == "my-profile"

    delete_active = await client.delete("/governance/profiles/my-profile", headers=AUTH)
    assert delete_active.status_code == 409

    switch_back = await client.put(
        "/governance/active", json={"name": "locked"}, headers=AUTH
    )
    assert switch_back.status_code == 200
    deleted = await client.delete("/governance/profiles/my-profile", headers=AUTH)
    assert deleted.status_code == 204

    delete_builtin = await client.delete("/governance/profiles/review", headers=AUTH)
    assert delete_builtin.status_code == 403
    update_builtin = await client.put(
        "/governance/profiles/explore",
        json={"postures": CUSTOM_PROFILE["postures"]},
        headers=AUTH,
    )
    assert update_builtin.status_code == 403
    unknown_active = await client.put(
        "/governance/active", json={"name": "does-not-exist"}, headers=AUTH
    )
    assert unknown_active.status_code == 404


async def test_answer_endpoint_resolves_pending_approval(
    gov_client: tuple[httpx.AsyncClient, StateManager],
) -> None:
    client, _sm = gov_client

    resolved = resolve_policy(AccessPolicy(providers=["openai"]), REVIEW).policy
    ctx = model_ctx(
        "summarize",
        "mock:m",
        MockEndpoint(id="mock:m"),
        resolved,
        pipeline_policy=AccessPolicy(providers=["openai"]),
    )

    sink = InMemoryDecisionSink()
    with run_context(sink, "run-http-answer", profile=REVIEW) as governance:
        task = asyncio.create_task(ModelExecutor().execute(ctx))
        pending = await wait_for_pending(governance)
        approval_id = pending[0].approval_id

        answered = await client.post(
            f"/governance/approvals/{approval_id}/answer",
            json={"answer": "allow_once"},
            headers=AUTH,
        )
        assert answered.status_code == 200
        assert answered.json()["node_id"] == "summarize"
        assert answered.json()["run_id"] == "run-http-answer"
        outputs = await task
        assert outputs["out"]

        already_done = await client.post(
            f"/governance/approvals/{approval_id}/answer",
            json={"answer": "deny"},
            headers=AUTH,
        )
        assert already_done.status_code == 404

    unknown = await client.post(
        "/governance/approvals/nope/answer",
        json={"answer": "deny"},
        headers=AUTH,
    )
    assert unknown.status_code == 404


async def test_answer_endpoint_rejects_bad_answer(
    gov_client: tuple[httpx.AsyncClient, StateManager],
) -> None:
    client, _sm = gov_client
    bad = await client.post(
        "/governance/approvals/x/answer",
        json={"answer": "shrug"},
        headers=AUTH,
    )
    assert bad.status_code == 422


async def test_http_answer_wakes_a_real_run(
    gov_client: tuple[httpx.AsyncClient, StateManager],
) -> None:
    """End-to-end: the HTTP answer resumes a suspended canvas-style run."""
    from komvos.governance.sinks import InMemoryDecisionSink
    from komvos.scheduler.engine import Scheduler

    client, _sm = gov_client
    dag = compile_pipeline(ungoverned_model_pipeline(), profile=REVIEW)
    # Make the model node pipeline-denied so it triggers Ask:
    dag.pipeline_policies["bot"] = AccessPolicy(providers=["openai"])

    events: list[Any] = []

    async def capture(event: Any) -> None:
        events.append(event)

    scheduler = Scheduler(
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
        event_callback=capture,
    )
    sink = InMemoryDecisionSink()
    with run_context(sink, "run-e2e", profile=REVIEW) as governance:
        task = asyncio.create_task(scheduler.run({"in": {"prompt": "hello"}}))
        pending = await wait_for_pending(governance)
        response = await client.post(
            f"/governance/approvals/{pending[0].approval_id}/answer",
            json={"answer": "deny"},
            headers=AUTH,
        )
        assert response.status_code == 200
        with pytest.raises(AccessDeniedError):
            await task


# ---------------------------------------------------------------------------
# TASK 7 — the G1 drift guard
# ---------------------------------------------------------------------------


def test_provider_default_hosts_match_cloud_endpoint_defaults() -> None:
    """
    PROVIDER_DEFAULT_HOSTS must agree with the base URLs CloudEndpoint.apply
    per provider. The comparison derives cloud.py's literals from its SOURCE
    rather than restating them a third time: if someone edits a URL there
    without updating egress.py (or vice versa) this fails.
    """
    from komvos.endpoints import cloud as cloud_module
    from komvos.governance.egress import PROVIDER_DEFAULT_HOSTS, url_host

    source = Path(cloud_module.__file__).read_text(encoding="utf-8")
    declared: dict[str, str] = {}
    for match in re.finditer(
        r"(?:el)?if self\.provider == \"(\w+)\":\s*\n\s*base_url = \"([^\"]+)\"",
        source,
    ):
        declared[match.group(1)] = match.group(2)

    # Every explicit literal in cloud.generate is accounted for...
    assert set(declared) == {"groq", "openrouter", "zhipu", "nvidia"}
    for provider, url in declared.items():
        assert url_host(url) is not None
        assert url_host(url) == PROVIDER_DEFAULT_HOSTS[provider], (
            f"{provider}: cloud.py uses {url} but egress checks "
            f"{PROVIDER_DEFAULT_HOSTS[provider]}"
        )
    # ...and nothing extra drifted into the table.
    assert {"groq", "openrouter", "zhipu", "nvidia"} <= set(PROVIDER_DEFAULT_HOSTS)


def test_import_guard_decision_outcomes() -> None:
    """TIMEOUT exists beside allow/deny and differs from DENIED."""
    assert DecisionOutcome.TIMEOUT is not DecisionOutcome.DENIED


async def test_real_app_mounts_the_governance_router(client: Any) -> None:
    """openapi.json is dev-mode-gated at import time, so check the routes."""
    from komvos.api.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/governance/profiles" in paths
    assert "/governance/active" in paths
    assert "/governance/approvals/{approval_id}/answer" in paths
