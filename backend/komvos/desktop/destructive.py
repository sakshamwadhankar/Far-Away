"""
backend/komvos/desktop/destructive.py

Explicit, defensible classification rules for destructive desktop actions.

Destructive operations are actions that can cause data loss, state corruption,
security boundary violation, unauthorized publication, irreversible system
modifications, or financial transactions.

When classification is uncertain or ambiguous, the classifier FAILS SAFE by
classifying the action as destructive.
"""

from __future__ import annotations

import re

from komvos.desktop.models import (
    ActionType,
    DesktopAction,
    DestructiveClassification,
)

# ── Pattern matching lists for destructive keywords ─────────────────────────

_DELETION_PATTERNS = (
    r"\b(delete|del|rm|remove|trash|erase|wipe|shred|truncate|drop|uninstall|purge|destroy)\b"
)

_OVERWRITE_PATTERNS = r"\b(overwrite|replace|discard|revert|reset|format|clear all)\b"

_SYSTEM_SECURITY_PATTERNS = (
    r"\b(regedit|powershell|cmd|netsh|taskkill|sc stop|chmod|chown|sudo|runas|"
    r"firewall|antivirus|password|keyring|credential|settings|control panel|"
    r"uac|diskpart|mkfs)\b"
)

_COMMUNICATION_PUBLISH_PATTERNS = (
    r"\b(send|publish|post|submit|deploy|tweet|broadcast|push|share|commit)\b"
)

_FINANCIAL_PATTERNS = (
    r"\b(buy|purchase|pay|payment|subscribe|checkout|order|transfer|credit card|"
    r"cvv|billing|wire)\b"
)

_DESTRUCTIVE_KEYS = frozenset({"delete", "backspace", "f4", "q"})
_DANGEROUS_HOTKEYS = (
    {"alt", "f4"},
    {"ctrl", "d"},
    {"ctrl", "w"},
    {"ctrl", "q"},
    {"shift", "delete"},
)


def classify_action(
    action: DesktopAction,
    target_element_name: str | None = None,
    target_element_role: str | None = None,
) -> DestructiveClassification:
    """
    Classify whether a planned desktop action is destructive.

    Evaluates:
      1. Action type semantics (done / wait / screenshot vs mutations).
      2. Key combinations and hotkeys (Alt+F4, Shift+Delete, etc.).
      3. Typed text content (shell commands, deletion tokens, system tools).
      4. Target UI element labels and semantics (buttons labeled 'Delete', 'Buy', etc.).
      5. Bias: FAILS SAFE to destructive when classification is uncertain.
    """
    # Safe read-only actions
    if action.action_type in (
        ActionType.SCREENSHOT,
        ActionType.WAIT,
        ActionType.DONE,
    ):
        return DestructiveClassification(
            is_destructive=False,
            reason=f"Action '{action.action_type.value}' is read-only.",
            category="read_only",
        )

    # 1. Check hotkeys
    if action.action_type == ActionType.HOTKEY and action.keys:
        lowered_keys = {k.lower().strip() for k in action.keys}
        for danger in _DANGEROUS_HOTKEYS:
            if danger.issubset(lowered_keys):
                combo = "+".join(action.keys)
                return DestructiveClassification(
                    is_destructive=True,
                    reason=(
                        f"Dangerous hotkey combo '{combo}' "
                        "can close apps or delete data."
                    ),
                    category="system_hotkey",
                )

    # 2. Check single key presses
    if action.action_type == ActionType.PRESS_KEY and action.key:
        key_lower = action.key.lower().strip()
        if key_lower == "delete":
            return DestructiveClassification(
                is_destructive=True,
                reason="Direct 'Delete' key press can destroy data or files.",
                category="deletion",
            )

    # 3. Check typed text
    if action.action_type == ActionType.TYPE_TEXT and action.text:
        text = action.text
        if re.search(_DELETION_PATTERNS, text, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text contains deletion keywords: {text!r}",
                category="deletion",
            )
        if re.search(_OVERWRITE_PATTERNS, text, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text contains overwrite keywords: {text!r}",
                category="overwrite",
            )
        if re.search(_SYSTEM_SECURITY_PATTERNS, text, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text references system/security tools: {text!r}",
                category="system_security",
            )
        if re.search(_COMMUNICATION_PUBLISH_PATTERNS, text, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text contains publication/sending keywords: {text!r}",
                category="communication_publish",
            )
        if re.search(_FINANCIAL_PATTERNS, text, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Typed text contains financial/payment keywords: {text!r}",
                category="financial",
            )

    # 4. Check target UI element text/role for click/drag actions
    combined_target = " ".join(
        filter(
            None,
            [
                target_element_name,
                target_element_role,
                action.target_application,
                action.expected_outcome,
            ],
        )
    )

    if combined_target:
        if re.search(_DELETION_PATTERNS, combined_target, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target UI element implies deletion: {combined_target!r}",
                category="deletion",
            )
        if re.search(_OVERWRITE_PATTERNS, combined_target, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target UI implies overwrite/reset: {combined_target!r}",
                category="overwrite",
            )
        if re.search(_SYSTEM_SECURITY_PATTERNS, combined_target, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target is system/security setting: {combined_target!r}",
                category="system_security",
            )
        if re.search(_COMMUNICATION_PUBLISH_PATTERNS, combined_target, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target triggers publishing/sending: {combined_target!r}",
                category="communication_publish",
            )
        if re.search(_FINANCIAL_PATTERNS, combined_target, re.IGNORECASE):
            return DestructiveClassification(
                is_destructive=True,
                reason=f"Target is financial transaction: {combined_target!r}",
                category="financial",
            )

    # 5. Non-destructive standard navigation clicks or text inputs
    if action.action_type in (
        ActionType.CLICK,
        ActionType.DOUBLE_CLICK,
        ActionType.RIGHT_CLICK,
        ActionType.SCROLL,
    ):
        # Ordinary scroll is non-destructive
        if action.action_type == ActionType.SCROLL:
            return DestructiveClassification(
                is_destructive=False,
                reason="Scroll action is non-destructive.",
                category="navigation",
            )

        # Standard click with known safe context
        if target_element_name or target_element_role:
            return DestructiveClassification(
                is_destructive=False,
                reason=f"Safe UI interaction on element {target_element_name!r}.",
                category="interaction",
            )

    # Standard safe text entry without trigger keywords
    if action.action_type == ActionType.TYPE_TEXT and action.text:
        return DestructiveClassification(
            is_destructive=False,
            reason="Standard benign text input.",
            category="typing",
        )

    # 6. FAIL SAFE: when an action's context is unknown, classify as destructive
    return DestructiveClassification(
        is_destructive=True,
        reason=(
            f"Uncertain or unverified action target for '{action.action_type.value}'; "
            "failing safe as destructive."
        ),
        category="fail_safe_uncertainty",
    )
