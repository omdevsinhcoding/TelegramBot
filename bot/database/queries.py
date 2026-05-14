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


async def get_total_stock():
    """Get total available stock across all active coupons."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT COALESCE(SUM(stock), 0) as total FROM coupons WHERE is_active = TRUE"
    )
    return row["total"]

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
                         discounted_price: float, stock: int):
    pool = await get_pool()
    row = await pool.fetchrow("""
        INSERT INTO coupons (title, description, original_price, discounted_price, stock)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
    """, title, description, original_price, discounted_price, stock)
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
                        amount: float, timeout_sec: int, quantity: int = 1):
    pool = await get_pool()
    await pool.execute("""
        INSERT INTO orders (order_id, user_id, coupon_id, amount, quantity, expires_at)
        VALUES ($1, $2, $3, $4, $5, NOW() + interval '1 second' * $6)
    """, order_id, user_id, coupon_id, amount, quantity, timeout_sec)


async def create_reward_order(order_id: str, user_id: int, coupon_id: int,
                               source: str, quantity: int = 1):
    """Create a zero-amount order for referral rewards / giveaway claims.
    
    Args:
        source: 'referral_reward' or 'giveaway'
    """
    pool = await get_pool()
    await pool.execute("""
        INSERT INTO orders (order_id, user_id, coupon_id, amount, quantity, status, source, paid_at, expires_at)
        VALUES ($1, $2, $3, 0, $4, 'delivered', $5, NOW(), NOW() + interval '1 year')
    """, order_id, user_id, coupon_id, quantity, source)


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

async def get_user_orders(telegram_id: int, limit: int = 10, offset: int = 0, exclude_cancelled: bool = False):
    pool = await get_pool()
    if exclude_cancelled:
        return await pool.fetch(
            "SELECT * FROM orders WHERE user_id = $1 AND status NOT IN ('cancelled', 'expired') ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            telegram_id, limit, offset
        )
    return await pool.fetch(
        "SELECT * FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
        telegram_id, limit, offset
    )

async def get_user_orders_count(telegram_id: int, exclude_cancelled: bool = False) -> int:
    pool = await get_pool()
    if exclude_cancelled:
        return await pool.fetchval(
            "SELECT COUNT(*) FROM orders WHERE user_id = $1 AND status NOT IN ('cancelled', 'expired')", telegram_id
        ) or 0
    return await pool.fetchval("SELECT COUNT(*) FROM orders WHERE user_id = $1", telegram_id) or 0


async def get_all_orders(limit: int = 50):
    pool = await get_pool()
    return await pool.fetch("SELECT * FROM orders ORDER BY created_at DESC LIMIT $1", limit)


async def get_recent_order_users(limit: int = 15):
    """Get recent users who placed orders, grouped by user."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT o.user_id,
               u.full_name,
               u.username,
               COUNT(o.order_id) as order_count,
               COALESCE(SUM(o.amount), 0) as total_spent,
               MAX(o.created_at) as last_order,
               COUNT(*) FILTER (WHERE o.status IN ('paid', 'delivered')) as paid_count,
               COUNT(*) FILTER (WHERE o.status = 'pending') as pending_count
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.telegram_id
        GROUP BY o.user_id, u.full_name, u.username
        ORDER BY MAX(o.created_at) DESC
        LIMIT $1
    """, limit)


async def get_user_all_orders(user_id: int, limit: int = 20):
    """Get all orders for a specific user (admin view - all statuses)."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT o.*, c.title as coupon_title
        FROM orders o
        LEFT JOIN coupons c ON o.coupon_id = c.id
        WHERE o.user_id = $1
        ORDER BY o.created_at DESC
        LIMIT $2
    """, user_id, limit)


async def get_order_by_id_admin(order_id: str):
    """Get any order by ID (admin can see all orders)."""
    pool = await get_pool()
    return await pool.fetchrow("""
        SELECT o.*, c.title as coupon_title, u.full_name, u.username
        FROM orders o
        LEFT JOIN coupons c ON o.coupon_id = c.id
        LEFT JOIN users u ON o.user_id = u.telegram_id
        WHERE o.order_id = $1
    """, order_id)


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
        "INSERT INTO free_coupons (title, code, codes_per_user, created_by) VALUES ($1, $2, $3, $4) RETURNING id",
        title, '', codes_per_user, created_by)
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


async def get_coupons_with_codes():
    """Get coupons that have unsold codes available (for giveaway selection)."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT c.id, c.title, c.stock,
               COUNT(cc.id) FILTER (WHERE cc.is_sold = FALSE) as available_codes
        FROM coupons c
        JOIN coupon_codes cc ON cc.coupon_id = c.id
        WHERE c.is_active = TRUE
        GROUP BY c.id, c.title, c.stock
        HAVING COUNT(cc.id) FILTER (WHERE cc.is_sold = FALSE) > 0
        ORDER BY c.title
    """)


async def get_coupon_unsold_codes(coupon_id: int, limit: int = 100):
    """Get unsold codes from a coupon."""
    pool = await get_pool()
    return await pool.fetch(
        "SELECT code FROM coupon_codes WHERE coupon_id = $1 AND is_sold = FALSE LIMIT $2",
        coupon_id, limit
    )

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
    import random, string
    if row and row["referral_code"]:
        code = row["referral_code"]
        # Auto-migrate old format codes to new ERROROO- format
        if not code.startswith("ERROROO-"):
            code = "ERROROO-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            await pool.execute("UPDATE users SET referral_code = $2 WHERE telegram_id = $1", user_id, code)
        return code
    code = "ERROROO-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
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


# ── REFERRAL REWARDS (Coupon-based milestones) ────────────

async def get_referral_rewards() -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT rr.*, c.title, c.stock FROM referral_rewards rr "
        "JOIN coupons c ON rr.coupon_id = c.id "
        "ORDER BY rr.referrals_needed ASC"
    )

async def get_referral_reward(reward_id: int):
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT rr.*, c.title, c.stock FROM referral_rewards rr "
        "JOIN coupons c ON rr.coupon_id = c.id WHERE rr.id = $1", reward_id
    )

async def add_referral_reward(coupon_id: int, referrals_needed: int):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO referral_rewards (coupon_id, referrals_needed) VALUES ($1, $2) "
        "ON CONFLICT (coupon_id) DO UPDATE SET referrals_needed = $2, is_active = TRUE",
        coupon_id, referrals_needed
    )

async def remove_referral_reward(reward_id: int):
    pool = await get_pool()
    await pool.execute("DELETE FROM referral_rewards WHERE id = $1", reward_id)

async def toggle_referral_reward(reward_id: int) -> bool:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT is_active FROM referral_rewards WHERE id = $1", reward_id)
    if not row:
        return False
    new = not row["is_active"]
    await pool.execute("UPDATE referral_rewards SET is_active = $2 WHERE id = $1", reward_id, new)
    return new

async def update_referral_reward_count(reward_id: int, count: int):
    pool = await get_pool()
    await pool.execute("UPDATE referral_rewards SET referrals_needed = $2 WHERE id = $1", reward_id, count)

async def get_claimable_rewards(user_id: int, ref_count: int) -> list:
    """Get rewards user can claim (enough referrals + not already claimed + has stock)."""
    pool = await get_pool()
    return await pool.fetch(
        "SELECT rr.*, c.title, c.stock FROM referral_rewards rr "
        "JOIN coupons c ON rr.coupon_id = c.id "
        "WHERE rr.is_active = TRUE AND rr.referrals_needed <= $2 AND c.stock > 0 "
        "AND rr.id NOT IN (SELECT reward_id FROM referral_claims WHERE user_id = $1) "
        "ORDER BY rr.referrals_needed ASC",
        user_id, ref_count
    )

async def get_user_referral_claims(user_id: int) -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT rc.*, c.title FROM referral_claims rc "
        "JOIN coupons c ON rc.coupon_id = c.id "
        "WHERE rc.user_id = $1 ORDER BY rc.claimed_at DESC",
        user_id
    )

async def claim_referral_reward(user_id: int, reward_id: int) -> str | None:
    """Claim a referral reward — assigns a coupon code to the user. Returns the code or None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Get reward details
            reward = await conn.fetchrow(
                "SELECT rr.*, c.stock FROM referral_rewards rr "
                "JOIN coupons c ON rr.coupon_id = c.id WHERE rr.id = $1 AND rr.is_active = TRUE",
                reward_id
            )
            if not reward or reward["stock"] <= 0:
                return None

            # Check not already claimed
            existing = await conn.fetchrow(
                "SELECT id FROM referral_claims WHERE user_id = $1 AND reward_id = $2",
                user_id, reward_id
            )
            if existing:
                return None

            # Get available code
            code_row = await conn.fetchrow(
                "SELECT id, code FROM coupon_codes WHERE coupon_id = $1 AND is_sold = FALSE LIMIT 1",
                reward["coupon_id"]
            )
            if not code_row:
                return None

            # Mark code as sold
            await conn.execute(
                "UPDATE coupon_codes SET is_sold = TRUE, sold_to = $2, sold_at = NOW() WHERE id = $1",
                code_row["id"], user_id
            )
            # Decrease stock
            await conn.execute(
                "UPDATE coupons SET stock = stock - 1 WHERE id = $1",
                reward["coupon_id"]
            )
            # Record claim
            await conn.execute(
                "INSERT INTO referral_claims (user_id, reward_id, coupon_id, code) VALUES ($1, $2, $3, $4)",
                user_id, reward_id, reward["coupon_id"], code_row["code"]
            )
            return code_row["code"]

