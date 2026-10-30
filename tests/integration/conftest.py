"""Integration tests run against the Neon `test` branch and nowhere else.

Put its connection string in .env as TEST_DATABASE_URL. Every test starts with the tables emptied,
so these tests refuse to run unless the target is clearly not the production database.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from dotenv import load_dotenv

from db.pool import close_pool, get_pool

load_dotenv()
PRODUCTION_URL = os.environ.get("DATABASE_URL")
TEST_URL = os.environ.get("TEST_DATABASE_URL")

TABLES = "verification_failures, support_tickets, bills, account_changes, cancellations, enrollments"
SCHEMA = (Path(__file__).resolve().parents[2] / "db" / "schema.sql").read_text(encoding="utf-8")


schema_applied = False  # the schema only needs to be applied once per run


def host(url: str) -> str:
    return urlsplit(url).hostname or ""


@pytest.fixture(autouse=True)
async def test_database(monkeypatch):
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    assert TEST_URL != PRODUCTION_URL, "TEST_DATABASE_URL must not be the production database"
    assert not PRODUCTION_URL or host(TEST_URL) != host(PRODUCTION_URL), (
        "TEST_DATABASE_URL points at the same server as DATABASE_URL; use the Neon `test` branch"
    )
    monkeypatch.setenv("DATABASE_URL", TEST_URL)  # the pool reads it when it opens
    global schema_applied
    pool = await get_pool()
    if not schema_applied:
        await pool.execute(SCHEMA)  # adds anything missing; safe to run again
        schema_applied = True
    await pool.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    yield
    await close_pool()
