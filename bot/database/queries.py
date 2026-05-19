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
    """Set wallet balance to exact value. AVOID in concurrent contexts.
    
    For concurrent-safe operations, use credit_wallet_atomic() or debit_wallet_atomic() instead.
    This function is kept for admin overrides and migration compatibility.
    """
    pool = await get_pool()
    await pool.execute(
        "UPDATE users SET wallet_balance = $2, updated_at = NOW() WHERE telegram_id = $1",
        telegram_id, new_balance
    )


async def credit_wallet_atomic(telegram_id: int, amount: float) -> dict:
    """Atomically add amount to wallet balance. Race-condition safe.
    
    Returns dict with 'balance_before' and 'balance_after'.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE users 
           SET wallet_balance = wallet_balance + $2, updated_at = NOW() 
           WHERE telegram_id = $1
           RETURNING wallet_balance - $2 AS balance_before, wallet_balance AS balance_after""",
        telegram_id, amount
    )
    if row:
        return {"balance_before": float(row["balance_before"]), "balance_after": float(row["balance_after"])}
    return {"balance_before": 0.0, "balance_after": 0.0}


async def debit_wallet_atomic(telegram_id: int, amount: float) -> dict | None:
    """Atomically deduct amount from wallet. Race-condition safe.
    
    Returns dict with 'balance_before' and 'balance_after', or None if insufficient funds.
    The WHERE clause ensures balance never goes negative.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE users 
           SET wallet_balance = wallet_balance - $2, updated_at = NOW() 
           WHERE telegram_id = $1 AND wallet_balance >= $2
           RETURNING wallet_balance + $2 AS balance_before, wallet_balance AS balance_after""",
        telegram_id, amount
    )
    if row:
        return {"balance_before": float(row["balance_before"]), "balance_after": float(row["balance_after"])}
    return None  # Insufficient funds


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
                         discounted_price: float, stock: int, created_by: int = None):
    pool = await get_pool()
    row = await pool.fetchrow("""
        INSERT INTO coupons (title, description, original_price, discounted_price, stock, created_by)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
    """, title, description, original_price, discounted_price, stock, created_by)
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


async def expire_stale_orders_no_release():
    """Expire pending orders past their timeout WITHOUT releasing stock.
    
    Used when reservation_enabled=False — stock was never decremented
    during order creation, so there's nothing to release back.
    """
    pool = await get_pool()
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
        """INSERT INTO coupon_codes (coupon_id, code) VALUES ($1, $2)
           ON CONFLICT (coupon_id, code) WHERE is_sold = FALSE DO NOTHING""",
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
    """Aggregate order stats. Revenue includes both 'paid' and 'delivered' orders."""
    pool = await get_pool()
    return await pool.fetchrow("""
        SELECT
            COUNT(*) FILTER (WHERE status IN ('paid', 'delivered')) as total_paid,
            COUNT(*) FILTER (WHERE status = 'pending') as total_pending,
            COUNT(*) FILTER (WHERE status = 'expired') as total_expired,
            COALESCE(SUM(amount) FILTER (WHERE status IN ('paid', 'delivered')), 0) as total_revenue,
            COUNT(*) as total_orders
        FROM orders
    """)


async def get_admin_sales_analytics() -> list:
    """Per-admin sales analytics: how much revenue each admin's products generated.

    Revenue is weighted per admin so 'loss per admin' can be calculated
    proportionally based on each admin's share of total revenue.
    """
    pool = await get_pool()
    return await pool.fetch("""
        SELECT
            c.created_by AS admin_id,
            COUNT(DISTINCT c.id) AS products_added,
            COUNT(o.order_id) FILTER (WHERE o.status IN ('paid', 'delivered')) AS total_sold,
            COALESCE(SUM(o.amount) FILTER (WHERE o.status IN ('paid', 'delivered')), 0) AS total_revenue,
            COUNT(o.order_id) FILTER (WHERE o.status = 'pending') AS pending_orders,
            COALESCE(SUM(o.amount) FILTER (WHERE o.status = 'pending'), 0) AS pending_revenue,
            COUNT(DISTINCT c.id) FILTER (WHERE c.is_active = TRUE) AS active_products
        FROM coupons c
        LEFT JOIN orders o ON o.coupon_id = c.id
        WHERE c.created_by IS NOT NULL
        GROUP BY c.created_by
        ORDER BY total_revenue DESC
    """)


async def get_product_analytics() -> list:
    """Product-level analytics with admin attribution."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT
            c.id AS coupon_id,
            c.title,
            c.discounted_price AS price,
            c.stock,
            c.is_active,
            c.created_by AS admin_id,
            c.created_at,
            COUNT(o.order_id) FILTER (WHERE o.status IN ('paid', 'delivered')) AS sold_count,
            COALESCE(SUM(o.amount) FILTER (WHERE o.status IN ('paid', 'delivered')), 0) AS revenue,
            COUNT(o.order_id) FILTER (WHERE o.status = 'pending') AS pending_count,
            (SELECT COUNT(*) FROM coupon_codes cc WHERE cc.coupon_id = c.id AND cc.is_sold = TRUE) AS codes_sold,
            (SELECT COUNT(*) FROM coupon_codes cc WHERE cc.coupon_id = c.id AND cc.is_sold = FALSE) AS codes_available
        FROM coupons c
        LEFT JOIN orders o ON o.coupon_id = c.id
        GROUP BY c.id, c.title, c.discounted_price, c.stock, c.is_active, c.created_by, c.created_at
        ORDER BY revenue DESC
    """)


