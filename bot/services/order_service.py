"""
DreamX Coupon Bot — Order Service
Business logic for order creation, payment, and delivery.

Uses a RESERVATION system: stock is reserved when order is created,
confirmed on payment success, and released on cancel/expire.
"""

from datetime import datetime, timezone, timedelta

from bot.database import queries as db
from bot.payments.upi import generate_unique_txn_id
from bot.utils.helpers import generate_order_id
from bot.utils.logger import logger


class OutOfStockError(Exception):
    """Raised when coupon stock is insufficient for the requested quantity."""
    pass


async def create_purchase_order(user_id: int, coupon_id: int, amount: float,
                                 gateway: str = "paytm", qty: int = 1) -> dict:
    """Create a new pending order with optional STOCK RESERVATION.

    When reservation_enabled=True (default):
      1. Atomically reserve stock (decrement stock, increment reserved_qty)
      2. If reservation fails → raise OutOfStockError
    
    When reservation_enabled=False (admin disabled):
      1. Simply check stock >= qty without reserving
      2. If insufficient → raise OutOfStockError
      (Stock is reduced on payment success via confirm_reservation which still works)

    The txn_ref uses the user's TXN_{timestamp}_{random} format.
    """
    # Check if reservation is enabled
    dyn = await db.get_dynamic_config()
    use_reservation = dyn.get("reservation_enabled", True)

    if use_reservation:
        # ── Step 1A: Reserve stock atomically ──
        reserved = await db.reserve_stock(coupon_id, qty)
        if not reserved:
            raise OutOfStockError(f"Not enough stock for coupon {coupon_id} (requested {qty})")
        # Use reservation_timeout so stock hold time is independent of payment window
        timeout_sec = dyn.get("reservation_timeout_seconds", 900)
    else:
        # ── Step 1B: Just check stock without reserving ──
        coupon_row = await db.get_coupon(coupon_id)
        if not coupon_row or coupon_row["stock"] < qty:
            raise OutOfStockError(f"Not enough stock for coupon {coupon_id} (requested {qty})")
        timeout_sec = dyn.get("payment_timeout_seconds", 600)

    # ── Step 2: Create order ──
    order_id = generate_order_id()           # human-readable: DX-xxxxx-XXXXXX
    txn_ref  = generate_unique_txn_id()      # Paytm ORDERID: TXN_{timestamp}_{random}

    await db.create_order(order_id, user_id, coupon_id, amount, timeout_sec, qty)

    # Use correct merchant ID based on selected gateway (dynamic from DB)
    ps = await db.get_payment_settings()
    if gateway == "wallet":
        merchant_id = "WALLET"
    elif gateway == "bharatpe":
        merchant_id = ps["bharatpe_merchant_id"]
    else:
        merchant_id = ps["paytm_mid"]

    await db.create_transaction(
        txn_ref, order_id, user_id, amount,
        merchant_id, gateway
    )

    logger.info(f"Order created ({'reserved' if use_reservation else 'no-reserve'}): {order_id}, "
                f"txn={txn_ref}, user={user_id}, amount={amount}, qty={qty}, gateway={gateway}")

    return {
        "order_id": order_id,
        "txn_ref": txn_ref,
        "amount": amount,
        "coupon_id": coupon_id,
        "gateway": gateway,
        "qty": qty,
    }


