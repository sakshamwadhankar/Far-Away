"""
backend/neuralflow/api/auth.py

Per-session bearer token authentication dependency for FastAPI.

The session token is set by Electron at backend spawn time via the
NEURALFLOW_SESSION_TOKEN environment variable.

DEV MODE: if NEURALFLOW_SESSION_TOKEN is not set, any non-empty bearer token
is accepted and a warning is logged. This allows pytest and manual curl testing
without Electron present.
"""

from __future__ import annotations

import logging
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency — validates the bearer token.

    Returns the token string on success.
    Raises HTTP 401 if the token is missing or invalid.
    """
    session_token = os.environ.get("NEURALFLOW_SESSION_TOKEN")

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

    if session_token is None:
        # Dev mode: no token configured — accept any non-empty value
        logger.warning(
            "NEURALFLOW_SESSION_TOKEN is not set. Running in dev mode: "
            "accepting any bearer token. DO NOT use in production."
        )
        if not provided:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Empty bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return provided

    if provided != session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return provided
