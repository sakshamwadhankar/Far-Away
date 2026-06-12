"""
backend/tests/test_merge_a.py

MERGE A integration test (Phase 1).

Verifies that:
  1. MockEndpoint (P2) correctly implements the ModelEndpoint Protocol
     defined in P1's base.py — including all four methods.
  2. A GenRequest from P1's base.py flows through MockEndpoint.generate()
     and yields well-typed Token objects.
  3. isinstance() structural-subtype check passes (runtime_checkable Protocol).

RULES:
  - MockEndpoint is the ONLY allowed fake per AGENT.md.
  - No live network calls.
  - No secrets in this file.
"""

import pytest
from neuralflow.endpoints.base import (
    GenRequest,
    Message,
    ModelEndpoint,
)
from neuralflow.endpoints.mock import MockEndpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(text: str = "hello world") -> GenRequest:
    return GenRequest(messages=[Message(role="user", content=text)])


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------


def test_mock_implements_model_endpoint_protocol() -> None:
    """MockEndpoint must satisfy the runtime_checkable ModelEndpoint Protocol."""
    endpoint = MockEndpoint()
    assert isinstance(endpoint, ModelEndpoint), (
        "MockEndpoint does not satisfy the ModelEndpoint Protocol. "
        "A required method or attribute is missing."
    )


# ---------------------------------------------------------------------------
# GenRequest → MockEndpoint.generate() → Token stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gen_request_flows_through_mock_endpoint() -> None:
    """
    A GenRequest (from P1's base.py) must flow through MockEndpoint.generate()
    and return a sequence of typed Token objects whose concatenated text
    equals the predefined response.
    """
    predefined = "merge a integration check"
    endpoint = MockEndpoint(token_delay=0.0, predefined_text=predefined)
    req = _make_request("trigger the flow")

    tokens = []
    async for tok in endpoint.generate(req):
        # Every yielded object must be a Token
        assert hasattr(tok, "text"), "Token missing .text attribute"
        assert hasattr(tok, "index"), "Token missing .index attribute"
        assert isinstance(tok.text, str)
        assert isinstance(tok.index, int)
        tokens.append(tok.text)

    assert "".join(tokens) == predefined, (
        f"Token stream reassembled as {' '.join(tokens)!r}, "
        f"expected {predefined!r}"
    )


# ---------------------------------------------------------------------------
# All four Protocol methods round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_protocol_methods_round_trip() -> None:
    """
    Verify that all four methods defined in ModelEndpoint (base.py) are
    callable on MockEndpoint and return the correct typed objects.
    """
    endpoint = MockEndpoint(token_delay=0.0, predefined_text="ok")
    req = _make_request()

    # generate() — async generator
    tokens = [tok async for tok in endpoint.generate(req)]
    assert len(tokens) > 0

    # health() — async
    health = await endpoint.health()
    assert health.online is True
    assert health.loaded is True
    assert health.warm is True

    # capabilities() — sync
    caps = endpoint.capabilities()
    assert caps.max_context > 0
    assert isinstance(caps.json_mode, bool)
    assert isinstance(caps.tools, bool)
    assert isinstance(caps.vision, bool)

    # estimate_cost() — sync, no network I/O
    cost = endpoint.estimate_cost(req)
    assert cost.usd >= 0.0
    assert cost.tokens_in >= 0
    assert cost.tokens_out >= 0
