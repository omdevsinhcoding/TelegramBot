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


async def get_users_paginated(limit: int = 15, offset: int = 0):
    """Get users with pagination for admin panel."""
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM users ORDER BY joined_at DESC LIMIT $1 OFFSET $2",
        limit, offset
    )


async def get_user_count():
    pool = await get_pool()
    row = await pool.fetchrow("SELECT COUNT(*) as cnt FROM users")
    return row["cnt"]


async def get_total_stock():
    """Total available stock = actual unsold codes across all active coupons.
    Counts directly from coupon_codes so it's always accurate.
    """
    pool = await get_pool()
    row = await pool.fetchrow("""
        SELECT COUNT(*) as total
        FROM coupon_codes cc
        JOIN coupons c ON c.id = cc.coupon_id
        WHERE cc.is_sold = FALSE AND c.is_active = TRUE
    """)
    return row["total"] if row else 0

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
    """Legacy: reduce stock by 1. Use reserve_stock() for new flow."""
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE coupons SET stock = stock - 1, updated_at = NOW() WHERE id = $1 AND stock > 0",
        coupon_id
    )
    return result == "UPDATE 1"


# ── RESERVATION SYSTEM ───────────────────────────────────

async def reserve_stock(coupon_id: int, qty: int = 1) -> bool:
    """Atomically reserve stock: decrement stock, increment reserved_qty.
    
    Returns True if reservation succeeded, False if not enough stock.
    This is race-condition safe — the WHERE clause ensures atomicity.
    """
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE coupons 
           SET stock = stock - $2, reserved_qty = COALESCE(reserved_qty, 0) + $2, updated_at = NOW()
           WHERE id = $1 AND stock >= $2""",
        coupon_id, qty
    )
    return result == "UPDATE 1"


async def release_reservation(coupon_id: int, qty: int = 1) -> bool:
    """Release reserved stock back to available (on cancel/expire).
    
    Returns stock to pool: stock += qty, reserved_qty -= qty.
    """
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE coupons 
           SET stock = stock + $2, reserved_qty = GREATEST(COALESCE(reserved_qty, 0) - $2, 0), updated_at = NOW()
           WHERE id = $1""",
        coupon_id, qty
    )
    return result == "UPDATE 1"


async def confirm_reservation(coupon_id: int, qty: int = 1) -> bool:
    """Confirm reservation on payment success.
    
    Stock was already decremented during reservation, just clear reserved_qty.
    """
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE coupons 
           SET reserved_qty = GREATEST(COALESCE(reserved_qty, 0) - $2, 0), updated_at = NOW()
           WHERE id = $1""",
        coupon_id, qty
    )
    return result == "UPDATE 1"


async def release_all_reservations() -> tuple[int, list]:
    """Release ALL currently pending-order reservations instantly.

    Called when the admin disables the reservation system.
    Restores stock for every pending order, expires those orders, and
    returns the list of affected orders so the caller can notify users.

    Returns:
        (count, affected_orders)
        count          — number of orders expired
        affected_orders — list of dicts: {order_id, user_id, coupon_title}
    """
    pool = await get_pool()

    # 0. Snapshot all pending orders BEFORE expiring (we need user_id for notifications)
    affected_rows = await pool.fetch("""
        SELECT o.order_id, o.user_id, COALESCE(c.title, 'your coupon') AS coupon_title
        FROM orders o
        LEFT JOIN coupons c ON o.coupon_id = c.id
        WHERE o.status = 'pending'
    """)
    affected = [dict(r) for r in affected_rows]

    # 1. Restore stock in one batch UPDATE (no N+1)
    await pool.execute("""
        UPDATE coupons
        SET stock        = stock + sub.total_qty,
            reserved_qty = 0,
            updated_at   = NOW()
        FROM (
            SELECT coupon_id, SUM(COALESCE(quantity, 1)) AS total_qty
            FROM orders
            WHERE status = 'pending'
            GROUP BY coupon_id
        ) sub
        WHERE coupons.id = sub.coupon_id
    """)

    # 2. Expire all pending orders
    result = await pool.execute("""
        UPDATE orders
        SET status = 'expired', updated_at = NOW()
        WHERE status = 'pending'
    """)

    try:
        count = int(result.split()[-1])
    except (IndexError, ValueError):
        count = len(affected)

    return count, affected


async def get_reservation_info(coupon_id: int) -> dict:
    """Get stock + reservation details in a SINGLE query.
    
    Returns dict with: stock, reserved_qty, wait_minutes.
    """
    pool = await get_pool()
    row = await pool.fetchrow("""
        SELECT c.stock, COALESCE(c.reserved_qty, 0) as reserved_qty,
               (SELECT MIN(expires_at) FROM orders 
                WHERE coupon_id = $1 AND status = 'pending') as earliest_expiry
        FROM coupons c WHERE c.id = $1
    """, coupon_id)
    
    if not row:
        return {"stock": 0, "reserved_qty": 0, "wait_minutes": 0}
    
    wait_minutes = 0
    if row["earliest_expiry"]:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        diff = (row["earliest_expiry"] - now).total_seconds()
        wait_minutes = max(1, int(diff / 60) + 1)
    
    return {
        "stock": row["stock"],
        "reserved_qty": row["reserved_qty"],
        "wait_minutes": wait_minutes,
    }


# ── WAITLIST ─────────────────────────────────────────────

async def add_to_waitlist(user_id: int, coupon_id: int):
    """Add user to waitlist for a coupon. Ignores if already waiting."""
    pool = await get_pool()
    await pool.execute("""
        INSERT INTO coupon_waitlist (user_id, coupon_id)
        VALUES ($1, $2) ON CONFLICT (user_id, coupon_id) DO NOTHING
    """, user_id, coupon_id)


async def get_waitlist_users(coupon_id: int) -> list:
    """Get all users waiting for a coupon."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT user_id FROM coupon_waitlist WHERE coupon_id = $1 ORDER BY created_at ASC",
        coupon_id
    )
    return [r["user_id"] for r in rows]


