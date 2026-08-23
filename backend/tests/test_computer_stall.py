"""
The computer node must stop when it stops making progress.

A vision agent whose keystrokes never land re-decides the same action every
step, spending one model call each time. Left alone it runs to max_steps (30
by default) and can burn a provider's entire daily free-tier quota on a single
run that was never going to advance. These tests pin the circuit breaker that
ends such a run early.
"""

from __future__ import annotations

from typing import Any

import pytest

from komvos.compiler.models import AccessPolicy, Node
from komvos.desktop.models import ActionType, DesktopAction
from komvos.executors import computer as computer_mod
from komvos.executors.base import ExecutorContext
from komvos.executors.computer import (
    MAX_CONSECUTIVE_NO_PROGRESS,
    ActionParseError,
    ComputerExecutor,
)
from komvos.scheduler.engine import EndpointRegistry


class _StuckClient:
    """Desktop client whose screen never changes, however many keys it gets."""

    def __init__(self) -> None:
        self.actions_executed = 0

    async def screenshot(self) -> bytes:
        return b"frame"

    async def get_accessibility_tree(self) -> dict[str, Any]:
        return {}

    async def get_active_window(self) -> str:
        return "Komvos"

    async def execute_action(self, action: DesktopAction) -> bool:
        self.actions_executed += 1
        return True


class _CountingEndpoint:
    """Stands in for the vision model; counts how many calls the run costs."""

    def __init__(self) -> None:
        self.calls = 0

    def check_access(self, policy: AccessPolicy, node_id: str) -> None:
        return None

    async def generate(self, req: Any):  # noqa: ANN401
        self.calls += 1
        raise AssertionError("unused — _decide_action is patched")


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    client = _StuckClient()
    endpoint = _CountingEndpoint()
    monkeypatch.setattr(computer_mod, "DesktopClient", lambda *a, **k: client)

    # The screen never changes, so the verifier always reports no progress.
    class _Failed:
        passed = False
        reason = "No detectable change on screen."
        delta_score = 0.0
        observed_changes: list[str] = []

    monkeypatch.setattr(computer_mod, "verify_action", lambda *a, **k: _Failed())

    class _Marked:
        image_base64 = ""
        elements: list[Any] = []
        active_window = "Komvos"

    monkeypatch.setattr(computer_mod, "annotate_screenshot", lambda *a, **k: _Marked())

    async def _decide(self: Any, **kwargs: Any) -> DesktopAction:
        endpoint.calls += 1
        return DesktopAction(action_type=ActionType.PRESS_KEY, key="win")

    monkeypatch.setattr(ComputerExecutor, "_decide_action", _decide)
    return {"client": client, "endpoint": endpoint}


def _ctx(endpoint: Any) -> ExecutorContext:
    async def emit(_event: Any) -> None:
        return None

    return ExecutorContext(
        node=Node(
            id="computer_agent",
            type="computer",
            endpoint_ref="vision",
            inputs=[],
            outputs=[],
        ),
        inputs={"task": "open browser and search for cu"},
        registry=EndpointRegistry({"vision": endpoint}),
        emit_fn=emit,
        policy=AccessPolicy.permissive(),
    )


async def test_stalled_run_stops_instead_of_burning_the_step_budget(
    patched: dict[str, Any],
) -> None:
    result = await ComputerExecutor().execute(_ctx(patched["endpoint"]))

    assert result["status"] == "stalled"
    assert result["steps_taken"] == MAX_CONSECUTIVE_NO_PROGRESS
    assert "changed nothing on screen" in result["result"]


async def test_stalled_run_costs_only_a_few_model_calls(
    patched: dict[str, Any],
) -> None:
    """The whole point: a doomed run must not spend 30 requests of quota."""
    await ComputerExecutor().execute(_ctx(patched["endpoint"]))

    assert patched["endpoint"].calls == MAX_CONSECUTIVE_NO_PROGRESS
    assert patched["endpoint"].calls < 30


# ── Action parsing ────────────────────────────────────────────────────────────
#
# A model that cannot produce the required JSON must never be read as "the task
# is done". That fallback made a too-weak model look like a successful run: it
# ended on step one with every node DONE and nothing performed.


