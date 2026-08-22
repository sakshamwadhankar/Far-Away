"""
backend/komvos/endpoints/mock.py

Mock ModelEndpoint for tests ONLY — never used in production code.

Supports:
  - predefined_text: static text response
  - json_response: dict that gets serialized as JSON tokens
  - response_fn: callable that returns a dynamic response string per request
    (needed for loop tests where iteration N returns different values)

Per AGENT.md rule 1: fakes only in clearly-named test files and this mock module.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from komvos.compiler.models import AccessPolicy
from komvos.endpoints.base import (
    AccessDeniedError,
    Caps,
    Cost,
    GenRequest,
    Health,
    Token,
)


class MockEndpoint:
    """
    Test-only endpoint that returns configurable responses.

    This class intentionally does NOT inherit from ModelEndpoint Protocol —
    it implements it structurally (duck typing). The Protocol is
    runtime_checkable, so isinstance() checks still work.
    """

    def __init__(
        self,
        *,
        id: str = "mock-endpoint",
        token_delay: float = 0.0,
        predefined_text: str = "This is a mock response.",
        json_response: dict[str, Any] | None = None,
        response_fn: Callable[[GenRequest], str] | None = None,
    ) -> None:
        self.id = id
        self.token_delay = token_delay
        self.predefined_text = predefined_text
        self.json_response = json_response
        self.response_fn = response_fn

    async def generate(self, req: GenRequest) -> AsyncIterator[Token]:
        """
        Yield tokens from the configured response source.

        Priority: response_fn > json_response > predefined_text
        """
        if self.response_fn is not None:
            text = self.response_fn(req)
        elif self.json_response is not None:
            text = json.dumps(self.json_response)
        else:
            text = self.predefined_text

        words = text.split(" ")
        for i, word in enumerate(words):
            if self.token_delay > 0:
                await asyncio.sleep(self.token_delay)
            # Append space except for the last word
            token_text = word + (" " if i < len(words) - 1 else "")
            yield Token(text=token_text, index=i)

    async def health(self) -> Health:
        return Health(online=True, loaded=True, warm=True)

    def capabilities(self) -> Caps:
        return Caps(max_context=4096, json_mode=True, tools=False, vision=False)

    def estimate_cost(self, req: GenRequest) -> Cost:
        return Cost(
            usd=0.001,
            tokens_in=10,
            tokens_out=len(self.predefined_text.split(" ")),
        )

    def check_access(self, policy: AccessPolicy, node_id: str) -> None:
        """
        The mock endpoint is a named endpoint kind like any other, so a policy
        that does not list "mock" withholds it.
        """
        if "mock" not in policy.providers:
            granted = ", ".join(policy.providers) if policy.providers else "(none)"
            raise AccessDeniedError(
                node_id=node_id,
                capability="provider:mock",
                detail=(
                    f"Node '{node_id}' (model:mock) requires provider 'mock', "
                    f"which its access policy does not grant. "
                    f"Granted providers: [{granted}]."
                ),
            )