# ── BOT SETTINGS QUERIES ─────────────────────────────────

async def get_bot_settings():
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM bot_settings ORDER BY id LIMIT 1")
    if not row:
        await pool.execute("INSERT INTO bot_settings (force_channel) VALUES (NULL)")
        row = await pool.fetchrow("SELECT * FROM bot_settings ORDER BY id LIMIT 1")
    return row

async def update_bot_settings(**kwargs):
    pool = await get_pool()
    sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs.keys()))
    await pool.execute(f"UPDATE bot_settings SET {sets}, updated_at = NOW()", *list(kwargs.values()))


async def get_payment_settings():
    """Get payment settings from DB (admin-managed)."""
    settings = await get_bot_settings()

    return {
        "paytm_mid": settings.get("paytm_mid") or "",
        "paytm_upi_id": settings.get("paytm_upi_id") or "",
        "paytm_qr_code": settings.get("paytm_qr_code") or "",
        "bharatpe_merchant_id": settings.get("bharatpe_merchant_id") or "",
        "bharatpe_token": settings.get("bharatpe_token") or "",
        "bharatpe_upi_id": settings.get("bharatpe_upi_id") or "",
        "bharatpe_qr_path": settings.get("bharatpe_qr_path") or "",
        "upi_payee_name": settings.get("upi_payee_name") or "",
        # Gateway visibility toggles
        "gateway_paytm_enabled": settings.get("gateway_paytm_enabled", True),
        "gateway_bharatpe_enabled": settings.get("gateway_bharatpe_enabled", True),
        "gateway_razorpay_enabled": settings.get("gateway_razorpay_enabled", False),
        # Razorpay credentials
        "razorpay_key_id": settings.get("razorpay_key_id") or "",
        "razorpay_key_secret": settings.get("razorpay_key_secret") or "",
    }


