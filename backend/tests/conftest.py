"""Shared pytest fixtures.

The HTTP client fixtures are defined in ``tests.test_api`` alongside the
endpoint registry they configure. Re-exporting them here makes pytest collect
them for *every* test module, so no test file has to import a fixture from
another test file (which reads as an unused import to linters).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from komvos.api.auth import DEV_MODE_ENV_VAR
from tests.test_api import client, slow_client

__all__ = ["client", "slow_client"]


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    Opt every test into dev-mode auth explicitly.

    Auth fails closed: with no KOMVOS_SESSION_TOKEN configured, requests are
    rejected unless KOMVOS_DEV=1 is set deliberately. The suite drives the API
    without Electron, so it sets that flag itself rather than leaning on an
    implicit fallback. Tests that exercise the fail-closed path delete the var
    with their own monkeypatch.
    """
    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    # Never inherit a real session token from the developer's shell — under
    # either the current or the pre-rename variable name.
    monkeypatch.delenv("KOMVOS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("NEURALFLOW_SESSION_TOKEN", raising=False)
    yield


@pytest.fixture(autouse=True)
def _restore_env() -> Iterator[None]:
    """
    Snapshot and restore os.environ around every test.

    Several tests set KOMVOS_SESSION_TOKEN or the mock-endpoint gate
    directly rather than through monkeypatch; this keeps that from leaking into
    the next test.
    """
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def _reset_provider_client_caches() -> Iterator[None]:
    """
    Clear the per-process HTTP client caches around every test.

    endpoints/cloud.py and endpoints/ollama.py cache one client per
    provider/base-url for the life of the process — correct in production,
    but it makes tests order-dependent: a client built by an earlier test
    survives a later test's monkeypatch of httpx.AsyncClient.
    """
    from komvos.endpoints import cloud as _cloud
    from komvos.endpoints import ollama as _ollama

    _cloud._CLIENTS.clear()
    _ollama._CLIENTS.clear()
    yield
    _cloud._CLIENTS.clear()
    _ollama._CLIENTS.clear()
