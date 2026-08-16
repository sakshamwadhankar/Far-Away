"""Shared pytest fixtures.

The HTTP client fixtures are defined in ``tests.test_api`` alongside the
endpoint registry they configure. Re-exporting them here makes pytest collect
them for *every* test module, so no test file has to import a fixture from
another test file (which reads as an unused import to linters).
"""

from __future__ import annotations

from tests.test_api import client, slow_client

__all__ = ["client", "slow_client"]
