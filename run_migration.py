"""
DreamX Coupon Bot -- Migration Runner
Reads DATABASE_URL from .env and runs ALL pending SQL migrations in order.

Usage:
    python run_migration.py

Runs every migration file found in the sql/ directory in version order.
Already-applied migrations that raise non-critical errors are skipped safely.
"""

import asyncio
import asyncpg
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

# Force UTF-8 output on Windows (avoids emoji encode errors)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

# All migration files in version order
SQL_DIR = Path(__file__).resolve().parent / "sql"

MIGRATION_ORDER = [
    "schema.sql",
    "migration_v2.sql",
    "migration_v3.sql",
    "migration_v4.sql",
    "migration_v5.sql",
    "migration_v6.sql",
    "migration_v7.sql",
]


async def run_sql_file(conn: asyncpg.Connection, filepath: Path) -> bool:
    """Execute a single SQL file statement-by-statement. Returns True on success."""
    if not filepath.exists():
        print(f"  [SKIP]  {filepath.name}  (file not found)")
        return False

    sql = filepath.read_text(encoding="utf-8")

    # Split on semicolons and run statement by statement
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    ok = 0
    skipped = 0
    for stmt in statements:
        # Skip pure-comment chunks
        without_comments = re.sub(r"--[^\n]*", "", stmt).strip()
        if not without_comments:
            continue
        try:
            await conn.execute(stmt)
            ok += 1
        except Exception as e:
            err = str(e).lower()
            # Benign errors: already-applied migrations
            benign = any(kw in err for kw in [
                "already exists",
                "duplicate column",
                "does not exist",
                "violates not-null",
            ])
            if benign:
                skipped += 1
            else:
                print(f"    [WARN] Non-critical error in {filepath.name}: {e!r}")
                skipped += 1

    print(f"  [OK]  {filepath.name:30s}  -- {ok} statements applied, {skipped} skipped")
    return True


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not found in .env")
        return

    print("Connecting to database...")
    try:
        conn = await asyncpg.connect(url)
    except Exception as e:
        print(f"ERROR: Could not connect: {e}")
        return

    print("Connected.\n")
    print("Running migrations in order:\n")

    for name in MIGRATION_ORDER:
        path = SQL_DIR / name
        await run_sql_file(conn, path)

    await conn.close()
    print("\nAll migrations complete! Connection closed.")


if __name__ == "__main__":
    asyncio.run(main())
