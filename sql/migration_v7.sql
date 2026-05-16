-- ============================================================
-- Migration V7: Fix BharatPe UTR "already used" false positives
-- ============================================================

-- 1. Add index on (utr, status, gateway) for faster duplicate checks
CREATE INDEX IF NOT EXISTS idx_txn_utr_status_gw
    ON transactions (utr, status, gateway)
    WHERE utr IS NOT NULL;

-- 2. Clean stale UTR values from non-BharatPe gateways
--    Razorpay stores payment_link_id in the utr column,
--    which can collide with real BharatPe UTR numbers.
--    Only clear UTR from razorpay rows where status != 'success'
--    (don't touch completed razorpay payments).
UPDATE transactions
SET utr = NULL
WHERE gateway = 'razorpay'
  AND status IN ('initiated', 'pending', 'failed', 'expired');

-- 3. Clear any empty-string UTRs that might cause phantom matches
UPDATE transactions
SET utr = NULL
WHERE utr = '';

-- DONE
