"""
DreamX Coupon Bot — Database Connection Pool
Async PostgreSQL connection management using asyncpg.

Key features:
  - Auto-reconnection on pool failure
  - Health checks before returning pool
  - Graceful retry with exponential backoff
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
    global _pool, _last_health_check
    dsn = Config.DATABASE_URL
    if not dsn:
        raise RuntimeError("DATABASE_URL is required in .env")

    logger.info("Connecting to PostgreSQL...")
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10, command_timeout=60)

    schema_path = Path(__file__).resolve().parent.parent.parent / "sql" / "schema.sql"
    if schema_path.exists():
        async with _pool.acquire() as conn:
            try:
                await conn.execute(schema_path.read_text(encoding="utf-8"))
                logger.info("Database schema applied.")
            except Exception as e:
                logger.warning(f"Schema note: {e}")

    # Migrations — add columns/tables that may not exist in older schemas
    async with _pool.acquire() as conn:
        try:
            await conn.execute("""
                ALTER TABLE transactions ADD COLUMN IF NOT EXISTS utr VARCHAR(32);
            """)
            await conn.execute("""
                ALTER TABLE orders ADD COLUMN IF NOT EXISTS qr_message_id BIGINT;
            """)
        except Exception:
            pass  # Column already exists or other non-critical issue

        # Free coupons / giveaway tables (multi-code)
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS free_coupons (
                    id              SERIAL PRIMARY KEY,
                    title           VARCHAR(128) NOT NULL,
                    code            TEXT DEFAULT '',
                    codes_per_user  INTEGER NOT NULL DEFAULT 1,
                    max_claims      INTEGER NOT NULL DEFAULT 0,
                    claimed_count   INTEGER NOT NULL DEFAULT 0,
                    is_active       BOOLEAN DEFAULT TRUE,
                    created_by      BIGINT NOT NULL,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await conn.execute("""
                ALTER TABLE free_coupons ADD COLUMN IF NOT EXISTS codes_per_user INTEGER DEFAULT 1;
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS free_coupon_codes (
                    id              SERIAL PRIMARY KEY,
                    free_coupon_id  INTEGER NOT NULL REFERENCES free_coupons(id) ON DELETE CASCADE,
                    code            TEXT NOT NULL,
                    is_claimed      BOOLEAN DEFAULT FALSE,
                    claimed_by      BIGINT REFERENCES users(telegram_id),
                    claimed_at      TIMESTAMPTZ,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS free_coupon_claims (
                    id              SERIAL PRIMARY KEY,
                    free_coupon_id  INTEGER NOT NULL REFERENCES free_coupons(id) ON DELETE CASCADE,
                    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
                    claimed_at      TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(free_coupon_id, user_id)
                );
            """)
        except Exception:
            pass

        # Referral system
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(16) UNIQUE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_earnings NUMERIC(12,2) DEFAULT 0.00;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance NUMERIC(12,2) DEFAULT 0.00;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referral_settings (
                    id                  SERIAL PRIMARY KEY,
                    mode                VARCHAR(32) DEFAULT 'balance',
                    commission_percent  NUMERIC(5,2) DEFAULT 10.0,
                    referrals_needed    INTEGER DEFAULT 3,
                    reward_code         TEXT DEFAULT '',
                    is_active           BOOLEAN DEFAULT TRUE,
                    updated_at          TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id          SERIAL PRIMARY KEY,
                    referrer_id BIGINT NOT NULL REFERENCES users(telegram_id),
                    referred_id BIGINT NOT NULL REFERENCES users(telegram_id),
                    status      VARCHAR(16) DEFAULT 'joined',
                    commission  NUMERIC(10,2) DEFAULT 0.00,
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(referred_id)
                );
            """)
            # Insert default referral settings if none exist
            existing = await conn.fetchrow("SELECT id FROM referral_settings LIMIT 1")
            if not existing:
                await conn.execute("INSERT INTO referral_settings (mode) VALUES ('balance')")
        except Exception:
            pass

        # Orders: add quantity column
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1;")
        except Exception:
            pass

    logger.info("Database pool ready.")
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
