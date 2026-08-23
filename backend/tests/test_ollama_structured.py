"""
Schema-constrained decoding for local models.

Plain JSON mode only promises that the reply parses. Asked for a desktop
action, a small local model answers `{"next_action": "..."}` — well-formed and
unusable, which is precisely how the computer node stalled. Passing the schema
through pins the field names, so the same model produces a parseable action.
"""

from __future__ import annotations

from typing import Any

import pytest

from komvos.endpoints.base import GenRequest, Message
from komvos.endpoints.ollama import OllamaEndpoint
from komvos.executors.computer import _ACTION_SCHEMA, ComputerExecutor


def _payload_for(req: GenRequest, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Run generate() far enough to capture the payload, without a live server."""
    captured: dict[str, Any] = {}

    class _Boom(RuntimeError):
        """Aborts generate() the instant the payload is built."""

    class _FakeClient:
        def build_request(
            self, _method: str, _url: str, json: dict[str, Any], **_kw: Any
        ) -> Any:
            captured.update(json)
            raise _Boom

    monkeypatch.setattr(
        "komvos.endpoints.ollama._get_client", lambda *_a, **_k: _FakeClient()
    )

    ep = OllamaEndpoint(
        id="ollama:test", base_url="http://127.0.0.1:11434/v1", model="test"
    )

    async def drive() -> None:
        async for _ in ep.generate(req):
            break

    import asyncio

    with pytest.raises(_Boom):
        asyncio.run(drive())
    return captured


def _req(**kw: Any) -> GenRequest:
    return GenRequest(
        messages=[Message(role="user", content="go")],
        response_format="json",
        **kw,
    )


def test_schema_is_sent_as_json_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _payload_for(_req(json_schema=_ACTION_SCHEMA), monkeypatch)
    rf = payload.get("response_format")
    assert rf is not None, "no response_format sent"
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == _ACTION_SCHEMA
    assert rf["json_schema"]["strict"] is True


def test_plain_json_mode_still_works_without_a_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload_for(_req(), monkeypatch)
    assert payload.get("response_format") == {"type": "json_object"}


def test_action_schema_requires_the_field_the_parser_needs() -> None:
    """The schema must pin exactly what _parse_action rejects output for."""
    assert "action_type" in _ACTION_SCHEMA["required"]
    enum = _ACTION_SCHEMA["properties"]["action_type"]["enum"]
    # Every enum value the schema allows must be one the parser accepts.
    for value in enum:
        action = ComputerExecutor()._parse_action(
            f'{{"action_type": "{value}", "thought": "t"}}'
        )
        assert action.action_type.value == value
