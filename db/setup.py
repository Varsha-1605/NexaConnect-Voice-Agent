import asyncio
import os

from dotenv import load_dotenv

from db.pool import close_pool, get_pool

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


async def main() -> None:
    load_dotenv()
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()

    pool = await get_pool()
    await pool.execute(schema)
    tables = await pool.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    )
    print("Tables:", ", ".join(t["table_name"] for t in tables))
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
