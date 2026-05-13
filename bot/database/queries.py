"""
DreamX Coupon Bot — Database Query Layer
All raw SQL queries encapsulated here.
"""

from bot.database.connection import get_pool
from bot.utils.logger import logger


# ── USER QUERIES ──────────────────────────────────────────

async def upsert_user(telegram_id: int, username: str | None, full_name: str | None):
    pool = await get_pool()
    await pool.execute("""
        INSERT INTO users (telegram_id, username, full_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (telegram_id) DO UPDATE
        SET username = $2, full_name = $3, updated_at = NOW()
    """, telegram_id, username, full_name)


async def get_user(telegram_id: int):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)


async def get_all_users():
    pool = await get_pool()
    return await pool.fetch("SELECT * FROM users ORDER BY joined_at DESC")


async def get_user_count():
    pool = await get_pool()
    row = await pool.fetchrow("SELECT COUNT(*) as cnt FROM users")
    return row["cnt"]


async def ban_user(telegram_id: int, banned: bool = True):
    pool = await get_pool()
    await pool.execute("UPDATE users SET is_banned = $2 WHERE telegram_id = $1", telegram_id, banned)


# ── WALLET QUERIES ────────────────────────────────────────

async def get_wallet_balance(telegram_id: int) -> float:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT wallet_balance FROM users WHERE telegram_id = $1", telegram_id)
    return float(row["wallet_balance"]) if row else 0.0


async def update_wallet_balance(telegram_id: int, new_balance: float):
    pool = await get_pool()
    await pool.execute(
        "UPDATE users SET wallet_balance = $2, updated_at = NOW() WHERE telegram_id = $1",
        telegram_id, new_balance
    )


async def add_wallet_transaction(user_id: int, amount: float, txn_type: str,
                                  bal_before: float, bal_after: float,
                                  reference: str = None, description: str = None):
    pool = await get_pool()
    await pool.execute("""
        INSERT INTO wallet_transactions (user_id, amount, txn_type, balance_before, balance_after, reference, description)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, user_id, amount, txn_type, bal_before, bal_after, reference, description)


async def get_wallet_history(telegram_id: int, limit: int = 10):
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM wallet_transactions WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
        telegram_id, limit
    )


# ── COUPON QUERIES ────────────────────────────────────────

async def create_coupon(title: str, description: str, original_price: float,
                         discounted_price: float, stock: int, category: str = None):
    pool = await get_pool()
    row = await pool.fetchrow("""
        INSERT INTO coupons (title, description, original_price, discounted_price, stock, category)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
    """, title, description, original_price, discounted_price, stock, category)
    return row["id"]


async def get_coupon(coupon_id: int):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM coupons WHERE id = $1", coupon_id)


async def get_active_coupons():
    pool = await get_pool()
    return await pool.fetch("SELECT * FROM coupons WHERE is_active = TRUE ORDER BY id DESC")


async def get_all_coupons():
    pool = await get_pool()
    return await pool.fetch("SELECT * FROM coupons ORDER BY id DESC")


async def update_coupon(coupon_id: int, **fields):
    pool = await get_pool()
    set_parts = []
    values = []
    idx = 1
    for key, val in fields.items():
        set_parts.append(f"{key} = ${idx}")
        values.append(val)
        idx += 1
    set_parts.append(f"updated_at = NOW()")
    values.append(coupon_id)
    query = f"UPDATE coupons SET {', '.join(set_parts)} WHERE id = ${idx}"
    await pool.execute(query, *values)


async def delete_coupon(coupon_id: int):
    pool = await get_pool()
    await pool.execute("DELETE FROM coupons WHERE id = $1", coupon_id)


async def reduce_stock(coupon_id: int) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE coupons SET stock = stock - 1, updated_at = NOW() WHERE id = $1 AND stock > 0",
        coupon_id
    )
    return result == "UPDATE 1"


# ── ORDER QUERIES ─────────────────────────────────────────

async def create_order(order_id: str, user_id: int, coupon_id: int,
                        amount: float, timeout_sec: int):
    pool = await get_pool()
    await pool.execute("""
        INSERT INTO orders (order_id, user_id, coupon_id, amount, expires_at)
        VALUES ($1, $2, $3, $4, NOW() + interval '1 second' * $5)
    """, order_id, user_id, coupon_id, amount, timeout_sec)


async def get_order(order_id: str):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)


async def update_order_status(order_id: str, status: str, txn_id: str = None):
    pool = await get_pool()
    if status == "paid":
        await pool.execute("""
            UPDATE orders SET status = $2, txn_id = $3, paid_at = NOW(), updated_at = NOW()
            WHERE order_id = $1
        """, order_id, status, txn_id)
    else:
        await pool.execute(
            "UPDATE orders SET status = $2, updated_at = NOW() WHERE order_id = $1",
            order_id, status
        )

async def update_order_qr_message_id(order_id: str, message_id: int):
    pool = await get_pool()
    await pool.execute(
        "UPDATE orders SET qr_message_id = $2 WHERE order_id = $1",
        order_id, message_id
    )


async def get_pending_orders():
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM orders WHERE status = 'pending' ORDER BY created_at ASC"
    )


async def get_user_orders(telegram_id: int, limit: int = 10):
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
        telegram_id, limit
    )


async def get_all_orders(limit: int = 50):
    pool = await get_pool()
    return await pool.fetch("SELECT * FROM orders ORDER BY created_at DESC LIMIT $1", limit)


async def expire_stale_orders():
    pool = await get_pool()
    return await pool.execute("""
        UPDATE orders SET status = 'expired', updated_at = NOW()
        WHERE status = 'pending' AND expires_at < NOW()
    """)


# ── TRANSACTION QUERIES ──────────────────────────────────

async def create_transaction(txn_ref: str, order_id: str, user_id: int,
                              amount: float, merchant_id: str, gateway: str = "paytm"):
    pool = await get_pool()
    await pool.execute("""
        INSERT INTO transactions (txn_ref, order_id, user_id, amount, merchant_id, gateway)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, txn_ref, order_id, user_id, amount, merchant_id, gateway)


