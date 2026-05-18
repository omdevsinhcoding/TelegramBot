"""
DreamX Coupon Bot — Database Connection Pool
Async PostgreSQL connection management using asyncpg.

Key features:
  - Auto-reconnection on pool failure
  - Health checks before returning pool
  - Graceful retry with exponential backoff
  - Schema auto-applied on first connect
"""

import asyncio
import time
import asyncpg
from pathlib import Path
from bot.config import Config
from bot.utils.logger import logger

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()
_db_ready = asyncio.Event()
_last_health_check: float = 0.0
_HEALTH_CHECK_INTERVAL = 30.0  # seconds between health checks


async def get_pool() -> asyncpg.Pool:
    """Return a healthy connection pool. Auto-reconnects if the pool is dead.

    Health checks are rate-limited to every 30s to avoid overhead.
    """
    global _pool, _last_health_check

    # Fast path — pool exists
    if _pool is not None:
        now = time.monotonic()
        # Only run health check every N seconds
        if (now - _last_health_check) >= _HEALTH_CHECK_INTERVAL:
            try:
                async with _pool.acquire(timeout=5) as conn:
                    await conn.execute("SELECT 1")
                _last_health_check = now
                return _pool
            except Exception as e:
                logger.warning(f"Pool health check failed: {e}. Reconnecting...")
                try:
                    await _pool.close()
                except Exception:
                    pass
                _pool = None
        else:
            return _pool

    # Reconnection with lock to prevent multiple simultaneous reconnects
    async with _pool_lock:
        # Double-check after acquiring lock (another coroutine may have reconnected)
        if _pool is not None:
            return _pool

        logger.info("Attempting database reconnection...")
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                _pool = await asyncpg.create_pool(
                    dsn=Config.DATABASE_URL,
                    min_size=2,
                    max_size=10,
                    command_timeout=60,
                )
                logger.info(f"Database reconnected successfully (attempt {attempt})")
                _db_ready.set()
                return _pool
            except Exception as e:
                wait_time = min(2 ** attempt, 30)
                logger.error(
                    f"Reconnection attempt {attempt}/{max_retries} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait_time)

        raise RuntimeError(
            "Database pool could not be established after multiple retries."
        )


async def wait_for_db(timeout: float = 60.0):
    """Block until the database pool is ready. Used by background tasks."""
    try:
        await asyncio.wait_for(_db_ready.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"Database did not become ready within {timeout}s")


async def init_db() -> asyncpg.Pool:
    """Initialize the database pool and apply schema.

    The schema.sql file is the single source of truth.
    All statements use IF NOT EXISTS / IF EXISTS, making it safe
    to run on both fresh and existing databases.
    """
    global _pool, _last_health_check
    dsn = Config.DATABASE_URL
    if not dsn:
        raise RuntimeError("DATABASE_URL is required in .env")

    logger.info("Connecting to PostgreSQL...")
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10, command_timeout=60)

    # Apply the unified schema (idempotent — safe on existing DBs)
    schema_path = Path(__file__).resolve().parent.parent.parent / "sql" / "schema.sql"
    if schema_path.exists():
        async with _pool.acquire() as conn:
            try:
                await conn.execute(schema_path.read_text(encoding="utf-8"))
                logger.info("Database schema applied successfully.")
            except Exception as e:
                logger.warning(f"Schema application note: {e}")

    # ── Compatibility migrations for existing databases ──────
    # These handle edge cases where an existing DB was created with
    # older schema versions. All are idempotent and non-critical.
    async with _pool.acquire() as conn:
        # Widen referral_code if it was created with old VARCHAR(16)
        try:
            await conn.execute("""
                DO $$ BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='users'
                          AND column_name='referral_code'
                          AND character_maximum_length IS NOT NULL
                          AND character_maximum_length < 32
                    ) THEN
                        ALTER TABLE users ALTER COLUMN referral_code TYPE VARCHAR(32);
                    END IF;
                END $$;
            """)
        except Exception:
            pass

        # Convert wallet_transactions.txn_type from ENUM to VARCHAR
        # (older schemas used an ENUM that can't hold referral_reward etc.)
        try:
            await conn.execute("""
                ALTER TABLE wallet_transactions
                ALTER COLUMN txn_type TYPE VARCHAR(50)
                USING txn_type::TEXT;
            """)
        except Exception:
            pass  # Already VARCHAR or other non-critical issue

        # Fix free_coupons.code NOT NULL constraint (legacy)
        try:
            await conn.execute("ALTER TABLE free_coupons ALTER COLUMN code SET DEFAULT '';")
            await conn.execute("ALTER TABLE free_coupons ALTER COLUMN code DROP NOT NULL;")
        except Exception:
            pass

        # Fix referral_claims FK from CASCADE to SET NULL (legacy)
        try:
            await conn.execute(
                "ALTER TABLE referral_claims ALTER COLUMN reward_id DROP NOT NULL;"
            )
            await conn.execute(
                "ALTER TABLE referral_claims "
                "DROP CONSTRAINT IF EXISTS referral_claims_reward_id_fkey;"
            )
            await conn.execute("""
                ALTER TABLE referral_claims
                ADD CONSTRAINT referral_claims_reward_id_fkey
                FOREIGN KEY (reward_id)
                REFERENCES referral_rewards(id) ON DELETE SET NULL;
            """)
        except Exception:
            pass

        # Add columns that may be missing in pre-v8 databases
        migrations = [
            "ALTER TABLE coupons ADD COLUMN IF NOT EXISTS reserved_qty INTEGER DEFAULT 0;",
            "ALTER TABLE coupons ADD COLUMN IF NOT EXISTS created_by BIGINT;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS qr_message_id BIGINT;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS source VARCHAR(32) DEFAULT 'purchase';",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(64) DEFAULT 'gateway';",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS utr VARCHAR(32);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance NUMERIC(12,2) DEFAULT 0.00;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_earnings NUMERIC(12,2) DEFAULT 0.00;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(32);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE referral_settings ADD COLUMN IF NOT EXISTS reward_amount NUMERIC(10,2) DEFAULT 10.0;",
            "ALTER TABLE referral_settings ADD COLUMN IF NOT EXISTS wallet_reward_max_amount NUMERIC(10,2) DEFAULT 250.00;",
            "ALTER TABLE referral_settings ADD COLUMN IF NOT EXISTS wallet_reward_duration_days INTEGER DEFAULT 30;",
            "ALTER TABLE referral_claims ADD COLUMN IF NOT EXISTS referrals_needed INTEGER DEFAULT 0;",
            "ALTER TABLE coupons ADD COLUMN IF NOT EXISTS category VARCHAR(64);",
        ]
        for sql in migrations:
            try:
                await conn.execute(sql)
            except Exception:
                pass

        # Ensure default settings rows exist
        try:
            existing = await conn.fetchrow("SELECT id FROM referral_settings LIMIT 1")
            if not existing:
                await conn.execute("INSERT INTO referral_settings (mode) VALUES ('commission')")
            existing = await conn.fetchrow("SELECT id FROM bot_settings LIMIT 1")
            if not existing:
                await conn.execute("INSERT INTO bot_settings (bot_name) VALUES ('DreamX Store')")
        except Exception:
            pass

    logger.info("Database pool ready — schema applied.")
    _last_health_check = time.monotonic()
    _db_ready.set()
    return _pool


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        _db_ready.clear()
        logger.info("Database pool closed.")
