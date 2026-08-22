"""
backend/komvos/serve/keys.py

Deployment key generation, hashing, and verification.

Deployment keys are a SEPARATE credential from the Electron session token
(komvos.api.auth). The session token authenticates the desktop app talking
to its own local backend; a deployment key authenticates a THIRD PARTY (curl,
LangChain, OpenWebUI, ...) talking to one specific deployed pipeline. They must
never be interchangeable, so this module deliberately shares no code with
api/auth.py.

Non-negotiable rules (see upgrade.md Phase 3.4):
  - Format: "kv_" + 32 bytes of secrets.token_urlsafe.
  - Only a SHA-256 hash is ever stored. The plaintext exists only in the
    process's memory during the single response that creates or rotates it.
  - Comparisons use hmac.compare_digest to avoid timing side-channels.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

KEY_PREFIX = "kv_"


def generate_key() -> tuple[str, str]:
    """
    Generate a new deployment key.

    Returns (plaintext, sha256_hex). The caller must persist ONLY the hash and
    return the plaintext to the user exactly once.
    """
    plaintext = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return plaintext, hash_key(plaintext)


def hash_key(plaintext: str) -> str:
    """SHA-256 hex digest of a deployment key."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def verify_key(plaintext: str, stored_hash: str) -> bool:
    """
    Constant-time comparison of a presented key against a stored hash.

    Rejects anything not shaped like a deployment key before hashing, so a
    request presenting, say, a session token never even reaches the digest
    comparison.
    """
    if not plaintext.startswith(KEY_PREFIX):
        return False
    return hmac.compare_digest(hash_key(plaintext), stored_hash)