async def get_recent_sales(limit: int = 50) -> list:
    """Recent paid/delivered orders with product and admin info."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT
            o.order_id,
            o.user_id,
            o.amount,
            o.quantity,
            o.status,
            o.paid_at,
            o.created_at,
            c.title AS coupon_title,
            c.created_by AS admin_id,
            u.full_name AS buyer_name,
            u.username AS buyer_username
        FROM orders o
        LEFT JOIN coupons c ON o.coupon_id = c.id
        LEFT JOIN users u ON o.user_id = u.telegram_id
        WHERE o.status IN ('paid', 'delivered')
        ORDER BY o.paid_at DESC NULLS LAST
        LIMIT $1
    """, limit)


async def get_daily_revenue(days: int = 30) -> list:
    """Daily revenue for chart data — includes 'delivered' orders."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT
            DATE(COALESCE(paid_at, updated_at)) AS day,
            COUNT(*) AS order_count,
            COALESCE(SUM(amount), 0) AS revenue
        FROM orders
        WHERE status IN ('paid', 'delivered')
          AND COALESCE(paid_at, updated_at) >= NOW() - interval '1 day' * $1
        GROUP BY DATE(COALESCE(paid_at, updated_at))
        ORDER BY day ASC
    """, days)


async def get_wallet_usage_stats() -> dict:
    """Get total wallet/referral reward usage across all purchases."""
    pool = await get_pool()
    row = await pool.fetchrow("""
        SELECT
            COUNT(*) FILTER (WHERE txn_type = 'purchase' AND amount < 0) AS wallet_purchases,
            COALESCE(SUM(ABS(amount)) FILTER (WHERE txn_type = 'purchase' AND amount < 0), 0) AS total_wallet_spent,
            COUNT(*) FILTER (WHERE txn_type IN ('referral_reward', 'referral_commission') AND amount > 0) AS total_rewards_given,
            COALESCE(SUM(amount) FILTER (WHERE txn_type IN ('referral_reward', 'referral_commission') AND amount > 0), 0) AS total_rewards_amount
        FROM wallet_transactions
    """)
    return dict(row) if row else {
        "wallet_purchases": 0, "total_wallet_spent": 0,
        "total_rewards_given": 0, "total_rewards_amount": 0
    }


async def get_payment_method_stats() -> list:
    """Breakdown of orders by payment method."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT
            COALESCE(payment_method, 'gateway') AS method,
            COUNT(*) AS order_count,
            COALESCE(SUM(amount), 0) AS total_amount
        FROM orders
        WHERE status IN ('paid', 'delivered')
        GROUP BY COALESCE(payment_method, 'gateway')
        ORDER BY total_amount DESC
    """)


async def get_total_referral_rewards_given() -> float:
    """Total referral reward money that was given out (this is the 'loss' pool)."""
    pool = await get_pool()
    # Sum all positive wallet transactions that are referral rewards
    val = await pool.fetchval("""
        SELECT COALESCE(SUM(amount), 0)
        FROM wallet_transactions
        WHERE amount > 0
          AND txn_type IN ('referral_reward', 'referral_commission')
    """)
    return float(val or 0)


async def get_total_wallet_used_in_purchases() -> float:
    """Total wallet balance used to pay for orders (the actual loss realized in sales)."""
    pool = await get_pool()
    val = await pool.fetchval("""
        SELECT COALESCE(SUM(ABS(amount)), 0)
        FROM wallet_transactions
        WHERE amount < 0
          AND txn_type = 'purchase'
    """)
    return float(val or 0)


async def get_admin_names_map(admin_ids: set) -> dict:
    """Get admin_id -> display_name mapping in a single bulk query (no N+1)."""
    if not admin_ids:
        return {}
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT telegram_id, full_name, username FROM users WHERE telegram_id = ANY($1::bigint[])",
        list(admin_ids)
    )
    names = {}
    for u in rows:
        names[u["telegram_id"]] = u["full_name"] or u["username"] or str(u["telegram_id"])
    # Fill in any missing IDs (admin not in users table)
    for aid in admin_ids:
        if aid not in names:
            names[aid] = str(aid)
    return names


async def get_recent_sales_detailed(limit: int = 20) -> list:
    """Recent sales with full details including payment method and admin info."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT
            o.order_id,
            o.user_id,
            o.amount,
            o.quantity,
            o.status,
            o.paid_at,
            o.created_at,
            COALESCE(o.payment_method, 'gateway') AS payment_method,
            c.title AS coupon_title,
            c.discounted_price AS unit_price,
            c.created_by AS admin_id,
            u.full_name AS buyer_name,
            u.username AS buyer_username
        FROM orders o
        LEFT JOIN coupons c ON o.coupon_id = c.id
        LEFT JOIN users u ON o.user_id = u.telegram_id
        WHERE o.status IN ('paid', 'delivered')
        ORDER BY o.paid_at DESC NULLS LAST
        LIMIT $1
    """, limit)


# ── FREE COUPON / GIVEAWAY QUERIES (MULTI-CODE) ──────────

async def create_free_coupon(title: str, codes_per_user: int, created_by: int) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO free_coupons (title, code, codes_per_user, created_by) VALUES ($1, $2, $3, $4) RETURNING id",
        title, '', codes_per_user, created_by)
    return row["id"]

