"""
backend/komvos/desktop/__init__.py

Desktop automation and governance domain package.
"""

from __future__ import annotations

from komvos.desktop.client import DesktopClient
from komvos.desktop.destructive import classify_action
from komvos.desktop.detection import is_computer_server_available, probe_computer_server
from komvos.desktop.grounding import annotate_screenshot
from komvos.desktop.models import (
    ActionType,
    DesktopAction,
    DestructiveClassification,
    MarkedScreen,
    ScreenElement,
    VerificationResult,
)
from komvos.desktop.verifier import verify_action

__all__ = [
    "ActionType",
    "DesktopAction",
    "DesktopClient",
    "DestructiveClassification",
    "MarkedScreen",
    "ScreenElement",
    "VerificationResult",
    "annotate_screenshot",
    "classify_action",
    "is_computer_server_available",
    "probe_computer_server",
    "verify_action",
]
