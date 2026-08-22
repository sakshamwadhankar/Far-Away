"""
backend/komvos/governance/profiles.py

The user's dial on top of the pipeline's own access policy.

A POSTURE says what happens when an action is NOT permitted by the
pipeline's access nodes:

  ENFORCE — deny and halt, exactly as the pre-profile system did.
  ASK     — suspend the run at that node, ask a human, act on the answer.
  AUDIT   — permit the action anyway, recording that the posture allowed it.

A PROFILE binds a posture to each governance domain plus the concrete limits
a domain needs. The profile is authoritative: it can LOOSEN what a pipeline
granted (that is the point of EXPLORE) as well as tighten it. Resolution —
how a profile and a pipeline policy combine into the policy actually in
force — lives in resolve.py; persistence in state/sqlite.py.

Retention is modelled here so the shape is right, but NOT enforced yet:
no code path produces retention decisions in this phase.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator

from komvos.governance.decisions import GovernanceDomain

logger = logging.getLogger(__name__)


class Posture(StrEnum):
    """What happens when the pipeline's own policy withholds an action."""

    ENFORCE = "enforce"
    ASK = "ask"
    AUDIT = "audit"


class RetentionMode(StrEnum):
    """
    How much of this run's content may be kept after it ends.

    Modelled now so profiles have the right shape; enforcement is a later
    phase and nothing reads this value today.
    """

    FULL = "full"
    METADATA = "metadata"


class GovernanceProfile(BaseModel):
    """A named binding of posture-per-domain plus concrete domain limits."""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=64)
    built_in: bool = False
    postures: dict[GovernanceDomain, Posture]
    spend_cap_usd: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Hard USD ceiling imposed under the Enforce posture. None means "
            "no profile cap beyond whatever the pipeline's policies say."
        ),
    )
    spend_ask_threshold_usd: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Under the Ask posture, projected spend above this asks a "
            "human; at or below it proceeds. None means only the pipeline's "
            "own ceiling triggers a question."
        ),
    )
    retention: RetentionMode = RetentionMode.FULL

    @model_validator(mode="after")
    def _postures_cover_every_domain(self) -> GovernanceProfile:
        missing = [d for d in GovernanceDomain if d not in self.postures]
        if missing:
            names = ", ".join(sorted(m.value for m in missing))
            raise ValueError(
                f"[Invalid Profile] Profile '{self.name}' has no posture for: "
                f"{names}. A profile must bind all four domains."
            )
        extra = [d for d in self.postures if d not in GovernanceDomain]
        if extra:  # pragma: no cover — dict[GovernanceDomain, ...] types this out
            raise ValueError(
                f"[Invalid Profile] Unknown domains in postures: {extra}."
            )
        return self


def _retention_posture(spend_posture: Posture) -> Posture:
    """
    Retention follows the strictness of spend until enforcement exists.

    Placeholder for a later phase: nothing produces retention decisions yet,
    so this only keeps the shape coherent (relaxed profiles record fully;
    LOCKED would hold content back).
    """
    return spend_posture


def _profile(
    name: str,
    *,
    providers: Posture,
    egress: Posture,
    spend: Posture,
    spend_cap_usd: float | None = None,
    spend_ask_threshold_usd: float | None = None,
    retention: RetentionMode,
) -> GovernanceProfile:
    return GovernanceProfile(
        name=name,
        built_in=True,
        postures={
            GovernanceDomain.PROVIDERS: providers,
            GovernanceDomain.EGRESS: egress,
            GovernanceDomain.SPEND: spend,
            GovernanceDomain.RETENTION: _retention_posture(spend),
        },
        spend_cap_usd=spend_cap_usd,
        spend_ask_threshold_usd=spend_ask_threshold_usd,
        retention=retention,
    )


EXPLORE = _profile(
    "explore",
    providers=Posture.AUDIT,
    egress=Posture.AUDIT,
    spend=Posture.AUDIT,
    retention=RetentionMode.FULL,
)

REVIEW = _profile(
    "review",
    providers=Posture.ASK,
    egress=Posture.ASK,
    spend=Posture.ASK,
    spend_ask_threshold_usd=1.0,
    retention=RetentionMode.FULL,
)

