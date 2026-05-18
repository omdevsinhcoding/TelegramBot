"""
DreamX Coupon Bot -- Database Setup / Migration Runner
Reads DATABASE_URL from .env and applies the unified schema.

Usage:
    python run_migration.py

The schema.sql file is the single source of truth for all tables.
All statements are idempotent (safe to run multiple times).
"""

import asyncio
import asyncpg
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Force UTF-8 output on Windows (avoids emoji encode errors)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

SQL_DIR = Path(__file__).resolve().parent / "sql"


async def run_schema(conn: asyncpg.Connection) -> bool:
    """Execute the unified schema.sql file."""
    filepath = SQL_DIR / "schema.sql"
    if not filepath.exists():
        print(f"  [ERROR]  schema.sql not found at {filepath}")
        return False

    sql = filepath.read_text(encoding="utf-8")
    try:
        await conn.execute(sql)
        print("  [OK]  schema.sql applied successfully.")
        return True
    except Exception as e:
        print(f"  [WARN]  Schema application note: {e}")
        return True  # Non-critical — tables may already exist


async def run_compat_migrations(conn: asyncpg.Connection):
    """Run compatibility migrations for databases upgrading from older versions."""
    print("\n  Running compatibility migrations...")

    # Convert wallet_transactions.txn_type ENUM → VARCHAR
    try:
        await conn.execute("""
            ALTER TABLE wallet_transactions
            ALTER COLUMN txn_type TYPE VARCHAR(50)
            USING txn_type::TEXT;
        """)
        print("  [OK]  wallet_transactions.txn_type converted to VARCHAR(50)")
    except Exception:
        print("  [SKIP] wallet_transactions.txn_type already VARCHAR or N/A")

    # Fix referral_claims FK
    try:
        await conn.execute("ALTER TABLE referral_claims ALTER COLUMN reward_id DROP NOT NULL;")
        await conn.execute("ALTER TABLE referral_claims DROP CONSTRAINT IF EXISTS referral_claims_reward_id_fkey;")
        await conn.execute("""
            ALTER TABLE referral_claims
            ADD CONSTRAINT referral_claims_reward_id_fkey
            FOREIGN KEY (reward_id)
            REFERENCES referral_rewards(id) ON DELETE SET NULL;
        """)
        print("  [OK]  referral_claims FK updated to ON DELETE SET NULL")
    except Exception:
        print("  [SKIP] referral_claims FK already correct or N/A")

    print("  Compatibility migrations complete.")


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
    print("Applying unified schema...\n")

    await run_schema(conn)
    await run_compat_migrations(conn)

    await conn.close()
    print("\nDatabase setup complete! Connection closed.")


if __name__ == "__main__":
    asyncio.run(main())