async def add_giveaway_codes(fc_id: int, codes: list) -> int:
    """Add codes to a giveaway, skipping duplicates.
    
    Returns the number of NEW codes actually inserted.
    """
    pool = await get_pool()
    # Deduplicate input
    seen = set()
    unique_codes = []
    for code in codes:
        c = code.strip()
        if c and c not in seen:
            seen.add(c)
            unique_codes.append(c)
    
    inserted = 0
    for c in unique_codes:
        result = await pool.execute(
            """INSERT INTO free_coupon_codes (free_coupon_id, code)
               VALUES ($1, $2)
               ON CONFLICT (free_coupon_id, code) WHERE is_claimed = FALSE
               DO NOTHING""",
            fc_id, c
        )
        if result and result.endswith("1"):
            inserted += 1
    
    # Update max_claims based on total unclaimed codes
    fc = await pool.fetchrow("SELECT codes_per_user FROM free_coupons WHERE id = $1", fc_id)
    total = await pool.fetchval("SELECT COUNT(*) FROM free_coupon_codes WHERE free_coupon_id = $1", fc_id)
    cpu = fc["codes_per_user"] if fc else 1
    await pool.execute("UPDATE free_coupons SET max_claims = $2 WHERE id = $1", fc_id, total // max(cpu, 1))
    return inserted


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
    """Get active giveaways with code counts in a single aggregate query."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT fc.*,
               COALESCE(agg.total_codes, 0)    AS total_codes,
               COALESCE(agg.unclaimed_codes, 0) AS unclaimed_codes
        FROM free_coupons fc
        LEFT JOIN (
            SELECT free_coupon_id,
                   COUNT(*) AS total_codes,
                   COUNT(*) FILTER (WHERE is_claimed = FALSE) AS unclaimed_codes
            FROM free_coupon_codes
            GROUP BY free_coupon_id
        ) agg ON agg.free_coupon_id = fc.id
        WHERE fc.is_active = TRUE
        ORDER BY fc.created_at DESC
    """)
    return [dict(r) for r in rows]

async def get_all_free_coupons() -> list:
    """Get all giveaways with code counts in a single aggregate query (no N+1)."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT fc.*,
               COALESCE(agg.total_codes, 0)    AS total_codes,
               COALESCE(agg.unclaimed_codes, 0) AS unclaimed_codes
        FROM free_coupons fc
        LEFT JOIN (
            SELECT free_coupon_id,
                   COUNT(*) AS total_codes,
                   COUNT(*) FILTER (WHERE is_claimed = FALSE) AS unclaimed_codes
            FROM free_coupon_codes
            GROUP BY free_coupon_id
        ) agg ON agg.free_coupon_id = fc.id
        ORDER BY fc.created_at DESC
    """)
    return [dict(r) for r in rows]

async def get_free_coupon(fc_id: int):
    """Get single giveaway with code counts in one query."""
    pool = await get_pool()
    row = await pool.fetchrow("""
        SELECT fc.*,
               COALESCE(agg.total_codes, 0)    AS total_codes,
               COALESCE(agg.unclaimed_codes, 0) AS unclaimed_codes
        FROM free_coupons fc
        LEFT JOIN (
            SELECT free_coupon_id,
                   COUNT(*) AS total_codes,
                   COUNT(*) FILTER (WHERE is_claimed = FALSE) AS unclaimed_codes
            FROM free_coupon_codes
            WHERE free_coupon_id = $1
            GROUP BY free_coupon_id
        ) agg ON agg.free_coupon_id = fc.id
        WHERE fc.id = $1
    """, fc_id)
    return dict(row) if row else None

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


async def check_referral_earning_cap(user_id: int, ref_settings: dict) -> bool:
    """Check if user can still earn referral rewards within the cap.

    Returns True if user is allowed to earn, False if they've hit the cap.
    Uses a rolling time window based on wallet_reward_duration_days and
    checks against wallet_reward_max_amount.

    If no caps are configured (or columns are missing), always returns True.
    """
    max_amount = ref_settings.get("wallet_reward_max_amount")
    duration_days = ref_settings.get("wallet_reward_duration_days")

    # No cap configured — always allow
    if not max_amount or float(max_amount) <= 0:
        return True
    if not duration_days or int(duration_days) <= 0:
        return True

    max_amount = float(max_amount)
    duration_days = int(duration_days)

    pool = await get_pool()
    # Sum all referral-related wallet credits in the rolling window
    # Matches both new (txn_type) and legacy (reference LIKE) patterns
    earned = await pool.fetchval("""
        SELECT COALESCE(SUM(amount), 0)
        FROM wallet_transactions
        WHERE user_id = $1
          AND amount > 0
          AND (
              txn_type IN ('referral_reward', 'referral_commission')
              OR reference LIKE 'referral_from_%'
              OR reference LIKE 'commission_from_%'
          )
          AND created_at >= NOW() - interval '1 day' * $2
    """, user_id, duration_days)

    return float(earned or 0) < max_amount


async def get_user_wallet(user_id: int) -> float:
    """Alias for get_wallet_balance (legacy compat)."""
    return await get_wallet_balance(user_id)

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
    """Get rewards user can claim based on their referral credit balance.

    Credit system (1 referral = 1 credit = 1 claim):
      - Each referral earns 1 credit
      - Each claim costs exactly 1 credit (regardless of referrals_needed)
      - referrals_needed = minimum referral count to UNLOCK the reward
      - pending_credits = total_refs - COUNT(all claims)
      - If pending_credits > 0 AND total_refs >= referrals_needed, user can claim

    Returns active rewards that have coupon stock available AND that the user
    has unlocked (total refs >= referrals_needed).
    """
    pool = await get_pool()

    # Calculate pending credits: 1 claim = 1 credit consumed
    consumed = await pool.fetchval(
        "SELECT COUNT(*) FROM referral_claims WHERE user_id = $1",
        user_id
    ) or 0
    pending_credits = ref_count - int(consumed)

    if pending_credits <= 0:
        return []

    # Return active rewards that have stock AND that the user has unlocked
    return await pool.fetch(
        """
        SELECT rr.*, c.title, c.stock
        FROM referral_rewards rr
        JOIN coupons c ON rr.coupon_id = c.id
        WHERE rr.is_active = TRUE
          AND rr.referrals_needed <= $1
        ORDER BY rr.referrals_needed ASC
        """,
        ref_count,
    )

