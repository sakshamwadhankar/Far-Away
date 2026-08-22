"""
backend/komvos/governance/posture.py

The single place that turns "the pipeline's own policy withheld this" into
an Enforce/Ask/Audit outcome.

Called by enforcement points (today: the model executor) AFTER their binary
check against the PIPELINE-only policy has failed — i.e. exactly when the
active profile's posture gets a say. Records its own GovernanceDecision on
every path, so all call sites emit identical attribution.

Served runs have no human to prompt: Ask degrades to Enforce there, and the
decision says a degrade happened and why — not merely that the action was
denied. An unanswered approval times out and fails closed, recorded with its
own outcome, distinct from a person saying no. Cancellation while suspended
propagates as PipelineCancelled so the node aborts cleanly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from komvos.compiler.models import AccessPolicy
from komvos.governance.approvals import (
    APPROVAL_TIMEOUT_SECONDS,
    ApprovalAnswer,
)
from komvos.governance.context import current_governance, record_decision
from komvos.governance.decisions import (
    DecisionOrigin,
    DecisionOutcome,
    GovernanceDomain,
)
from komvos.governance.profiles import Posture


@dataclass(frozen=True)
class PostureOutcome:
    """What the posture layer decided, and how to talk about it."""

    allowed: bool
    outcome: DecisionOutcome
    origin: DecisionOrigin
    reason: str


def answer_effects(domain: GovernanceDomain, capability: str) -> dict[str, str]:
    """What each possible answer will do — for the pending-approval event."""
    return {
        "allow_once": f"This {domain.value} request ({capability}) proceeds once.",
        "allow_for_run": (
            f"Only this exact {domain.value} capability ({capability}) "
            "proceeds for the remainder of the run; nothing else widens."
        ),
        "deny": f"The node fails with an access denial ({capability}).",
        "timeout": (
            "If unanswered within the timeout the request FAILS CLOSED "
            "(recorded as a timeout, not a denial)."
        ),
    }


async def consult_posture(
    *,
    domain: GovernanceDomain,
    capability: str,
    node_id: str,
    pipeline_reason: str,
    effective_policy: AccessPolicy,
    governed_by: tuple[str, ...] = (),
    cancel_token: Any = None,
    notify: Callable[[Any], Awaitable[None]] | None = None,
    timeout: float = APPROVAL_TIMEOUT_SECONDS,
) -> PostureOutcome:
    """
    Apply the active profile's posture to a pipeline-policy denial.

    Exactly one GovernanceDecision is recorded here per invocation. Raises
    PipelineCancelled when cancellation fires while suspended on an approval.
    """
    governance = current_governance()
    if governance is None or governance.profile is None:
        # Fail closed: nothing but the pipeline's own policy is in force,
        # and it just said no.
        await _decide(
            domain=domain,
            capability=capability,
            node_id=node_id,
            outcome=DecisionOutcome.DENIED,
            origin=DecisionOrigin.PIPELINE_POLICY,
            reason=pipeline_reason,
            effective_policy=effective_policy,
            governed_by=governed_by,
        )
        return PostureOutcome(
            False, DecisionOutcome.DENIED, DecisionOrigin.PIPELINE_POLICY,
            pipeline_reason,
        )

    profile = governance.profile
    posture = profile.postures[domain]

    # -- ENFORCE -----------------------------------------------------------
    if posture is Posture.ENFORCE:
        origin = DecisionOrigin.PIPELINE_AND_PROFILE
        reason = (
            f"{pipeline_reason} Profile '{profile.name}' upholds the "
            "pipeline's own policy for this domain."
        )
        await _decide(domain, capability, node_id, DecisionOutcome.DENIED,
                      origin, reason, effective_policy, governed_by)
        return PostureOutcome(False, DecisionOutcome.DENIED, origin, reason)

    # -- AUDIT ---------------------------------------------------------------
    if posture is Posture.AUDIT:
        reason = (
            f"Permitted by profile '{profile.name}' audit posture despite a "
            f"pipeline-policy denial: {pipeline_reason}"
        )
        await _decide(domain, capability, node_id, DecisionOutcome.ALLOWED,
                      DecisionOrigin.PROFILE, reason, effective_policy,
                      governed_by)
        return PostureOutcome(True, DecisionOutcome.ALLOWED,
                              DecisionOrigin.PROFILE, reason)

    # -- ASK ---------------------------------------------------------------

    # A served run has no human at the other end of an HTTP request. Degrade
    # to Enforce rather than block the request waiting for a person, and say
    # that a degrade happened — do not let it read as an ordinary denial.
    if governance.served:
        reason = (
            f"[Ask degraded to Enforce] Served runs have no human to prompt, "
            f"so profile '{profile.name}' could not ask: {pipeline_reason}"
        )
        await _decide(domain, capability, node_id, DecisionOutcome.DENIED,
                      DecisionOrigin.PROFILE, reason, effective_policy,
                      governed_by)
        return PostureOutcome(False, DecisionOutcome.DENIED,
                              DecisionOrigin.PROFILE, reason)

    resolution = await governance.approvals.request(
        node_id=node_id,
        domain=domain,
        capability=capability,
        reason=pipeline_reason,
        cancel_token=cancel_token,
        notify=notify,
        timeout=timeout,
    )

    if resolution.outcome is DecisionOutcome.TIMEOUT:
        reason = resolution.reason
    elif resolution.answer in (ApprovalAnswer.ALLOW_ONCE, ApprovalAnswer.ALLOW_FOR_RUN):
        reason = (
            f"{resolution.reason} The pipeline itself had withheld this: "
            f"{pipeline_reason}"
        )
    else:
        reason = f"{resolution.reason} Pipeline denial was: {pipeline_reason}"

    await _decide(domain, capability, node_id, resolution.outcome,
                  DecisionOrigin.PROFILE, reason, effective_policy, governed_by)
    return PostureOutcome(
        allowed=resolution.outcome is DecisionOutcome.ALLOWED,
        outcome=resolution.outcome,
        origin=DecisionOrigin.PROFILE,
        reason=reason,
    )


async def _decide(
    domain: GovernanceDomain,
    capability: str,
    node_id: str,
    outcome: DecisionOutcome,
    origin: DecisionOrigin,
    reason: str,
    effective_policy: AccessPolicy,
    governed_by: tuple[str, ...],
) -> None:
    await record_decision(
        domain=domain,
        capability=capability,
        outcome=outcome,
        reason=reason,
        node_id=node_id,
        effective_policy=effective_policy,
        governed_by=governed_by,
        origin=origin,
    )
