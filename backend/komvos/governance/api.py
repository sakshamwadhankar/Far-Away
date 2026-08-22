"""
backend/komvos/governance/api.py

HTTP surface for governance profiles and approvals (Gov-2).

Routes (all behind session-token auth, like the rest of the management API):

    GET    /governance/profiles                     list all, marks the active one
    GET    /governance/profiles/{name}              read one
    POST   /governance/profiles                     create a custom profile
    PUT    /governance/profiles/{name}              replace a CUSTOM profile
    DELETE /governance/profiles/{name}              delete a custom profile
    GET    /governance/active                       which profile is in force
    PUT    /governance/active                       switch the active profile
    POST   /governance/approvals/{id}/answer        answer a pending approval

P1 additions — the decision log (query, filter, summarize, export):

    GET    /governance/decisions                    filtered list, keyset pages
    GET    /governance/decisions/summary            counts by outcome and domain
    GET    /governance/decisions/export             filtered set as JSON or CSV

Deleting a built-in profile fails with a clear message rather than mutating
shared behaviour, and deleting the ACTIVE profile fails rather than leaving
the system with no active profile. Built by FACTORY (not importing
api/main.py) for the same circular-import reason as komvos.serve.routes.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError

from komvos.governance.approvals import (
    AnswerRejectedError,
    ApprovalAnswer,
    find_approval,
)
from komvos.governance.decisions import (
    GovernanceDomain,
)
from komvos.governance.profiles import (
    BUILT_IN_PROFILES,
    GovernanceProfile,
    Posture,
    RetentionMode,
    get_active_profile_name,
    is_built_in_name,
    load_custom_profiles,
    load_profile,
    normalize_profile_name,
    set_active_profile_name,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class _PostureBody(BaseModel):
    """The posture fields shared by create and update."""

    postures: dict[GovernanceDomain, Posture]
    spend_cap_usd: float | None = Field(default=None, ge=0.0)
    spend_ask_threshold_usd: float | None = Field(default=None, ge=0.0)
    retention: RetentionMode = RetentionMode.FULL


class ProfileCreateRequest(_PostureBody):
    name: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$"
    )


class ProfileUpdateRequest(_PostureBody):
    pass


class SetActiveProfileRequest(BaseModel):
    name: str = Field(min_length=1)


class ApprovalAnswerRequest(BaseModel):
    answer: Literal["allow_once", "allow_for_run", "deny"]


class GovernanceProfileResponse(BaseModel):
    profile: GovernanceProfile
    is_active: bool


class GovernanceProfilesResponse(BaseModel):
    profiles: list[GovernanceProfileResponse]
    active_name: str


class ActiveProfileResponse(BaseModel):
    name: str
    profile: GovernanceProfile


class ApprovalAnswerResponse(BaseModel):
    approval_id: str
    accepted_answer: str
    node_id: str
    run_id: str


# ---------------------------------------------------------------------------
# Decision-log response models (P1)
# ---------------------------------------------------------------------------


class GovernanceDecisionResponse(BaseModel):
    """One stored decision, exactly as it was recorded."""

    seq: int
    decision_id: str
    run_id: str
    node_id: str
    domain: str
    capability: str
    outcome: str
    origin: str
    reason: str
    governed_by: list[str]
    effective_policy: dict[str, Any]
    when_utc: str
    when_ms: int


class GovernanceDecisionsPage(BaseModel):
    """
    One page of decisions, newest first.

    `next_cursor` feeds straight back as the `cursor` query parameter; None
    means the end of the (filtered) log.
    """

    decisions: list[GovernanceDecisionResponse]
    next_cursor: int | None = None


class GovernanceDecisionsSummary(BaseModel):
    total: int
    by_outcome: dict[str, int]
    by_domain: dict[str, int]


#: Filterable columns shared by the list and export endpoints. Literal types
#: make an unknown value a 422 from the framework rather than a silent empty
#: result set.
DomainFilter = Literal["providers", "egress", "spend", "retention"]
OutcomeFilter = Literal["allow", "deny", "timeout"]
OriginFilter = Literal[
    "pipeline_policy",
    "profile",
    "pipeline_and_profile",
    "human_allow_once",
    "human_allow_for_run",
    "human_deny",
]


def _decision_filters(
    run_id: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    domain: DomainFilter | None = Query(default=None),
    outcome: OutcomeFilter | None = Query(default=None),
    origin: OriginFilter | None = Query(default=None),
    since_ms: int | None = Query(default=None, ge=0),
    until_ms: int | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "node_id": node_id,
        "domain": domain,
        "outcome": outcome,
        "origin": origin,
        "since_ms": since_ms,
        "until_ms": until_ms,
    }


#: Upper bound on one export's row count. Exports are read from a local
#: SQLite file, but an unbounded SELECT still turns into unbounded memory
#: in the response builder; past this many rows, re-export with a narrower
#: time range.
EXPORT_ROW_CAP = 50_000


def _export_rows(state_manager: Any, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """All matching rows oldest-first, walking keyset pages."""
    collected: list[dict[str, Any]] = []
    cursor: int | None = None
    while len(collected) < EXPORT_ROW_CAP:
        rows, next_cursor = state_manager.query_governance_decisions(
            **filters, cursor=cursor, limit=1000, newest_first=False
        )
        collected.extend(rows)
        if next_cursor is None:
            break
        cursor = next_cursor
    return collected[:EXPORT_ROW_CAP]


def _profile_response(
    profile: GovernanceProfile, active_name: str
) -> GovernanceProfileResponse:
    return GovernanceProfileResponse(
        profile=profile, is_active=normalize_profile_name(active_name) == profile.name
    )


def _build_custom_profile(
    name: str, body: _PostureBody
) -> GovernanceProfile:
    try:
        return GovernanceProfile(
            name=name,
            built_in=False,
            postures=dict(body.postures),
            spend_cap_usd=body.spend_cap_usd,
            spend_ask_threshold_usd=body.spend_ask_threshold_usd,
            retention=body.retention,
        )
    except ValidationError as exc:
        # str() rather than exc.errors(): the raw error list carries
        # non-JSON-serializable context objects and would 500 on encode.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def create_governance_router(
    *,
    verify_token_dep: Callable[..., Any],
    get_state_manager_fn: Callable[[], Any],
) -> APIRouter:
    """
    Build the governance router. Injected deps mirror serve/routes: main.py
    passes its session-token dependency and StateManager accessor without
    this module ever importing api/main.py.
    """
    router = APIRouter(prefix="/governance", dependencies=[Depends(verify_token_dep)])

    def _all_profiles(state_manager: Any) -> dict[str, GovernanceProfile]:
        profiles: dict[str, GovernanceProfile] = dict(BUILT_IN_PROFILES)
        profiles.update(load_custom_profiles(state_manager))
        return profiles

    @router.get("/profiles", response_model=GovernanceProfilesResponse)
    async def list_profiles() -> GovernanceProfilesResponse:
        state_manager = get_state_manager_fn()
        active_name = get_active_profile_name(state_manager)
        return GovernanceProfilesResponse(
            profiles=[
                _profile_response(p, active_name)
                for p in _all_profiles(state_manager).values()
            ],
            active_name=normalize_profile_name(active_name),
        )

    @router.get("/profiles/{name}", response_model=GovernanceProfileResponse)
    async def read_profile(name: str) -> GovernanceProfileResponse:
        state_manager = get_state_manager_fn()
        profile = load_profile(name, state_manager)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found.")
        return _profile_response(profile, get_active_profile_name(state_manager))

    @router.post("/profiles", response_model=GovernanceProfileResponse, status_code=201)
    async def create_profile(body: ProfileCreateRequest) -> GovernanceProfileResponse:
        state_manager = get_state_manager_fn()
        if is_built_in_name(body.name):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"'{body.name}' is a built-in profile and cannot be "
                    "redefined. Create a profile with a different name, or "
                    "copy the built-in under a new name."
                ),
            )
        canonical = normalize_profile_name(body.name)
        if load_profile(canonical, state_manager) is not None:
            raise HTTPException(
                status_code=409, detail=f"A profile named '{canonical}' already exists."
            )
        profile = _build_custom_profile(canonical, body)
        state_manager.save_governance_profile(
            profile.name, json.dumps(profile.model_dump(mode="json"))
        )
        return _profile_response(profile, get_active_profile_name(state_manager))

    @router.put("/profiles/{name}", response_model=GovernanceProfileResponse)
    async def update_profile(
        name: str, body: ProfileUpdateRequest
    ) -> GovernanceProfileResponse:
        state_manager = get_state_manager_fn()
        if is_built_in_name(name):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Profile '{name}' is built-in and cannot be modified. "
                    "Copy it under a new name and edit the copy."
                ),
            )
        if load_profile(name, state_manager) is None:
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found.")
        profile = _build_custom_profile(name, body)
        state_manager.save_governance_profile(
            profile.name, json.dumps(profile.model_dump(mode="json"))
        )
        return _profile_response(profile, get_active_profile_name(state_manager))

    @router.delete("/profiles/{name}", status_code=204, response_model=None)
    async def delete_profile(name: str) -> None:
        state_manager = get_state_manager_fn()
        if is_built_in_name(name):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Profile '{name}' is built-in and cannot be deleted."
                ),
            )
        active_name = get_active_profile_name(state_manager)
        if normalize_profile_name(active_name) == normalize_profile_name(name):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Profile '{name}' is currently active. Switch to another "
                    "profile before deleting it — governance must always have "
                    "an active profile."
                ),
            )
        if not state_manager.delete_governance_profile(normalize_profile_name(name)):
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found.")

    @router.get("/active", response_model=ActiveProfileResponse)
    async def get_active() -> ActiveProfileResponse:
        state_manager = get_state_manager_fn()
        name = get_active_profile_name(state_manager)
        profile = load_profile(name, state_manager)
        assert profile is not None  # noqa: S101 — get_active_profile_name validates
        return ActiveProfileResponse(name=normalize_profile_name(name), profile=profile)

    @router.put("/active", response_model=ActiveProfileResponse)
    async def set_active(body: SetActiveProfileRequest) -> ActiveProfileResponse:
        state_manager = get_state_manager_fn()
        profile = load_profile(body.name, state_manager)
        if profile is None:
            known = ", ".join(sorted(_all_profiles(state_manager)))
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Profile '{body.name}' not found. Known profiles: {known}."
                ),
            )
        set_active_profile_name(state_manager, profile.name)
        return ActiveProfileResponse(name=profile.name, profile=profile)

    @router.post(
        "/approvals/{approval_id}/answer", response_model=ApprovalAnswerResponse
    )
    async def answer_approval(
        approval_id: str, body: ApprovalAnswerRequest
    ) -> ApprovalAnswerResponse:
        found = find_approval(approval_id)
        if found is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Approval '{approval_id}' is no longer pending. It may "
                    "already have been answered, timed out, or its run ended. "
                    "Pending approvals do not survive a restart."
                ),
            )
        registry, question = found
        try:
            registry.answer(approval_id, ApprovalAnswer(body.answer))
        except AnswerRejectedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ApprovalAnswerResponse(
            approval_id=approval_id,
            accepted_answer=body.answer,
            node_id=question.node_id,
            run_id=question.run_id,
        )

    # -------------------------------------------------------------------
    # Decision log (P1): query, summarize, export.
    #
    # Every read runs through asyncio.to_thread for the same reason the run
    # trace does: sqlite3 is a blocking C extension, and a large filtered
    # scan on the event loop would stall an in-flight run's WebSocket pump.
    # -------------------------------------------------------------------

    @router.get("/decisions", response_model=GovernanceDecisionsPage)
    async def list_decisions(
        filters: dict[str, Any] = Depends(_decision_filters),
        cursor: int | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> GovernanceDecisionsPage:
        """
        Newest-first page of decisions. Pagination is KEYSET over the
        monotonic `seq`, never OFFSET: page N costs what page 1 costs, on a
        table that only grows. Feed `next_cursor` back as `cursor`.
        """
        state_manager = get_state_manager_fn()
        rows, next_cursor = await asyncio.to_thread(
            state_manager.query_governance_decisions,
            **filters,
            cursor=cursor,
            limit=limit,
            newest_first=True,
        )
        return GovernanceDecisionsPage(
            decisions=[GovernanceDecisionResponse(**row) for row in rows],
            next_cursor=next_cursor,
        )

    @router.get(
        "/decisions/summary", response_model=GovernanceDecisionsSummary
    )
    async def decisions_summary(
        filters: dict[str, Any] = Depends(_decision_filters),
    ) -> GovernanceDecisionsSummary:
        """Counts by outcome and by domain for a run, or overall."""
        state_manager = get_state_manager_fn()
        # A breakdown BY outcome/domain makes no sense filtered ON them;
        # only the scope and time-range filters apply here.
        scope = {
            key: filters[key]
            for key in ("run_id", "since_ms", "until_ms")
            if filters.get(key) is not None
        }
        summary = await asyncio.to_thread(
            state_manager.summarize_governance_decisions, **scope
        )
        return GovernanceDecisionsSummary(**summary)

    @router.get("/decisions/export")
    async def export_decisions(
        filters: dict[str, Any] = Depends(_decision_filters),
        format: Literal["json", "csv"] = Query(default="json"),
    ) -> Response:
        """
        The filtered decision set as a download: chronological JSON array or
        spreadsheet-friendly CSV. Same filters as the list endpoint.
        """
        state_manager = get_state_manager_fn()
        rows = await asyncio.to_thread(_export_rows, state_manager, filters)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if format == "csv":
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(
                [
                    "when_utc",
                    "run_id",
                    "node_id",
                    "domain",
                    "capability",
                    "outcome",
                    "origin",
                    "governed_by",
                    "reason",
                    "effective_policy",
                ]
            )
            for row in rows:
                writer.writerow(
                    [
                        row["when_utc"],
                        row["run_id"],
                        row["node_id"],
                        row["domain"],
                        row["capability"],
                        row["outcome"],
                        row["origin"],
                        ";".join(row.get("governed_by") or []),
                        row["reason"],
                        json.dumps(row.get("effective_policy") or {}, sort_keys=True),
                    ]
                )
            payload = buffer.getvalue()
            return Response(
                content=payload,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="governance-decisions-{stamp}.csv"'
                    )
                },
            )

        return Response(
            content=json.dumps(rows, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="governance-decisions-{stamp}.json"'
                )
            },
        )

    return router