@pytest.mark.parametrize(
    "raw",
    [
        # Verbatim moondream output: valid JSON, describes no action at all.
        '{"text": "Hello", "language": "en-US", "type": "chat", "from": "John"}',
        # A loose `"done" in text` check read this negation as completion.
        "I am not done yet, still working on it",
        '{"foo": 1}',
        "",
        "   ",
    ],
)
def test_unusable_output_is_rejected_not_treated_as_done(raw: str) -> None:
    with pytest.raises(ActionParseError):
        ComputerExecutor()._parse_action(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"action_type": "press_key", "key": "win"}', "press_key"),
        (
            '```json' + "\n" + '{"action_type": "click", "target_mark": 3}'
            + "\n" + '```',
            "click",
        ),
        ('{"target_mark": 7}', "click"),          # bare mark is a click
        ('{"action_type": "done", "thought": "finished"}', "done"),
        ('{"action": "type_text", "text": "chrome"}', "type_text"),
    ],
)
def test_genuine_actions_still_parse(raw: str, expected: str) -> None:
    assert ComputerExecutor()._parse_action(raw).action_type.value == expected


async def test_model_that_never_returns_an_action_stalls_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end-to-end shape of the bug: it must stall, not report success."""
    client = _StuckClient()
    endpoint = _CountingEndpoint()
    monkeypatch.setattr(computer_mod, "DesktopClient", lambda *a, **k: client)

    class _Marked:
        image_base64 = ""
        elements: list[Any] = []
        active_window = "Komvos"

    monkeypatch.setattr(computer_mod, "annotate_screenshot", lambda *a, **k: _Marked())

    async def _decide(self: Any, **kwargs: Any) -> Any:
        endpoint.calls += 1
        raise ActionParseError("no action in reply")

    monkeypatch.setattr(ComputerExecutor, "_decide_action", _decide)

    result = await ComputerExecutor().execute(_ctx(endpoint))

    assert result["status"] == "stalled"
    assert result["status"] != "completed"
    assert client.actions_executed == 0
    assert endpoint.calls == MAX_CONSECUTIVE_NO_PROGRESS


# ── Transient provider failures ───────────────────────────────────────────────
#
# A 503 "high demand" on step five used to abort the run and discard every step
# the agent had already completed. It is a failed step, not a dead run — but a
# provider that is genuinely down must still stop things promptly.


class _Boom(Exception):
    """Stands in for a provider 503."""

    status_code = 503


async def test_transient_model_failure_does_not_kill_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _StuckClient()
    endpoint = _CountingEndpoint()
    monkeypatch.setattr(computer_mod, "DesktopClient", lambda *a, **k: client)

    class _Marked:
        image_base64 = ""
        elements: list[Any] = []
        active_window = "Komvos"

    monkeypatch.setattr(computer_mod, "annotate_screenshot", lambda *a, **k: _Marked())

    # Fail twice, then succeed with a real action and finish.
    async def _decide(self: Any, **kwargs: Any) -> DesktopAction:
        endpoint.calls += 1
        if endpoint.calls <= 2:
            raise _Boom("503 Service Unavailable")
        return DesktopAction(action_type=ActionType.DONE, thought="finished")

    monkeypatch.setattr(ComputerExecutor, "_decide_action", _decide)

    result = await ComputerExecutor().execute(_ctx(endpoint))

    # Survived the blips and completed rather than erroring out.
    assert result["status"] == "completed"
    assert endpoint.calls == 3


async def test_persistent_model_outage_still_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _StuckClient()
    endpoint = _CountingEndpoint()
    monkeypatch.setattr(computer_mod, "DesktopClient", lambda *a, **k: client)

    class _Marked:
        image_base64 = ""
        elements: list[Any] = []
        active_window = "Komvos"

    monkeypatch.setattr(computer_mod, "annotate_screenshot", lambda *a, **k: _Marked())

    async def _decide(self: Any, **kwargs: Any) -> DesktopAction:
        endpoint.calls += 1
        raise _Boom("503 Service Unavailable")

    monkeypatch.setattr(ComputerExecutor, "_decide_action", _decide)

    with pytest.raises(_Boom):
        await ComputerExecutor().execute(_ctx(endpoint))
    # Bounded by the stall breaker, not retried forever.
    assert endpoint.calls == MAX_CONSECUTIVE_NO_PROGRESS
