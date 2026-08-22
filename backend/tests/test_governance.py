"""
backend/tests/test_governance.py

Gov-1 — governance decisions, served-mode access enforcement, egress
control, and per-scope cost ceilings.

Covers:
  * the decoy bypass: a pipeline whose only access node governs a dead-end
    branch must be REJECTED in served mode, and must still compile locally
  * egress: denied when allow_network is false (call never leaves the
    machine), domain allow/deny with dot-boundary matching, and a remote
    Ollama base URL being subject to policy
  * per-scope cost ceilings applying independently per branch
  * decisions emitted on ALLOW, not only on DENY

No test here talks to a real provider: outbound transports are booby-trapped
or faked, following the pattern of test_access_policy.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from komvos.compiler.dag import compile as compile_pipeline
from komvos.compiler.models import AccessPolicy
from komvos.compiler.validation import PipelineValidationErrors
from komvos.endpoints.base import AccessDeniedError, GenRequest, Message
from komvos.endpoints.cloud import CloudEndpoint
from komvos.endpoints.mock import MockEndpoint
from komvos.endpoints.ollama import OllamaEndpoint
from komvos.executors.base import ExecutorContext
from komvos.executors.model import ModelExecutor
from komvos.governance import (
    DecisionOutcome,
    GovernanceDomain,
    InMemoryDecisionSink,
    endpoint_egress_host,
    host_allowed,
    run_context,
)
from komvos.governance.context import record_decision
from komvos.governance.decisions import DecisionOrigin, GovernanceDecision
from komvos.scheduler.engine import EndpointRegistry, SchedulerEvent

PIPELINE_ID = "00000000-0000-4000-a000-00000000d001"


def decoy_pipeline() -> dict[str, Any]:
    """
    The TASK 2 reproduction: input -> model(cloud) -> output, plus a separate
    access node granting NO providers, connected through its scope port to a
    transform node nothing else consumes. The model node is ungoverned.
    """
    return {
        "schema_version": "2.1",
        "id": PIPELINE_ID,
        "name": "Decoy bypass",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "summarize",
                "type": "model",
                "endpoint_ref": "openai:model",
                "inputs": [{"name": "prompt", "type": "text"}],
                "outputs": [{"name": "out", "type": "text"}],
            },
            {"id": "out", "type": "output", "inputs": [{"name": "r", "type": "text"}]},
            {
                "id": "decoy-transform",
                "type": "transform",
                "inputs": [{"name": "x", "type": "text"}],
                "outputs": [{"name": "y", "type": "text"}],
            },
            {
                "id": "gate-nothing",
                "type": "access",
                "config": {"access_policy": {"providers": []}},
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "summarize.prompt"},
            {"from": "summarize.out", "to": "out.r"},
            {"from": "in.prompt", "to": "decoy-transform.x"},
            {"from": "gate-nothing.scope", "to": "decoy-transform.x"},
        ],
        "endpoints": {"openai:model": {"kind": "openai", "model": "gpt-4o-mini"}},
    }


def governed_pipeline(provider: str = "mock") -> dict[str, Any]:
    """input -> model -> output with the access node actually covering the model."""
    return {
        "schema_version": "2.1",
        "id": PIPELINE_ID,
        "name": "Governed pipeline",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "summarize",
                "type": "model",
                "endpoint_ref": f"{provider}:model",
                "inputs": [{"name": "prompt", "type": "text"}],
                "outputs": [{"name": "out", "type": "text"}],
            },
            {"id": "out", "type": "output", "inputs": [{"name": "r", "type": "text"}]},
            {
                "id": "gate-1",
                "type": "access",
                "config": {"access_policy": {"providers": [provider]}},
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "summarize.prompt"},
            {"from": "summarize.out", "to": "out.r"},
            {"from": "gate-1.scope", "to": "summarize.prompt"},
        ],
        "endpoints": {f"{provider}:model": {"kind": provider, "model": "m"}},
    }


def two_scope_pipeline() -> dict[str, Any]:
    """
    Two independent branches with different spend ceilings: branch_a capped
    at 0.0005 USD, branch_b at 10 USD. Each gate scopes ONLY its own branch.
    """
    return {
        "schema_version": "2.1",
        "id": PIPELINE_ID,
        "name": "Two-scope ceilings",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "branch_a",
                "type": "model",
                "endpoint_ref": "mock:model",
                "inputs": [{"name": "prompt", "type": "text"}],
                "outputs": [{"name": "out", "type": "text"}],
            },
            {
                "id": "branch_b",
                "type": "model",
                "endpoint_ref": "mock:model",
                "inputs": [{"name": "prompt", "type": "text"}],
                "outputs": [{"name": "out", "type": "text"}],
            },
            {
                "id": "gate-a",
                "type": "access",
                "config": {
                    "access_policy": {"providers": ["mock"], "max_cost_usd": 0.0005}
                },
            },
            {
                "id": "gate-b",
                "type": "access",
                "config": {
                    "access_policy": {"providers": ["mock"], "max_cost_usd": 10.0}
                },
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "branch_a.prompt"},
            {"from": "in.prompt", "to": "branch_b.prompt"},
            {"from": "gate-a.scope", "to": "branch_a.prompt"},
            {"from": "gate-b.scope", "to": "branch_b.prompt"},
        ],
        "endpoints": {"mock:model": {"kind": "mock", "model": "m"}},
    }


def model_ctx(
    node_id: str,
    endpoint_ref: str,
    endpoint: Any,
    policy: AccessPolicy,
    governed_by: tuple[str, ...] = (),
) -> ExecutorContext:
    node_doc = {
        "id": node_id,
        "type": "model",
        "endpoint_ref": endpoint_ref,
        "inputs": [{"name": "prompt", "type": "text"}],
        "outputs": [{"name": "out", "type": "text"}],
    }
    from komvos.compiler.models import Node

    return ExecutorContext(
        node=Node.model_validate(node_doc),
        inputs={"prompt": "hello"},
        registry=EndpointRegistry({endpoint_ref: endpoint}),
        emit_fn=lambda _e: None,
        policy=policy,
        policy_sources=governed_by,
    )


# ---------------------------------------------------------------------------
# TASK 2 — served-mode governance
# ---------------------------------------------------------------------------


def test_decoy_pipeline_rejected_in_served_mode() -> None:
    """
    A pipeline whose only access node governs an unrelated dead-end branch
    must not compile for serving while its model nodes run ungoverned.
    """
    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(decoy_pipeline(), mode="served")

    message = "\n".join(excinfo.value.errors)
    assert "[Access Required]" in message
    # Names every offending node...
    assert "'summarize'" in message
    # ...and not the governed dead-end branch.
    assert "decoy-transform" not in message
    # Says what to do about it.
    assert "scope" in message


def test_correctly_governed_pipeline_still_compiles_served() -> None:
    dag = compile_pipeline(governed_pipeline(), mode="served")
    assert dag.policy_sources["summarize"] == ("gate-1",)


def test_local_mode_unaffected_by_served_governance() -> None:
    """The same decoy, and any gate-less pipeline, still compile on the canvas."""
    dag = compile_pipeline(decoy_pipeline(), mode="local")
    assert dag.pipeline.id == PIPELINE_ID
    assert dag.policy_sources["summarize"] == ()

    ungated = governed_pipeline()
    ungated["nodes"] = [n for n in ungated["nodes"] if n["type"] != "access"]
    ungated["edges"] = [e for e in ungated["edges"] if "gate" not in e["from"]]
    dag = compile_pipeline(ungated, mode="local")
    assert dag.policy_sources["summarize"] == ()


def test_every_model_node_must_be_governed_not_just_one() -> None:
    """Two ungoverned model nodes produce two errors, each named."""
    doc = governed_pipeline()
    # Point the only gate at the output node, leaving BOTH models ungoverned.
    doc["edges"] = [e for e in doc["edges"] if e["from"] != "gate-1.scope"]
    doc["edges"].append({"from": "gate-1.scope", "to": "out.r"})
    doc["nodes"].append(
        {
            "id": "second",
            "type": "model",
            "endpoint_ref": "mock:model",
            "inputs": [{"name": "prompt", "type": "text"}],
            "outputs": [{"name": "out", "type": "text"}],
        }
    )

    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(doc, mode="served")
    message = "\n".join(excinfo.value.errors)
    assert "'summarize'" in message and "'second'" in message
    assert len(excinfo.value.errors) == 2


# ---------------------------------------------------------------------------
# Host matching semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "domains", "expected"),
    [
        ("api.example.com", ["example.com"], True),
        ("example.com", ["example.com"], True),
        ("a.b.example.com", ["example.com"], True),
        ("notexample.com", ["example.com"], False),
        ("evilexample.com", ["example.com"], False),
        ("api.example.com", ["api.example.com"], True),
        ("other.example.com", ["api.example.com"], False),
        ("API.Example.COM", ["example.com"], True),
        ("api.example.com:8443"[:0] or "api.example.com", ["other.com"], False),
    ],
)
def test_host_matching_is_dot_boundary_not_substring(
    host: str, domains: list[str], expected: bool
) -> None:
    assert host_allowed(host, domains) is expected


def test_empty_allowed_domains_means_unrestricted() -> None:
    """The reading intersect() depends on: empty list restricts nothing."""
    assert host_allowed("anything.example.net", []) is True


def test_endpoint_egress_host_resolution() -> None:
    default = CloudEndpoint(provider="anthropic", model_name="claude")
    assert endpoint_egress_host(default) == "api.anthropic.com"

    custom = CloudEndpoint(
        provider="openai_compatible", model_name="m", base_url="https://llm.corp/v1"
    )
    assert endpoint_egress_host(custom) == "llm.corp"

    tunnel = OllamaEndpoint(id="ollama:qwen", base_url="https://mytunnel.dev/v1")
    assert endpoint_egress_host(tunnel) == "mytunnel.dev"

    local = OllamaEndpoint(id="ollama:qwen")
    assert endpoint_egress_host(local) == "127.0.0.1"

    assert endpoint_egress_host(MockEndpoint()) is None


# ---------------------------------------------------------------------------
# Egress enforcement through the executor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_egress_denied_when_allow_network_false_and_call_never_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    allow_network=false denies a cloud destination before any socket, key
    read, or client construction happens.
    """
    import keyring

    calls: list[str] = []

    def _explode(name: str) -> Any:
        def _fail(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            raise AssertionError(f"denied node reached {name}")

        return _fail

    monkeypatch.setattr(keyring, "get_password", _explode("keyring.get_password"))
    monkeypatch.setattr(httpx.AsyncClient, "send", _explode("httpx.send"))
    monkeypatch.setattr(httpx.AsyncClient, "stream", _explode("httpx.stream"))

    sink = InMemoryDecisionSink()
    endpoint = CloudEndpoint(provider="anthropic", model_name="claude")
    ctx = model_ctx(
        "summarize",
        "anthropic:model",
        endpoint,
        # Provider granted, network denied: the denial must come from egress.
        AccessPolicy(providers=["anthropic"], allow_network=False),
        governed_by=("gate-1",),
    )

    with run_context(sink, "run-egress-deny"), pytest.raises(
        AccessDeniedError
    ) as excinfo:
        await ModelExecutor().execute(ctx)

    assert excinfo.value.capability == "egress:api.anthropic.com"
    assert calls == [], f"denied node performed outbound work: {calls}"

    decisions = sink.for_run("run-egress-deny")
    assert [
        (d.domain, d.outcome, d.capability) for d in decisions
    ] == [
        (GovernanceDomain.PROVIDERS, DecisionOutcome.ALLOWED, "provider:anthropic"),
        (
            GovernanceDomain.EGRESS,
            DecisionOutcome.DENIED,
            "egress:api.anthropic.com",
        ),
    ]
    assert decisions[-1].governed_by == ("gate-1",)


@pytest.mark.asyncio
async def test_host_outside_allowed_domains_denied_inside_permitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Full executor path: a host inside allowed_domains runs end-to-end (over a
    faked transport); a sibling host outside the list is denied.
    """
    from types import SimpleNamespace

    import openai

    class _FakeCompletions:
        async def create(self, **_kwargs: Any) -> Any:
            async def _chunks() -> Any:
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))]
                )

            return _chunks()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, **_kwargs: Any) -> None:
            self.chat = _FakeChat()

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *_a: "test-key")

    endpoint = CloudEndpoint(
        provider="openai_compatible",
        model_name="m",
        base_url="https://api.tenant.example.com/v1",
    )
    permitted = AccessPolicy(
        providers=["openai_compatible"],
        allow_network=True,
        allowed_domains=["example.com"],
    )

    sink = InMemoryDecisionSink()
    with run_context(sink, "run-egress-allow"):
        outputs = await ModelExecutor().execute(
            model_ctx("summarize", "oai:m", endpoint, permitted)
        )
    assert outputs["out"] == "hello"
    egress_decisions = [
        d
        for d in sink.for_run("run-egress-allow")
        if d.domain is GovernanceDomain.EGRESS
    ]
    assert (
        egress_decisions
        and egress_decisions[-1].outcome is DecisionOutcome.ALLOWED
        and "no domain restriction" not in egress_decisions[-1].reason
    )

    outside = AccessPolicy(
        providers=["openai_compatible"],
        allow_network=True,
        allowed_domains=["other.com"],
    )
    with pytest.raises(AccessDeniedError) as excinfo:
        await ModelExecutor().execute(
            model_ctx("summarize", "oai:m", endpoint, outside)
        )
    assert "egress:api.tenant.example.com" in excinfo.value.capability


@pytest.mark.asyncio
async def test_remote_ollama_base_url_is_subject_to_egress_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    resolve_ollama_base can hand back a remote tunnel URL. That traffic is
    real egress: denied when the policy withholds allow_network, even though
    local models themselves are granted.
    """
    exploded: list[str] = []

    def _explode(*_args: Any, **_kwargs: Any) -> Any:
        exploded.append("httpx.stream")
        raise AssertionError("denied node reached httpx.AsyncClient.stream")

    monkeypatch.setattr(httpx.AsyncClient, "stream", _explode)

    endpoint = OllamaEndpoint(id="ollama:qwen", base_url="https://mytunnel.dev/v1")
    policy = AccessPolicy(providers=["ollama"], allow_local_models=True)

    with pytest.raises(AccessDeniedError) as excinfo:
        await ModelExecutor().execute(
            model_ctx("local-node", "ollama:qwen", endpoint, policy)
        )

    assert excinfo.value.capability == "egress:mytunnel.dev"
    assert exploded == []


@pytest.mark.asyncio
async def test_loopback_ollama_is_exempt_from_allow_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Local models are governed by allow_local_models, not by egress: a
    loopback Ollama URL runs even when allow_network is false.
    """

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

        async def aiter_lines(self) -> Any:
            yield 'data: {"choices":[{"delta":{"content":"hi"}}]}'
            yield "data: [DONE]"

    class _FakeStreamCM:
        async def __aenter__(self) -> _FakeResponse:
            return _FakeResponse()

        async def __aexit__(self, *exc: Any) -> bool:
            return False

    class _FakeAsyncClient:
        def __init__(self, **_kw: Any) -> None:
            self.started = True

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        def stream(self, *_a: Any, **_k: Any) -> _FakeStreamCM:
            return _FakeStreamCM()

        # OllamaEndpoint builds a request and sends it with stream=True so the
        # retry layer can replay it; mirror that surface here.
        def build_request(self, *_a: Any, **_k: Any) -> object:
            return object()

        async def send(self, *_a: Any, **_k: Any) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    endpoint = OllamaEndpoint(id="ollama:qwen")
    policy = AccessPolicy(providers=["ollama"], allow_local_models=True)

    outputs = await ModelExecutor().execute(
        model_ctx("local-node", "ollama:qwen", endpoint, policy)
    )
    assert outputs["out"] == "hi"


# ---------------------------------------------------------------------------
# Per-scope cost ceilings
# ---------------------------------------------------------------------------


def test_two_scopes_keep_their_own_ceilings_after_compile() -> None:
    dag = compile_pipeline(two_scope_pipeline())
    assert dag.effective_policies["branch_a"].max_cost_usd == 0.0005
    assert dag.effective_policies["branch_b"].max_cost_usd == 10.0


@pytest.mark.asyncio
async def test_per_scope_cost_ceilings_apply_independently() -> None:
    """
    branch_a (ceiling 0.0005, mock costs 0.001/call) is denied before its
    first call; branch_b (ceiling 10) completes. The run-wide minimum would
    have capped BOTH branches at 0.0005.
    """
    dag = compile_pipeline(two_scope_pipeline())
    endpoint = MockEndpoint(id="mock:model", predefined_text="ok")

    sink = InMemoryDecisionSink()
    with run_context(sink, "run-scopes"):
        with pytest.raises(AccessDeniedError) as excinfo:
            await ModelExecutor().execute(
                model_ctx(
                    "branch_a",
                    "mock:model",
                    endpoint,
                    dag.effective_policies["branch_a"],
                    governed_by=("gate-a",),
                )
            )
        outputs = await ModelExecutor().execute(
            model_ctx(
                "branch_b",
                "mock:model",
                endpoint,
                dag.effective_policies["branch_b"],
                governed_by=("gate-b",),
            )
        )

    assert excinfo.value.capability == "max_cost_usd"
    assert outputs["out"] == "ok"

    decisions = sink.for_run("run-scopes")
    a_denials = [
        d
        for d in decisions
        if d.node_id == "branch_a"
        and d.domain is GovernanceDomain.SPEND
        and d.outcome is DecisionOutcome.DENIED
    ]
    b_allows = [
        d
        for d in decisions
        if d.node_id == "branch_b"
        and d.domain is GovernanceDomain.SPEND
        and d.outcome is DecisionOutcome.ALLOWED
    ]
    assert len(a_denials) == 1
    assert b_allows


# ---------------------------------------------------------------------------
# Decisions exist on ALLOW, not just DENY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decisions_are_emitted_on_allow() -> None:
    """A fully successful run records provider and spend ALLOWED decisions."""
    doc = governed_pipeline()
    doc["endpoints"]["mock:model"] = {"kind": "mock", "model": "m"}
    dag = compile_pipeline(doc)

    captured: list[SchedulerEvent] = []

    async def capture(event: SchedulerEvent) -> None:
        captured.append(event)

    scheduler_events = capture
    from komvos.scheduler.engine import Scheduler

    scheduler = Scheduler(
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
        event_callback=scheduler_events,
    )

    sink = InMemoryDecisionSink()
    with run_context(sink, "run-happy"):
        result = await scheduler.run({"in": {"prompt": "hello"}})

    assert result.completed
    decisions = sink.for_run("run-happy")
    outcomes = {(d.domain, d.outcome) for d in decisions}
    assert (GovernanceDomain.PROVIDERS, DecisionOutcome.ALLOWED) in outcomes
    assert (GovernanceDomain.SPEND, DecisionOutcome.ALLOWED) in outcomes
    assert all(d.outcome is DecisionOutcome.ALLOWED for d in decisions)
    # Attribution travels with the decision.
    providers_decision = next(
        d for d in decisions if d.domain is GovernanceDomain.PROVIDERS
    )
    assert providers_decision.governed_by == ("gate-1",)
    assert providers_decision.origin is DecisionOrigin.PIPELINE_POLICY
    assert providers_decision.effective_policy.providers == ["mock"]


@pytest.mark.asyncio
async def test_pipeline_runner_binds_a_decision_sink_for_its_run() -> None:
    """The runner wires the sink once; code under it never threads it."""
    from komvos.scheduler.runner import PipelineRunner

    dag = compile_pipeline(governed_pipeline())
    runner = PipelineRunner(
        "run-runner",
        dag,
        EndpointRegistry({"mock:model": MockEndpoint(id="mock:model")}),
    )

    queue: asyncio.Queue[Any] = asyncio.Queue()
    await runner.run(queue)

    assert runner.decision_sink is not None
    decisions = runner.decision_sink.for_run("run-runner")
    assert decisions
    assert any(
        d.domain is GovernanceDomain.PROVIDERS and d.outcome is DecisionOutcome.ALLOWED
        for d in decisions
    )


# ---------------------------------------------------------------------------
# Record mechanics
# ---------------------------------------------------------------------------


def test_decision_record_shape() -> None:
    now = GovernanceDecision(
        run_id="r",
        node_id="n",
        domain=GovernanceDomain.RETENTION,
        capability="retention:x",
        outcome=DecisionOutcome.DENIED,
        reason="because",
        effective_policy=AccessPolicy(),
    )
    assert now.when.tzinfo is not None
    assert now.origin is DecisionOrigin.PIPELINE_POLICY
    assert now.governed_by == ()


@pytest.mark.asyncio
async def test_recording_without_a_bound_run_is_a_no_op() -> None:
    decision = await record_decision(
        domain=GovernanceDomain.EGRESS,
        capability="egress:host",
        outcome=DecisionOutcome.ALLOWED,
        reason="unbound",
        node_id="n",
        effective_policy=AccessPolicy.permissive(),
    )
    assert decision is not None
    assert current_sink_if_any() is None


def current_sink_if_any() -> Any:
    from komvos.governance import current_sink

    return current_sink()


def test_gen_request_import_guard() -> None:
    req = GenRequest(messages=[Message(role="user", content="x")])
    assert req.max_tokens >= 1


def test_asyncio_import_guard() -> None:
    """Keep the asyncio import meaningful for signature parity with siblings."""
    assert callable(asyncio.run)
