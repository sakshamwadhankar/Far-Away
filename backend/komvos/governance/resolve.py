"""
backend/komvos/governance/resolve.py

Pure resolution: pipeline policy + profile -> the policy actually in force,
with the ORIGIN of every value.

The profile is authoritative and works in both directions:

  - LOOSEN (Audit/Ask postures): capabilities the pipeline withheld become
    available, because the posture itself will handle the difference — Audit
    permits and records; Ask asks a human. Resolution must loosen so the
    compiler's capability check agrees with what the run will actually do;
    otherwise a profile-permitted pipeline would fail to compile.
  - TIGHTEN (Enforce limits): the profile's spend cap can lower the
    pipeline's own ceiling.

Origins are not bookkeeping — they are the point. A capability granted only
by the profile MUST be attributable to the profile in every decision about
it: a grant the pipeline never asked for has to be visible in the log.

Enforcement at runtime therefore runs against BOTH views: the executor's
binary checks use the resolved policy (so nothing denies that resolution
already decided to allow), and when a check against the PIPELINE-only
policy would have failed, the posture decides what happens next. Under
Enforce the two policies are identical, which is exactly why compile-time
and run-time cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from komvos.compiler.models import ENDPOINT_KINDS, AccessPolicy
from komvos.governance.decisions import DecisionOrigin, GovernanceDomain
from komvos.governance.profiles import GovernanceProfile, Posture


@dataclass(frozen=True)
class ResolvedPolicy:
    """One node's policy in force, plus who is responsible for each value."""

    policy: AccessPolicy
    origins: dict[str, DecisionOrigin] = field(default_factory=dict)
    """
    Capability key -> origin. Keys mirror capability strings used in
    decisions ("provider:<kind>", "egress", "max_cost_usd",
    "allow_local_models"). Values not present default to PIPELINE_POLICY.
    """

    def origin_of(self, key: str) -> DecisionOrigin:
        return self.origins.get(key, DecisionOrigin.PIPELINE_POLICY)


def _min_optional(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def resolve_policy(
    pipeline_policy: AccessPolicy,
    profile: GovernanceProfile | None,
) -> ResolvedPolicy:
    """
    Combine one node's pipeline-derived effective policy with the active
    profile. Pure: no I/O, no clock, no context.

    With `profile=None` the result is byte-identical to the input policy and
    every origin is PIPELINE_POLICY — compile() without a profile behaves
    exactly as it did before profiles existed.
    """
    if profile is None:
        return ResolvedPolicy(policy=pipeline_policy)

    origins: dict[str, DecisionOrigin] = {}
    resolved = pipeline_policy.model_copy(deep=True)

    # -- providers and local models ---------------------------------------
    # Ask/Audit open the whole provider catalog at the policy level: the
    # capability check passes, and the posture layer handles interactively
    # what the pipeline would have denied.
    if profile.postures[GovernanceDomain.PROVIDERS] in (Posture.ASK, Posture.AUDIT):
        for kind in ENDPOINT_KINDS:
            if kind not in resolved.providers:
                resolved.providers.append(kind)
                origins[f"provider:{kind}"] = DecisionOrigin.PROFILE
        if not resolved.allow_local_models:
            resolved.allow_local_models = True
            origins["allow_local_models"] = DecisionOrigin.PROFILE

    # -- egress ------------------------------------------------------------
    # Ask/Audit open egress at the POLICY level: the host check passes, and
    # the posture layer handles what the pipeline would have denied. An
    # empty allowed_domains list means "no domain restriction" (the reading
    # intersect() depends on), which is exactly what the loosened policy
    # should carry while the interactive layer governs hosts.
    if profile.postures[GovernanceDomain.EGRESS] in (Posture.ASK, Posture.AUDIT):
        if not resolved.allow_network:
            resolved.allow_network = True
            origins["allow_network"] = DecisionOrigin.PROFILE
        if resolved.allowed_domains:
            resolved.allowed_domains = []
            origins["allowed_domains"] = DecisionOrigin.PROFILE

    # -- desktop -----------------------------------------------------------
    # Ask/Audit open desktop control at the POLICY level: the compiler check
    # passes, and the posture layer handles interactively what the pipeline
    # would have denied.
    if profile.postures[GovernanceDomain.DESKTOP] in (Posture.ASK, Posture.AUDIT):
        if not resolved.allow_desktop:
            resolved.allow_desktop = True
            origins["allow_desktop"] = DecisionOrigin.PROFILE
        if resolved.allowed_applications:
            resolved.allowed_applications = []
            origins["allowed_applications"] = DecisionOrigin.PROFILE
        if not resolved.allow_destructive:
            resolved.allow_destructive = True
            origins["allow_destructive"] = DecisionOrigin.PROFILE

    # -- spend ---------------------------------------------------------------
    ceiling = pipeline_policy.max_cost_usd
    posture = profile.postures[GovernanceDomain.SPEND]
    if posture is Posture.ENFORCE:
        new_ceiling = _min_optional(ceiling, profile.spend_cap_usd)
    elif posture is Posture.ASK:
        # The ceiling becomes an ask-trigger, not a wall: breach asks a human.
        # The profile threshold joins whatever the pipeline already says.
        new_ceiling = _min_optional(ceiling, profile.spend_ask_threshold_usd)
    else:  # AUDIT — record, no cap.
        new_ceiling = None

    if new_ceiling != ceiling:
        # Every change here originates from the profile: resolution only ever
        # tightens (Enforce/Ask) or removes a cap (Audit).
        origins["max_cost_usd"] = DecisionOrigin.PROFILE
    resolved.max_cost_usd = new_ceiling

    return ResolvedPolicy(policy=resolved, origins=origins)


def spend_origin(
    pipeline_ceiling: float | None, resolved_ceiling: float | None
) -> DecisionOrigin:
    """Who owns an operative spend ceiling at decision time."""
    if resolved_ceiling is None:
        return DecisionOrigin.PIPELINE_POLICY  # nothing constrains spend
    if pipeline_ceiling is None or resolved_ceiling < pipeline_ceiling:
        return DecisionOrigin.PROFILE
    if resolved_ceiling > pipeline_ceiling:  # pragma: no cover — never loosened here
        return DecisionOrigin.PIPELINE_POLICY
    return DecisionOrigin.PIPELINE_AND_PROFILE