async def get_transaction(txn_ref: str):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM transactions WHERE txn_ref = $1", txn_ref)


async def update_transaction(txn_ref: str, status: str, raw_response: str = None):
    pool = await get_pool()
    await pool.execute("""
        UPDATE transactions SET status = $2, raw_response = $3, verified_at = NOW(), updated_at = NOW()
        WHERE txn_ref = $1
    """, txn_ref, status, raw_response)


async def get_pending_transactions():
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM transactions WHERE status IN ('initiated', 'pending') ORDER BY created_at ASC"
    )


# ── COUPON CODES QUERIES ─────────────────────────────────

async def add_coupon_code(coupon_id: int, code: str):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO coupon_codes (coupon_id, code) VALUES ($1, $2)",
        coupon_id, code
    )


async def get_available_code(coupon_id: int):
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT * FROM coupon_codes WHERE coupon_id = $1 AND is_sold = FALSE LIMIT 1",
        coupon_id
    )


async def mark_code_sold(code_id: int, user_id: int, order_id: str):
    pool = await get_pool()
    await pool.execute("""
        UPDATE coupon_codes SET is_sold = TRUE, sold_to = $2, order_id = $3, sold_at = NOW()
        WHERE id = $1
    """, code_id, user_id, order_id)


# ── ADMIN LOG QUERIES ────────────────────────────────────

async def add_admin_log(admin_id: int, action: str, target_type: str = None,
                         target_id: str = None, details: str = None):
    import json
    pool = await get_pool()
    # Schema uses JSONB; wrap plain strings in a JSON object
    details_json = None
    if details is not None:
        if isinstance(details, str):
            details_json = json.dumps({"info": details})
        elif isinstance(details, dict):
            details_json = json.dumps(details)
        else:
            details_json = json.dumps({"info": str(details)})
    await pool.execute("""
        INSERT INTO admin_logs (admin_id, action, target_type, target_id, details)
        VALUES ($1, $2, $3, $4, $5::jsonb)
    """, admin_id, action, target_type, target_id, details_json)


async def get_admin_logs(limit: int = 20):
    pool = await get_pool()
    return await pool.fetch("SELECT * FROM admin_logs ORDER BY created_at DESC LIMIT $1", limit)


# ── BROADCAST QUERIES ────────────────────────────────────

async def create_broadcast(admin_id: int, message_text: str, total_users: int):
    pool = await get_pool()
    row = await pool.fetchrow("""
        INSERT INTO broadcasts (admin_id, message_text, total_users)
        VALUES ($1, $2, $3) RETURNING id
    """, admin_id, message_text, total_users)
    return row["id"]


