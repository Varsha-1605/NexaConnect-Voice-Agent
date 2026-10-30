import asyncio
import os

from dotenv import load_dotenv

import asyncpg

from db.pool import clean_url

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


async def main() -> None:
    load_dotenv()
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()

    # Tables are created with the owner connection; the agent's own role cannot change tables.
    admin_url = os.environ.get("ADMIN_DATABASE_URL")
    if not admin_url:
        raise SystemExit("ADMIN_DATABASE_URL is not set in .env (the owner connection string)")
    connection = await asyncpg.connect(clean_url(admin_url), statement_cache_size=0)
    try:
        await connection.execute(schema)
        tables = await connection.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        print("Tables:", ", ".join(t["table_name"] for t in tables))
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
