"""
backend/komvos/endpoints/base.py

ModelEndpoint Protocol and supporting types — exactly as specified in TRD §3.
This file defines the CONTRACT that every model backend must implement.

BREAKING CHANGE: any modification to this file must be announced before P2
continues implementing CloudEndpoint / OllamaEndpoint.

No application logic here — pure type definitions and the Protocol only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from komvos.compiler.models import AccessPolicy

# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


class AccessDeniedError(Exception):
    """
    Raised when a node reaches for a capability its effective access policy
    withholds.

    Raised BEFORE any request is issued, so a denied call never leaves the
    machine. Carries enough structure for the scheduler to emit an
    `access_denied` event naming the node and the capability.
    """

    def __init__(self, node_id: str, capability: str, detail: str) -> None:
        self.node_id = node_id
        self.capability = capability
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Supporting types (TRD §3 sketch, fully typed)
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A single chat message passed to a model endpoint."""

    role: Literal["system", "user", "assistant"]
    content: str


class GenRequest(BaseModel):
    """
    Request passed to ModelEndpoint.generate().
    No API keys here — endpoints read keys from the OS keychain at runtime.
    """

    messages: list[Message] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1)
    response_format: Literal["text", "json"] = "text"
    """
    Hint for structured-output mode.
    'json'  → endpoint uses native JSON mode where available, else
              repair-prompt fallback.
    'text'  → plain streamed text.
    """


class Token(BaseModel):
    """A single streamed token from a model endpoint."""

    text: str
    index: int
    usage: Cost | None = Field(
        default=None,
        description="Actual measured token usage / cost reported by the provider.",
    )


class Health(BaseModel):
    """Liveness / readiness report for a model endpoint."""

    online: bool
    loaded: bool
    warm: bool


class Caps(BaseModel):
    """Capability advertisement for a model endpoint."""

    max_context: int = Field(ge=1, description="Maximum context length in tokens.")
    json_mode: bool = Field(description="Native structured/JSON output mode supported.")
    tools: bool = Field(description="Tool/function calling supported.")
    vision: bool = Field(description="Image input supported.")


class Cost(BaseModel):
    """Estimated or actual cost for a generation request."""

    usd: float = Field(ge=0.0, description="Cost in US dollars.")
    tokens_in: int = Field(ge=0, description="Prompt token count.")
    tokens_out: int = Field(ge=0, description="Completion token count.")
    is_estimate: bool = Field(
        default=False,
        description=(
            "True if cost is an estimate fallback rather than measured provider usage."
        ),
    )


# ---------------------------------------------------------------------------
# ModelEndpoint Protocol (TRD §3)
# ---------------------------------------------------------------------------


@runtime_checkable
class ModelEndpoint(Protocol):
    """
    The single interface every model backend must implement.
    The scheduler is endpoint-agnostic: it calls only these four methods.

    Implementations live in backend/komvos/endpoints/:
      - CloudEndpoint  (openai | anthropic | google | openai_compatible)
      - OllamaEndpoint (single-machine local — Phase 4)
      - [ExoEndpoint]  (sharded multi-machine — R1, not in this file)

    API keys are NEVER passed in here. Implementations read them from the
    OS keychain via `keyring` at instantiation or first use.
    """

    id: str
    """Unique identifier for this endpoint instance, e.g. 'cloud:gpt-4o'."""

    def check_access(self, policy: AccessPolicy, node_id: str) -> None:
        """
        Raise AccessDeniedError if `policy` does not permit this endpoint.

        Called by the model executor immediately BEFORE generate(), so a call
        the policy forbids never leaves the machine. Implementations must not
        perform I/O — this is a pure comparison against the policy.
        """
        ...

    def generate(self, req: GenRequest) -> AsyncIterator[Token]:
        """
        Stream tokens for a generation request.
        Must yield at least one Token; raises on hard failure.

        Declared as a plain (non-``async def``) method returning an
        ``AsyncIterator``: every implementation is an async *generator*, so
        calling it returns the iterator directly rather than a coroutine that
        must be awaited. Declaring this ``async def`` would type the call as
        ``Coroutine[..., AsyncIterator[Token]]`` and break `async for`.
        """
        ...

    async def health(self) -> Health:
        """
        Report whether the endpoint is online, model loaded, and warm.
        Must not raise — return Health(online=False, ...) on connectivity failure.
        """
        ...

    def capabilities(self) -> Caps:
        """
        Return static capability advertisement for this endpoint/model.
        Must not perform network I/O.
        """
        ...

    def estimate_cost(self, req: GenRequest) -> Cost:
        """
        Return estimated cost for a request BEFORE execution.
        Used by the scheduler for budget enforcement.
        Must not perform network I/O — uses local pricing tables.
        Raises NotImplementedError only if pricing data is genuinely unavailable.
        """
        ...

    def calculate_cost(
        self, tokens_in: int, tokens_out: int, is_estimate: bool = False
    ) -> Cost:
        """
        Calculate cost from measured or estimated token counts.
        """
        ...

