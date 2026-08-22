import json
import os
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

# Load pricing table
PRICING_FILE = os.path.join(os.path.dirname(__file__), "pricing.json")
try:
    with open(PRICING_FILE) as f:
        PRICING = json.load(f)
except FileNotFoundError:
    PRICING = {}


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

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)

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

            stream = await client.chat.completions.create(**kwargs)
            index = 0
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield Token(text=chunk.choices[0].delta.content, index=index)
                    index += 1

        elif self.provider == "anthropic":
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=api_key)

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

            async with client.messages.stream(**kwargs) as stream:
                index = 0
                async for text in stream.text_stream:
                    yield Token(text=text, index=index)
                    index += 1

        elif self.provider == "google":
            from google import genai

            client = genai.Client(
                api_key=api_key, http_options={"api_version": "v1alpha"}
            )
            contents = [m.content for m in req.messages]
            prompt = "\n".join(contents)

            response_stream = await client.aio.models.generate_content_stream(
                model=self.model_name, contents=prompt
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
