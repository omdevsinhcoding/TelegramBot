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
    
    Stock was already reserved during order creation.
    We just confirm the reservation and deliver codes.
    
    Args:
        bot: aiogram Bot instance for sending referral notifications.
    """
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        logger.warning(f"Cannot complete order {order_id}: invalid status")
        return False

    qty = order.get("quantity", 1) or 1

    # ── Confirm the reservation (clear reserved_qty, stock stays decremented) ──
    await db.confirm_reservation(order["coupon_id"], qty)

    # Mark order paid
    await db.update_order_status(order_id, "paid", txn_ref)
    await db.update_transaction(txn_ref, "success")

    # Try to deliver coupon codes (one per qty)
    delivered = 0
    for _ in range(qty):
        code_row = await db.get_available_code(order["coupon_id"])
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

    logger.info(f"Order completed: {order_id}, delivered {delivered}/{qty} codes")
    return True


async def cancel_order(order_id: str, bot=None) -> bool:
    """Cancel a pending order and RELEASE reserved stock back to pool.
    
    Args:
        bot: aiogram Bot instance for sending waitlist notifications.
    """
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        return False

    qty = order.get("quantity", 1) or 1
    coupon_id = order["coupon_id"]

    # ── Release reserved stock ──
    await db.release_reservation(coupon_id, qty)

    await db.update_order_status(order_id, "cancelled")
    logger.info(f"Order cancelled + stock released: {order_id} (qty={qty})")

    # ── Notify waitlisted users ──
    await _notify_waitlist(coupon_id, bot)
    return True


async def expire_orders(bot=None):
    """Expire stale pending orders (also releases reservations via DB query).
    
    After expiring, notify waitlisted users that coupons are available.
    """
    # Get coupon IDs that are about to expire (before the expire query runs)
    pool = await db.get_pool()
    expiring = await pool.fetch("""
        SELECT DISTINCT coupon_id FROM orders
        WHERE status = 'pending' AND expires_at < NOW()
    """)
    
    result = await db.expire_stale_orders()
    logger.info(f"Expired stale orders: {result}")
    
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