# ── USER MANAGEMENT QUERIES ─────────────────────────────

async def search_user(query: str):
    """Search user by Telegram ID or username."""
    pool = await get_pool()
    # Try as integer (Telegram ID)
    if query.lstrip("-").isdigit():
        tid = int(query)
        row = await pool.fetchrow("SELECT * FROM users WHERE telegram_id = $1", tid)
        if row:
            return [row]
    # Search by username (partial match)
    clean = query.lstrip("@")
    rows = await pool.fetch(
        "SELECT * FROM users WHERE username ILIKE $1 OR full_name ILIKE $1 LIMIT 10",
        f"%{clean}%"
    )
    return rows


async def get_user_order_stats(telegram_id: int) -> dict:
    """Get comprehensive order statistics for a user."""
    pool = await get_pool()
    row = await pool.fetchrow("""
        SELECT 
            COUNT(*) as total_orders,
            COUNT(*) FILTER (WHERE status IN ('paid', 'delivered')) as total_paid,
            COUNT(*) FILTER (WHERE status = 'pending') as total_pending,
            COUNT(*) FILTER (WHERE status = 'cancelled') as total_cancelled,
            COUNT(*) FILTER (WHERE status = 'expired') as total_expired,
            COUNT(*) FILTER (WHERE status = 'delivered') as total_delivered,
            COALESCE(SUM(amount) FILTER (WHERE status IN ('paid', 'delivered')), 0) as total_spent
        FROM orders WHERE user_id = $1
    """, telegram_id)
    return dict(row) if row else {
        "total_orders": 0, "total_paid": 0, "total_pending": 0,
        "total_cancelled": 0, "total_expired": 0, "total_delivered": 0, "total_spent": 0
    }