async def complete_order(order_id: str, txn_ref: str, user_id: int, bot=None) -> bool:
    """Mark order as paid and deliver coupon(s).
    
    Handles both reservation modes:
    - reservation_enabled=True:  stock was pre-decremented → just clear reserved_qty
    - reservation_enabled=False: stock NOT pre-decremented → decrement now via reduce_stock
    
    Args:
        bot: aiogram Bot instance for sending referral notifications.
    """
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        logger.warning(f"Cannot complete order {order_id}: invalid status")
        return False

    qty = order.get("quantity", 1) or 1
    coupon_id = order["coupon_id"]

    # ── Handle stock based on reservation mode ──
    dyn = await db.get_dynamic_config()
    use_reservation = dyn.get("reservation_enabled", True)

    if use_reservation:
        # Stock was already decremented during reservation — just clear reserved_qty
        await db.confirm_reservation(coupon_id, qty)
    else:
        # Stock was NOT decremented — decrement it now
        for _ in range(qty):
            await db.reduce_stock(coupon_id)

    # Mark order paid
    await db.update_order_status(order_id, "paid", txn_ref)
    await db.update_transaction(txn_ref, "success")

    # Try to deliver coupon codes (one per qty)
    delivered = 0
    for _ in range(qty):
        code_row = await db.get_available_code(coupon_id)
        if code_row:
            await db.mark_code_sold(code_row["id"], user_id, order_id)
            delivered += 1

    if delivered > 0:
        await db.update_order_status(order_id, "delivered")

    # Reward referrer if applicable (works for ALL payment methods)
    from bot.handlers.referral import process_referral_on_purchase
    try:
        await process_referral_on_purchase(user_id, order["amount"], bot=bot)
    except Exception as e:
        logger.error(f"Referral process failed for order {order_id}: {e}")

    # ── Check stock alerts after delivery ──
    if bot and coupon_id:
        try:
            from bot.services.stock_alert_service import check_stock_alerts
            await check_stock_alerts(bot, coupon_id=coupon_id)
        except Exception as e:
            logger.warning(f"Stock alert check failed (non-critical): {e}")

    logger.info(f"Order completed: {order_id}, delivered {delivered}/{qty} codes")
    return True



async def cancel_order(order_id: str, bot=None) -> bool:
    """Cancel a pending order and release stock if it was reserved.
    
    Only releases stock back when reservation_enabled=True (stock was pre-decremented).
    When reservation_enabled=False, stock was never taken so nothing to release.
    
    Args:
        bot: aiogram Bot instance for sending waitlist notifications.
    """
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        return False

    qty = order.get("quantity", 1) or 1
    coupon_id = order["coupon_id"]

    # ── Only release stock if reservation system is ON ──
    dyn = await db.get_dynamic_config()
    use_reservation = dyn.get("reservation_enabled", True)

    if use_reservation:
        # Stock was decremented during order creation → release it back
        await db.release_reservation(coupon_id, qty)
        logger.info(f"Order cancelled + stock released: {order_id} (qty={qty})")
    else:
        # Stock was NOT decremented → nothing to release
        logger.info(f"Order cancelled (no-reserve mode): {order_id} (qty={qty})")

    # ── Refund wallet portion for combo payments ──
    payment_method = order.get("payment_method", "")
    if payment_method and payment_method.startswith("combo_"):
        user_id = order["user_id"]
        try:
            # Find the wallet deduction for this specific order
            # Search by order_id first (most reliable), then fallback to coupon_id pattern
            pool = await db.get_pool()
            wt = await pool.fetchrow(
                """SELECT ABS(amount) as amt, balance_after FROM wallet_transactions
                   WHERE user_id = $1 AND txn_type = 'purchase'
                     AND (reference LIKE $2 OR reference LIKE $3)
                   ORDER BY created_at DESC LIMIT 1""",
                user_id, f"%{order_id}%", f"combo_coupon_{coupon_id}%"
            )
            if wt:
                refund_amt = float(wt["amt"])
                # Use atomic credit to prevent race condition
                result = await db.credit_wallet_atomic(user_id, refund_amt)
                await db.add_wallet_transaction(
                    user_id, refund_amt, "refund",
                    bal_before=result["balance_before"], bal_after=result["balance_after"],
                    reference=f"cancel_{order_id}",
                    description=f"Refund for cancelled combo order {order_id}",
                )
                logger.info(f"Combo wallet refund: user={user_id}, refund=₹{refund_amt}, order={order_id}")
        except Exception as e:
            logger.error(f"Failed to refund combo wallet for order {order_id}: {e}")

    await db.update_order_status(order_id, "cancelled")

    # ── Notify waitlisted users ──
    await _notify_waitlist(coupon_id, bot)
    return True


