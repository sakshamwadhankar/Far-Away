"""Shared helpers for reading secrets from the OS keychain."""

import keyring

SERVICE = "komvos"
_LEGACY_SERVICE = "neuralflow"


def get_secret(key_name: str) -> str | None:
    """
    Return a secret stored under ``key_name`` from the OS keychain.

    Reads from the current "komvos" service first and falls back to the
    legacy "neuralflow" service so keys saved before the rename keep working.
    """
    return keyring.get_password(SERVICE, key_name) or keyring.get_password(
        _LEGACY_SERVICE, key_name
    )
