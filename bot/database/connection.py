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

        # Bot Settings
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    id SERIAL PRIMARY KEY,
                    force_channel TEXT DEFAULT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Payment settings columns
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS paytm_mid TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS paytm_upi_id TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS paytm_qr_code TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS bharatpe_merchant_id TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS bharatpe_token TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS bharatpe_upi_id TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS bharatpe_qr_path TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS upi_payee_name TEXT DEFAULT '';")
            # Disclaimer columns
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS disclaimer_text TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS disclaimer_buttons TEXT DEFAULT '';")
        except Exception:
            pass

        # User ban column
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;")
        except Exception:
            pass

        # Wallet balance column on users
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance NUMERIC(12,2) DEFAULT 0.00;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_earnings NUMERIC(12,2) DEFAULT 0.00;")
        except Exception:
            pass

        # Wallet transactions table
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount NUMERIC(12,2) NOT NULL,
                    txn_type VARCHAR(50) NOT NULL,
                    balance_before NUMERIC(12,2) DEFAULT 0,
                    balance_after NUMERIC(12,2) DEFAULT 0,
                    reference TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
        except Exception:
            pass

        # Fix txn_type column if it uses an ENUM type — convert to VARCHAR
        try:
            await conn.execute("""
                ALTER TABLE wallet_transactions
                ALTER COLUMN txn_type TYPE VARCHAR(50)
                USING txn_type::TEXT;
            """)
        except Exception:
            pass

        # Migrate old referral codes to new ERROROO-XXXXXXXX format
        try:
            import random, string
            old_codes = await conn.fetch(
                "SELECT telegram_id FROM users WHERE referral_code IS NOT NULL AND referral_code != '' AND referral_code NOT LIKE 'ERROROO-%'"
            )
            for row in old_codes:
                new_code = "ERROROO-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
                await conn.execute(
                    "UPDATE users SET referral_code = $2 WHERE telegram_id = $1",
                    row["telegram_id"], new_code
                )
            if old_codes:
                logger.info(f"Migrated {len(old_codes)} old referral codes to ERROROO- format")
        except Exception as e:
            logger.warning(f"Referral code migration error (non-critical): {e}")

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

        # Referral rewards — admin picks existing coupons as milestones
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referral_rewards (
                    id              SERIAL PRIMARY KEY,
                    coupon_id       INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
                    referrals_needed INTEGER NOT NULL DEFAULT 3,
                    is_active       BOOLEAN DEFAULT TRUE,
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(coupon_id)
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referral_claims (
                    id              SERIAL PRIMARY KEY,
                    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
                    reward_id       INTEGER NOT NULL REFERENCES referral_rewards(id) ON DELETE CASCADE,
                    coupon_id       INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
                    code            TEXT NOT NULL,
                    claimed_at      TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, reward_id)
                );
            """)
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
