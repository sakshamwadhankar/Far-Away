"""
backend/komvos/endpoints/ollama.py

OllamaEndpoint implementation for local models using the OpenAI-compatible /v1 API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx

from komvos.compiler.models import AccessPolicy
from komvos.endpoints.base import (
    AccessDeniedError,
    Caps,
    Cost,
    GenRequest,
    Health,
    Token,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client reuse, explicit timeouts, bounded retries.
# These mirror the cloud endpoint policy in endpoints/cloud.py so local and
# remote providers behave identically under failure.
# ---------------------------------------------------------------------------

CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 120.0
WRITE_TIMEOUT_S = 30.0
POOL_TIMEOUT_S = 10.0

RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_S = 0.5
RETRY_MAX_DELAY_S = 8.0

#: One httpx client per base URL for the process lifetime — keeps connections
#: alive across nodes and loop iterations instead of a fresh pool per call.
_CLIENTS: dict[str, httpx.AsyncClient] = {}


def _get_client(base_url: str) -> httpx.AsyncClient:
    """Return the cached AsyncClient for this base URL, building once."""
    client = _CLIENTS.get(base_url)
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                READ_TIMEOUT_S,
                connect=CONNECT_TIMEOUT_S,
                write=WRITE_TIMEOUT_S,
                pool=POOL_TIMEOUT_S,
            )
        )
        _CLIENTS[base_url] = client
    return client


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with ±20% jitter, capped at RETRY_MAX_DELAY_S."""
    delay: float = min(RETRY_MAX_DELAY_S, RETRY_BASE_DELAY_S * (2 ** (attempt - 1)))
    return delay * random.uniform(0.8, 1.2)


def _retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


class OllamaEndpoint:
    """
    Ollama backend for local model inference via OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        id: str,
        base_url: str = "http://127.0.0.1:11434/v1",
        model: str = "qwen2.5:3b",
    ):
        self.id = id
        self._base_url = base_url.rstrip("/")
        self._model = model

    def check_access(self, policy: AccessPolicy, node_id: str) -> None:
        """
        Refuse to run a local model when the effective policy withholds it.

        Called before generate(), so no request reaches the Ollama server.
        """
        if not policy.allow_local_models:
            raise AccessDeniedError(
                node_id=node_id,
                capability="allow_local_models",
                detail=(
                    f"Node '{node_id}' (model:ollama) requires local models, "
                    "which its access policy does not grant."
                ),
            )

    async def generate(self, req: GenRequest) -> AsyncIterator[Token]:
        formatted_messages: list[dict[str, Any]] = []
        for msg in req.messages:
            if msg.images:
                parts: list[dict[str, Any]] = [{"type": "text", "text": msg.content}]
                for img in msg.images:
                    url = (
                        img
                        if img.startswith("data:")
                        else f"data:image/jpeg;base64,{img}"
                    )
                    parts.append({"type": "image_url", "image_url": {"url": url}})
                formatted_messages.append({"role": msg.role, "content": parts})
            else:
                formatted_messages.append({"role": msg.role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": formatted_messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if req.response_format == "json":
            if req.json_schema:
                # Schema-constrained decoding. Plain json_object only promises
                # parseable JSON — a small model asked for a desktop action
                # returns {"nextAction": "..."} and the caller has nothing to
                # act on. Pinning the schema is what makes local models usable.
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_response",
                        "schema": req.json_schema,
                        "strict": True,
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}

        client = _get_client(self._base_url)

        # Retryable boundary is stream opening: a 429/5xx status or a
        # connection-level failure gets bounded exponential backoff. Once the
        # stream is open and returning bytes, failures surface as-is.
        attempt = 0
        while True:
            attempt += 1
            request = client.build_request(
                "POST",
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={"ngrok-skip-browser-warning": "true"},
            )
            try:
                response = await client.send(request, stream=True)
            except httpx.TransportError as exc:
                if attempt >= RETRY_ATTEMPTS:
                    raise
                delay = _backoff_delay(attempt)
                logger.warning(
                    "Ollama connection failed (%s); retrying in %.2fs "
                    "(attempt %d/%d)",
                    exc,
                    delay,
                    attempt,
                    RETRY_ATTEMPTS,
                )
                await asyncio.sleep(delay)
                continue
            if _retryable_status(response.status_code) and attempt < RETRY_ATTEMPTS:
                delay = _backoff_delay(attempt)
                logger.warning(
                    "Ollama returned %d; retrying in %.2fs (attempt %d/%d)",
                    response.status_code,
                    delay,
                    attempt,
                    RETRY_ATTEMPTS,
                )
                await response.aclose()
                await asyncio.sleep(delay)
                continue
            break

        try:
            response.raise_for_status()
            idx = 0
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        cost_obj = None
                        usage = data.get("usage")
                        if usage:
                            tin = int(usage.get("prompt_tokens", 0) or 0)
                            tout = int(usage.get("completion_tokens", 0) or 0)
                            cost_obj = self.calculate_cost(
                                tin, tout, is_estimate=False
                            )

                        choices = data.get("choices", [])
                        if choices and "delta" in choices[0]:
                            text = choices[0]["delta"].get("content", "")
                            if text:
                                yield Token(
                                    text=text, index=idx, usage=cost_obj
                                )
                                idx += 1
                        elif cost_obj is not None:
                            yield Token(text="", index=idx, usage=cost_obj)
                            idx += 1
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to decode stream line: {data_str}")
        finally:
            await response.aclose()

    async def health(self) -> Health:
        try:
            client = _get_client(self._base_url)
            resp = await client.get(f"{self._base_url}/models", timeout=2.0)
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                loaded = any(m.get("id") == self._model for m in models)
                return Health(online=True, loaded=loaded, warm=loaded)
        except httpx.RequestError:
            pass
        return Health(online=False, loaded=False, warm=False)

    def capabilities(self) -> Caps:
        is_vision = any(
            tag in self._model.lower()
            for tag in ("vision", "llava", "vl", "bakllava", "minicpm", "moondream")
        )
        return Caps(
            max_context=8192,
            json_mode=True,
            tools=False,
            vision=is_vision,
        )

    def calculate_cost(
        self, tokens_in: int, tokens_out: int, is_estimate: bool = False
    ) -> Cost:
        return Cost(
            usd=0.0,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            is_estimate=is_estimate,
        )

    def estimate_cost(self, req: GenRequest) -> Cost:
        tokens_in = sum(len(msg.content) // 4 for msg in req.messages)
        return self.calculate_cost(tokens_in, 0, is_estimate=True)

