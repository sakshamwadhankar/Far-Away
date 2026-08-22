"""
backend/komvos/endpoints/hermes.py

Hermes Agent connection and detection helper.

Hermes Agent (github.com/NousResearch/hermes-agent, port 8642) is an
OpenAI-compatible server that turns local or remote models into autonomous
subagents.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from komvos.secrets import get_secret

logger = logging.getLogger(__name__)

DEFAULT_HERMES_URL = "http://127.0.0.1:8642/v1"


def get_hermes_base_url() -> str:
    """
    Get the configured Hermes base URL from env, secret, or default.
    """
    env_url = os.environ.get("KOMVOS_HERMES_URL")
    if env_url:
        return env_url.rstrip("/")
    saved = get_secret("hermes_base_url")
    if saved and saved.startswith("http"):
        return saved.rstrip("/")
    return DEFAULT_HERMES_URL


async def probe_hermes_server() -> dict[str, Any]:
    """
    Probe the Hermes Agent server for liveness and model availability.
    """
    base_url = get_hermes_base_url()
    models_url = f"{base_url}/models" if not base_url.endswith("/models") else base_url
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            resp = await client.get(models_url)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                return {
                    "status": "ok",
                    "message": "Hermes Agent is running",
                    "base_url": base_url,
                    "models": [m.get("id") for m in models if isinstance(m, dict)],
                }
    except Exception as exc:
        logger.debug(f"Hermes Agent probe failed at {models_url}: {exc}")

    return {
        "status": "error",
        "message": f"Hermes Agent not reachable at {base_url}",
        "base_url": base_url,
    }
