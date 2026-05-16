-- ============================================================
-- DreamX Coupon Bot — Migration v4
-- Two independent bug-fixes bundled together.
-- All statements are idempotent (safe to re-run).
-- ============================================================


-- ────────────────────────────────────────────────────────────
-- FIX A: Referral reward "free reuse" bug
--
-- ROOT CAUSE:
--   referral_claims.reward_id had ON DELETE CASCADE, so when the
--   admin deleted a reward ALL claim records were wiped.  The next
--   time admin added a new reward the users appeared to have 0
--   claims and could claim again for free.
--
-- FIX:
--   1. Add referrals_needed column — persists refs consumed per
--      claim even after the referral_rewards row is deleted.
--   2. Make reward_id nullable (prerequisite for SET NULL FK).
--   3. Switch FK to ON DELETE SET NULL so claims survive deletion.
-- ────────────────────────────────────────────────────────────

ALTER TABLE referral_claims
    ADD COLUMN IF NOT EXISTS referrals_needed INTEGER DEFAULT 0;

ALTER TABLE referral_claims
    ALTER COLUMN reward_id DROP NOT NULL;

ALTER TABLE referral_claims
    DROP CONSTRAINT IF EXISTS referral_claims_reward_id_fkey;

ALTER TABLE referral_claims
    ADD CONSTRAINT referral_claims_reward_id_fkey
    FOREIGN KEY (reward_id)
    REFERENCES referral_rewards(id) ON DELETE SET NULL;


-- ────────────────────────────────────────────────────────────
-- FIX B: Reservation system bugs
--
-- BUG 1: Disabling reservation did not release existing stock.
--        (Fixed in Python — release_all_reservations() now called
--         from the toggle handler. No schema change needed.)
--
-- BUG 2: Admin had no way to set how long stock stays reserved.
--        Added reservation_timeout_seconds column (default 15 min).
--        Separate from payment_timeout_seconds so the two timers
--        can be tuned independently.
-- ────────────────────────────────────────────────────────────

ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS reservation_timeout_seconds INTEGER DEFAULT 900;


-- ============================================================
-- DONE.  Restart the bot after running this migration.
-- ============================================================