async def remove_from_waitlist(user_id: int, coupon_id: int):
    """Remove user from waitlist (after notification or purchase)."""
    pool = await get_pool()
    await pool.execute(
        "DELETE FROM coupon_waitlist WHERE user_id = $1 AND coupon_id = $2",
        user_id, coupon_id
    )


async def clear_waitlist(coupon_id: int):
    """Clear entire waitlist for a coupon."""
    pool = await get_pool()
    await pool.execute("DELETE FROM coupon_waitlist WHERE coupon_id = $1", coupon_id)


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
    """Fetch user orders with coupon title + code count in ONE query (no N+1)."""
    pool = await get_pool()
    cancel_filter = "AND o.status NOT IN ('cancelled', 'expired')" if exclude_cancelled else ""
    return await pool.fetch(f"""
        SELECT o.*, c.title as coupon_title,
               COALESCE(cc.code_count, 0) as code_count
        FROM orders o
        LEFT JOIN coupons c ON c.id = o.coupon_id
        LEFT JOIN (
            SELECT order_id, COUNT(*) as code_count 
            FROM coupon_codes WHERE is_sold = TRUE
            GROUP BY order_id
        ) cc ON cc.order_id = o.order_id
        WHERE o.user_id = $1 {cancel_filter}
        ORDER BY o.created_at DESC LIMIT $2 OFFSET $3
    """, telegram_id, limit, offset)

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
    """Expire pending orders past their timeout AND release reserved stock.
    
    Uses batch SQL — no N+1 queries.
    """
    pool = await get_pool()
    
    # Batch release: aggregate qty per coupon, then release all at once
    await pool.execute("""
        UPDATE coupons SET 
            stock = stock + sub.total_qty,
            reserved_qty = GREATEST(COALESCE(reserved_qty, 0) - sub.total_qty, 0),
            updated_at = NOW()
        FROM (
            SELECT coupon_id, SUM(COALESCE(quantity, 1)) as total_qty 
            FROM orders 
            WHERE status = 'pending' AND expires_at < NOW()
            GROUP BY coupon_id
        ) sub
        WHERE coupons.id = sub.coupon_id
    """)
    
    # Mark expired
    result = await pool.execute("""
        UPDATE orders SET status = 'expired', updated_at = NOW()
        WHERE status = 'pending' AND expires_at < NOW()
    """)
    return result


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

