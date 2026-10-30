import asyncio
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

from config import (
    DB_CONNECT_TIMEOUT,
    DB_IDLE_CONNECTION_SECONDS,
    DB_POOL_MAX,
    DB_POOL_MIN,
    DB_QUERY_TIMEOUT,
    DB_READ_RETRY_DELAY,
)

_pool: asyncpg.Pool | None = None


def clean_url(url: str) -> str:
    # asyncpg rejects channel_binding
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "channel_binding"]
    return urlunsplit(parts._replace(query=urlencode(query)))


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set in .env")
    return clean_url(url)


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            _dsn(),
            min_size=DB_POOL_MIN,
            max_size=DB_POOL_MAX,
            # needed for Neon pooled endpoint
            statement_cache_size=0,
            command_timeout=DB_QUERY_TIMEOUT,
            timeout=DB_CONNECT_TIMEOUT,
            max_inactive_connection_lifetime=DB_IDLE_CONNECTION_SECONDS,
        )
    return _pool


async def get_pool() -> asyncpg.Pool:
    return _pool or await init_pool()


# retry dropped connections, not bad queries
RETRYABLE_ERRORS = (
    asyncpg.PostgresConnectionError,
    asyncpg.InterfaceError,
    ConnectionError,
    OSError,
    TimeoutError,
)


async def run_read_with_retry(read):
    try:
        return await read()
    except RETRYABLE_ERRORS:
        await asyncio.sleep(DB_READ_RETRY_DELAY)
        return await read()


async def read_rows(query: str, *args) -> list:
    return await run_read_with_retry(lambda: _pool_call("fetch", query, args))


async def read_row(query: str, *args):
    return await run_read_with_retry(lambda: _pool_call("fetchrow", query, args))


async def read_value(query: str, *args):
    return await run_read_with_retry(lambda: _pool_call("fetchval", query, args))


async def _pool_call(method: str, query: str, args: tuple):
    return await getattr(await get_pool(), method)(query, *args)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
