"""
backend/komvos/governance/context.py

Run-scoped reachability for everything governance needs below the runner.

The problem: permission checks happen deep inside endpoint calls, but the
things that know the run identity — decision sink, active profile, whether
this run is served, the approval registry — live at the top. Threading all of
that through every executor and endpoint signature would touch every call
site — and every FUTURE call site, forever.

So the PipelineRunner binds ONE RunGovernance object for the duration of a
run, exactly the way the existing event callback is injected once at the top
and reaches executors without each caller passing it down. Code below the
runner asks this module for the current state; with nothing bound (bare-
Scheduler tests, non-run paths), recording is a no-op and Ask fails closed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from komvos.compiler.models import AccessPolicy
from komvos.governance.approvals import ApprovalRegistry, registry_for, remove_registry
from komvos.governance.decisions import (
    DecisionOrigin,
    DecisionOutcome,
    GovernanceDecision,
    GovernanceDomain,
)
from komvos.governance.sinks import DecisionSink

if TYPE_CHECKING:
    from komvos.governance.profiles import GovernanceProfile


@dataclass
class RunGovernance:
    """Everything governance needs for one run, bound at its start."""

    run_id: str
    sink: DecisionSink | None = None
    profile: GovernanceProfile | None = None
    served: bool = False
    approvals: ApprovalRegistry = field(init=False)
    """
    Per-run approval registry. Pending approvals are process-local by
    design: they do not survive a restart, and the whole registry is
    dropped when the run ends.
    """

    def __post_init__(self) -> None:
        # Registered in the module-level per-run table so the HTTP answering
        # endpoint can find this run's pending approvals; unbind_run_context
        # removes it when the run ends.
        self.approvals = registry_for(self.run_id)


_gov_cv: ContextVar[RunGovernance | None] = ContextVar(
    "komvos_governance_run", default=None
)


def bind_run_context(governance: RunGovernance) -> Token[RunGovernance | None]:
    """Bind the run's governance state; returns an opaque reset handle."""
    return _gov_cv.set(governance)


def unbind_run_context(token: Token[RunGovernance | None]) -> None:
    """
    Undo one bind_run_context() and drop the run's approval registry, so an
    ended run cannot leak pending approvals.
    """
    gov = _gov_cv.get()
    if gov is not None:
        remove_registry(gov.run_id)
    _gov_cv.reset(token)


@contextmanager
def run_context(
    sink: DecisionSink | None,
    run_id: str,
    *,
    profile: GovernanceProfile | None = None,
    served: bool = False,
) -> Iterator[RunGovernance]:
    """
    Bind a RunGovernance for a `with:` block. G1 signature
    `run_context(sink, run_id)` keeps working unchanged.
    """
    governance = RunGovernance(run_id=run_id, sink=sink, profile=profile, served=served)
    token = bind_run_context(governance)
    try:
        yield governance
    finally:
        unbind_run_context(token)


def current_governance() -> RunGovernance | None:
    """The bound run's governance state, or None outside a governed run."""
    return _gov_cv.get()


def current_sink() -> DecisionSink | None:
    gov = _gov_cv.get()
    return gov.sink if gov is not None else None


def current_run_id() -> str:
    gov = _gov_cv.get()
    return gov.run_id if gov is not None else ""


async def record_decision(
    *,
    domain: GovernanceDomain,
    capability: str,
    outcome: DecisionOutcome,
    reason: str,
    node_id: str,
    effective_policy: AccessPolicy,
    governed_by: tuple[str, ...] = (),
    origin: DecisionOrigin = DecisionOrigin.PIPELINE_POLICY,
) -> GovernanceDecision | None:
    """
    Build a GovernanceDecision and hand it to the current sink.

    Returns the decision even when no sink is bound (so callers can assert on
    it in tests); returns None only if construction itself is skipped. Never
    raises into the enforcement path: governance logging must not be able to
    break the pipeline it is watching.
    """
    decision = GovernanceDecision(
        run_id=current_run_id(),
        node_id=node_id,
        domain=domain,
        capability=capability,
        outcome=outcome,
        reason=reason,
        governed_by=governed_by,
        effective_policy=effective_policy,
        origin=origin,
    )
    sink = current_sink()
    if sink is not None:
        await sink.record(decision)
    return decision
