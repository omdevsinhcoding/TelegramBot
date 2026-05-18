-- ============================================================
-- Migration V8: Admin Referral System Stabilization
-- All statements are idempotent (safe to re-run).
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- 1. Add created_by to coupons (admin attribution)
-- ────────────────────────────────────────────────────────────
ALTER TABLE coupons ADD COLUMN IF NOT EXISTS created_by BIGINT REFERENCES users(telegram_id);

-- ────────────────────────────────────────────────────────────
-- 2. Add wallet reward caps to referral_settings
--    - wallet_reward_max_amount: max total a user can earn (e.g. ₹250)
--    - wallet_reward_duration_days: rolling window in days (e.g. 30)
-- ────────────────────────────────────────────────────────────
ALTER TABLE referral_settings
    ADD COLUMN IF NOT EXISTS wallet_reward_max_amount NUMERIC(10, 2) DEFAULT 250.00;

ALTER TABLE referral_settings
    ADD COLUMN IF NOT EXISTS wallet_reward_duration_days INTEGER DEFAULT 30;

-- ────────────────────────────────────────────────────────────
-- 3. Add missing bot_settings columns used by admin.py
--    (Ensures existing deployments don't crash on missing cols)
-- ────────────────────────────────────────────────────────────
ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS gateway_paytm_name VARCHAR(64) DEFAULT 'Paytm';

ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS gateway_bharatpe_name VARCHAR(64) DEFAULT 'BharatPe';

ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS gateway_razorpay_name VARCHAR(64) DEFAULT 'Razorpay';

ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS channels_static_enabled BOOLEAN DEFAULT TRUE;

ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS ban_message TEXT;

ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS ban_buttons TEXT DEFAULT '[]';

-- ============================================================
-- DONE. Restart the bot after running this migration.
-- ============================================================
