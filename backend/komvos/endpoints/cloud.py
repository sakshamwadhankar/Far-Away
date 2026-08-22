import asyncio
import json
import logging
import os
import random
from collections.abc import AsyncIterator
from typing import Any

from komvos.compiler.models import AccessPolicy
from komvos.secrets import get_secret

from .base import (
    AccessDeniedError,
    Caps,
    Cost,
    GenRequest,
    Health,
    ModelEndpoint,
    Token,
)

logger = logging.getLogger(__name__)

# Load pricing table
PRICING_FILE = os.path.join(os.path.dirname(__file__), "pricing.json")
try:
    with open(PRICING_FILE) as f:
        PRICING = json.load(f)
except FileNotFoundError:
    PRICING = {}

# ---------------------------------------------------------------------------
# Provider resilience: explicit timeouts, client reuse, bounded retries.
# ---------------------------------------------------------------------------

#: Seconds to wait for the TCP/TLS connection to the provider.
CONNECT_TIMEOUT_S = 10.0
#: Seconds allowed between streamed bytes once a response is flowing. This is
#: what a stalled generation is capped by, not the whole response duration.
READ_TIMEOUT_S = 120.0
WRITE_TIMEOUT_S = 30.0
POOL_TIMEOUT_S = 10.0

#: 1 initial attempt + 2 retries for rate-limit (429) and server-error (5xx)
#: responses. Backoff doubles per attempt from RETRY_BASE_DELAY_S, capped at
#: RETRY_MAX_DELAY_S, with ±20% jitter so concurrent nodes do not sync up.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_S = 0.5
RETRY_MAX_DELAY_S = 8.0

#: One SDK client per (provider kind, resolved base URL, API key) for the
#: process lifetime — connection reuse across pipeline nodes and loop
#: iterations. The API key is part of the key so rotating a key in Settings
#: takes effect on the next call instead of being masked by the cache.
_CLIENTS: dict[tuple[str, str, str], Any] = {}


def _http_timeout() -> Any:
    """Explicit connect/read/write/pool timeouts shared by HTTP-based SDKs."""
    import httpx

    return httpx.Timeout(
        CONNECT_TIMEOUT_S,
        read=READ_TIMEOUT_S,
        write=WRITE_TIMEOUT_S,
        pool=POOL_TIMEOUT_S,
    )


def _get_cached_client(
    kind: str, base_url: str, api_key: str, factory: Any
) -> Any:
    """Return the cached client for this (kind, base URL, key), building once."""
    key = (kind, base_url, api_key)
    client = _CLIENTS.get(key)
    if client is None:
        client = factory()
        _CLIENTS[key] = client
        logger.debug("Constructed %s client for %s", kind, base_url or "default")
    return client


