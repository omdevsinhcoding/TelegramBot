-- ============================================================
-- Migration V5: Fix duplicate coupon codes causing wrong stock counts
-- ============================================================

-- 1. Remove duplicate coupon_codes rows (keep the oldest row per coupon_id + code combo)
DELETE FROM coupon_codes a
USING coupon_codes b
WHERE a.coupon_id = b.coupon_id
  AND a.code = b.code
  AND a.id > b.id
  AND a.is_sold = FALSE
  AND b.is_sold = FALSE;

-- 2. Add UNIQUE constraint to prevent future duplicates
--    Only unsold codes need uniqueness — sold codes are historical records
--    Use a unique index with a condition instead
CREATE UNIQUE INDEX IF NOT EXISTS idx_coupon_codes_unique_unsold
    ON coupon_codes (coupon_id, code)
    WHERE is_sold = FALSE;

-- 3. Same fix for free_coupon_codes (giveaway system)
DELETE FROM free_coupon_codes a
USING free_coupon_codes b
WHERE a.free_coupon_id = b.free_coupon_id
  AND a.code = b.code
  AND a.id > b.id
  AND a.is_claimed = FALSE
  AND b.is_claimed = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_free_coupon_codes_unique_unclaimed
    ON free_coupon_codes (free_coupon_id, code)
    WHERE is_claimed = FALSE;

-- 4. Sync all coupon stocks to match actual unsold code counts
UPDATE coupons c
SET stock = sub.unsold,
    updated_at = NOW()
FROM (
    SELECT coupon_id, COUNT(*) as unsold
    FROM coupon_codes
    WHERE is_sold = FALSE
    GROUP BY coupon_id
) sub
WHERE c.id = sub.coupon_id;

-- Zero out coupons with no unsold codes
UPDATE coupons SET stock = 0, updated_at = NOW()
WHERE id NOT IN (SELECT DISTINCT coupon_id FROM coupon_codes WHERE is_sold = FALSE);
