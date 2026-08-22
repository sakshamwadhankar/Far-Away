"""
backend/komvos/governance/approvals.py

Ask-posture plumbing: a genuine mid-run suspension waiting for a human.

A pending approval is an asyncio.Future awaited by the suspended node. The
event loop is never blocked: every other node in the same parallel tier keeps
running while one node waits, and the WebSocket pump keeps pumping.

Answers:
  allow_once      — this capability, this node, this once.
  allow_for_run   — same domain AND same capability only, for the remainder
                    of the run. Never widens to anything else.
  deny            — the node fails with AccessDeniedError.

Fail-closed guarantees (also stated in the package README):
  - An unanswered approval times out and is recorded as its own outcome,
    distinct from a human denial.
  - Pending approvals live only in process memory. They do NOT survive a
    process restart; a restart leaves nothing to answer and any run that was
    waiting is gone with it.
  - The registry is strictly per-run and removed when the run ends — on the
    success path, on error, and on cancellation alike.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from komvos.governance.decisions import DecisionOutcome, GovernanceDomain

logger = logging.getLogger(__name__)

#: How long a pending approval waits for a human before failing closed.
#: Also importable from komvos.serve.routes, where it sits beside
#: SERVED_WALL_CLOCK_BUDGET_SECONDS so both ceilings are discovered together.
APPROVAL_TIMEOUT_SECONDS = 300.0


class ApprovalAnswer(StrEnum):
    """The answers a human can give."""

    ALLOW_ONCE = "allow_once"
    ALLOW_FOR_RUN = "allow_for_run"
    DENY = "deny"


class PendingApproval(BaseModel):
    """One question currently waiting for a human."""

    approval_id: str
    run_id: str
    node_id: str
    domain: GovernanceDomain
    capability: str
    reason: str
    asked_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000))


class ApprovalResolution(BaseModel):
    """What came back from asking."""

    outcome: DecisionOutcome
    answer: ApprovalAnswer | None = None
    reason: str


class AnswerRejectedError(Exception):
    """The approval being answered no longer exists or was already settled."""


class ApprovalRegistry:
    """
    Pending approvals and run-scoped grants for ONE run.

    `request()` awaits an asyncio.Future — a real suspension. Cancellation of
    the awaiting task propagates straight out of the await and the pending
    entry is removed in a finally block, so nothing leaks.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._pending: dict[str, asyncio.Future[ApprovalAnswer]] = {}
        self._questions: dict[str, PendingApproval] = {}
        self._allow_for_run: set[tuple[GovernanceDomain, str]] = set()

    # -- asking ----------------------------------------------------------

    def has_grant(self, domain: GovernanceDomain, capability: str) -> bool:
        return (domain, capability) in self._allow_for_run

    async def request(
        self,
        *,
        node_id: str,
        domain: GovernanceDomain,
        capability: str,
        reason: str,
        timeout: float = APPROVAL_TIMEOUT_SECONDS,
        cancel_token: Any = None,
        notify: Callable[[PendingApproval], Awaitable[None]] | None = None,
    ) -> ApprovalResolution:
        """
        Ask a human and wait.

        Returns immediately with an ALLOWED resolution if the operator
        already granted this exact domain+capability for the remainder of
        the run. Otherwise suspends until answered, denied, timed out, or
        cancelled.

        When `cancel_token` is given (a scheduler CancelToken), the
        suspension wakes on cancellation too and raises PipelineCancelled,
        so a kill switch or wall-clock expiry aborts a waiting node instead
        of leaving it parked until the timeout.

        `notify` is awaited once the question is registered and still
        unanswered — the point where a UI event announcing the pending
        approval should be emitted.
        """
        if self.has_grant(domain, capability):
            return ApprovalResolution(
                outcome=DecisionOutcome.ALLOWED,
                answer=ApprovalAnswer.ALLOW_FOR_RUN,
                reason=(
                    f"Allowed for the remainder of this run by an earlier "
                    f"operator answer ({domain.value}:{capability})."
                ),
            )

        approval_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[ApprovalAnswer] = loop.create_future()
        question = PendingApproval(
            approval_id=approval_id,
            run_id=self.run_id,
            node_id=node_id,
            domain=domain,
            capability=capability,
            reason=reason,
        )
        self._pending[approval_id] = fut
        self._questions[approval_id] = question

        try:
            if notify is not None:
                try:
                    await notify(question)
                except Exception:  # noqa: BLE001 — notification must never kill enforcement
                    logger.exception(
                        "Failed to emit approval_pending event for %s",
                        approval_id,
                    )
            answer_task = asyncio.ensure_future(fut)
            cancel_task = (
                asyncio.ensure_future(cancel_token.wait_until_cancelled())
                if cancel_token is not None
                else None
            )
            tasks: set[asyncio.Future[Any]] = {answer_task}
            if cancel_task is not None:
                tasks.add(cancel_task)
            try:
                done, unfinished = await asyncio.wait(
                    tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                for task in unfinished:
                    task.cancel()
                # Retrieve results/exceptions so nothing is left unretrieved.
                for task in unfinished:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

            if answer_task in done:
                if answer_task.cancelled():
                    raise asyncio.CancelledError
                answer = answer_task.result()
            elif cancel_task is not None and cancel_task in done:
                from komvos.scheduler.engine import PipelineCancelled

                raise PipelineCancelled(cancel_token.reason)
            else:
                return ApprovalResolution(
                    outcome=DecisionOutcome.TIMEOUT,
                    reason=(
                        f"No answer within {timeout:.0f}s; failed closed "
                        "(approval timeout is not a denial by a person)."
                    ),
                )
        finally:
            self._pending.pop(approval_id, None)
            self._questions.pop(approval_id, None)

        if answer is ApprovalAnswer.DENY:
            return ApprovalResolution(
                outcome=DecisionOutcome.DENIED,
                answer=answer,
                reason="Denied by operator.",
            )
        if answer is ApprovalAnswer.ALLOW_FOR_RUN:
            self._allow_for_run.add((domain, capability))
        return ApprovalResolution(
            outcome=DecisionOutcome.ALLOWED,
            answer=answer,
            reason=(
                "Allowed once by operator."
                if answer is ApprovalAnswer.ALLOW_ONCE
                else "Allowed for the remainder of this run by operator."
            ),
        )

    def pending(self) -> list[PendingApproval]:
        """Questions still waiting, oldest first."""
        return sorted(self._questions.values(), key=lambda q: q.asked_at_ms)

    def get_question(self, approval_id: str) -> PendingApproval | None:
        return self._questions.get(approval_id)

    def answer(self, approval_id: str, answer: ApprovalAnswer) -> None:
        """
        Deliver a human's answer. Raises AnswerRejectedError if the approval
        is gone (already answered, timed out, or the run ended).
        """
        fut = self._pending.get(approval_id)
        if fut is None or fut.done():
            raise AnswerRejectedError(
                f"Approval '{approval_id}' is no longer pending. It may "
                "already have been answered, timed out, or its run ended."
            )
        fut.set_result(answer)

    def close(self) -> None:
        """
        Tear down the registry: settle anything still pending as denied so
        no future is left unretrieved, then drop all state. Called when the
        run ends, on every path.
        """
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result(ApprovalAnswer.DENY)
        self._pending.clear()
        self._questions.clear()
        self._allow_for_run.clear()


#: Per-run registries for the lifetime of each run, keyed by run id. The
#: HTTP answering endpoint finds approvals here; PipelineRunner removes the
#: entry in its finally block so an ended run cannot leak one.
_REGISTRIES: dict[str, ApprovalRegistry] = {}


def registry_for(run_id: str) -> ApprovalRegistry:
    existing = _REGISTRIES.get(run_id)
    if existing is None:
        existing = ApprovalRegistry(run_id)
        _REGISTRIES[run_id] = existing
    return existing


def remove_registry(run_id: str) -> None:
    registry = _REGISTRIES.pop(run_id, None)
    if registry is not None:
        registry.close()


def find_approval(approval_id: str) -> tuple[ApprovalRegistry, PendingApproval] | None:
    """Locate a pending approval across all live runs."""
    for registry in _REGISTRIES.values():
        question = registry.get_question(approval_id)
        if question is not None:
            return registry, question
    return None