async def get_user_referral_claims(user_id: int) -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT rc.*, c.title FROM referral_claims rc "
        "JOIN coupons c ON rc.coupon_id = c.id "
        "WHERE rc.user_id = $1 ORDER BY rc.claimed_at DESC",
        user_id
    )

async def get_referral_pending_credits(user_id: int) -> int:
    """Get user's pending referral claim credits.
    
    Each referral = 1 credit earned.
    Each claim = 1 credit consumed (regardless of referrals_needed).
    pending = total_referrals - COUNT(claims)
    """
    pool = await get_pool()
    total_refs = await pool.fetchval(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id = $1", user_id
    ) or 0
    consumed = await pool.fetchval(
        "SELECT COUNT(*) FROM referral_claims WHERE user_id = $1",
        user_id
    ) or 0
    return max(0, int(total_refs) - int(consumed))


async def claim_referral_reward(user_id: int, reward_id: int) -> str | None:
    """Claim a referral reward — credit-based system.

    1 referral = 1 credit. Each claim costs exactly 1 credit.
    referrals_needed = minimum referral count to UNLOCK the reward (threshold).
    Users can claim the same reward multiple times as long as they have credits
    AND their total refs >= referrals_needed.
    Returns the coupon code string, or None if claim failed.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Get reward details + stock
            reward = await conn.fetchrow(
                "SELECT rr.*, c.stock FROM referral_rewards rr "
                "JOIN coupons c ON rr.coupon_id = c.id WHERE rr.id = $1 AND rr.is_active = TRUE",
                reward_id
            )
            if not reward:
                return None

            # 2. Check coupon stock
            if reward["stock"] <= 0:
                return None  # Out of stock — caller should show appropriate message

            # 3. Verify user has unlocked this reward AND has pending credits
            total_refs = await conn.fetchval(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = $1", user_id
            ) or 0
            # Check unlock threshold: user must have at least referrals_needed total refs
            if int(total_refs) < reward["referrals_needed"]:
                return None  # Reward not unlocked yet

            # Check pending credits: 1 claim = 1 credit consumed
            consumed = await conn.fetchval(
                "SELECT COUNT(*) FROM referral_claims WHERE user_id = $1",
                user_id
            ) or 0
            pending = int(total_refs) - int(consumed)
            if pending < 1:
                return None  # No credits left

            # 4. Get an unsold code
            code_row = await conn.fetchrow(
                "SELECT id, code FROM coupon_codes WHERE coupon_id = $1 AND is_sold = FALSE LIMIT 1",
                reward["coupon_id"]
            )
            if not code_row:
                return None  # No codes left

            # 5. Mark code as sold
            await conn.execute(
                "UPDATE coupon_codes SET is_sold = TRUE, sold_to = $2, sold_at = NOW() WHERE id = $1",
                code_row["id"], user_id
            )
            # Decrease stock
            await conn.execute(
                "UPDATE coupons SET stock = stock - 1 WHERE id = $1 AND stock > 0",
                reward["coupon_id"]
            )
            # 6. Record claim — each claim costs 1 credit
            #    Store referrals_needed for historical reference only
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
    (i.e. the schema hasn't been fully applied). Run 'python run_migration.py'
    to ensure all columns exist.
    """
    pool = await get_pool()
    sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs.keys()))
    await pool.execute(f"UPDATE bot_settings SET {sets}, updated_at = NOW()", *list(kwargs.values()))


