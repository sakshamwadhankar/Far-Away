"""
backend/komvos/governance/sinks.py

Where decisions go. A sink receives decisions; the in-memory implementation
is the only one on purpose — persistence (and the schema that would come with
it) is designed in a later phase, and a schema chosen now would be wrong.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from komvos.governance.decisions import GovernanceDecision


@runtime_checkable
class DecisionSink(Protocol):
    """
    Receives governance decisions.

    `record` is a coroutine by design, even though today's only implementation
    appends to a list: a later phase suspends a running pipeline at the
    decision point to ask a human for approval, then resumes it. A synchronous
    sink would force a rewrite of every call site the day that lands.
    """

    async def record(self, decision: GovernanceDecision) -> None:
        """Store (or forward) one decision."""
        ...


class InMemoryDecisionSink:
    """
    Keeps every decision for the process lifetime, queryable per run.

    Appends happen on a single event loop, so a plain list is safe; consumers
    read `decisions` / `for_run` after (not during) concurrent mutation unless
    they accept whatever prefix is committed.
    """

    def __init__(self) -> None:
        self._decisions: list[GovernanceDecision] = []

    async def record(self, decision: GovernanceDecision) -> None:
        self._decisions.append(decision)

    @property
    def decisions(self) -> list[GovernanceDecision]:
        """Every decision recorded so far, in emission order."""
        return list(self._decisions)

    def for_run(self, run_id: str) -> list[GovernanceDecision]:
        """Decisions for one run, in emission order."""
        return [d for d in self._decisions if d.run_id == run_id]
