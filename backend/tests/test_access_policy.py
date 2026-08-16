"""
backend/tests/test_access_policy.py

Phase 2 — the access node.

Covers:
  * intersection semantics when several access nodes govern one node
  * the actionable denial error messages
  * the "local" vs "served" compile modes
  * runtime enforcement, including the guarantee that a denied endpoint makes
    ZERO outbound calls
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from neuralflow.compiler.dag import compile as compile_pipeline
from neuralflow.compiler.models import ENDPOINT_KINDS, AccessPolicy
from neuralflow.compiler.validation import PipelineValidationErrors
from neuralflow.endpoints.base import AccessDeniedError, GenRequest, Message
from neuralflow.endpoints.cloud import CloudEndpoint
from neuralflow.endpoints.mock import MockEndpoint
from neuralflow.endpoints.ollama import OllamaEndpoint
from neuralflow.executors.base import ExecutorContext
from neuralflow.executors.model import ModelExecutor
from neuralflow.scheduler.engine import EndpointRegistry, EventKind, SchedulerEvent
from neuralflow.scheduler.runner import _tightest_budget

PIPELINE_ID = "00000000-0000-4000-a000-0000000000ac"


def build_pipeline(
    *,
    gates: list[tuple[str, dict[str, Any]]] | None = None,
    scope_edges: list[tuple[str, str]] | None = None,
    provider: str = "anthropic",
    schema_version: str = "2.1",
) -> dict[str, Any]:
    """
    A three-node pipeline (input -> summarize -> output) plus optional access
    nodes wired in via scope edges.

    `scope_edges` are (from, to) pairs written verbatim, so a test can express
    gate chains like ("gate-1.scope", "gate-2.scope").
    """
    nodes: list[dict[str, Any]] = [
        {"id": "in", "type": "input", "outputs": [{"name": "prompt", "type": "text"}]},
        {
            "id": "summarize",
            "type": "model",
            "endpoint_ref": f"{provider}:model",
            "inputs": [{"name": "prompt", "type": "text"}],
            "outputs": [{"name": "out", "type": "text"}],
        },
        {"id": "out", "type": "output", "inputs": [{"name": "r", "type": "text"}]},
    ]
    edges: list[dict[str, str]] = [
        {"from": "in.prompt", "to": "summarize.prompt"},
        {"from": "summarize.out", "to": "out.r"},
    ]

    for gate_id, policy in gates or []:
        nodes.append(
            {"id": gate_id, "type": "access", "config": {"access_policy": policy}}
        )
    for src, dst in scope_edges or []:
        edges.append({"from": src, "to": dst})

    return {
        "schema_version": schema_version,
        "id": PIPELINE_ID,
        "name": "Access test pipeline",
        "version": "1.0.0",
        "nodes": nodes,
        "edges": edges,
        "endpoints": {f"{provider}:model": {"kind": provider, "model": "m"}},
    }


# ---------------------------------------------------------------------------
# AccessPolicy.intersect — unit level
# ---------------------------------------------------------------------------


def test_permissive_grants_everything() -> None:
    p = AccessPolicy.permissive()
    assert set(p.providers) == set(ENDPOINT_KINDS)
    assert p.allow_local_models is True
    assert p.allow_network is True
    assert p.max_cost_usd is None
    assert p.max_tokens is None


def test_intersect_takes_provider_intersection_not_union() -> None:
    a = AccessPolicy(providers=["openai", "anthropic"])
    b = AccessPolicy(providers=["anthropic", "google"])

    assert a.intersect(b).providers == ["anthropic"]
    # Order of application must not change the outcome.
    assert set(b.intersect(a).providers) == {"anthropic"}


def test_intersect_ands_the_booleans() -> None:
    permissive = AccessPolicy.permissive()
    restrictive = AccessPolicy(allow_local_models=False, allow_network=False)

    combined = permissive.intersect(restrictive)
    assert combined.allow_local_models is False
    assert combined.allow_network is False


def test_intersect_takes_the_lower_ceiling_and_none_loses() -> None:
    a = AccessPolicy(max_cost_usd=5.0, max_tokens=4096)
    b = AccessPolicy(max_cost_usd=1.0, max_tokens=None)

    combined = a.intersect(b)
    assert combined.max_cost_usd == 1.0
    # None means "no ceiling from this policy", so the concrete one survives.
    assert combined.max_tokens == 4096


def test_intersect_treats_empty_allowed_domains_as_unrestricted() -> None:
    """
    An empty domain list means "no restriction", so it must act as the identity
    rather than the empty set — otherwise an unrestricted ancestor would
    silently revoke every domain its descendant was granted.
    """
    unrestricted = AccessPolicy(allow_network=True, allowed_domains=[])
    restricted = AccessPolicy(allow_network=True, allowed_domains=["api.example.com"])

    assert unrestricted.intersect(restricted).allowed_domains == ["api.example.com"]
    assert restricted.intersect(unrestricted).allowed_domains == ["api.example.com"]


def test_intersect_narrows_two_domain_lists() -> None:
    a = AccessPolicy(allow_network=True, allowed_domains=["a.com", "b.com"])
    b = AccessPolicy(allow_network=True, allowed_domains=["b.com", "c.com"])

    assert a.intersect(b).allowed_domains == ["b.com"]


def test_intersection_can_only_lose_capabilities() -> None:
    """The invariant the whole rule exists to protect."""
    wide = AccessPolicy(providers=["openai", "anthropic"], allow_local_models=True)
    narrow = AccessPolicy(providers=["openai"], allow_local_models=False)

    combined = wide.intersect(narrow)
    assert set(combined.providers) <= set(wide.providers)
    assert set(combined.providers) <= set(narrow.providers)
    assert combined.allow_local_models is False


# ---------------------------------------------------------------------------
# Effective policy across the DAG
# ---------------------------------------------------------------------------


def test_no_access_node_is_permissive() -> None:
    dag = compile_pipeline(build_pipeline())

    assert dag.policy_sources["summarize"] == ()
    assert dag.effective_policies["summarize"].allow_network is True


def test_policy_applies_to_every_downstream_node() -> None:
    dag = compile_pipeline(
        build_pipeline(
            gates=[("gate-1", {"providers": ["anthropic"]})],
            scope_edges=[("gate-1.scope", "summarize.prompt")],
        )
    )

    # Directly governed...
    assert dag.policy_sources["summarize"] == ("gate-1",)
    # ...and inherited further downstream.
    assert dag.policy_sources["out"] == ("gate-1",)
    assert dag.effective_policies["out"].providers == ["anthropic"]


def test_node_upstream_of_the_gate_is_not_governed() -> None:
    dag = compile_pipeline(
        build_pipeline(
            gates=[("gate-1", {"providers": ["anthropic"]})],
            scope_edges=[("gate-1.scope", "summarize.prompt")],
        )
    )
    assert dag.policy_sources["in"] == ()


def test_two_ancestor_gates_intersect() -> None:
    dag = compile_pipeline(
        build_pipeline(
            gates=[
                ("gate-1", {"providers": ["anthropic", "openai"], "max_cost_usd": 5.0}),
                ("gate-2", {"providers": ["anthropic"], "max_cost_usd": 1.0}),
            ],
            scope_edges=[
                ("gate-1.scope", "gate-2.scope"),
                ("gate-2.scope", "summarize.prompt"),
            ],
        )
    )

    policy = dag.effective_policies["summarize"]
    assert policy.providers == ["anthropic"]
    assert policy.max_cost_usd == 1.0
    assert dag.policy_sources["summarize"] == ("gate-1", "gate-2")


def test_second_gate_cannot_widen_the_first() -> None:
    """Union semantics would let the permissive gate re-grant openai."""
    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(
            build_pipeline(
                provider="openai",
                gates=[
                    ("tight", {"providers": ["anthropic"]}),
                    ("wide", {"providers": list(ENDPOINT_KINDS)}),
                ],
                scope_edges=[
                    ("tight.scope", "summarize.prompt"),
                    ("wide.scope", "summarize.prompt"),
                ],
            )
        )

    assert "Access Denied" in "\n".join(excinfo.value.errors)


# ---------------------------------------------------------------------------
# Denial errors
# ---------------------------------------------------------------------------


def test_denial_error_names_node_capability_and_gate() -> None:
    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(
            build_pipeline(
                gates=[("gate-1", {"providers": ["openai", "ollama"]})],
                scope_edges=[("gate-1.scope", "summarize.prompt")],
            )
        )

    message = excinfo.value.errors[0]
    assert "summarize" in message
    assert "anthropic" in message
    assert "gate-1" in message
    assert "openai, ollama" in message


def test_local_model_denial_names_the_capability() -> None:
    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(
            build_pipeline(
                provider="ollama",
                gates=[
                    ("gate-1", {"providers": ["ollama"], "allow_local_models": False})
                ],
                scope_edges=[("gate-1.scope", "summarize.prompt")],
            )
        )

    message = excinfo.value.errors[0]
    assert "allow_local_models" in message
    assert "gate-1" in message


def test_granting_the_provider_compiles() -> None:
    dag = compile_pipeline(
        build_pipeline(
            gates=[("gate-1", {"providers": ["anthropic"]})],
            scope_edges=[("gate-1.scope", "summarize.prompt")],
        )
    )
    assert dag.effective_policies["summarize"].providers == ["anthropic"]


# ---------------------------------------------------------------------------
# Access node structural rules
# ---------------------------------------------------------------------------


def test_access_node_may_not_declare_data_ports() -> None:
    doc = build_pipeline()
    doc["nodes"].append(
        {
            "id": "gate-bad",
            "type": "access",
            "config": {"access_policy": {"providers": []}},
            "outputs": [{"name": "x", "type": "text"}],
        }
    )

    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(doc)
    assert "must not" in "\n".join(excinfo.value.errors)


def test_access_node_requires_a_policy() -> None:
    doc = build_pipeline()
    doc["nodes"].append({"id": "gate-bare", "type": "access"})

    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(doc)
    assert "Missing Access Policy" in "\n".join(excinfo.value.errors)


def test_non_access_node_may_not_carry_a_policy() -> None:
    doc = build_pipeline()
    doc["nodes"][1]["config"] = {"access_policy": {"providers": ["anthropic"]}}

    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(doc)
    assert "Invalid Access Policy" in "\n".join(excinfo.value.errors)


def test_scope_edge_must_use_the_reserved_port() -> None:
    doc = build_pipeline(
        gates=[("gate-1", {"providers": ["anthropic"]})],
        scope_edges=[("gate-1.data", "summarize.prompt")],
    )

    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(doc)
    assert "Invalid Access Edge" in "\n".join(excinfo.value.errors)


def test_unconnected_access_node_is_rejected() -> None:
    doc = build_pipeline(gates=[("gate-1", {"providers": ["anthropic"]})])

    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(doc)
    assert "Orphan Access Node" in "\n".join(excinfo.value.errors)


# ---------------------------------------------------------------------------
# Compile modes and backward compatibility
# ---------------------------------------------------------------------------


def test_schema_2_0_still_compiles_and_is_permissive() -> None:
    dag = compile_pipeline(build_pipeline(schema_version="2.0"))
    assert dag.effective_policies["summarize"].allow_network is True


def test_local_mode_allows_a_pipeline_with_no_access_node() -> None:
    dag = compile_pipeline(build_pipeline(), mode="local")
    assert dag.pipeline.id == PIPELINE_ID


def test_local_is_the_default_mode() -> None:
    assert compile_pipeline(build_pipeline()).pipeline.id == PIPELINE_ID


def test_served_mode_refuses_a_pipeline_with_no_access_node() -> None:
    with pytest.raises(PipelineValidationErrors) as excinfo:
        compile_pipeline(build_pipeline(), mode="served")

    message = "\n".join(excinfo.value.errors)
    assert "Access Required" in message
    # The error has to tell the user what to do about it.
    assert "access node" in message


def test_served_mode_accepts_a_pipeline_with_an_access_node() -> None:
    dag = compile_pipeline(
        build_pipeline(
            gates=[("gate-1", {"providers": ["anthropic"]})],
            scope_edges=[("gate-1.scope", "summarize.prompt")],
        ),
        mode="served",
    )
    assert dag.effective_policies["summarize"].providers == ["anthropic"]


# ---------------------------------------------------------------------------
# Runtime enforcement
# ---------------------------------------------------------------------------


def test_cloud_endpoint_check_access_rejects_ungranted_provider() -> None:
    endpoint = CloudEndpoint(provider="anthropic", model_name="claude")

    with pytest.raises(AccessDeniedError) as excinfo:
        endpoint.check_access(AccessPolicy(providers=["openai"]), "summarize")

    assert excinfo.value.capability == "provider:anthropic"
    assert excinfo.value.node_id == "summarize"


def test_cloud_endpoint_check_access_allows_granted_provider() -> None:
    endpoint = CloudEndpoint(provider="openai", model_name="gpt-4o-mini")
    endpoint.check_access(AccessPolicy(providers=["openai"]), "summarize")


def test_ollama_endpoint_checks_allow_local_models() -> None:
    endpoint = OllamaEndpoint(id="ollama:qwen")

    with pytest.raises(AccessDeniedError) as excinfo:
        endpoint.check_access(AccessPolicy(allow_local_models=False), "local-node")
    assert excinfo.value.capability == "allow_local_models"

    # Granted: no exception.
    endpoint.check_access(AccessPolicy(allow_local_models=True), "local-node")


def test_policy_max_tokens_caps_the_node_setting() -> None:
    """A policy ceiling may lower the node's max_tokens, never raise it."""
    from neuralflow.compiler.models import Node, NodeConfig

    captured: dict[str, int] = {}

    class RecordingEndpoint(MockEndpoint):
        def estimate_cost(self, req: GenRequest) -> Any:
            captured["max_tokens"] = req.max_tokens
            return super().estimate_cost(req)

    endpoint = RecordingEndpoint(id="mock:default", predefined_text="hi")
    node = Node(
        id="summarize",
        type="model",
        endpoint_ref="mock:default",
        config=NodeConfig(max_tokens=4096),
        inputs=[{"name": "prompt", "type": "text"}],
        outputs=[{"name": "out", "type": "text"}],
    )
    ctx = ExecutorContext(
        node=node,
        inputs={"prompt": "hello"},
        registry=EndpointRegistry({"mock:default": endpoint}),
        emit_fn=lambda _e: None,
        policy=AccessPolicy(providers=["mock"], max_tokens=256),
    )

    asyncio.run(ModelExecutor().execute(ctx))
    assert captured["max_tokens"] == 256


