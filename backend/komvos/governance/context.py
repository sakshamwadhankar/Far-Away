"""
backend/komvos/governance/context.py

Run-scoped reachability for decision sinks.

The problem: a permission check happens deep inside an endpoint call, but the
thing that knows the run identity is the PipelineRunner at the top. Threading
a sink parameter through every executor and endpoint signature would touch
every call site — and every FUTURE call site, forever.

So the runner binds (sink, run_id) for the duration of a run, exactly the way
the existing event callback is injected once at the top and reaches executors
without each caller passing it down. Code below the runner asks the context
for the current sink; with nothing bound, recording is a no-op, which keeps
bare-Scheduler tests and non-run paths working unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NamedTuple

from komvos.compiler.models import AccessPolicy
from komvos.governance.decisions import (
    DecisionOrigin,
    DecisionOutcome,
    GovernanceDecision,
    GovernanceDomain,
)
from komvos.governance.sinks import DecisionSink

_sink_cv: ContextVar[DecisionSink | None] = ContextVar(
    "komvos_governance_sink", default=None
)
_run_cv: ContextVar[str] = ContextVar("komvos_governance_run", default="")


class _BoundRun(NamedTuple):
    """Tokens needed to undo one bind_run_context()."""

    sink_token: object
    run_token: object


def bind_run_context(sink: DecisionSink, run_id: str) -> _BoundRun:
    """
    Bind the decision sink and run id for the current context until unbound.

    Returns an opaque handle; pass it to unbind_run_context() in a finally
    block. Prefer the bind_run_context() context manager below.
    """
    return _BoundRun(_sink_cv.set(sink), _run_cv.set(run_id))


def unbind_run_context(bound: _BoundRun) -> None:
    """Undo one bind_run_context(); safe to call exactly once per binding."""
    _sink_cv.reset(bound.sink_token)  # type: ignore[arg-type]
    _run_cv.reset(bound.run_token)  # type: ignore[arg-type]


@contextmanager
def run_context(sink: DecisionSink, run_id: str) -> Iterator[None]:
    """Context-manager form of bind/unbind, for `with:` blocks."""
    bound = bind_run_context(sink, run_id)
    try:
        yield
    finally:
        unbind_run_context(bound)


def current_sink() -> DecisionSink | None:
    """The sink bound for this run, or None outside a governed run."""
    return _sink_cv.get()


def current_run_id() -> str:
    """The run id bound for this context; empty string when none."""
    return _run_cv.get()


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
