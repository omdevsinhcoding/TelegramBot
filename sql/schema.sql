-- ============================================================
-- DreamX Coupon Bot — PostgreSQL Schema
-- Version: 1.0.0
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
    is_banned       BOOLEAN DEFAULT FALSE,
    joined_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_telegram_id ON users (telegram_id);

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
    is_active           BOOLEAN DEFAULT TRUE,
    coupon_code_data    TEXT,          -- actual coupon code/content to deliver
    category            VARCHAR(64),
    image_url           TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_coupons_active ON coupons (is_active);

-- ────────────────────────────────────────────────────────────
-- 3. ORDERS
-- ────────────────────────────────────────────────────────────
CREATE TYPE order_status AS ENUM ('pending', 'paid', 'delivered', 'expired', 'cancelled', 'refunded');

CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    order_id        VARCHAR(64) UNIQUE NOT NULL,   -- human-readable order ID
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
    coupon_id       INTEGER NOT NULL REFERENCES coupons(id),
    amount          NUMERIC(10, 2) NOT NULL,
    status          order_status DEFAULT 'pending',
    txn_id          VARCHAR(128),                  -- UPI/payment txn reference
    payment_method  VARCHAR(32) DEFAULT 'upi',
    paid_at         TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,                   -- payment timeout
    qr_message_id   BIGINT,                        -- Telegram message ID of QR code
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_orders_user ON orders (user_id);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_order_id ON orders (order_id);
CREATE INDEX idx_orders_txn_id ON orders (txn_id);

-- ────────────────────────────────────────────────────────────
-- 4. TRANSACTIONS (Payment Verification Log)
-- ────────────────────────────────────────────────────────────
CREATE TYPE txn_status AS ENUM ('initiated', 'pending', 'success', 'failed', 'expired');

CREATE TABLE IF NOT EXISTS transactions (
    id              SERIAL PRIMARY KEY,
    txn_ref         VARCHAR(128) UNIQUE NOT NULL,
    order_id        VARCHAR(64) NOT NULL REFERENCES orders(order_id),
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
    amount          NUMERIC(10, 2) NOT NULL,
    upi_id          VARCHAR(128),
    merchant_id     VARCHAR(64),
    utr             VARCHAR(32),                   -- BharatPe UTR submitted by user
    status          txn_status DEFAULT 'initiated',
    gateway         VARCHAR(32) DEFAULT 'paytm',   -- paytm / bharatpe
    raw_response    JSONB,
    verified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_txn_ref ON transactions (txn_ref);
CREATE INDEX idx_txn_order ON transactions (order_id);
CREATE INDEX idx_txn_status ON transactions (status);

-- ────────────────────────────────────────────────────────────
-- 5. WALLET TRANSACTIONS
-- ────────────────────────────────────────────────────────────
CREATE TYPE wallet_txn_type AS ENUM ('topup', 'purchase', 'refund', 'admin_credit', 'admin_debit');

CREATE TABLE IF NOT EXISTS wallet_transactions (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
    amount          NUMERIC(10, 2) NOT NULL,
    txn_type        wallet_txn_type NOT NULL,
    balance_before  NUMERIC(12, 2) NOT NULL,
    balance_after   NUMERIC(12, 2) NOT NULL,
    reference       VARCHAR(128),                  -- order_id or txn_ref
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_wallet_txn_user ON wallet_transactions (user_id);

-- ────────────────────────────────────────────────────────────
-- 6. ADMIN LOGS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_logs (
    id              SERIAL PRIMARY KEY,
    admin_id        BIGINT NOT NULL,
    action          VARCHAR(64) NOT NULL,
    target_type     VARCHAR(32),                   -- user / coupon / order
    target_id       VARCHAR(64),
    details         JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_admin_logs_admin ON admin_logs (admin_id);

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
    status          VARCHAR(16) DEFAULT 'pending', -- pending / running / completed
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

CREATE INDEX idx_coupon_codes_coupon ON coupon_codes (coupon_id, is_sold);