async def get_payment_settings():
    """Get payment settings from DB (admin-managed)."""
    settings = await get_bot_settings()

    # Helper: safely read a column that may not exist yet in the schema.
    # Uses this for ALL fields so a missing column never raises KeyError.
    def _safe_get(key, default):
        try:
            val = settings[key]
            return val if val is not None else default
        except (KeyError, Exception):
            return default

    return {
        "paytm_mid":              _safe_get("paytm_mid", ""),
        "paytm_upi_id":           _safe_get("paytm_upi_id", ""),
        "paytm_qr_code":          _safe_get("paytm_qr_code", ""),
        "bharatpe_merchant_id":   _safe_get("bharatpe_merchant_id", ""),
        "bharatpe_token":         _safe_get("bharatpe_token", ""),
        "bharatpe_upi_id":        _safe_get("bharatpe_upi_id", ""),
        "bharatpe_qr_path":       _safe_get("bharatpe_qr_path", ""),
        "upi_payee_name":         _safe_get("upi_payee_name", ""),
        # Gateway visibility toggles
        "gateway_paytm_enabled":    _safe_get("gateway_paytm_enabled", True),
        "gateway_bharatpe_enabled": _safe_get("gateway_bharatpe_enabled", True),
        "gateway_razorpay_enabled": _safe_get("gateway_razorpay_enabled", False),
        # Razorpay credentials
        "razorpay_key_id":     _safe_get("razorpay_key_id", ""),
        "razorpay_key_secret": _safe_get("razorpay_key_secret", ""),
        # Custom gateway display names — added in migration v6
        "gateway_paytm_name":    _safe_get("gateway_paytm_name", "Paytm"),
        "gateway_bharatpe_name": _safe_get("gateway_bharatpe_name", "BharatPe"),
        "gateway_razorpay_name": _safe_get("gateway_razorpay_name", "Razorpay"),
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
            "Run 'python run_migration.py' to update the database schema. Using safe defaults."
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

async def add_coupon_codes_bulk(coupon_id: int, codes: list[str]) -> int:
    """Insert multiple coupon codes in a single transaction.
    
    Much faster than inserting one-by-one. Prevents timeout errors
    when admin pastes hundreds of codes.
    
    Deduplicates codes:
      - Removes duplicates within the input list itself
      - Skips codes that already exist as unsold for this coupon (ON CONFLICT)
    
    Returns the number of NEW codes actually inserted.
    """
    if not codes:
        return 0

    # ── Deduplicate input list (preserve order, keep first occurrence) ──
    seen = set()
    unique_codes = []
    for c in codes:
        c_stripped = c.strip()
        if c_stripped and c_stripped not in seen:
            seen.add(c_stripped)
            unique_codes.append(c_stripped)

    if not unique_codes:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Use INSERT ... ON CONFLICT to skip duplicates at DB level
            # The unique partial index idx_coupon_codes_unique_unsold
            # covers (coupon_id, code) WHERE is_sold = FALSE
            inserted = 0
            for code in unique_codes:
                result = await conn.execute(
                    """INSERT INTO coupon_codes (coupon_id, code)
                       VALUES ($1, $2)
                       ON CONFLICT (coupon_id, code) WHERE is_sold = FALSE
                       DO NOTHING""",
                    coupon_id, code
                )
                # asyncpg returns "INSERT 0 1" on success, "INSERT 0 0" on conflict
                if result and result.endswith("1"):
                    inserted += 1

    # Sync coupons.stock with actual unsold count
    await sync_coupon_stock(coupon_id)
    return inserted


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


# ── COUPON CATEGORY QUERIES ──────────────────────────────

async def get_all_categories() -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM coupon_categories ORDER BY sort_order, name"
    )


async def get_visible_categories() -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM coupon_categories WHERE is_visible = TRUE ORDER BY sort_order, name"
    )


async def get_category(cat_id: int):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM coupon_categories WHERE id = $1", cat_id)


async def get_category_by_name(name: str):
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT * FROM coupon_categories WHERE LOWER(name) = LOWER($1)", name
    )


async def create_category(name: str) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO coupon_categories (name) VALUES ($1) RETURNING id", name
    )
    return row["id"]


async def update_category_name(cat_id: int, new_name: str):
    pool = await get_pool()
    await pool.execute(
        "UPDATE coupon_categories SET name = $2 WHERE id = $1", cat_id, new_name
    )


async def toggle_category_visibility(cat_id: int) -> bool:
    pool = await get_pool()
    row = await pool.fetchrow(
        "UPDATE coupon_categories SET is_visible = NOT is_visible WHERE id = $1 RETURNING is_visible",
        cat_id
    )
    return row["is_visible"] if row else False


async def delete_category(cat_id: int):
    """Delete category and unset category on all coupons that used it."""
    pool = await get_pool()
    cat = await pool.fetchrow("SELECT name FROM coupon_categories WHERE id = $1", cat_id)
    if cat:
        await pool.execute(
            "UPDATE coupons SET category = NULL, updated_at = NOW() WHERE category = $1",
            cat["name"]
        )
    await pool.execute("DELETE FROM coupon_categories WHERE id = $1", cat_id)


async def get_coupons_by_category(category_name: str) -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM coupons WHERE category = $1 ORDER BY id DESC",
        category_name
    )


async def get_uncategorized_coupons() -> list:
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM coupons WHERE category IS NULL OR category = '' ORDER BY id DESC"
    )


async def move_coupon_to_category(coupon_id: int, category_name: str | None):
    pool = await get_pool()
    await pool.execute(
        "UPDATE coupons SET category = $2, updated_at = NOW() WHERE id = $1",
        coupon_id, category_name
    )


async def get_category_stock_summary() -> list:
    """Get stock count per category for admin overview."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT
            COALESCE(c.category, '(Uncategorized)') AS category,
            COUNT(*) AS coupon_count,
            COALESCE(SUM(c.stock), 0) AS total_stock,
            COUNT(*) FILTER (WHERE c.is_active) AS active_count
        FROM coupons c
        GROUP BY COALESCE(c.category, '(Uncategorized)')
        ORDER BY category
    """)


# ── MANUAL EXTRACTION QUERIES ────────────────────────────