async def sync_coupon_stock(coupon_id: int):
    """Reconcile coupons.stock with the real count of unsold codes.

    Call this after any operation that changes coupon_codes (add, delete).
    The coupons.stock column is used for fast stock checks / reservations,
    so keeping it in sync is critical for accurate display.
    """
    pool = await get_pool()
    await pool.execute("""
        UPDATE coupons
        SET stock = (
            SELECT COUNT(*) FROM coupon_codes
            WHERE coupon_id = $1 AND is_sold = FALSE
        ),
        updated_at = NOW()
        WHERE id = $1
    """, coupon_id)


async def sync_all_coupon_stocks():
    """Reconcile stock for ALL coupons in one query. Use after bulk operations."""
    pool = await get_pool()
    await pool.execute("""
        UPDATE coupons c
        SET stock = sub.unsold,
            updated_at = NOW()
        FROM (
            SELECT coupon_id, COUNT(*) as unsold
            FROM coupon_codes
            WHERE is_sold = FALSE
            GROUP BY coupon_id
        ) sub
        WHERE c.id = sub.coupon_id
    """)
    # Zero out coupons that have no codes at all
    await pool.execute("""
        UPDATE coupons SET stock = 0, updated_at = NOW()
        WHERE id NOT IN (SELECT DISTINCT coupon_id FROM coupon_codes WHERE is_sold = FALSE)
    """)


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
    # Get coupon_id before marking sold (needed for stock sync)
    row = await pool.fetchrow("SELECT coupon_id FROM coupon_codes WHERE id = $1", code_id)
    await pool.execute("""
        UPDATE coupon_codes SET is_sold = TRUE, sold_to = $2, order_id = $3, sold_at = NOW()
        WHERE id = $1
    """, code_id, user_id, order_id)
    # Sync stock: ensure coupons.stock matches actual unsold count
    if row:
        await sync_coupon_stock(row["coupon_id"])


async def get_coupon_unsold_codes_list(coupon_id: int) -> list[str]:
    """Get all unsold/remaining codes for a coupon (admin download)."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT code FROM coupon_codes WHERE coupon_id = $1 AND is_sold = FALSE ORDER BY id",
        coupon_id
    )
    return [r["code"] for r in rows]


async def get_coupon_code_stats(coupon_id: int) -> dict:
    """Get code statistics for a coupon."""
    pool = await get_pool()
    row = await pool.fetchrow("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE is_sold = TRUE) as sold,
            COUNT(*) FILTER (WHERE is_sold = FALSE) as unsold
        FROM coupon_codes WHERE coupon_id = $1
    """, coupon_id)
    return dict(row) if row else {"total": 0, "sold": 0, "unsold": 0}