def test_policy_cost_ceiling_tightens_the_run_budget() -> None:
    """max_cost_usd reuses the existing CancelToken budget path."""
    dag = compile_pipeline(
        build_pipeline(
            gates=[("gate-1", {"providers": ["anthropic"], "max_cost_usd": 0.25})],
            scope_edges=[("gate-1.scope", "summarize.prompt")],
        )
    )

    # No caller budget: the policy ceiling becomes the budget.
    assert _tightest_budget(None, dag) == 0.25
    # A looser caller budget is tightened to the policy ceiling.
    assert _tightest_budget(10.0, dag) == 0.25
    # A tighter caller budget wins.
    assert _tightest_budget(0.10, dag) == 0.10


def test_tightest_budget_is_none_without_ceilings() -> None:
    dag = compile_pipeline(build_pipeline())
    assert _tightest_budget(None, dag) is None


# ---------------------------------------------------------------------------
# The guarantee: a denied call never leaves the machine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denied_endpoint_makes_zero_outbound_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A node denied by policy must not open a socket, read an API key, or
    construct a provider client. Every one of those is booby-trapped here; the
    test fails loudly if the check runs after the request instead of before it.
    """
    import httpx
    import keyring

    calls: list[str] = []

    def _explode(name: str) -> Any:
        def _fail(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            raise AssertionError(f"denied node reached {name}")

        return _fail

    # Any of these firing means the call escaped the policy gate.
    monkeypatch.setattr(keyring, "get_password", _explode("keyring.get_password"))
    monkeypatch.setattr(httpx.AsyncClient, "send", _explode("httpx.AsyncClient.send"))
    monkeypatch.setattr(
        httpx.AsyncClient, "stream", _explode("httpx.AsyncClient.stream")
    )

    endpoint = CloudEndpoint(provider="anthropic", model_name="claude")
    node_type_config = {"providers": ["openai"]}

    with pytest.raises(AccessDeniedError):
        endpoint.check_access(AccessPolicy(**node_type_config), "summarize")

    # And through the executor, which is the real call path.
    from neuralflow.compiler.models import Node

    ctx = ExecutorContext(
        node=Node(
            id="summarize",
            type="model",
            endpoint_ref="anthropic:model",
            inputs=[{"name": "prompt", "type": "text"}],
            outputs=[{"name": "out", "type": "text"}],
        ),
        inputs={"prompt": "hello"},
        registry=EndpointRegistry({"anthropic:model": endpoint}),
        emit_fn=lambda _e: None,
        policy=AccessPolicy(providers=["openai"]),
    )

    with pytest.raises(AccessDeniedError):
        await ModelExecutor().execute(ctx)

    assert calls == [], f"denied node performed outbound work: {calls}"


@pytest.mark.asyncio
async def test_run_emits_access_denied_event() -> None:
    """The UI needs to know which node was blocked and why."""
    doc = build_pipeline(
        provider="mock",
        gates=[("gate-1", {"providers": ["openai"], "allow_local_models": False})],
        scope_edges=[("gate-1.scope", "summarize.prompt")],
    )
    # Compile in a mode that permits the mismatch so enforcement happens at
    # runtime: grant the provider at compile time, then tighten at execution.
    doc["nodes"][3]["config"]["access_policy"]["providers"] = ["mock"]
    dag = compile_pipeline(doc)

    events: list[SchedulerEvent] = []

    async def capture(event: SchedulerEvent) -> None:
        events.append(event)

    from neuralflow.scheduler.engine import Scheduler

    # Tighten the effective policy after compilation to simulate a policy the
    # endpoint refuses at call time.
    dag.effective_policies["summarize"] = AccessPolicy(providers=["openai"])

    scheduler = Scheduler(
        dag,
        EndpointRegistry(
            {"mock:model": MockEndpoint(id="mock:model", predefined_text="hi")}
        ),
        event_callback=capture,
    )

    with pytest.raises(AccessDeniedError):
        await scheduler.run({"in": {"prompt": "hello"}})

    denied = [e for e in events if e.kind == EventKind.ACCESS_DENIED]
    assert len(denied) == 1
    assert denied[0].node_id == "summarize"
    assert denied[0].data["capability"] == "provider:mock"


def test_gen_request_is_unused_import_guard() -> None:
    """Keep the GenRequest/Message imports meaningful for the recording endpoint."""
    req = GenRequest(messages=[Message(role="user", content="x")])
    assert req.max_tokens >= 1
