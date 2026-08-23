"""
Coordinate scaling and mark quality for desktop grounding.

Both cases here came from a real machine: a 125% display made every mark land
a quarter of the way off its widget, and phantom OS windows became clickable
marks that an agent looped on until the run timed out.
"""

from __future__ import annotations

import pytest

from komvos.desktop.grounding import (
    derive_input_scale,
    is_junk_element,
    scale_elements,
)
from komvos.desktop.models import ScreenElement


def _el(x: int, y: int, w: int, h: int, mark: int = 1) -> ScreenElement:
    return ScreenElement(
        mark_id=mark, bbox=(x, y, w, h), center=(x + w // 2, y + h // 2)
    )


def test_derives_the_real_measured_scaling_factor() -> None:
    """1920x1200 screenshot with a 1536x960 logical tree is 125% scaling."""
    taskbar = [_el(0, 912, 1536, 48), _el(1298, 912, 238, 48, 2)]
    assert derive_input_scale(taskbar, 1920, 1200) == (1.25, 1.25)


def test_unscaled_display_is_left_alone() -> None:
    assert derive_input_scale([_el(0, 1152, 1920, 48)], 1920, 1200) == (1.0, 1.0)


@pytest.mark.parametrize(
    "elements",
    [
        [],                                # nothing to measure
        [_el(0, 0, 200, 900)],             # tree covers a sliver; axes disagree
        [_el(0, 0, 1, 1)],                 # absurd ratio
    ],
)
def test_refuses_to_guess_when_the_tree_does_not_span_the_screen(
    elements: list[ScreenElement],
) -> None:
    assert derive_input_scale(elements, 1920, 1200) == (1.0, 1.0)


def test_scaling_moves_the_taskbar_to_the_bottom_of_the_screen() -> None:
    """The concrete symptom: an unscaled taskbar mark sat 22% too high."""
    taskbar = _el(0, 912, 1536, 48)
    scaled = scale_elements([taskbar], (1.25, 1.25))[0]
    assert scaled.bbox == (0, 1140, 1920, 60)
    # Centre must now fall inside the physical screen's bottom bar.
    assert 1140 <= scaled.center[1] <= 1200


@pytest.mark.parametrize(
    ("role", "name"),
    [
        ("Window", "Non Client Input Sink Window"),
        ("MSCTFIME UI", ""),
        ("Window", "Default IME"),
    ],
)
def test_phantom_windows_are_not_offered_as_marks(role: str, name: str) -> None:
    assert is_junk_element(role, name)


@pytest.mark.parametrize(
    ("role", "name"),
    [
        ("Button", "&Browse..."),
        ("Button", "OK"),
        ("Edit", "Open:"),
        ("Window", "Downloads - File Explorer"),
    ],
)
def test_real_controls_are_kept(role: str, name: str) -> None:
    assert not is_junk_element(role, name)