async def get_giveaway_unclaimed_codes_list(fc_id: int) -> list[str]:
    """Get all unclaimed codes for a giveaway (admin download)."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT code FROM free_coupon_codes WHERE free_coupon_id = $1 AND is_claimed = FALSE ORDER BY id",
        fc_id
    )
    return [r["code"] for r in rows]


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

async def set_all_free_coupons_active(active: bool):
    """Enable or disable ALL giveaways at once."""
    pool = await get_pool()
    await pool.execute("UPDATE free_coupons SET is_active = $1", active)

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

async def get_referrals_for_user(referrer_id: int) -> list:
    """Return all referral rows where user is the referrer, with referred user's name."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT r.referrer_id, r.referred_id, r.status, r.commission,
               COALESCE(u.full_name, u.username, r.referred_id::text) AS referred_name,
               r.created_at
        FROM referrals r
        LEFT JOIN users u ON u.telegram_id = r.referred_id
        WHERE r.referrer_id = $1
        ORDER BY r.created_at DESC
    """, referrer_id)

async def delete_referral(referrer_id: int, referred_id: int) -> dict:
    """Delete a referral record and reverse the wallet credit.

    Returns: {deleted: bool, reversed_amount: float}
    """
    pool = await get_pool()

    # 1. Get the referral row so we know how much commission/reward was given
    ref_row = await pool.fetchrow(
        "SELECT status, commission FROM referrals WHERE referrer_id = $1 AND referred_id = $2",
        referrer_id, referred_id
    )
    if not ref_row:
        return {"deleted": False, "reversed_amount": 0.0}

    commission = float(ref_row["commission"] or 0)
    reward_reversed = commission

    # 2. Try to reverse wallet credit (non-critical — must not block deletion)
    try:
        if commission > 0:
            await pool.execute("""
                UPDATE users
                SET wallet_balance    = GREATEST(0, wallet_balance    - $2),
                    referral_earnings = GREATEST(0, referral_earnings - $2)
                WHERE telegram_id = $1
            """, referrer_id, commission)
        else:
            # Commission column is 0 — check wallet_transactions for the actual reward
            # Match ALL possible reference formats used across the codebase
            txn = await pool.fetchrow("""
                SELECT amount FROM wallet_transactions
                WHERE user_id = $1
                  AND reference IN ($2, $3, $4)
                ORDER BY created_at DESC LIMIT 1
            """, referrer_id,
                f"referral_from_{referred_id}",
                f"ref_join_reward_from_{referred_id}",
                f"ref_backfill_from_{referred_id}"
            )
            if txn:
                reward_reversed = float(txn["amount"])
                await pool.execute("""
                    UPDATE users
                    SET wallet_balance    = GREATEST(0, wallet_balance    - $2),
                        referral_earnings = GREATEST(0, referral_earnings - $2)
                    WHERE telegram_id = $1
                """, referrer_id, reward_reversed)
            else:
                # Fallback: check referral settings for default reward amount
                try:
                    ref_settings = await pool.fetchrow("SELECT reward_amount FROM referral_settings LIMIT 1")
                    if ref_settings:
                        reward_reversed = float(ref_settings["reward_amount"] or 0)
                        if reward_reversed > 0:
                            await pool.execute("""
                                UPDATE users
                                SET wallet_balance    = GREATEST(0, wallet_balance    - $2),
                                    referral_earnings = GREATEST(0, referral_earnings - $2)
                                WHERE telegram_id = $1
                            """, referrer_id, reward_reversed)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[REFERRAL] Wallet reversal failed (non-critical): {e}")
        reward_reversed = 0.0

    # 3. Delete the referral record (CRITICAL — must always execute)
    await pool.execute(
        "DELETE FROM referrals WHERE referrer_id = $1 AND referred_id = $2",
        referrer_id, referred_id
    )

    # 4. Clear referred_by on the referred user so they can enter a new code
    await pool.execute(
        "UPDATE users SET referred_by = NULL WHERE telegram_id = $1",
        referred_id
    )

    return {"deleted": True, "reversed_amount": reward_reversed}

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
    """Get rewards user can claim based on *remaining* (unconsumed) referrals.

    Remaining = total_refs - SUM(referrals_needed of all past claims).

    This ensures that if admin removes a reward and adds a new one, users
    CANNOT reuse referrals that were already consumed by prior claims.
    Claims survive reward deletion because the FK is ON DELETE SET NULL,
    and referrals_needed is persisted on the claim row itself.
    """
    pool = await get_pool()
    return await pool.fetch(
        """
        SELECT rr.*, c.title, c.stock
        FROM referral_rewards rr
        JOIN coupons c ON rr.coupon_id = c.id
        WHERE rr.is_active = TRUE
          AND c.stock > 0
          AND rr.referrals_needed <= (
            $2::int - COALESCE(
              (SELECT SUM(COALESCE(rc.referrals_needed, 0))
               FROM referral_claims rc WHERE rc.user_id = $1),
              0
            )
          )
          AND rr.id NOT IN (
            SELECT reward_id FROM referral_claims
            WHERE user_id = $1 AND reward_id IS NOT NULL
          )
        ORDER BY rr.referrals_needed ASC
        """,
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
    """Claim a referral reward — assigns a coupon code to the user. Returns the code or None.

    Inside a single atomic transaction:
      1. Verifies reward is active + has stock.
      2. Verifies user hasn't already claimed THIS reward_id.
      3. Computes remaining refs = total_refs - already_consumed_refs and
         ensures the user actually has enough *new* referrals to earn this reward.
         This prevents free re-claims when admin removes and re-adds a reward.
      4. Assigns an unsold code, decrements stock, and records the claim with
         the referrals_needed value so future eligibility checks stay accurate
         even after the reward row itself is deleted.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Get reward details
            reward = await conn.fetchrow(
                "SELECT rr.*, c.stock FROM referral_rewards rr "
                "JOIN coupons c ON rr.coupon_id = c.id WHERE rr.id = $1 AND rr.is_active = TRUE",
                reward_id
            )
            if not reward or reward["stock"] <= 0:
                return None

            # 2. Check this exact reward_id hasn't been claimed already
            existing = await conn.fetchrow(
                "SELECT id FROM referral_claims WHERE user_id = $1 AND reward_id = $2",
                user_id, reward_id
            )
            if existing:
                return None

            # 3. ── CORE FIX: verify remaining (unconsumed) referrals ──────
            # Count total referrals this user has made
            total_refs = await conn.fetchval(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = $1", user_id
            ) or 0
            # Sum of referrals_needed across ALL past claims (survives reward deletion)
            consumed_refs = await conn.fetchval(
                "SELECT COALESCE(SUM(COALESCE(referrals_needed, 0)), 0) "
                "FROM referral_claims WHERE user_id = $1",
                user_id
            ) or 0
            remaining_refs = int(total_refs) - int(consumed_refs)
            if remaining_refs < reward["referrals_needed"]:
                return None  # Not enough new referrals — cannot claim
            # ────────────────────────────────────────────────────────────

            # 4. Get an unsold code
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
            # Record claim — store referrals_needed so consumption is tracked
            # permanently even if the referral_rewards row is later deleted.
            await conn.execute(
                "INSERT INTO referral_claims "
                "(user_id, reward_id, coupon_id, code, referrals_needed) "
                "VALUES ($1, $2, $3, $4, $5)",
                user_id, reward_id, reward["coupon_id"],
                code_row["code"], reward["referrals_needed"]
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
    """Update one or more bot_settings columns.
    
    Raises asyncpg.UndefinedColumnError if a column doesn't exist yet
    (i.e. the relevant migration hasn't been run). Callers that toggle
    reservation_enabled / waitlist_enabled should ensure migration_v3.sql
    has been applied first.
    """
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


async def get_bot_name() -> str:
    """Get the admin-configured bot name. Defaults to 'DreamX Store'."""
    settings = await get_bot_settings()
    return (settings.get("bot_name") or "DreamX Store") if settings else "DreamX Store"


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
        payment_timeout_seconds: int (default 600) — payment session expiry
        reservation_timeout_seconds: int (default 900) — how long stock stays held
        bharatpe_min_recharge: float (default 10)
        payment_poll_interval: int (default 30)
        reservation_enabled: bool (default True) — stock reservation system on/off
        waitlist_enabled: bool (default True) — waitlist on/off
    """
    try:
        settings = await get_bot_settings()
        if settings is None:
            raise ValueError("No bot_settings row")

        # Helper: safely read a column that may not exist yet in the schema
        def _safe_get(key, default):
            try:
                val = settings[key]
                return val if val is not None else default
            except (KeyError, Exception):
                return default

        return {
            "payment_timeout_seconds": int(_safe_get("payment_timeout_seconds", 600)),
            "reservation_timeout_seconds": int(_safe_get("reservation_timeout_seconds", 900)),
            "bharatpe_min_recharge": float(_safe_get("bharatpe_min_recharge", 10)),
            "payment_poll_interval": int(_safe_get("payment_poll_interval", 30)),
            "reservation_enabled": bool(_safe_get("reservation_enabled", True)),
            "waitlist_enabled": bool(_safe_get("waitlist_enabled", True)),
        }
    except Exception:
        # Column(s) missing — return safe defaults
        import logging as _log
        _log.getLogger("dreamx_bot").warning(
            "get_dynamic_config: Could not read all columns. "
            "Run sql/migration_v3.sql + migration_v4.sql. Using safe defaults."
        )
        return {
            "payment_timeout_seconds": 600,
            "reservation_timeout_seconds": 900,
            "bharatpe_min_recharge": 10.0,
            "payment_poll_interval": 30,
            "reservation_enabled": True,
            "waitlist_enabled": True,
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
    # Sync coupons.stock with actual unsold count
    await sync_coupon_stock(coupon_id)
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