async def update_broadcast(broadcast_id: int, sent: int, failed: int, status: str):
    pool = await get_pool()
    if status == 'completed':
        await pool.execute("""
            UPDATE broadcasts SET sent_count = $2, failed_count = $3, status = $4,
            completed_at = NOW()
            WHERE id = $1
        """, broadcast_id, sent, failed, status)
    else:
        await pool.execute("""
            UPDATE broadcasts SET sent_count = $2, failed_count = $3, status = $4
            WHERE id = $1
        """, broadcast_id, sent, failed, status)


# ── ANALYTICS ─────────────────────────────────────────────

async def get_sales_stats():
    pool = await get_pool()
    return await pool.fetchrow("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'paid') as total_paid,
            COUNT(*) FILTER (WHERE status = 'pending') as total_pending,
            COUNT(*) FILTER (WHERE status = 'expired') as total_expired,
            COALESCE(SUM(amount) FILTER (WHERE status = 'paid'), 0) as total_revenue,
            COUNT(*) as total_orders
        FROM orders
    """)


# ── FREE COUPON / GIVEAWAY QUERIES (MULTI-CODE) ──────────

async def create_free_coupon(title: str, codes_per_user: int, created_by: int) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO free_coupons (title, codes_per_user, created_by) VALUES ($1, $2, $3) RETURNING id",
        title, codes_per_user, created_by)
    return row["id"]

async def add_giveaway_codes(fc_id: int, codes: list):
    pool = await get_pool()
    for code in codes:
        c = code.strip()
        if c:
            await pool.execute("INSERT INTO free_coupon_codes (free_coupon_id, code) VALUES ($1, $2)", fc_id, c)
    fc = await pool.fetchrow("SELECT codes_per_user FROM free_coupons WHERE id = $1", fc_id)
    total = await pool.fetchval("SELECT COUNT(*) FROM free_coupon_codes WHERE free_coupon_id = $1", fc_id)
    cpu = fc["codes_per_user"] if fc else 1
    await pool.execute("UPDATE free_coupons SET max_claims = $2 WHERE id = $1", fc_id, total // max(cpu, 1))

async def get_active_free_coupons() -> list:
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM free_coupons WHERE is_active = TRUE ORDER BY created_at DESC")
    result = []
    for r in rows:
        unclaimed = await pool.fetchval("SELECT COUNT(*) FROM free_coupon_codes WHERE free_coupon_id = $1 AND is_claimed = FALSE", r["id"])
        result.append({**dict(r), "unclaimed_codes": unclaimed})
    return result

async def get_all_free_coupons() -> list:
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM free_coupons ORDER BY created_at DESC")
    result = []
    for r in rows:
        total = await pool.fetchval("SELECT COUNT(*) FROM free_coupon_codes WHERE free_coupon_id = $1", r["id"])
        unclaimed = await pool.fetchval("SELECT COUNT(*) FROM free_coupon_codes WHERE free_coupon_id = $1 AND is_claimed = FALSE", r["id"])
        result.append({**dict(r), "total_codes": total, "unclaimed_codes": unclaimed})
    return result

async def get_free_coupon(fc_id: int):
    pool = await get_pool()
    r = await pool.fetchrow("SELECT * FROM free_coupons WHERE id = $1", fc_id)
    if not r: return None
    total = await pool.fetchval("SELECT COUNT(*) FROM free_coupon_codes WHERE free_coupon_id = $1", fc_id)
    unclaimed = await pool.fetchval("SELECT COUNT(*) FROM free_coupon_codes WHERE free_coupon_id = $1 AND is_claimed = FALSE", fc_id)
    return {**dict(r), "total_codes": total, "unclaimed_codes": unclaimed}

async def claim_free_coupon(fc_id: int, user_id: int) -> list | None:
    pool = await get_pool()
    existing = await pool.fetchrow("SELECT id FROM free_coupon_claims WHERE free_coupon_id = $1 AND user_id = $2", fc_id, user_id)
    if existing: return None
    fc = await pool.fetchrow("SELECT * FROM free_coupons WHERE id = $1 AND is_active = TRUE", fc_id)
    if not fc: return None
    cpu = fc["codes_per_user"] or 1
    available = await pool.fetch(
        "SELECT id, code FROM free_coupon_codes WHERE free_coupon_id = $1 AND is_claimed = FALSE ORDER BY id LIMIT $2", fc_id, cpu)
    if len(available) < cpu: return None
    codes = []
    for row in available:
        await pool.execute("UPDATE free_coupon_codes SET is_claimed = TRUE, claimed_by = $2, claimed_at = NOW() WHERE id = $1", row["id"], user_id)
        codes.append(row["code"])
    try:
        await pool.execute("INSERT INTO free_coupon_claims (free_coupon_id, user_id) VALUES ($1, $2)", fc_id, user_id)
    except Exception: pass
    await pool.execute("UPDATE free_coupons SET claimed_count = claimed_count + 1 WHERE id = $1", fc_id)
    return codes

async def has_user_claimed(fc_id: int, user_id: int) -> bool:
    pool = await get_pool()
    return bool(await pool.fetchrow("SELECT id FROM free_coupon_claims WHERE free_coupon_id = $1 AND user_id = $2", fc_id, user_id))

async def reclaim_unclaimed_codes(fc_id: int) -> list:
    pool = await get_pool()
    rows = await pool.fetch("SELECT code FROM free_coupon_codes WHERE free_coupon_id = $1 AND is_claimed = FALSE", fc_id)
    codes = [r["code"] for r in rows]
    await pool.execute("DELETE FROM free_coupon_codes WHERE free_coupon_id = $1 AND is_claimed = FALSE", fc_id)
    return codes

async def delete_free_coupon(fc_id: int):
    pool = await get_pool()
    await pool.execute("DELETE FROM free_coupons WHERE id = $1", fc_id)

async def toggle_free_coupon(fc_id: int) -> bool:
    pool = await get_pool()
    fc = await pool.fetchrow("SELECT is_active FROM free_coupons WHERE id = $1", fc_id)
    if not fc: return False
    new_status = not fc["is_active"]
    await pool.execute("UPDATE free_coupons SET is_active = $2 WHERE id = $1", fc_id, new_status)
    return new_status

# ── REFERRAL QUERIES ─────────────────────────────────────

async def get_referral_settings():
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM referral_settings ORDER BY id LIMIT 1")

async def update_referral_settings(**kwargs):
    pool = await get_pool()
    sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs.keys()))
    await pool.execute(f"UPDATE referral_settings SET {sets}, updated_at = NOW()", *list(kwargs.values()))

async def get_or_create_referral_code(user_id: int) -> str:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT referral_code FROM users WHERE telegram_id = $1", user_id)
    if row and row["referral_code"]: return row["referral_code"]
    import random, string
    code = "REF" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    await pool.execute("UPDATE users SET referral_code = $2 WHERE telegram_id = $1", user_id, code)
    return code

async def get_user_by_referral_code(code: str):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM users WHERE referral_code = $1", code)

async def record_referral(referrer_id: int, referred_id: int) -> bool:
    pool = await get_pool()
    try:
        await pool.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES ($1, $2)", referrer_id, referred_id)
        await pool.execute("UPDATE users SET referred_by = $1 WHERE telegram_id = $2", referrer_id, referred_id)
        return True
    except Exception: return False

async def get_referral_count(user_id: int) -> int:
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM referrals WHERE referrer_id = $1", user_id) or 0

async def get_referral_history(user_id: int, limit: int = 20) -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT r.*, u.username, u.full_name FROM referrals r JOIN users u ON r.referred_id = u.telegram_id "
        "WHERE r.referrer_id = $1 ORDER BY r.created_at DESC LIMIT $2", user_id, limit)

async def add_referral_earnings(user_id: int, amount: float):
    pool = await get_pool()
    await pool.execute(
        "UPDATE users SET referral_earnings = referral_earnings + $2, wallet_balance = wallet_balance + $2 WHERE telegram_id = $1",
        user_id, amount)

async def get_user_wallet(user_id: int) -> float:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT wallet_balance FROM users WHERE telegram_id = $1", user_id)
    return float(row["wallet_balance"]) if row else 0.0

async def get_user_referral_earnings(user_id: int) -> float:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT referral_earnings FROM users WHERE telegram_id = $1", user_id)
    return float(row["referral_earnings"]) if row else 0.0