LOCKED = _profile(
    "locked",
    providers=Posture.ENFORCE,
    egress=Posture.ENFORCE,
    spend=Posture.ENFORCE,
    retention=RetentionMode.METADATA,
)

BUILT_IN_PROFILES: dict[str, GovernanceProfile] = {
    p.name: p for p in (EXPLORE, REVIEW, LOCKED)
}

#: Default for databases (and deployment rows) from before profiles existed,
#: and for any missing/corrupt active-profile setting. LOCKED keeps behaviour
#: identical to the pre-profile system — the pipeline's own policy decides —
#: which is both the strictest sensible fallback and the only one that can
#: never silently permit more than before.
DEFAULT_PROFILE_NAME = LOCKED.name

_PROFILE_NAMES = {p.name.lower() for p in BUILT_IN_PROFILES.values()}


def get_built_in(name: str) -> GovernanceProfile | None:
    return BUILT_IN_PROFILES.get(name.lower())


def is_built_in_name(name: str) -> bool:
    return name.lower() in _PROFILE_NAMES


def normalize_profile_name(name: str) -> str:
    for p in BUILT_IN_PROFILES.values():
        if p.name.lower() == name.lower():
            return p.name
    return name


# ---------------------------------------------------------------------------
# Persistence over StateManager
#
# Built-ins live in code; only custom profiles and the active selection are
# stored. Every read fails safe: a missing or corrupt setting falls back to
# DEFAULT_PROFILE_NAME (LOCKED — the strictest sensible behaviour), never to
# anything permissive.
# ---------------------------------------------------------------------------

ACTIVE_PROFILE_SETTING_KEY = "active_governance_profile"


def load_custom_profiles(state_manager: Any) -> dict[str, GovernanceProfile]:
    """Custom profiles from storage; corrupt entries are skipped by the store."""
    from komvos.governance.profiles import GovernanceProfile as _GP  # noqa: PLC0415

    profiles: dict[str, GovernanceProfile] = {}
    for row in state_manager.list_governance_profiles():
        try:
            spec = dict(row["spec"])
            spec.setdefault("name", row["name"])
            profile = _GP.model_validate(spec)
            if profile.built_in:
                continue  # built-ins are never stored nor editable
            profiles[profile.name] = profile
        except ValidationError:
            logger.warning("Skipping invalid custom profile %r", row.get("name"))
    return profiles


def load_profile(name: str, state_manager: Any) -> GovernanceProfile | None:
    """Resolve a profile by name: built-ins first, then custom.

    Missing or corrupt entries return None.
    """
    built = get_built_in(name)
    if built is not None:
        return built
    row = state_manager.get_governance_profile(normalize_profile_name(name))
    if row is None:
        return None
    try:
        spec = dict(row["spec"])
        spec.setdefault("name", row["name"])
        profile = GovernanceProfile.model_validate(spec)
        if profile.built_in:  # defensive: never load a stored "built-in"
            return None
        return profile
    except ValidationError:
        logger.warning("Corrupt profile %r treated as absent", name)
        return None


def get_active_profile_name(state_manager: Any) -> str:
    """Active selection, or DEFAULT_PROFILE_NAME when unset/corrupt."""
    value = state_manager.get_setting(ACTIVE_PROFILE_SETTING_KEY)
    if value is None or not isinstance(value, str):
        return DEFAULT_PROFILE_NAME
    # A name that resolves to no known profile must not silently become
    # anything permissive.
    if load_profile(value, state_manager) is None:
        return DEFAULT_PROFILE_NAME
    return str(value)


def set_active_profile_name(state_manager: Any, name: str) -> None:
    state_manager.set_setting(ACTIVE_PROFILE_SETTING_KEY, normalize_profile_name(name))


def active_profile(state_manager: Any) -> GovernanceProfile:
    profile = load_profile(get_active_profile_name(state_manager), state_manager)
    # Unreachable in practice (get_active_profile_name already validated);
    # kept so this function can never return None.
    assert profile is not None  # noqa: S101
    return profile
