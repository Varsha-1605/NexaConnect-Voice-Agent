import argparse
import asyncio
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import asyncpg
from dotenv import load_dotenv

from db.pool import clean_url

ROLE = "app_user"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def url_for_role(admin_url: str, password: str) -> str:
    parts = urlsplit(admin_url)
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=f"{ROLE}:{quote(password, safe='')}@{host}"))


def set_env_value(name: str, value: str) -> None:
    text = ENV_FILE.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    line = f"{name}={value}"
    if re.search(rf"^{name}=.*$", text, flags=re.M):
        text = re.sub(rf"^{name}=.*$", lambda _: line, text, flags=re.M)
    else:
        text = text.rstrip("\r\n") + newline + line + newline
    ENV_FILE.write_text(text, encoding="utf-8", newline="")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="use the Neon test branch")
    parser.add_argument("--rotate", action="store_true", help="set a new password for an existing role")
    args = parser.parse_args()

    load_dotenv(ENV_FILE)
    admin_name = "TEST_ADMIN_DATABASE_URL" if args.test else "ADMIN_DATABASE_URL"
    app_name = "TEST_DATABASE_URL" if args.test else "DATABASE_URL"
    admin_url = os.environ.get(admin_name)
    if not admin_url:
        raise SystemExit(f"{admin_name} is not set in .env (the owner connection string)")

    connection = await asyncpg.connect(clean_url(admin_url), statement_cache_size=0)
    try:
        exists = await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", ROLE)
        password = None
        if not exists or args.rotate:
            password = secrets.token_urlsafe(24)
            verb = "ALTER" if exists else "CREATE"
            # password is inlined: role statements take no parameters
            await connection.execute(f"{verb} ROLE {ROLE} LOGIN PASSWORD '{password}'")
        await connection.execute(
            f"""
            REVOKE ALL ON SCHEMA public FROM {ROLE};
            GRANT USAGE ON SCHEMA public TO {ROLE};
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE};
            GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {ROLE};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO {ROLE};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE};
            """
        )
    finally:
        await connection.close()

    if password:
        set_env_value(app_name, url_for_role(admin_url, password))
        print(f"{ROLE} {'updated' if exists else 'created'}; {app_name} in .env now uses it.")
    else:
        print(f"{ROLE} already exists; privileges refreshed. Use --rotate to set a new password.")


if __name__ == "__main__":
    asyncio.run(main())
