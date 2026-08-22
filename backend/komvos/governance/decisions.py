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
    TIMEOUT = "timeout"
    """The Ask posture's approval window expired: failed closed, but
    distinguishable from a human saying no."""


class DecisionOrigin(StrEnum):
    """
    WHICH source produced the outcome.

    A decision's outcome can come from the pipeline's own access policy,
    from the user's active profile (which may LOOSEN as well as tighten),
    from both agreeing — or from a HUMAN answering an approval prompt.
    A grant the pipeline never made must be visible in the log as coming
    from the profile, not silently mixed in; and "the profile auto-granted
    this" is a different event from "a person approved this", so human
    origins are recorded separately, with the exact answer they gave:
    allow-once and allow-for-run age very differently after the run ends.
    """

    PIPELINE_POLICY = "pipeline_policy"
    PROFILE = "profile"
    PIPELINE_AND_PROFILE = "pipeline_and_profile"

    HUMAN_ALLOW_ONCE = "human_allow_once"
    """A person answered an approval with allow-once: this one action proceeds."""

    HUMAN_ALLOW_FOR_RUN = "human_allow_for_run"
    """A person granted this exact capability for the remainder of the run."""

    HUMAN_DENY = "human_deny"
    """A person said no — distinct from policy denying and from timing out."""


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