async def extract_coupon_codes(coupon_id: int, quantity: int, admin_id: int) -> list[str]:
    """Atomically extract N unsold codes from a coupon for manual distribution.

    1. Fetches N unsold codes
    2. Marks them as sold (sold_to=admin, order_id='EXTRACT-...')
    3. Syncs stock
    4. Logs extraction

    Returns list of extracted code strings (may be < quantity if not enough stock).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Fetch unsold codes
            rows = await conn.fetch(
                "SELECT id, code FROM coupon_codes "
                "WHERE coupon_id = $1 AND is_sold = FALSE "
                "ORDER BY id LIMIT $2",
                coupon_id, quantity
            )
            if not rows:
                return []

            codes = [r["code"] for r in rows]
            code_ids = [r["id"] for r in rows]

            # Generate extraction order ID
            import time
            extract_ref = f"EXTRACT-{int(time.time())}-{admin_id}"

            # Mark codes as sold
            await conn.execute(
                "UPDATE coupon_codes SET is_sold = TRUE, sold_to = $1, "
                "order_id = $2, sold_at = NOW() WHERE id = ANY($3::int[])",
                admin_id, extract_ref, code_ids
            )

            # Sync stock
            await conn.execute("""
                UPDATE coupons SET stock = (
                    SELECT COUNT(*) FROM coupon_codes
                    WHERE coupon_id = $1 AND is_sold = FALSE
                ), updated_at = NOW() WHERE id = $1
            """, coupon_id)

            # Log extraction
            codes_text = "\n".join(codes)
            await conn.execute(
                "INSERT INTO admin_extractions (admin_id, coupon_id, quantity, codes) "
                "VALUES ($1, $2, $3, $4)",
                admin_id, coupon_id, len(codes), codes_text
            )

    return codes


async def get_extraction_history(coupon_id: int = None, limit: int = 20) -> list:
    pool = await get_pool()
    if coupon_id:
        return await pool.fetch(
            "SELECT ae.*, c.title AS coupon_title FROM admin_extractions ae "
            "JOIN coupons c ON c.id = ae.coupon_id "
            "WHERE ae.coupon_id = $1 ORDER BY ae.created_at DESC LIMIT $2",
            coupon_id, limit
        )
    return await pool.fetch(
        "SELECT ae.*, c.title AS coupon_title FROM admin_extractions ae "
        "JOIN coupons c ON c.id = ae.coupon_id "
        "ORDER BY ae.created_at DESC LIMIT $1",
        limit
    )


async def clear_coupon_stock(coupon_id: int, admin_id: int) -> int:
    """Delete all unsold codes for a coupon and sync stock. Returns count deleted."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await conn.fetchval(
                "WITH deleted AS ("
                "  DELETE FROM coupon_codes WHERE coupon_id = $1 AND is_sold = FALSE RETURNING id"
                ") SELECT COUNT(*) FROM deleted",
                coupon_id
            )
            await conn.execute(
                "UPDATE coupons SET stock = 0, updated_at = NOW() WHERE id = $1",
                coupon_id
            )
            # Log action
            await add_admin_log(
                admin_id, "clear_stock", "coupon", str(coupon_id),
                f"Cleared {result} unsold codes"
            )
    return result or 0