async def expire_orders(bot=None):
    """Expire stale pending orders.
    
    Only releases reserved stock if reservation system is enabled.
    After expiring, notifies waitlisted users that coupons are available.
    """
    # Check if reservation is enabled
    dyn = await db.get_dynamic_config()
    use_reservation = dyn.get("reservation_enabled", True)

    # Get coupon IDs that are about to expire (before the expire query runs)
    pool = await db.get_pool()
    expiring = await pool.fetch("""
        SELECT DISTINCT coupon_id FROM orders
        WHERE status = 'pending' AND expires_at < NOW()
    """)
    # ── Refund wallet for combo orders that are expiring ──
    try:
        combo_orders = await pool.fetch("""
            SELECT order_id, user_id, coupon_id, payment_method FROM orders
            WHERE status = 'pending' AND expires_at < NOW()
              AND payment_method LIKE 'combo_%'
        """)
        for co in combo_orders:
            try:
                wt = await pool.fetchrow(
                    """SELECT ABS(amount) as amt FROM wallet_transactions
                       WHERE user_id = $1 AND txn_type = 'purchase'
                         AND (reference LIKE $2 OR reference LIKE $3)
                       ORDER BY created_at DESC LIMIT 1""",
                    co["user_id"], f"%{co['order_id']}%", f"combo_coupon_{co['coupon_id']}%"
                )
                if wt:
                    refund_amt = float(wt["amt"])
                    # Use atomic credit for race-safe refund
                    result = await db.credit_wallet_atomic(co["user_id"], refund_amt)
                    await db.add_wallet_transaction(
                        co["user_id"], refund_amt, "refund",
                        bal_before=result["balance_before"], bal_after=result["balance_after"],
                        reference=f"expire_{co['order_id']}",
                        description=f"Refund for expired combo order {co['order_id']}",
                    )
                    logger.info(f"Combo expire refund: user={co['user_id']}, ₹{refund_amt}, order={co['order_id']}")
            except Exception as e:
                logger.error(f"Combo expire refund failed for {co['order_id']}: {e}")
    except Exception as e:
        logger.warning(f"Combo expire refund scan failed: {e}")

    if use_reservation:
        # Stock was pre-decremented → release it back + expire orders
        result = await db.expire_stale_orders()
    else:
        # Stock was NOT decremented → just expire orders WITHOUT releasing stock
        result = await db.expire_stale_orders_no_release()
    
    logger.info(f"Expired stale orders ({'with-release' if use_reservation else 'no-release'}): {result}")
    
    # Notify waitlisted users for each affected coupon
    for row in expiring:
        await _notify_waitlist(row["coupon_id"], bot)


async def _notify_waitlist(coupon_id: int, bot=None):
    """Send notification to waitlisted users that a coupon is now available."""
    if not bot:
        return
    
    try:
        from bot.services.coupon_service import get_coupon_detail
        coupon = await get_coupon_detail(coupon_id)
        if not coupon or coupon["stock"] <= 0:
            return  # Still no stock available
        
        waitlist = await db.get_waitlist_users(coupon_id)
        if not waitlist:
            return
        
        from bot.utils.helpers import escape_md
        title = escape_md(coupon["title"])
        stock = coupon["stock"]
        
        text = (
            f"🔔 *Coupon Available\\!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛍️ *{title}* is now available\\!\n"
            f"📦 Stock: *{stock}* left\n\n"
            f"⚡ *Grab it fast before someone else does\\!*"
        )
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Buy Now", callback_data=f"coupon_detail:{coupon_id}")],
        ])
        
        for user_id in waitlist:
            try:
                await bot.send_message(user_id, text, parse_mode="MarkdownV2", reply_markup=kb)
                await db.remove_from_waitlist(user_id, coupon_id)
                logger.info(f"Waitlist notification sent: user={user_id}, coupon={coupon_id}")
            except Exception as e:
                logger.warning(f"Failed to notify waitlist user {user_id}: {e}")
                await db.remove_from_waitlist(user_id, coupon_id)
    except Exception as e:
        logger.error(f"Waitlist notification failed for coupon {coupon_id}: {e}")


async def get_user_order_history(user_id: int, limit: int = 5, offset: int = 0) -> list:
    rows = await db.get_user_orders(user_id, limit, offset, exclude_cancelled=True)
    return [dict(r) for r in rows]

async def get_user_order_history_count(user_id: int) -> int:
    return await db.get_user_orders_count(user_id, exclude_cancelled=True)


async def get_delivered_code(order_id: str, coupon_id: int):
    """Get the coupon code that was delivered for this order (returns first code)."""
    pool = await db.get_pool()
    return await pool.fetchrow(
        "SELECT code FROM coupon_codes WHERE order_id = $1 AND coupon_id = $2 AND is_sold = TRUE LIMIT 1",
        order_id, coupon_id
    )


async def get_all_delivered_codes(order_id: str) -> list:
    """Get ALL coupon codes delivered for this order."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT code FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE",
        order_id
    )
    return [r["code"] for r in rows]
