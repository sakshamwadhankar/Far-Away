"""
backend/komvos/desktop/detection.py

Probing and availability detection for the local desktop automation server.

Follows the existing pattern established by Ollama detection: checks loopback
connectivity on the configured port and reports status so the UI can inform the
user before a run begins.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from komvos.secrets import get_secret

logger = logging.getLogger(__name__)

#: Default port for the computer-server.
#: 8000 collides with the Komvos dev server; 8100 provides an isolated loopback port.
DEFAULT_COMPUTER_SERVER_PORT = 8100


def get_computer_server_port() -> int:
    """Read the configured computer server port from environment or secret."""
    env_port = os.environ.get("KOMVOS_DESKTOP_SERVER_PORT") or os.environ.get(
        "KOMVOS_COMPUTER_SERVER_PORT"
    )
    if env_port and env_port.isdigit():
        return int(env_port)

    saved_port = get_secret("computer_server_port")
    if saved_port and str(saved_port).isdigit():
        return int(saved_port)

    return DEFAULT_COMPUTER_SERVER_PORT


def get_computer_server_url() -> str:
    """
    Get the loopback base URL for the computer server.
    Enforces loopback strictly: remote hosts are rejected.
    """
    custom_url = get_secret("computer_server_url") or os.environ.get(
        "KOMVOS_COMPUTER_SERVER_URL"
    )
    if custom_url:
        custom_url = custom_url.strip().rstrip("/")
        # Verify loopback
        if not (
            "127.0.0.1" in custom_url
            or "localhost" in custom_url
            or "::1" in custom_url
        ):
            logger.warning(
                "Non-loopback URL '%s' rejected for desktop computer server. "
                "Falling back to loopback.",
                custom_url,
            )
        else:
            return custom_url

    port = get_computer_server_port()
    return f"http://127.0.0.1:{port}"


async def probe_computer_server() -> dict[str, Any]:
    """
    Probe the local computer-server status over loopback.
    Returns status payload indicating online status and version metadata.
    """
    base_url = get_computer_server_url()
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            resp = await client.get(f"{base_url}/status")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "online": True,
                    "url": base_url,
                    "status": "ok",
                    "details": data,
                }
    except Exception as exc:
        logger.debug("Computer server not reachable at %s: %s", base_url, exc)

    return {
        "online": False,
        "url": base_url,
        "status": "offline",
        "message": f"Computer server not reachable at {base_url}",
    }


async def is_computer_server_available() -> bool:
    """Quick boolean check whether the desktop computer server is available."""
    res = await probe_computer_server()
    return bool(res.get("online"))
