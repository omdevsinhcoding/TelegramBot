-- ============================================================
-- DreamX Coupon Bot — Unified PostgreSQL Schema
-- Version: 3.0.0 (consolidated from schema + migrations v2-v8)
--
-- This is the SINGLE SOURCE OF TRUTH for the database schema.
-- Safe to run on both fresh and existing databases.
-- All statements are idempotent (IF NOT EXISTS / IF EXISTS).
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ────────────────────────────────────────────────────────────
-- 1. USERS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    telegram_id     BIGINT UNIQUE NOT NULL,
    username        VARCHAR(64),
    full_name       VARCHAR(128),
    wallet_balance  NUMERIC(12, 2) DEFAULT 0.00,
    referral_code   VARCHAR(32) UNIQUE,
    referred_by     BIGINT,
    referral_earnings NUMERIC(12, 2) DEFAULT 0.00,
    is_banned       BOOLEAN DEFAULT FALSE,
    joined_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users (telegram_id);

-- ────────────────────────────────────────────────────────────
-- 2. COUPONS (Products)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS coupons (
    id                  SERIAL PRIMARY KEY,
    title               VARCHAR(128) NOT NULL,
    description         TEXT,
    original_price      NUMERIC(10, 2) NOT NULL,
    discounted_price    NUMERIC(10, 2) NOT NULL,
    stock               INTEGER DEFAULT 0,
    reserved_qty        INTEGER DEFAULT 0,
    is_active           BOOLEAN DEFAULT TRUE,
    coupon_code_data    TEXT,
    category            VARCHAR(64),
    image_url           TEXT,
    created_by          BIGINT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coupons_active ON coupons (is_active);

-- ────────────────────────────────────────────────────────────
-- 3. ORDERS
-- ────────────────────────────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE order_status AS ENUM ('pending', 'paid', 'delivered', 'expired', 'cancelled', 'refunded');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    order_id        VARCHAR(64) UNIQUE NOT NULL,
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
    coupon_id       INTEGER NOT NULL REFERENCES coupons(id),
    amount          NUMERIC(10, 2) NOT NULL,
    quantity        INTEGER DEFAULT 1,
    status          order_status DEFAULT 'pending',
    txn_id          VARCHAR(128),
    payment_method  VARCHAR(64) DEFAULT 'gateway',
    paid_at         TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    qr_message_id   BIGINT,
    source          VARCHAR(32) DEFAULT 'purchase',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders (order_id);
CREATE INDEX IF NOT EXISTS idx_orders_txn_id ON orders (txn_id);
CREATE INDEX IF NOT EXISTS idx_orders_user_status ON orders(user_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_coupon_status ON orders(coupon_id, status);

-- ────────────────────────────────────────────────────────────
-- 4. TRANSACTIONS (Payment Verification Log)
-- ────────────────────────────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE txn_status AS ENUM ('initiated', 'pending', 'success', 'failed', 'expired');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS transactions (
    id              SERIAL PRIMARY KEY,
    txn_ref         VARCHAR(128) UNIQUE NOT NULL,
    order_id        VARCHAR(64) NOT NULL REFERENCES orders(order_id),
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
    amount          NUMERIC(10, 2) NOT NULL,
    upi_id          VARCHAR(128),
    merchant_id     VARCHAR(64),
    utr             VARCHAR(32),
    status          txn_status DEFAULT 'initiated',
    gateway         VARCHAR(32) DEFAULT 'paytm',
    raw_response    JSONB,
    verified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_txn_ref ON transactions (txn_ref);
CREATE INDEX IF NOT EXISTS idx_txn_order ON transactions (order_id);
CREATE INDEX IF NOT EXISTS idx_txn_status ON transactions (status);
CREATE INDEX IF NOT EXISTS idx_txn_utr_status_gw ON transactions (utr, status, gateway) WHERE utr IS NOT NULL;

-- ────────────────────────────────────────────────────────────
-- 5. WALLET TRANSACTIONS
--    Uses VARCHAR(50) instead of ENUM to support dynamic types
--    (topup, purchase, refund, admin_credit, admin_debit,
--     referral_reward, referral_commission)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
    amount          NUMERIC(12, 2) NOT NULL,
    txn_type        VARCHAR(50) NOT NULL,
    balance_before  NUMERIC(12, 2) DEFAULT 0,
    balance_after   NUMERIC(12, 2) DEFAULT 0,
    reference       TEXT,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wallet_txn_user ON wallet_transactions (user_id);

-- ────────────────────────────────────────────────────────────
-- 6. ADMIN LOGS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_logs (
    id              SERIAL PRIMARY KEY,
    admin_id        BIGINT NOT NULL,
    action          VARCHAR(64) NOT NULL,
    target_type     VARCHAR(32),
    target_id       VARCHAR(64),
    details         JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs (admin_id);

-- ────────────────────────────────────────────────────────────
-- 7. BROADCAST MESSAGES
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS broadcasts (
    id              SERIAL PRIMARY KEY,
    admin_id        BIGINT NOT NULL,
    message_text    TEXT NOT NULL,
    total_users     INTEGER DEFAULT 0,
    sent_count      INTEGER DEFAULT 0,
    failed_count    INTEGER DEFAULT 0,
    status          VARCHAR(16) DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- ────────────────────────────────────────────────────────────
-- 8. COUPON CODES INVENTORY (deliverable codes)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS coupon_codes (
    id              SERIAL PRIMARY KEY,
    coupon_id       INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
    code            TEXT NOT NULL,
    is_sold         BOOLEAN DEFAULT FALSE,
    sold_to         BIGINT REFERENCES users(telegram_id),
    order_id        VARCHAR(64),
    sold_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coupon_codes_coupon ON coupon_codes (coupon_id, is_sold);
CREATE INDEX IF NOT EXISTS idx_coupon_codes_order ON coupon_codes(order_id) WHERE is_sold = TRUE;

-- Unique partial index: prevent duplicate unsold codes per coupon
CREATE UNIQUE INDEX IF NOT EXISTS idx_coupon_codes_unique_unsold
    ON coupon_codes (coupon_id, code) WHERE is_sold = FALSE;

-- ────────────────────────────────────────────────────────────
-- 9. FREE COUPONS / GIVEAWAY SYSTEM
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS free_coupons (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(128) NOT NULL,
    code            TEXT DEFAULT '',
    max_claims      INTEGER NOT NULL DEFAULT 0,
    claimed_count   INTEGER NOT NULL DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_by      BIGINT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    codes_per_user  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS free_coupon_claims (
    id              SERIAL PRIMARY KEY,
    free_coupon_id  INTEGER NOT NULL REFERENCES free_coupons(id) ON DELETE CASCADE,
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
    claimed_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(free_coupon_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_free_coupon_claims_user ON free_coupon_claims (user_id);
CREATE INDEX IF NOT EXISTS idx_free_coupon_claims_coupon ON free_coupon_claims (free_coupon_id);

-- ────────────────────────────────────────────────────────────
-- 10. FREE COUPON CODES (multi-code giveaway inventory)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS free_coupon_codes (
    id              SERIAL PRIMARY KEY,
    free_coupon_id  INTEGER NOT NULL REFERENCES free_coupons(id) ON DELETE CASCADE,
    code            TEXT NOT NULL,
    is_claimed      BOOLEAN DEFAULT FALSE,
    claimed_by      BIGINT,
    claimed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_free_coupon_codes_coupon ON free_coupon_codes (free_coupon_id, is_claimed);

-- Unique partial index: prevent duplicate unclaimed codes per giveaway
CREATE UNIQUE INDEX IF NOT EXISTS idx_free_coupon_codes_unique_unclaimed
    ON free_coupon_codes (free_coupon_id, code) WHERE is_claimed = FALSE;

-- ────────────────────────────────────────────────────────────
-- 11. REFERRALS (who referred whom)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referrals (
    id          SERIAL PRIMARY KEY,
    referrer_id BIGINT NOT NULL REFERENCES users(telegram_id),
    referred_id BIGINT NOT NULL REFERENCES users(telegram_id),
    status      VARCHAR(32) DEFAULT 'joined',
    commission  NUMERIC(12, 2) DEFAULT 0.00,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(referred_id)
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals (referrer_id);
CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals (referred_id);

-- ────────────────────────────────────────────────────────────
-- 12. REFERRAL SETTINGS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referral_settings (
    id                          SERIAL PRIMARY KEY,
    is_active                   BOOLEAN DEFAULT TRUE,
    mode                        VARCHAR(32) DEFAULT 'commission',
    commission_percent          NUMERIC(5, 2) DEFAULT 10.00,
    reward_amount               NUMERIC(10, 2) DEFAULT 10.00,
    wallet_reward_max_amount    NUMERIC(10, 2) DEFAULT 250.00,
    wallet_reward_duration_days INTEGER DEFAULT 30,
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default settings if none exist
INSERT INTO referral_settings (is_active, mode, commission_percent, reward_amount)
SELECT TRUE, 'commission', 10.00, 10.00
WHERE NOT EXISTS (SELECT 1 FROM referral_settings);

-- ────────────────────────────────────────────────────────────
-- 13. REFERRAL REWARDS (milestone coupon rewards)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referral_rewards (
    id                SERIAL PRIMARY KEY,
    coupon_id         INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
    referrals_needed  INTEGER NOT NULL DEFAULT 5,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(coupon_id)
);

-- ────────────────────────────────────────────────────────────
-- 14. REFERRAL CLAIMS (tracks who claimed which reward)
--     reward_id is nullable + ON DELETE SET NULL so claims
--     survive reward deletion (prevents free-reuse bug).
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referral_claims (
    id                  SERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(telegram_id),
    reward_id           INTEGER REFERENCES referral_rewards(id) ON DELETE SET NULL,
    coupon_id           INTEGER NOT NULL REFERENCES coupons(id),
    code                TEXT,
    referrals_needed    INTEGER DEFAULT 0,
    claimed_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, reward_id)
);

CREATE INDEX IF NOT EXISTS idx_referral_claims_user ON referral_claims (user_id);

-- ────────────────────────────────────────────────────────────
-- 15. COUPON WAITLIST
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS coupon_waitlist (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    coupon_id   INTEGER NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, coupon_id)
);

-- ────────────────────────────────────────────────────────────
-- 16. BOT SETTINGS (single-row config table)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_settings (
    id                          SERIAL PRIMARY KEY,
    bot_name                    TEXT DEFAULT 'DreamX Store',
    force_channel               TEXT,
    force_join_apply_admins     BOOLEAN DEFAULT FALSE,
    -- Payment: Paytm
    paytm_mid                   TEXT DEFAULT '',
    paytm_upi_id                TEXT DEFAULT '',
    paytm_qr_code               TEXT DEFAULT '',
    -- Payment: BharatPe
    bharatpe_merchant_id        TEXT DEFAULT '',
    bharatpe_token              TEXT DEFAULT '',
    bharatpe_upi_id             TEXT DEFAULT '',
    bharatpe_qr_path            TEXT DEFAULT '',
    -- Payment: Razorpay
    razorpay_key_id             TEXT DEFAULT '',
    razorpay_key_secret         TEXT DEFAULT '',
    -- Payment: Common
    upi_payee_name              TEXT DEFAULT '',
    payment_timeout_seconds     INTEGER DEFAULT 600,
    bharatpe_min_recharge       NUMERIC(10, 2) DEFAULT 10,
    payment_poll_interval       INTEGER DEFAULT 30,
    -- Gateway toggles
    gateway_paytm_enabled       BOOLEAN DEFAULT TRUE,
    gateway_bharatpe_enabled    BOOLEAN DEFAULT TRUE,
    gateway_razorpay_enabled    BOOLEAN DEFAULT FALSE,
    -- Gateway display names
    gateway_paytm_name          VARCHAR(64) DEFAULT 'Paytm',
    gateway_bharatpe_name       VARCHAR(64) DEFAULT 'BharatPe',
    gateway_razorpay_name       VARCHAR(64) DEFAULT 'Razorpay',
    -- Disclaimer / Support
    disclaimer_text             TEXT DEFAULT '',
    disclaimer_buttons          TEXT DEFAULT '[]',
    disclaimer_content          TEXT DEFAULT '',
    disclaimer_mode             VARCHAR(16) DEFAULT 'button',
    -- Ban message
    ban_message                 TEXT DEFAULT '',
    ban_buttons                 TEXT DEFAULT '[]',
    -- Channels
    channels_list               TEXT DEFAULT '[]',
    channels_static_enabled     BOOLEAN DEFAULT TRUE,
    channels_inline_enabled     BOOLEAN DEFAULT TRUE,
    -- Reservation system
    reservation_enabled         BOOLEAN DEFAULT TRUE,
    waitlist_enabled            BOOLEAN DEFAULT TRUE,
    reservation_timeout_seconds INTEGER DEFAULT 900,
    -- Timestamps
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default settings row if none exist
INSERT INTO bot_settings (bot_name) SELECT 'DreamX Store'
WHERE NOT EXISTS (SELECT 1 FROM bot_settings);

-- ────────────────────────────────────────────────────────────
-- 17. ADMINS (dynamically added via admin panel)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admins (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    added_by    BIGINT,
    added_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- END OF SCHEMA — All tables and indexes defined above.
-- ============================================================
