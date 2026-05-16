-- ============================================================
-- Migration V6: Fix BharatPe validation + Configurable gateway names
-- ============================================================

-- 1. Add custom display names for payment gateways
--    Admin can rename "Paytm" to "UPI Gateway" etc.
ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS gateway_paytm_name    VARCHAR(64) DEFAULT 'Paytm';
ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS gateway_bharatpe_name VARCHAR(64) DEFAULT 'BharatPe';
ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS gateway_razorpay_name VARCHAR(64) DEFAULT 'Razorpay';

-- 2. Fix UTR early-store issue: clear stale UTRs from failed verifications
--    Only clear UTRs where the transaction status is still 'initiated' or 'pending'
--    (verified UTRs with status='success' are kept intact)
UPDATE transactions SET utr = NULL
WHERE utr IS NOT NULL
  AND status IN ('initiated', 'pending')
  AND order_id IN (SELECT order_id FROM orders WHERE status = 'pending');

-- DONE
