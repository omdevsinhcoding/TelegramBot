-- ============================================================
-- DreamX Coupon Bot — Migration v2
-- Run this on your live PostgreSQL database to add missing
-- columns and tables that the bot code depends on.
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- 1. Add missing columns to USERS table
-- ────────────────────────────────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by       BIGINT REFERENCES users(telegram_id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code     VARCHAR(32) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_earnings NUMERIC(12, 2) DEFAULT 0.00;

-- ────────────────────────────────────────────────────────────
-- 2. Add missing columns to ORDERS table
-- ────────────────────────────────────────────────────────────
ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1;

-- ────────────────────────────────────────────────────────────
-- 3. Add missing columns to COUPONS table
-- ────────────────────────────────────────────────────────────
ALTER TABLE coupons ADD COLUMN IF NOT EXISTS reserved_qty INTEGER DEFAULT 0;

-- ────────────────────────────────────────────────────────────
-- 4. Add missing columns to TRANSACTIONS table
-- ────────────────────────────────────────────────────────────
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS utr VARCHAR(32);

-- ────────────────────────────────────────────────────────────
-- 5. REFERRALS table
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referrals (
    id          SERIAL PRIMARY KEY,
    referrer_id BIGINT NOT NULL REFERENCES users(telegram_id),
    referred_id BIGINT NOT NULL REFERENCES users(telegram_id),
    status      VARCHAR(32) DEFAULT 'joined',   -- joined / purchased
    commission  NUMERIC(12, 2) DEFAULT 0.00,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(referred_id)   -- each user can only be referred once
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals (referrer_id);
CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals (referred_id);

-- ────────────────────────────────────────────────────────────
-- 6. REFERRAL SETTINGS table
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referral_settings (
    id                  SERIAL PRIMARY KEY,
    is_active           BOOLEAN DEFAULT TRUE,
    mode                VARCHAR(32) DEFAULT 'commission',  -- commission / wallet_reward / code_reward
    commission_percent  NUMERIC(5, 2) DEFAULT 10.00,
    reward_amount       NUMERIC(10, 2) DEFAULT 10.00,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default settings if none exist
INSERT INTO referral_settings (is_active, mode, commission_percent, reward_amount)
SELECT TRUE, 'commission', 10.00, 10.00
WHERE NOT EXISTS (SELECT 1 FROM referral_settings);

-- ────────────────────────────────────────────────────────────
-- 7. REFERRAL REWARDS table (milestone coupon rewards)
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
-- 8. REFERRAL CLAIMS table (tracks who claimed which reward)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referral_claims (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(telegram_id),
    reward_id   INTEGER NOT NULL REFERENCES referral_rewards(id) ON DELETE CASCADE,
    coupon_id   INTEGER NOT NULL REFERENCES coupons(id),
    code        TEXT,
    claimed_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, reward_id)
);

CREATE INDEX IF NOT EXISTS idx_referral_claims_user ON referral_claims (user_id);

-- ────────────────────────────────────────────────────────────
-- 9. COUPON WAITLIST table
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS coupon_waitlist (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(telegram_id),
    coupon_id   INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, coupon_id)
);

-- ────────────────────────────────────────────────────────────
-- 10. BOT SETTINGS table (if not already created)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_settings (
    id                          SERIAL PRIMARY KEY,
    bot_name                    VARCHAR(128),
    force_channel               TEXT,
    force_channel_enabled       BOOLEAN DEFAULT FALSE,
    disclaimer_text             TEXT,
    disclaimer_content          TEXT,
    disclaimer_buttons          TEXT DEFAULT '[]',
    disclaimer_mode             VARCHAR(32) DEFAULT 'none',
    channels_list               TEXT DEFAULT '[]',
    channels_inline_enabled     BOOLEAN DEFAULT TRUE,
    paytm_mid                   VARCHAR(128),
    paytm_upi_id                VARCHAR(128),
    paytm_qr_code               TEXT,
    bharatpe_merchant_id        VARCHAR(128),
    bharatpe_token              TEXT,
    bharatpe_upi_id             VARCHAR(128),
    bharatpe_qr_path            TEXT,
    upi_payee_name              VARCHAR(128),
    gateway_paytm_enabled       BOOLEAN DEFAULT TRUE,
    gateway_bharatpe_enabled    BOOLEAN DEFAULT TRUE,
    gateway_razorpay_enabled    BOOLEAN DEFAULT FALSE,
    razorpay_key_id             VARCHAR(128),
    razorpay_key_secret         VARCHAR(128),
    payment_timeout_seconds     INTEGER DEFAULT 600,
    bharatpe_min_recharge       NUMERIC(10, 2) DEFAULT 10,
    payment_poll_interval       INTEGER DEFAULT 30,
    giveaway_enabled            BOOLEAN DEFAULT TRUE,
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default settings row if none exist
INSERT INTO bot_settings DEFAULT VALUES
WHERE NOT EXISTS (SELECT 1 FROM bot_settings);

-- ────────────────────────────────────────────────────────────
-- 11. ADMINS table
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admins (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    added_by    BIGINT,
    added_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────
-- DONE — All missing schema objects created.
-- ────────────────────────────────────────────────────────────
