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

Deleting a built-in profile fails with a clear message rather than mutating
shared behaviour, and deleting the ACTIVE profile fails rather than leaving
the system with no active profile. Built by FACTORY (not importing
api/main.py) for the same circular-import reason as komvos.serve.routes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from komvos.governance.approvals import (
    AnswerRejectedError,
    ApprovalAnswer,
    find_approval,
)
from komvos.governance.decisions import GovernanceDomain
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

    return router