def _is_retryable(exc: BaseException) -> bool:
    """
    True for rate-limit and server-error responses worth retrying.

    The provider SDKs shape their errors differently (openai/anthropic set
    ``status_code`` on APIStatusError subclasses, google-genai sets ``code``
    on APIError), but the well-known names are stable across versions, so both
    attributes and class names are checked.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int):
        return status == 429 or 500 <= status < 600
    return type(exc).__name__ in {"RateLimitError", "InternalServerError"}


async def _retry_with_backoff(attempt_fn: Any, what: str) -> Any:
    """Await ``attempt_fn()``, retrying retryable failures with backoff."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return await attempt_fn()
        except Exception as exc:  # noqa: BLE001 - classified below
            if not _is_retryable(exc) or attempt == RETRY_ATTEMPTS:
                raise
            delay = min(
                RETRY_MAX_DELAY_S, RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
            )
            delay *= random.uniform(0.8, 1.2)
            logger.warning(
                "%s failed (%s: %s); retrying in %.2fs (attempt %d/%d)",
                what,
                type(exc).__name__,
                exc,
                delay,
                attempt,
                RETRY_ATTEMPTS,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable: retry loop always returns or raises")


class CloudEndpoint(ModelEndpoint):
    id: str

    def __init__(self, provider: str, model_name: str, base_url: str | None = None):
        """
        provider: 'openai', 'anthropic', 'google', or 'openai_compatible'
        """
        self.provider = provider
        self.model_name = model_name
        self.base_url = base_url
        self.id = f"{provider}:{model_name}"

    def check_access(self, policy: AccessPolicy, node_id: str) -> None:
        """
        Refuse a provider the effective policy does not grant.

        Called before generate(), so a denied request is never sent — no API
        key is read, no socket is opened, no credits are spent.
        """
        if self.provider not in policy.providers:
            granted = ", ".join(policy.providers) if policy.providers else "(none)"
            raise AccessDeniedError(
                node_id=node_id,
                capability=f"provider:{self.provider}",
                detail=(
                    f"Node '{node_id}' (model:{self.provider}) requires provider "
                    f"'{self.provider}', which its access policy does not grant. "
                    f"Granted providers: [{granted}]."
                ),
            )

    def _get_api_key(self) -> str:
        # For openai_compatible, we might use the openai key or a specific
        # one; default to the provider name.
        key_name = "openai" if self.provider == "openai_compatible" else self.provider
        api_key = get_secret(key_name)
        if not api_key:
            raise ValueError(
                f"Missing API key for provider '{key_name}' in OS keychain. "
                "Please add it via keyring or Settings."
            )
        return api_key

    async def generate(self, req: GenRequest) -> AsyncIterator[Token]:
        api_key = self._get_api_key()

        if self.provider in (
            "openai",
            "openai_compatible",
            "groq",
            "openrouter",
            "zhipu",
            "nvidia",
        ):
            from openai import AsyncOpenAI

            base_url = self.base_url
            if not base_url:
                if self.provider == "groq":
                    base_url = "https://api.groq.com/openai/v1"
                elif self.provider == "openrouter":
                    base_url = "https://openrouter.ai/api/v1"
                elif self.provider == "zhipu":
                    base_url = "https://open.bigmodel.cn/api/paas/v4"
                elif self.provider == "nvidia":
                    base_url = "https://integrate.api.nvidia.com/v1"

            cache_key = base_url or "https://api.openai.com/v1"
            # max_retries=0: the SDK's own retry loop is disabled so the
            # bounded backoff policy below is the single source of truth.
            client = _get_cached_client(
                f"openai:{self.provider}",
                cache_key,
                api_key,
                lambda: AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=_http_timeout(),
                    max_retries=0,
                ),
            )

            msgs_dicts = [m.model_dump() for m in req.messages]
            kwargs: dict[str, Any] = {
                "model": self.model_name,
                "messages": msgs_dicts,
                "stream": True,
            }
            # Add other params like temperature/max_tokens directly from req
            # if they exist.
            if hasattr(req, "temperature"):
                kwargs["temperature"] = req.temperature
            if hasattr(req, "max_tokens"):
                kwargs["max_tokens"] = req.max_tokens

            if req.response_format == "json":
                kwargs["response_format"] = {"type": "json_object"}

            # Retry only stream creation — once tokens flow the request has
            # been accepted and a mid-stream failure is surfaced as-is.
            stream = await _retry_with_backoff(
                lambda: client.chat.completions.create(**kwargs),
                f"{self.provider} chat completion",
            )
            index = 0
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield Token(text=chunk.choices[0].delta.content, index=index)
                    index += 1

        elif self.provider == "anthropic":
            from anthropic import AsyncAnthropic

            # max_retries=0 — same single retry policy as above.
            client = _get_cached_client(
                "anthropic",
                "https://api.anthropic.com",
                api_key,
                lambda: AsyncAnthropic(
                    api_key=api_key,
                    timeout=_http_timeout(),
                    max_retries=0,
                ),
            )

            # Anthropic handles system message separately
            system_msg = next(
                (m.content for m in req.messages if m.role == "system"), ""
            )
            user_msgs = [m.model_dump() for m in req.messages if m.role != "system"]

            kwargs = {
                "model": self.model_name,
                "messages": user_msgs,
                "max_tokens": getattr(req, "max_tokens", 1024),
            }
            if hasattr(req, "temperature"):
                kwargs["temperature"] = req.temperature
            if system_msg:
                kwargs["system"] = system_msg

            manager = client.messages.stream(**kwargs)
            # The connection is opened on stream entry; that is the retryable
            # boundary. Entering manually (instead of `async with`) lets the
            # retry policy apply without replaying already-streamed tokens.
            stream = await _retry_with_backoff(manager.__aenter__, "anthropic stream")
            try:
                index = 0
                async for text in stream.text_stream:
                    yield Token(text=text, index=index)
                    index += 1
            finally:
                await manager.__aexit__(None, None, None)

        elif self.provider == "google":
            from google import genai

            client = _get_cached_client(
                "google",
                "genai",
                api_key,
                lambda: genai.Client(
                    api_key=api_key,
                    http_options={
                        "api_version": "v1alpha",
                        # genai's http_options timeout is in milliseconds.
                        "timeout": int(READ_TIMEOUT_S * 1000),
                    },
                ),
            )
            contents = [m.content for m in req.messages]
            prompt = "\n".join(contents)

            response_stream = await _retry_with_backoff(
                lambda: client.aio.models.generate_content_stream(
                    model=self.model_name, contents=prompt
                ),
                "google generate_content_stream",
            )
            index = 0
            async for chunk in response_stream:
                if chunk.text:
                    yield Token(text=chunk.text, index=index)
                    index += 1
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    async def health(self) -> Health:
        try:
            self._get_api_key()
            return Health(online=True, loaded=True, warm=True)
        except ValueError:
            return Health(online=False, loaded=False, warm=False)

    def capabilities(self) -> Caps:
        json_mode = self.provider in (
            "openai",
            "openai_compatible",
            "google",
            "groq",
            "openrouter",
            "zhipu",
            "nvidia",
        )
        return Caps(max_context=128000, json_mode=json_mode, tools=True, vision=True)

    def estimate_cost(self, req: GenRequest) -> Cost:
        provider_pricing = PRICING.get(self.provider, {})
        model_pricing = provider_pricing.get(
            self.model_name, {"input": 0.0, "output": 0.0}
        )

        chars = sum(len(m.content) for m in req.messages)
        tokens_in = max(1, chars // 4)
        tokens_out = getattr(req, "max_tokens", 1024)

        cost_in = (tokens_in / 1_000_000) * model_pricing["input"]
        cost_out = (tokens_out / 1_000_000) * model_pricing["output"]

        return Cost(usd=cost_in + cost_out, tokens_in=tokens_in, tokens_out=tokens_out)
