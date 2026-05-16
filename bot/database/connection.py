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
            # Ban message columns
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS ban_message TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS ban_buttons TEXT DEFAULT '[]';")
        except Exception:
            pass

        # User ban column
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;")
        except Exception:
            pass

        # Orders quantity column
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1;")
        except Exception:
            pass

        # Fix free_coupons.code NOT NULL constraint (legacy)
        try:
            await conn.execute("ALTER TABLE free_coupons ALTER COLUMN code SET DEFAULT '';")
            await conn.execute("ALTER TABLE free_coupons ALTER COLUMN code DROP NOT NULL;")
            await conn.execute("ALTER TABLE free_coupons ADD COLUMN IF NOT EXISTS codes_per_user INTEGER DEFAULT 1;")
        except Exception:
            pass

        # Ensure free_coupon_codes table exists (multi-code giveaway inventory)
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS free_coupon_codes (
                    id SERIAL PRIMARY KEY,
                    free_coupon_id INTEGER NOT NULL REFERENCES free_coupons(id) ON DELETE CASCADE,
                    code TEXT NOT NULL,
                    is_claimed BOOLEAN DEFAULT FALSE,
                    claimed_by BIGINT,
                    claimed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
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
                    mode                VARCHAR(32) DEFAULT 'commission',
                    commission_percent  NUMERIC(5,2) DEFAULT 10.0,
                    reward_amount       NUMERIC(10,2) DEFAULT 10.0,
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
                await conn.execute("INSERT INTO referral_settings (mode) VALUES ('commission')")

            # Migration: add reward_amount column + rename 'balance' -> 'commission'
            await conn.execute("ALTER TABLE referral_settings ADD COLUMN IF NOT EXISTS reward_amount NUMERIC(10,2) DEFAULT 10.0;")
            await conn.execute("UPDATE referral_settings SET mode = 'commission' WHERE mode = 'balance';")
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

        # Orders: add source column to distinguish purchase / referral_reward / giveaway
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS source VARCHAR(32) DEFAULT 'purchase';")
        except Exception:
            pass

        # Bot settings: add disclaimer_mode (button / description)
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS disclaimer_mode VARCHAR(16) DEFAULT 'button';")
        except Exception:
            pass

        # Gateway enable/disable toggles (in bot_settings)
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS gateway_paytm_enabled BOOLEAN DEFAULT TRUE;")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS gateway_bharatpe_enabled BOOLEAN DEFAULT TRUE;")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS gateway_razorpay_enabled BOOLEAN DEFAULT FALSE;")
        except Exception:
            pass

        # Razorpay credentials (in bot_settings)
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS razorpay_key_id TEXT DEFAULT '';")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS razorpay_key_secret TEXT DEFAULT '';")
        except Exception:
            pass

        # Dynamic config: payment timeout, min recharge, poll interval
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS payment_timeout_seconds INTEGER DEFAULT 600;")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS bharatpe_min_recharge NUMERIC(10,2) DEFAULT 10;")
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS payment_poll_interval INTEGER DEFAULT 30;")
        except Exception:
            pass

        # Admins table for dynamic admin management
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    added_by BIGINT NOT NULL,
                    added_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
        except Exception:
            pass

        # Separate disclaimer content (disclaimer_text is for Support info)
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS disclaimer_content TEXT DEFAULT '';")
        except Exception:
            pass

        # Channel links for "Our Channels" user button
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS channels_list TEXT DEFAULT '[]';")
        except Exception:
            pass

        # Toggle for channels button visibility — static keyboard
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS channels_static_enabled BOOLEAN DEFAULT TRUE;")
        except Exception:
            pass

        # Toggle for channels button visibility — inline/floating
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS channels_inline_enabled BOOLEAN DEFAULT TRUE;")
        except Exception:
            pass

        # Customizable bot name (admin can change via Bot Settings)
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS bot_name TEXT DEFAULT 'DreamX Store';")
        except Exception:
            pass

        # Admin toggle: whether force join applies to admins too
        try:
            await conn.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS force_join_apply_admins BOOLEAN DEFAULT FALSE;")
        except Exception:
            pass

        # Coupon reservation system — track reserved stock
        try:
            await conn.execute("ALTER TABLE coupons ADD COLUMN IF NOT EXISTS reserved_qty INTEGER DEFAULT 0;")
        except Exception:
            pass

        # Reservation hold duration — separate from payment session timeout
        # Default 900s (15 min): how long stock stays locked while order is pending
        try:
            await conn.execute(
                "ALTER TABLE bot_settings "
                "ADD COLUMN IF NOT EXISTS reservation_timeout_seconds INTEGER DEFAULT 900;"
            )
        except Exception as e:
            logger.warning(f"reservation_timeout_seconds migration (non-critical): {e}")

        # Waitlist for users wanting reserved coupons
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS coupon_waitlist (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    coupon_id INTEGER NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, coupon_id)
                );
            """)
        except Exception:
            pass

        # Performance indexes
        try:
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_orders_user_status ON orders(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_orders_coupon_status ON orders(coupon_id, status);
                CREATE INDEX IF NOT EXISTS idx_coupon_codes_order ON coupon_codes(order_id) WHERE is_sold = TRUE;
            """)
        except Exception:
            pass

        # ── Referral claims: fix free-reward bug (migration v4) ────────────
        # Problem: referral_claims.reward_id had ON DELETE CASCADE, so when
        # admin removed a reward all claim records were wiped. A new reward
        # then looked claimable for free because the consumption history was gone.
        #
        # Fix:
        #   1. Add referrals_needed column — persists how many refs were consumed
        #      per claim even after the referral_rewards row is deleted.
        #   2. Make reward_id nullable — required before changing FK to SET NULL.
        #   3. Switch FK to ON DELETE SET NULL so claims survive reward deletion.
        try:
            # Step 1: add referrals_needed column if missing
            await conn.execute(
                "ALTER TABLE referral_claims "
                "ADD COLUMN IF NOT EXISTS referrals_needed INTEGER DEFAULT 0;"
            )
        except Exception as e:
            logger.warning(f"referral_claims add referrals_needed (non-critical): {e}")

        try:
            # Step 2: make reward_id nullable (prerequisite for SET NULL FK)
            await conn.execute(
                "ALTER TABLE referral_claims ALTER COLUMN reward_id DROP NOT NULL;"
            )
        except Exception as e:
            logger.warning(f"referral_claims drop not-null (non-critical): {e}")

        try:
            # Step 3: drop old CASCADE FK and recreate as SET NULL
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
            logger.info("referral_claims FK updated to ON DELETE SET NULL.")
        except Exception as e:
            logger.warning(f"referral_claims FK change (non-critical): {e}")
        # ──────────────────────────────────────────────────────────────────

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
