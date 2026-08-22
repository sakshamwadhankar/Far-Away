"""
backend/komvos/governance/sinks.py

Where decisions go. Sinks compose: a run records into its in-memory sink
for in-process querying, and — when a StateManager is available — into the
SQLite decision log so history survives a restart, and onto the run's event
queue so the UI sees governance happen live.

Persistence is a property of the sink, not of the enforcement points:
`record` stays async, and the SQLite write runs via asyncio.to_thread for
the same reason every trace write does (sqlite3 is blocking; on the loop it
stalls the WebSocket pump).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from komvos.governance.decisions import GovernanceDecision

if TYPE_CHECKING:
    from collections.abc import Sequence

    from komvos.scheduler.events import WsGovernanceDecisionEvent

logger = logging.getLogger(__name__)


@runtime_checkable
class DecisionSink(Protocol):
    """
    Receives governance decisions.

    `record` is a coroutine by design, even though the first implementation
    appended to a list: the Ask posture suspends a running pipeline at the
    decision point to ask a human for approval, then resumes it. A synchronous
    sink would have forced a rewrite of every call site; an async one makes
    suspension a property of the sink, not a migration.
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


def decision_to_row(decision: GovernanceDecision) -> dict[str, Any]:
    """
    Flatten one decision into the columns StateManager.save_governance_decision
    persists. The full effective-policy snapshot travels as JSON so a stored
    line can be read without replaying compilation.
    """
    return {
        "decision_id": uuid.uuid4().hex,
        "run_id": decision.run_id,
        "node_id": decision.node_id,
        "domain": decision.domain.value,
        "capability": decision.capability,
        "outcome": decision.outcome.value,
        "origin": decision.origin.value,
        "reason": decision.reason,
        "governed_by_json": (
            "[" + ", ".join(f'"{n}"' for n in decision.governed_by) + "]"
        ),
        "policy_json": decision.effective_policy.model_dump_json(),
        "when_utc": decision.when.isoformat(),
        "when_ms": int(decision.when.timestamp() * 1000),
    }


class SqliteDecisionSink:
    """
    Persists decisions through StateManager, off the event loop.

    Governance logging must never be able to break the pipeline it is
    watching: a failed write is logged and dropped, never raised into the
    enforcement path. (A lost audit line beats a dead run.)
    """

    def __init__(self, state_manager: Any) -> None:
        self._state_manager = state_manager

    async def record(self, decision: GovernanceDecision) -> None:
        try:
            await asyncio.to_thread(
                self._state_manager.save_governance_decision,
                **decision_to_row(decision),
            )
        except Exception:  # noqa: BLE001 — see docstring: never kill enforcement
            logger.exception(
                "Failed to persist governance decision for run %s", decision.run_id
            )


class QueueDecisionSink:
    """
    Publishes each decision onto a run's WsEvent queue as a typed event, so
    the desktop UI sees governance happening in real time rather than only
    in history. Decisions are bounded by enforcement points (a handful per
    node), not by tokens, so this does not need the token stream's buffering
    discipline on the producer side; the client still buffers before render.
    """

    def __init__(self, queue: asyncio.Queue) -> None:  # type: ignore[type-arg]
        self._queue = queue

    async def record(self, decision: GovernanceDecision) -> None:
        # Deferred import keeps scheduler out of governance's import graph
        # at module load; events.py itself depends only on pydantic.
        from komvos.scheduler.events import WsGovernanceDecisionEvent

        event: WsGovernanceDecisionEvent = WsGovernanceDecisionEvent(
            run_id=decision.run_id,
            node_id=decision.node_id,
            domain=decision.domain.value,
            capability=decision.capability,
            outcome=decision.outcome.value,
            origin=decision.origin.value,
            reason=decision.reason,
        )
        await self._queue.put(event)


class CompositeDecisionSink:
    """Fans each decision out to several sinks, in construction order."""

    def __init__(self, sinks: Sequence[DecisionSink]) -> None:
        self._sinks = tuple(sinks)

    async def record(self, decision: GovernanceDecision) -> None:
        for sink in self._sinks:
            await sink.record(decision)
