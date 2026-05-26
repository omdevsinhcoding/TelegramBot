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


async def run_orders_fk_migration(conn: asyncpg.Connection):
    """Make orders.coupon_id nullable so deleting a coupon preserves order history."""
    print("\n  Running orders FK migration...")

    # 1. Drop NOT NULL on coupon_id
    try:
        await conn.execute("ALTER TABLE orders ALTER COLUMN coupon_id DROP NOT NULL;")
        print("  [OK]  orders.coupon_id is now nullable")
    except Exception:
        print("  [SKIP] orders.coupon_id already nullable or N/A")

    # 2. Update FK to ON DELETE SET NULL (drop old FK, add new one)
    try:
        await conn.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_coupon_id_fkey;")
        await conn.execute("""
            ALTER TABLE orders
            ADD CONSTRAINT orders_coupon_id_fkey
            FOREIGN KEY (coupon_id)
            REFERENCES coupons(id) ON DELETE SET NULL;
        """)
        print("  [OK]  orders FK updated to ON DELETE SET NULL")
    except Exception as e:
        print(f"  [SKIP] orders FK already correct or N/A: {e}")

    print("  Orders FK migration complete.")


async def run_v9_stock_expense_migration(conn: asyncpg.Connection):
    """Add stock alert, stock logging, and expense tracking tables (v9)."""
    print("\n  Running v9 stock/expense migration...")

    # 1. stock_alert_settings table
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_alert_settings (
                id              SERIAL PRIMARY KEY,
                global_threshold INTEGER DEFAULT 5,
                is_enabled      BOOLEAN DEFAULT TRUE,
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
            INSERT INTO stock_alert_settings (global_threshold, is_enabled)
            SELECT 5, TRUE WHERE NOT EXISTS (SELECT 1 FROM stock_alert_settings);
        """)
        print("  [OK]  stock_alert_settings table ready")
    except Exception as e:
        print(f"  [SKIP] stock_alert_settings: {e}")

    # 2. stock_alerts_sent table
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_alerts_sent (
                id          SERIAL PRIMARY KEY,
                coupon_id   INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
                stock_level INTEGER NOT NULL,
                alerted_at  TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(coupon_id, stock_level)
            );
            CREATE INDEX IF NOT EXISTS idx_stock_alerts_coupon ON stock_alerts_sent (coupon_id);
        """)
        print("  [OK]  stock_alerts_sent table ready")
    except Exception as e:
        print(f"  [SKIP] stock_alerts_sent: {e}")

    # 3. coupon_stock_logs table
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS coupon_stock_logs (
                id              SERIAL PRIMARY KEY,
                coupon_id       INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
                admin_id        BIGINT NOT NULL,
                action          VARCHAR(32) NOT NULL,
                quantity        INTEGER NOT NULL DEFAULT 0,
                cost_per_unit   NUMERIC(10, 2) DEFAULT 0.00,
                total_cost      NUMERIC(12, 2) DEFAULT 0.00,
                notes           TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_stock_logs_coupon ON coupon_stock_logs (coupon_id);
            CREATE INDEX IF NOT EXISTS idx_stock_logs_admin ON coupon_stock_logs (admin_id);
            CREATE INDEX IF NOT EXISTS idx_stock_logs_created ON coupon_stock_logs (created_at);
        """)
        print("  [OK]  coupon_stock_logs table ready")
    except Exception as e:
        print(f"  [SKIP] coupon_stock_logs: {e}")

    # 4. admin_expenses table
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_expenses (
                id              SERIAL PRIMARY KEY,
                admin_id        BIGINT NOT NULL,
                expense_type    VARCHAR(64) NOT NULL,
                amount          NUMERIC(12, 2) NOT NULL,
                description     TEXT,
                coupon_id       INTEGER REFERENCES coupons(id) ON DELETE SET NULL,
                reference       TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_expenses_admin ON admin_expenses (admin_id);
            CREATE INDEX IF NOT EXISTS idx_expenses_type ON admin_expenses (expense_type);
            CREATE INDEX IF NOT EXISTS idx_expenses_created ON admin_expenses (created_at);
        """)
        print("  [OK]  admin_expenses table ready")
    except Exception as e:
        print(f"  [SKIP] admin_expenses: {e}")

    # 5. Add cost_per_unit column to coupons (tracks acquisition cost)
    try:
        await conn.execute("""
            ALTER TABLE coupons ADD COLUMN IF NOT EXISTS cost_per_unit NUMERIC(10, 2) DEFAULT 0.00;
        """)
        print("  [OK]  coupons.cost_per_unit column added")
    except Exception as e:
        print(f"  [SKIP] coupons.cost_per_unit: {e}")

    print("  v9 migration complete.")


async def run_v10_display_title_migration(conn: asyncpg.Connection):
    """Add display_title column to orders for giveaway/custom title support (v10)."""
    print("\n  Running v10 display_title migration...")

    try:
        await conn.execute("""
            ALTER TABLE orders ADD COLUMN display_title TEXT;
        """)
        print("  [OK]  orders.display_title column added")
    except Exception:
        print("  [SKIP] orders.display_title already exists")

    print("  v10 migration complete.")


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
    await run_orders_fk_migration(conn)
    await run_v9_stock_expense_migration(conn)
    await run_v10_display_title_migration(conn)

    await conn.close()
    print("\nDatabase setup complete! Connection closed.")


if __name__ == "__main__":
    asyncio.run(main())
