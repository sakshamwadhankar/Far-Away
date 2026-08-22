"""
backend/komvos/api/auth.py

Per-session bearer token authentication for FastAPI (HTTP and WebSocket).

The session token is set by Electron at backend spawn time via the
KOMVOS_SESSION_TOKEN environment variable.

SECURITY — fail closed. There are exactly two ways a request authenticates:

  1. KOMVOS_SESSION_TOKEN is set (or its pre-rename alias
     NEURALFLOW_SESSION_TOKEN), and the caller presents that exact token.
  2. No token is configured *and* KOMVOS_DEV=1, in which case any non-empty
     token is accepted so pytest and curl can drive the API.

Anything else is a 401. In particular, an unset session token on its own is
NOT a bypass: without an explicit KOMVOS_DEV=1 opt-in, a backend started with
no token configured rejects every request rather than accepting every request.
"""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

#: Env var that must be exactly "1" to enable developer conveniences —
#: the tokenless auth fallback, localhost CORS origins, and /docs.
DEV_MODE_ENV_VAR = "KOMVOS_DEV"

SESSION_TOKEN_ENV_VAR = "KOMVOS_SESSION_TOKEN"

#: Pre-rename alias, accepted for one release with a deprecation warning.
LEGACY_SESSION_TOKEN_ENV_VAR = "NEURALFLOW_SESSION_TOKEN"


def is_dev_mode() -> bool:
    """
    True only when KOMVOS_DEV is explicitly set to "1".

    Read at call time, not import time, so tests and the Electron spawn path
    can set it per-process without import-order surprises.
    """
    return os.environ.get(DEV_MODE_ENV_VAR) == "1"


def session_token() -> str | None:
    """The configured session token, or None if the backend started without one."""
    value = os.environ.get(SESSION_TOKEN_ENV_VAR)
    if value is not None:
        return value
    # One-release compatibility with the pre-rename variable name.
    legacy = os.environ.get(LEGACY_SESSION_TOKEN_ENV_VAR)
    if legacy is not None:
        logger.warning(
            "Environment variable %s is deprecated and will be removed in a "
            "future release; set %s instead.",
            LEGACY_SESSION_TOKEN_ENV_VAR,
            SESSION_TOKEN_ENV_VAR,
        )
    return legacy


def check_token(provided: str | None) -> bool:
    """
    Core auth decision, shared by the HTTP dependency and the WebSocket handler.

    Returns True if `provided` authenticates. Compared with
    `hmac.compare_digest` so a wrong token cannot be recovered by timing.
    """
    if not provided:
        return False

    configured = session_token()

    if configured is None:
        # No token configured. Only a deliberate KOMVOS_DEV=1 opt-in makes this
        # acceptable; otherwise fail closed.
        if not is_dev_mode():
            return False
        logger.warning(
            "%s is not set and %s=1: accepting any non-empty bearer token. "
            "DO NOT use this outside local development.",
            SESSION_TOKEN_ENV_VAR,
            DEV_MODE_ENV_VAR,
        )
        return True

    return hmac.compare_digest(provided, configured)


def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency — validates the bearer token.

    Returns the token string on success.
    Raises HTTP 401 if the token is missing, empty, or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing Authorization header. "
                "Expected: Authorization: Bearer <token>"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided = credentials.credentials

    if not check_token(provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing session token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return provided
