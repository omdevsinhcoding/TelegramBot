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
    """Create a new pending order with STOCK RESERVATION.

    1. Atomically reserve stock (decrement stock, increment reserved_qty)
    2. If reservation fails → raise OutOfStockError
    3. Create order + transaction records

    The txn_ref uses the user's TXN_{timestamp}_{random} format.
    This same ID is used as 'tr' in UPI URL AND as ORDERID for Paytm status checks.
    """
    # ── Step 1: Reserve stock atomically ──
    reserved = await db.reserve_stock(coupon_id, qty)
    if not reserved:
        raise OutOfStockError(f"Not enough stock for coupon {coupon_id} (requested {qty})")

    # ── Step 2: Create order ──
    order_id = generate_order_id()           # human-readable: DX-xxxxx-XXXXXX
    txn_ref = generate_unique_txn_id()       # Paytm ORDERID: TXN_{timestamp}_{random}
    dyn = await db.get_dynamic_config()
    timeout_sec = dyn["payment_timeout_seconds"]

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

    logger.info(f"Order created (reserved): {order_id}, txn={txn_ref}, user={user_id}, "
                f"amount={amount}, qty={qty}, gateway={gateway}")

    return {
        "order_id": order_id,
        "txn_ref": txn_ref,
        "amount": amount,
        "coupon_id": coupon_id,
        "gateway": gateway,
        "qty": qty,
    }


async def complete_order(order_id: str, txn_ref: str, user_id: int) -> bool:
    """Mark order as paid and deliver coupon(s).
    
    Stock was already reserved during order creation.
    We just confirm the reservation and deliver codes.
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

    # Reward referrer if applicable
    from bot.handlers.referral import process_referral_on_purchase
    try:
        await process_referral_on_purchase(user_id, order["amount"])
    except Exception as e:
        logger.error(f"Referral process failed for order {order_id}: {e}")

    logger.info(f"Order completed: {order_id}, delivered {delivered}/{qty} codes")
    return True


async def cancel_order(order_id: str) -> bool:
    """Cancel a pending order and RELEASE reserved stock back to pool."""
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        return False

    qty = order.get("quantity", 1) or 1

    # ── Release reserved stock ──
    await db.release_reservation(order["coupon_id"], qty)

    await db.update_order_status(order_id, "cancelled")
    logger.info(f"Order cancelled + stock released: {order_id} (qty={qty})")
    return True


async def expire_orders():
    """Expire stale pending orders (also releases reservations via DB query)."""
    result = await db.expire_stale_orders()
    logger.info(f"Expired stale orders: {result}")


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
