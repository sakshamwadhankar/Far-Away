"""
backend/neuralflow/endpoints/ollama.py

OllamaEndpoint implementation for local models using the OpenAI-compatible /v1 API.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from neuralflow.endpoints.base import Caps, Cost, GenRequest, Health, ModelEndpoint, Token

logger = logging.getLogger(__name__)


class OllamaEndpoint:
    """
    Ollama backend for local model inference via OpenAI-compatible endpoint.
    """

    def __init__(self, id: str, base_url: str = "http://127.0.0.1:11434/v1", model: str = "qwen2.5:3b"):
        self.id = id
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def generate(self, req: GenRequest) -> AsyncIterator[Token]:
        payload = {
            "model": self._model,
            "messages": [msg.model_dump() for msg in req.messages],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True}
        }
        if req.response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        idx = 0
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", 
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={"ngrok-skip-browser-warning": "true"}
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices and "delta" in choices[0]:
                                text = choices[0]["delta"].get("content", "")
                                if text:
                                    yield Token(text=text, index=idx)
                                    idx += 1
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode stream line: {data_str}")

    async def health(self) -> Health:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._base_url}/models")
                if resp.status_code == 200:
                    models = resp.json().get("data", [])
                    loaded = any(m.get("id") == self._model for m in models)
                    return Health(online=True, loaded=loaded, warm=loaded)
        except httpx.RequestError:
            pass
        return Health(online=False, loaded=False, warm=False)

    def capabilities(self) -> Caps:
        return Caps(
            max_context=8192,
            json_mode=True,
            tools=False,
            vision=False,
        )

    def estimate_cost(self, req: GenRequest) -> Cost:
        tokens_in = sum(len(msg.content) // 4 for msg in req.messages)
        return Cost(
            usd=0.0,
            tokens_in=tokens_in,
            tokens_out=0,
        )