async def delete_specific_codes(coupon_id: int, code_ids: list[int]) -> int:
    """Delete specific unsold coupon codes by their IDs. Returns count deleted."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await conn.fetchval(
                "WITH deleted AS ("
                "  DELETE FROM coupon_codes WHERE id = ANY($1::int[]) "
                "  AND coupon_id = $2 AND is_sold = FALSE RETURNING id"
                ") SELECT COUNT(*) FROM deleted",
                code_ids, coupon_id
            )
            await conn.execute("""
                UPDATE coupons SET stock = (
                    SELECT COUNT(*) FROM coupon_codes
                    WHERE coupon_id = $1 AND is_sold = FALSE
                ), updated_at = NOW() WHERE id = $1
            """, coupon_id)
    return result or 0


# ── PROMOTIONAL LOSS TRACKING ────────────────────────────

async def record_promotional_loss(
    loss_type: str, amount: float,
    admin_id: int = None, coupon_owner_admin_id: int = None,
    user_id: int = None, coupon_id: int = None,
    order_id: str = None, reference: str = None,
    details: dict = None
):
    """Record a promotional/platform loss event.
    
    loss_type values:
        referral_reward, wallet_reward, coupon_reward,
        giveaway, manual_distribution, promotional_discount,
        free_coupon, extraction
    """
    import json
    pool = await get_pool()
    details_json = json.dumps(details) if details else None
    await pool.execute("""
        INSERT INTO promotional_losses 
        (loss_type, amount, admin_id, coupon_owner_admin_id, user_id,
         coupon_id, order_id, reference, details)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
    """, loss_type, amount, admin_id, coupon_owner_admin_id,
        user_id, coupon_id, order_id, reference, details_json)


async def get_total_promotional_losses() -> dict:
    """Get aggregate promotional losses by type."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT loss_type,
               COUNT(*) as event_count,
               COALESCE(SUM(amount), 0) as total_amount
        FROM promotional_losses
        GROUP BY loss_type
        ORDER BY total_amount DESC
    """)
    result = {}
    grand_total = 0
    for r in rows:
        result[r["loss_type"]] = {
            "count": r["event_count"],
            "amount": float(r["total_amount"])
        }
        grand_total += float(r["total_amount"])
    result["_grand_total"] = grand_total
    return result


async def get_admin_promotional_losses() -> list:
    """Get promotional losses grouped by admin."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT 
            admin_id,
            COUNT(*) as event_count,
            COALESCE(SUM(amount), 0) as total_loss,
            COUNT(*) FILTER (WHERE loss_type = 'giveaway') as giveaway_count,
            COALESCE(SUM(amount) FILTER (WHERE loss_type = 'giveaway'), 0) as giveaway_loss,
            COUNT(*) FILTER (WHERE loss_type = 'extraction') as extraction_count,
            COALESCE(SUM(amount) FILTER (WHERE loss_type = 'extraction'), 0) as extraction_loss,
            COUNT(*) FILTER (WHERE loss_type IN ('referral_reward', 'wallet_reward')) as reward_count,
            COALESCE(SUM(amount) FILTER (WHERE loss_type IN ('referral_reward', 'wallet_reward')), 0) as reward_loss
        FROM promotional_losses
        WHERE admin_id IS NOT NULL
        GROUP BY admin_id
        ORDER BY total_loss DESC
    """)


async def get_promotional_loss_history(limit: int = 50) -> list:
    """Get recent promotional loss events."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT pl.*, c.title as coupon_title
        FROM promotional_losses pl
        LEFT JOIN coupons c ON pl.coupon_id = c.id
        ORDER BY pl.created_at DESC
        LIMIT $1
    """, limit)


async def get_admin_loss_share() -> list:
    """Calculate each admin's share of total promotional losses.
    
    Uses the unified admin set (seed + DB, deduplicated).
    For losses not attributed to a specific admin, they are
    distributed equally among all admins.
    """
    pool = await get_pool()
    
    # Get ALL admins (seed + DB, deduplicated)
    all_admin_ids = await get_all_admin_ids()
    admin_count = len(all_admin_ids)
    if admin_count == 0:
        return []
    
    # Get attributed losses (where admin_id IS NOT NULL)
    attributed = await pool.fetch("""
        SELECT admin_id,
               COALESCE(SUM(amount), 0) as attributed_loss
        FROM promotional_losses
        WHERE admin_id IS NOT NULL
        GROUP BY admin_id
    """)
    
    # Get unattributed losses (where admin_id IS NULL)
    unattributed = await pool.fetchval("""
        SELECT COALESCE(SUM(amount), 0)
        FROM promotional_losses
        WHERE admin_id IS NULL
    """) or 0
    
    # Build result
    attr_map = {r["admin_id"]: float(r["attributed_loss"]) for r in attributed}
    shared_per_admin = float(unattributed) / admin_count if admin_count > 0 else 0
    
    result = []
    for aid in all_admin_ids:
        direct = attr_map.get(aid, 0)
        result.append({
            "admin_id": aid,
            "direct_loss": direct,
            "shared_loss": shared_per_admin,
            "total_loss": direct + shared_per_admin
        })
    
    return sorted(result, key=lambda x: x["total_loss"], reverse=True)


# ── GIVEAWAY OWNERSHIP LOGGING ───────────────────────────

async def log_giveaway_distribution(
    giveaway_id: int = None,
    executor_admin_id: int = 0,
    coupon_owner_admin_id: int = None,
    source_coupon_id: int = None,
    coupon_category: str = None,
    codes_distributed: list = None,
    quantity: int = 0,
    total_value: float = 0.0,
    is_self_stock: bool = False,
    loss_absorbed_by: int = None
) -> int:
    """Log a giveaway distribution event with ownership tracking."""
    pool = await get_pool()
    codes_text = "\n".join(codes_distributed) if codes_distributed else ""
    row = await pool.fetchrow("""
        INSERT INTO giveaway_logs 
        (giveaway_id, executor_admin_id, coupon_owner_admin_id,
         source_coupon_id, coupon_category, codes_distributed,
         quantity, total_value, is_self_stock, loss_absorbed_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
    """, giveaway_id, executor_admin_id, coupon_owner_admin_id,
        source_coupon_id, coupon_category, codes_text,
        quantity, total_value, is_self_stock, loss_absorbed_by)
    return row["id"]


async def get_giveaway_log_history(limit: int = 50) -> list:
    """Get recent giveaway distribution logs."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT gl.*,
               fc.title as giveaway_title,
               c.title as source_coupon_title
        FROM giveaway_logs gl
        LEFT JOIN free_coupons fc ON gl.giveaway_id = fc.id
        LEFT JOIN coupons c ON gl.source_coupon_id = c.id
        ORDER BY gl.created_at DESC
        LIMIT $1
    """, limit)


async def get_admin_giveaway_stats() -> list:
    """Get giveaway stats per admin (executor)."""
    pool = await get_pool()
    return await pool.fetch("""
        SELECT 
            executor_admin_id as admin_id,
            COUNT(*) as total_distributions,
            COALESCE(SUM(quantity), 0) as total_codes_given,
            COALESCE(SUM(total_value), 0) as total_value_given,
            COUNT(*) FILTER (WHERE is_self_stock = TRUE) as self_stock_count,
            COALESCE(SUM(total_value) FILTER (WHERE is_self_stock = TRUE), 0) as self_stock_value,
            COUNT(*) FILTER (WHERE is_self_stock = FALSE) as other_stock_count,
            COALESCE(SUM(total_value) FILTER (WHERE is_self_stock = FALSE), 0) as other_stock_value
        FROM giveaway_logs
        GROUP BY executor_admin_id
        ORDER BY total_value_given DESC
    """)


# ── COMPREHENSIVE ADMIN ANALYTICS ────────────────────────

async def get_full_analytics() -> dict:
    """Get comprehensive analytics for the admin dashboard."""
    pool = await get_pool()
    
    # Sales stats
    sales = await get_sales_stats()
    
    # Wallet/referral stats
    wallet_stats = await get_wallet_usage_stats()
    
    # Promotional losses
    promo_losses = await get_total_promotional_losses()
    
    # Admin-wise losses
    admin_losses = await get_admin_loss_share()
    
    # Total referral rewards given
    referral_total = await get_total_referral_rewards_given()
    
    # Total wallet used in purchases
    wallet_used = await get_total_wallet_used_in_purchases()
    
    # Giveaway stats
    giveaway_stats = await get_admin_giveaway_stats()
    
    # Category stock
    cat_stock = await get_category_stock_summary()
    
    # Recent extractions
    extractions = await get_extraction_history(limit=10)
    
    return {
        "sales": dict(sales) if sales else {},
        "wallet_stats": wallet_stats,
        "promotional_losses": promo_losses,
        "admin_losses": admin_losses,
        "referral_total_given": referral_total,
        "wallet_used_in_purchases": wallet_used,
        "giveaway_stats": [dict(g) for g in giveaway_stats],
        "category_stock": [dict(c) for c in cat_stock],
        "recent_extractions": [dict(e) for e in extractions],
    }


# ── REFERRAL LEADERBOARD ANALYTICS ───────────────────────

async def get_referral_leaderboard(limit: int = 50, offset: int = 0) -> list:
    """Get top referrers sorted by referral count.
    
    Returns per-user:
    - referral count, total commission earned, total wallet rewards,
    - user info (name, username, join date)
    """
    pool = await get_pool()
    return await pool.fetch("""
        SELECT 
            u.telegram_id,
            COALESCE(u.full_name, '') as full_name,
            COALESCE(u.username, '') as username,
            u.joined_at as join_date,
            COUNT(r.id) as referral_count,
            COALESCE(SUM(r.commission), 0) as total_commission,
            COALESCE(
                (SELECT SUM(wt.amount) 
                 FROM wallet_transactions wt 
                 WHERE wt.user_id = u.telegram_id 
                   AND wt.txn_type = 'referral_reward' 
                   AND wt.amount > 0), 0
            ) as wallet_rewards_earned,
            COALESCE(
                (SELECT SUM(wt.amount) 
                 FROM wallet_transactions wt 
                 WHERE wt.user_id = u.telegram_id 
                   AND wt.txn_type = 'referral_commission' 
                   AND wt.amount > 0), 0
            ) as commission_rewards_earned,
            u.referral_earnings
        FROM users u
        INNER JOIN referrals r ON r.referrer_id = u.telegram_id
        GROUP BY u.telegram_id, u.full_name, u.username, 
                 u.joined_at, u.referral_earnings
        HAVING COUNT(r.id) > 0
        ORDER BY referral_count DESC, total_commission DESC
        LIMIT $1 OFFSET $2
    """, limit, offset)


async def get_referral_leaderboard_count() -> int:
    """Get total number of users who have at least 1 referral."""
    pool = await get_pool()
    return await pool.fetchval("""
        SELECT COUNT(DISTINCT referrer_id) FROM referrals
    """) or 0


async def get_referral_summary_stats() -> dict:
    """Get platform-wide referral summary stats."""
    pool = await get_pool()
    row = await pool.fetchrow("""
        SELECT 
            COUNT(*) as total_referrals,
            COUNT(DISTINCT referrer_id) as total_referrers,
            COUNT(DISTINCT referred_id) as total_referred,
            COALESCE(SUM(commission), 0) as total_commission_paid
        FROM referrals
    """)
    
    total_rewards = await pool.fetchval("""
        SELECT COALESCE(SUM(amount), 0) 
        FROM wallet_transactions 
        WHERE txn_type IN ('referral_reward', 'referral_commission') 
          AND amount > 0
    """) or 0
    
    return {
        "total_referrals": row["total_referrals"] if row else 0,
        "total_referrers": row["total_referrers"] if row else 0,
        "total_referred": row["total_referred"] if row else 0,
        "total_commission_paid": float(row["total_commission_paid"]) if row else 0,
        "total_rewards_distributed": float(total_rewards),
    }


# ── CATEGORY-AWARE COUPON BROWSING ───────────────────────

async def get_active_coupons_categorized() -> dict:
    """Get all visible categories for the shop folder view.
    
    Categories are pure folders — always shown if visible, regardless
    of whether they have products or stock. Individual product stock
    is only relevant when browsing inside a category.
    
    Returns dict:
        {
            "categories": [{"id", "name", "coupon_count", "total_stock"}],
        }
    """
    pool = await get_pool()
    
    # Get ALL visible categories with their product counts
    # LEFT JOIN ensures empty categories still appear
    categories = await pool.fetch("""
        SELECT cc.id, cc.name, cc.sort_order,
               COUNT(c.id) FILTER (WHERE c.is_active = TRUE) as coupon_count,
               COALESCE(SUM(c.stock) FILTER (WHERE c.is_active = TRUE), 0) as total_stock
        FROM coupon_categories cc
        LEFT JOIN coupons c ON c.category = cc.name
        WHERE cc.is_visible = TRUE
        GROUP BY cc.id, cc.name, cc.sort_order
        ORDER BY cc.sort_order, cc.name
    """)
    
    return {
        "categories": [dict(c) for c in categories],
    }


async def get_active_coupons_in_category(category_name: str) -> list:
    """Get active coupons in a specific category for user browsing."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT * FROM coupons 
        WHERE is_active = TRUE AND category = $1
        ORDER BY id DESC
    """, category_name)
    return [dict(r) for r in rows]


async def get_coupon_owner_admin(coupon_id: int) -> int | None:
    """Get the admin who created/owns a coupon."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT created_by FROM coupons WHERE id = $1", coupon_id
    )
    return row["created_by"] if row and row["created_by"] else None


async def get_all_admin_ids() -> set[int]:
    """Get the deduplicated set of ALL admin Telegram IDs (seed + DB).
    
    This is the single source of truth for admin counting across the system.
    Merges .env seed admins with dynamically added DB admins.
    """
    pool = await get_pool()
    rows = await pool.fetch("SELECT telegram_id FROM admins")
    db_ids = {row["telegram_id"] for row in rows}
    from bot.config import Config
    return db_ids | set(Config.ADMIN_IDS)


async def get_admin_count() -> int:
    """Get total number of unique active admins (seed + DB, deduplicated)."""
    all_ids = await get_all_admin_ids()
    return len(all_ids)

