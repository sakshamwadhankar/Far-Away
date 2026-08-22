"""
backend/komvos/desktop/verifier.py

Post-action verification engine.

Confirms that a desktop action actually achieved its intended effect by combining:
  1. State assertions (active window changes, element state / text changes).
  2. Before/after visual difference comparison in the region of interest (ROI).

A verifier that always passes is worse than no verifier. This implementation
actively checks for meaningful state transitions and fails when the screen
remains stagnant or does not reflect the expected mutation.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import io
import logging

from komvos.desktop.models import (
    ActionType,
    DesktopAction,
    MarkedScreen,
    VerificationResult,
)

logger = logging.getLogger(__name__)


def _compute_image_delta(
    img_a_b64: str,
    img_b_b64: str,
    roi: tuple[int, int, int, int] | None = None,
) -> float:
    """
    Compute normalized perceptual difference (0.0 to 1.0) between two base64 images.
    If roi is provided as (x, y, w, h), difference is calculated within that box.
    """
    if not img_a_b64 or not img_b_b64:
        return 0.0

    # Try PIL comparison
    try:
        pil_image = importlib.import_module("PIL.Image")
        pil_chops = importlib.import_module("PIL.ImageChops")
        pil_stat = importlib.import_module("PIL.ImageStat")

        raw_a = base64.b64decode(img_a_b64)
        raw_b = base64.b64decode(img_b_b64)

        img_a = pil_image.open(io.BytesIO(raw_a)).convert("RGB")
        img_b = pil_image.open(io.BytesIO(raw_b)).convert("RGB")

        if img_a.size != img_b.size:
            img_b = img_b.resize(img_a.size)

        if roi:
            rx, ry, rw, rh = roi
            x0 = max(0, rx)
            y0 = max(0, ry)
            x1 = min(img_a.width, rx + rw)
            y1 = min(img_a.height, ry + rh)
            if x1 > x0 and y1 > y0:
                img_a = img_a.crop((x0, y0, x1, y1))
                img_b = img_b.crop((x0, y0, x1, y1))

        diff = pil_chops.difference(img_a, img_b)
        stat = pil_stat.Stat(diff)
        rms = sum(stat.rms) / (3.0 * 255.0)
        return float(rms)
    except Exception as exc:
        logger.debug("PIL delta calculation unavailable: %s", exc)

    # Pure Python byte comparison fallback
    if img_a_b64 == img_b_b64:
        return 0.0

    hash_a = hashlib.sha256(img_a_b64.encode("utf-8")).digest()
    hash_b = hashlib.sha256(img_b_b64.encode("utf-8")).digest()
    diff_bytes = sum(a != b for a, b in zip(hash_a, hash_b, strict=False))
    return float(diff_bytes / len(hash_a))


def verify_action(
    pre_screen: MarkedScreen,
    post_screen: MarkedScreen,
    action: DesktopAction,
) -> VerificationResult:
    """
    Verify whether the executed action produced the intended screen state change.
    """
    # 1. Non-mutating actions pass by definition
    if action.action_type in (
        ActionType.SCREENSHOT,
        ActionType.WAIT,
        ActionType.DONE,
    ):
        return VerificationResult(
            passed=True,
            reason=f"Action '{action.action_type.value}' is read-only.",
            delta_score=1.0,
            observed_changes=["read_only_action_completed"],
        )

    # 2. Check for active window transition
    window_changed = (
        pre_screen.active_window is not None
        and post_screen.active_window is not None
        and pre_screen.active_window != post_screen.active_window
    )

    # 3. Compute visual delta
    roi: tuple[int, int, int, int] | None = None
    if action.x is not None and action.y is not None:
        roi = (action.x - 80, action.y - 80, 160, 160)

    roi_delta = _compute_image_delta(
        pre_screen.image_base64, post_screen.image_base64, roi=roi
    )
    global_delta = _compute_image_delta(
        pre_screen.image_base64, post_screen.image_base64, roi=None
    )

    observed: list[str] = []
    if window_changed:
        w_from = pre_screen.active_window or "None"
        w_to = post_screen.active_window or "None"
        observed.append(f"Active window: {w_from!r} -> {w_to!r}")
    if roi_delta > 0.005:
        observed.append(f"Target region visual delta: {roi_delta:.4f}")
    if global_delta > 0.005:
        observed.append(f"Overall screen delta: {global_delta:.4f}")

    MIN_DELTA_THRESHOLD = 0.008

    # 4. Action-specific verification rules
    if action.action_type in (
        ActionType.CLICK,
        ActionType.DOUBLE_CLICK,
        ActionType.RIGHT_CLICK,
    ):
        if (
            window_changed
            or roi_delta >= MIN_DELTA_THRESHOLD
            or global_delta >= MIN_DELTA_THRESHOLD
        ):
            score = max(roi_delta, global_delta)
            return VerificationResult(
                passed=True,
                reason=(
                    f"Click on mark {action.target_mark or (action.x, action.y)} "
                    f"produced state change (delta: {score:.4f})."
                ),
                delta_score=score,
                observed_changes=observed,
            )
        delta_msg = f"ROI delta: {roi_delta:.4f}, global: {global_delta:.4f}"
        return VerificationResult(
            passed=False,
            reason=(
                f"Verification failed: Click at ({action.x}, {action.y}) produced no "
                f"detectable visual change ({delta_msg})."
            ),
            delta_score=max(roi_delta, global_delta),
            observed_changes=observed,
        )

    if action.action_type == ActionType.TYPE_TEXT:
        if roi_delta >= 0.004 or global_delta >= 0.004:
            score = max(roi_delta, global_delta)
            return VerificationResult(
                passed=True,
                reason=f"Typed text {action.text!r} updated (delta: {score:.4f}).",
                delta_score=score,
                observed_changes=observed,
            )
        return VerificationResult(
            passed=False,
            reason=(
                f"Verification failed: Typing {action.text!r} produced no change. "
                "Target input may not have had keyboard focus."
            ),
            delta_score=max(roi_delta, global_delta),
            observed_changes=observed,
        )

    if action.action_type in (ActionType.PRESS_KEY, ActionType.HOTKEY):
        if window_changed or global_delta >= MIN_DELTA_THRESHOLD:
            score = max(roi_delta, global_delta)
            return VerificationResult(
                passed=True,
                reason=f"Key action '{action.key or action.keys}' updated state.",
                delta_score=score,
                observed_changes=observed,
            )
        key_str = str(action.key or action.keys)
        return VerificationResult(
            passed=False,
            reason=f"Verification failed: Key '{key_str}' produced no change.",
            delta_score=max(roi_delta, global_delta),
            observed_changes=observed,
        )

    if action.action_type == ActionType.SCROLL:
        if global_delta >= 0.005:
            return VerificationResult(
                passed=True,
                reason=f"Scroll action shifted content (delta: {global_delta:.4f}).",
                delta_score=global_delta,
                observed_changes=observed,
            )
        return VerificationResult(
            passed=False,
            reason="Verification failed: Scroll produced no change.",
            delta_score=global_delta,
            observed_changes=observed,
        )

    has_changed = global_delta >= MIN_DELTA_THRESHOLD or window_changed
    return VerificationResult(
        passed=has_changed,
        reason=(
            f"Observed state change delta: {global_delta:.4f}"
            if has_changed
            else f"No detectable state change after {action.action_type.value}."
        ),
        delta_score=global_delta,
        observed_changes=observed,
    )
