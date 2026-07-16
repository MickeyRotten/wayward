"""Test bootstrap.

CRITICAL: WAYWARD_DATA_DIR must point at a throwaway directory BEFORE any
``server.*`` module is imported — server/db/database.py resolves its data root
at import time. This keeps the suite from ever touching a real server/data
(worlds, saves, characters).
"""

import asyncio
import os
import tempfile

_TMP_DATA = tempfile.mkdtemp(prefix="wayward-test-data-")
os.environ["WAYWARD_DATA_DIR"] = _TMP_DATA

import pytest  # noqa: E402


def run(coro):
    """Run a coroutine to completion from a sync test."""
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def client():
    """One app instance for the whole session, on the throwaway data dir.
    Boot creates a fresh Fantasy campaign (Hero + Varena) via the template
    path — tests may rely on that seed content."""
    from fastapi.testclient import TestClient
    from server.main import app

    with TestClient(app) as c:
        yield c
