"""
backend/komvos/governance/decisions.py

The GovernanceDecision record — the single artifact every permit/deny point
in the system produces.

A decision is a fact, not a message: it records what was requested, what the
effective policy was, who constrained it, and what was decided, so that a run
can be audited after the fact without replaying it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from komvos.compiler.models import AccessPolicy


class GovernanceDomain(StrEnum):
    """
    The closed set of capability domains governance applies to.

    Every decision names exactly one domain. Adding a domain is a deliberate
    act (it means a new class of capability is now governed), not a string
    that drifted in via a call site.
    """

    PROVIDERS = "providers"
    """Which model providers may be called."""

    EGRESS = "egress"
    """Which hosts outbound network traffic may reach."""

    SPEND = "spend"
    """How much money a scope is permitted to commit."""

    RETENTION = "retention"
    """What may be kept, and for how long. Declared but not yet enforced:
    the schema carries no retention field yet."""


class DecisionOutcome(StrEnum):
    """What was decided. ALLOWED is recorded as deliberately as DENIED."""

    ALLOWED = "allow"
    DENIED = "deny"


class DecisionOrigin(StrEnum):
    """
    WHICH source produced the outcome.

    Today every constraint comes from the pipeline's own access policy. A
    later phase introduces a user profile that can override a pipeline's
    policy in either direction — including grants the pipeline never asked
    for. When that happens those decisions must be visible in the log as
    coming from somewhere else, not silently mixed in as if the pipeline had
    granted them. The field exists now so call sites never have to change.
    """

    PIPELINE_POLICY = "pipeline_policy"


class GovernanceDecision(BaseModel):
    """
    One record of one permission decision.

    Emitted on ALLOW and DENY alike: a log that only records denials looks
    empty during a successful demo, which is exactly when someone will be
    looking at it.
    """

    when: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC instant the decision was made.",
    )
    run_id: str = Field(description="Pipeline run the decision belongs to.")
    node_id: str = Field(description="Node making the request.")
    domain: GovernanceDomain = Field(description="Which capability class.")
    capability: str = Field(
        description=(
            "The specific thing requested, e.g. 'provider:openai' or "
            "'egress:api.anthropic.com'."
        )
    )
    outcome: DecisionOutcome = Field(description="Allowed or denied.")
    reason: str = Field(
        description="Human-readable explanation of why this outcome happened."
    )
    governed_by: tuple[str, ...] = Field(
        default=(),
        description=(
            "IDs of the access nodes whose policies produced the effective "
            "policy. Empty means the node was ungoverned (permissive)."
        ),
    )
    effective_policy: AccessPolicy = Field(
        description="Snapshot of the policy values that actually applied."
    )
    origin: DecisionOrigin = Field(
        default=DecisionOrigin.PIPELINE_POLICY,
        description="Which source produced the constraint (see DecisionOrigin).",
    )
