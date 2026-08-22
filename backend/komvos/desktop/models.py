"""
backend/komvos/desktop/models.py

Data models for desktop automation actions, grounding, and verification.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    """The set of discrete actions the desktop action layer can execute."""

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    DRAG = "drag"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    DONE = "done"


class DesktopAction(BaseModel):
    """One discrete desktop operation requested by the model."""

    model_config = {"extra": "forbid"}

    action_type: ActionType
    target_mark: int | None = Field(
        default=None,
        description="Mark number chosen by the model from the grounded overlay.",
    )
    x: int | None = Field(default=None, description="Resolved pixel X coordinate.")
    y: int | None = Field(default=None, description="Resolved pixel Y coordinate.")
    text: str | None = Field(default=None, description="Text to type.")
    key: str | None = Field(default=None, description="Key name to press.")
    keys: list[str] | None = Field(
        default=None, description="Key sequence for hotkey combos."
    )
    scroll_dx: int | None = Field(default=None, description="Horizontal scroll amount.")
    scroll_dy: int | None = Field(default=None, description="Vertical scroll amount.")
    target_application: str | None = Field(
        default=None, description="Name of the target application window."
    )
    thought: str | None = Field(
        default=None, description="Model's reasoning before taking the action."
    )
    expected_outcome: str | None = Field(
        default=None,
        description="What the model expects to change on screen after this action.",
    )


class ScreenElement(BaseModel):
    """An interactive UI element detected on the screen."""

    model_config = {"extra": "forbid"}

    mark_id: int
    role: str = "element"
    name: str = ""
    bbox: tuple[int, int, int, int]  # (x, y, width, height)
    center: tuple[int, int]  # (x, y)


class MarkedScreen(BaseModel):
    """A screenshot captured and annotated with numbered mark badges."""

    model_config = {"extra": "forbid"}

    elements: list[ScreenElement]
    grid_used: bool = False
    screen_width: int
    screen_height: int
    active_window: str | None = None
    image_base64: str = ""


class DestructiveClassification(BaseModel):
    """The result of classifying whether an action is destructive."""

    model_config = {"extra": "forbid"}

    is_destructive: bool
    reason: str
    category: str = "none"


class VerificationResult(BaseModel):
    """Outcome of verifying whether an action achieved its intended effect."""

    model_config = {"extra": "forbid"}

    passed: bool
    reason: str
    delta_score: float = 0.0
    observed_changes: list[str] = Field(default_factory=list)
    state_details: dict[str, Any] = Field(default_factory=dict)
