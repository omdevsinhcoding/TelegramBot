-- ============================================================
-- DreamX Coupon Bot — Migration v4
-- Fixes the "free referral reward reuse" bug.
--
-- ROOT CAUSE:
--   referral_claims.reward_id had ON DELETE CASCADE, so when the
--   admin deleted a referral reward, ALL claim records for that
--   reward were wiped from referral_claims.  The next time admin
--   added a *new* reward, users who had already claimed the old
--   one appeared to have 0 claims and could instantly claim the
--   new reward for free, even without making any new referrals.
--
-- FIX (3 steps, all idempotent / safe to re-run):
--   1. Add referrals_needed column to referral_claims so the
--      number of referrals consumed by each claim is stored
--      permanently on the claim row — independent of the
--      referral_rewards row that may later be deleted.
--   2. Make reward_id nullable (prerequisite for SET NULL FK).
--   3. Change the FK from ON DELETE CASCADE to ON DELETE SET NULL
--      so claim rows survive when admin removes a reward.
-- ============================================================

-- Step 1: persist how many refs were consumed by this claim
ALTER TABLE referral_claims
    ADD COLUMN IF NOT EXISTS referrals_needed INTEGER DEFAULT 0;

-- Step 2: allow reward_id to be NULL (set when the reward is deleted)
ALTER TABLE referral_claims
    ALTER COLUMN reward_id DROP NOT NULL;

-- Step 3: swap CASCADE for SET NULL on the FK
ALTER TABLE referral_claims
    DROP CONSTRAINT IF EXISTS referral_claims_reward_id_fkey;

ALTER TABLE referral_claims
    ADD CONSTRAINT referral_claims_reward_id_fkey
    FOREIGN KEY (reward_id)
    REFERENCES referral_rewards(id) ON DELETE SET NULL;

-- ============================================================
-- DONE.  Restart the bot after running this migration.
-- ============================================================
