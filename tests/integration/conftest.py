"""Integration tests run against the Neon `test` branch and nowhere else.

Put its connection strings in .env: TEST_DATABASE_URL (the limited app_user the agent uses) and
TEST_ADMIN_DATABASE_URL (the owner, used only to create tables and empty them). Every test starts with the tables emptied,
so these tests refuse to run unless the target is clearly not the production database.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from dotenv import load_dotenv

import asyncpg

from db.pool import clean_url, close_pool

load_dotenv()
PRODUCTION_URL = os.environ.get("DATABASE_URL")
TEST_URL = os.environ.get("TEST_DATABASE_URL")
TEST_ADMIN_URL = os.environ.get("TEST_ADMIN_DATABASE_URL")

TABLES = "verification_failures, support_tickets, bills, account_changes, cancellations, enrollments"
SCHEMA = (Path(__file__).resolve().parents[2] / "db" / "schema.sql").read_text(encoding="utf-8")


schema_applied = False  # the schema only needs to be applied once per run


def host(url: str) -> str:
    return urlsplit(url).hostname or ""


@pytest.fixture(autouse=True)
async def test_database(monkeypatch):
    if not TEST_URL or not TEST_ADMIN_URL:
        pytest.skip("TEST_DATABASE_URL and TEST_ADMIN_DATABASE_URL must both be set")
    assert TEST_URL != PRODUCTION_URL, "TEST_DATABASE_URL must not be the production database"
    assert not PRODUCTION_URL or host(TEST_URL) != host(PRODUCTION_URL), (
        "TEST_DATABASE_URL points at the same server as DATABASE_URL; use the Neon `test` branch"
    )
    monkeypatch.setenv("DATABASE_URL", TEST_URL)  # the pool reads it when it opens
    global schema_applied
    admin = await asyncpg.connect(clean_url(TEST_ADMIN_URL), statement_cache_size=0)
    try:
        if not schema_applied:
            await admin.execute(SCHEMA)  # adds anything missing; safe to run again
            schema_applied = True
        await admin.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    finally:
        await admin.close()
    yield
    await close_pool()
