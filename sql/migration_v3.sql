-- ============================================================
-- DreamX Coupon Bot — Migration v3
-- RUN THIS on your live PostgreSQL database to fix the errors:
--   "column reservation_enabled of relation bot_settings does not exist"
--   "column waitlist_enabled of relation bot_settings does not exist"
--
-- Safe to run multiple times (uses IF NOT EXISTS).
-- ============================================================

-- reservation_enabled: controls whether stock reservation system is active
-- When ON:  stock is locked per order (prevents overselling)
-- When OFF: first-paid-first-served, no locking
ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS reservation_enabled BOOLEAN DEFAULT TRUE;

-- waitlist_enabled: controls whether users are put on a waitlist when stock is 0
-- When ON:  out-of-stock users join a queue and get notified when stock returns
-- When OFF: users see a simple "out of stock" message instead
ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS waitlist_enabled BOOLEAN DEFAULT TRUE;

-- force_join_apply_admins: whether force join also applies to admins
ALTER TABLE bot_settings
    ADD COLUMN IF NOT EXISTS force_join_apply_admins BOOLEAN DEFAULT FALSE;

-- ============================================================
-- DONE. All 3 missing columns added.
-- ============================================================