async def get_user_referrals(telegram_id: int, limit: int = 20):
    """Get all referrals made by a user."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT r.*, u.username, u.full_name
        FROM referrals r
        JOIN users u ON u.telegram_id = r.referred_id
        WHERE r.referrer_id = $1
        ORDER BY r.created_at DESC LIMIT $2
    """, telegram_id, limit)


async def set_user_referrer(user_id: int, referrer_id: int):
    """Set or change who referred a user. Admin-only operation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update users table
            await conn.execute(
                "UPDATE users SET referred_by = $2 WHERE telegram_id = $1",
                user_id, referrer_id
            )
            # Upsert referral record
            await conn.execute("""
                INSERT INTO referrals (referrer_id, referred_id, status)
                VALUES ($1, $2, 'joined')
                ON CONFLICT (referred_id) DO UPDATE SET referrer_id = $1
            """, referrer_id, user_id)


async def is_user_banned(telegram_id: int) -> bool:
    """Check if a user is banned."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT is_banned FROM users WHERE telegram_id = $1", telegram_id
    )
    return bool(row and row["is_banned"])


async def get_referrer_of(telegram_id: int):
    """Get who referred this user."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT referred_by FROM users WHERE telegram_id = $1", telegram_id
    )
    if row and row["referred_by"]:
        return await pool.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1", row["referred_by"]
        )
    return None


# ── DYNAMIC CONFIG QUERIES ──────────────────────────────

async def get_dynamic_config() -> dict:
    """Get dynamic settings from bot_settings (admin-managed).
    
    Returns dict with:
        payment_timeout_seconds: int (default 600)
        bharatpe_min_recharge: float (default 10)
        payment_poll_interval: int (default 30)
    """
    settings = await get_bot_settings()
    return {
        "payment_timeout_seconds": int(settings.get("payment_timeout_seconds") or 600),
        "bharatpe_min_recharge": float(settings.get("bharatpe_min_recharge") or 10),
        "payment_poll_interval": int(settings.get("payment_poll_interval") or 30),
    }


# ── BULK COUPON CODE INSERT ─────────────────────────────

async def add_coupon_codes_bulk(coupon_id: int, codes: list[str]):
    """Insert multiple coupon codes in a single transaction.
    
    Much faster than inserting one-by-one. Prevents timeout errors
    when admin pastes hundreds of codes.
    """
    if not codes:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                "INSERT INTO coupon_codes (coupon_id, code) VALUES ($1, $2)",
                [(coupon_id, code) for code in codes]
            )
    return len(codes)


# ── ADMIN MANAGEMENT QUERIES ────────────────────────────

async def get_all_admins() -> list:
    """Get all dynamically-added admins from DB."""
    pool = await get_pool()
    return await pool.fetch("SELECT * FROM admins ORDER BY added_at DESC")


async def add_admin(telegram_id: int, added_by: int) -> bool:
    """Add a new admin to the DB. Returns True if added, False if already exists."""
    pool = await get_pool()
    try:
        await pool.execute(
            "INSERT INTO admins (telegram_id, added_by) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            telegram_id, added_by
        )
        return True
    except Exception:
        return False


async def remove_admin(telegram_id: int) -> bool:
    """Remove an admin from the DB. Returns True if removed."""
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM admins WHERE telegram_id = $1", telegram_id
    )
    return result != "DELETE 0"


async def get_db_admin_ids() -> set[int]:
    """Get set of all admin Telegram IDs from DB (for fast lookup)."""
    pool = await get_pool()
    rows = await pool.fetch("SELECT telegram_id FROM admins")
    return {row["telegram_id"] for row in rows}
