"""
DreamX Coupon Bot — Order Service
Business logic for order creation, payment, and delivery.
"""

from datetime import datetime, timezone, timedelta

from bot.config import Config
from bot.database import queries as db
from bot.payments.upi import generate_unique_txn_id
from bot.utils.helpers import generate_order_id
from bot.utils.logger import logger


async def create_purchase_order(user_id: int, coupon_id: int, amount: float,
                                 gateway: str = "paytm") -> dict:
    """Create a new pending order and transaction record.

    The txn_ref uses the user's TXN_{timestamp}_{random} format.
    This same ID is used as 'tr' in UPI URL AND as ORDERID for Paytm status checks.
    """
    order_id = generate_order_id()           # human-readable: DX-xxxxx-XXXXXX
    txn_ref = generate_unique_txn_id()       # Paytm ORDERID: TXN_{timestamp}_{random}
    timeout_sec = Config.PAYMENT_TIMEOUT

    await db.create_order(order_id, user_id, coupon_id, amount, timeout_sec)

    # Use correct merchant ID based on selected gateway
    if gateway == "bharatpe":
        merchant_id = Config.BHARATPE_MERCHANT_ID
    else:
        merchant_id = Config.PAYTM_MID

    await db.create_transaction(
        txn_ref, order_id, user_id, amount,
        merchant_id, gateway
    )

    logger.info(f"Order created: {order_id}, txn={txn_ref}, user={user_id}, amount={amount}, gateway={gateway}")

    return {
        "order_id": order_id,
        "txn_ref": txn_ref,
        "amount": amount,
        "coupon_id": coupon_id,
        "gateway": gateway,
    }


async def complete_order(order_id: str, txn_ref: str, user_id: int) -> bool:
    """Mark order as paid and deliver coupon(s). Returns True on success."""
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        logger.warning(f"Cannot complete order {order_id}: invalid status")
        return False

    qty = order.get("quantity", 1) or 1

    # Reduce stock atomically for each unit
    for _ in range(qty):
        stock_ok = await db.reduce_stock(order["coupon_id"])
        if not stock_ok:
            logger.warning(f"Stock reduction failed for coupon {order['coupon_id']}")
            break

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

    logger.info(f"Order completed: {order_id}, delivered {delivered}/{qty} codes")
    return True


async def cancel_order(order_id: str) -> bool:
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        return False
    await db.update_order_status(order_id, "cancelled")
    logger.info(f"Order cancelled: {order_id}")
    return True


async def expire_orders():
    """Expire stale pending orders."""
    result = await db.expire_stale_orders()
    logger.info(f"Expired stale orders: {result}")


async def get_user_order_history(user_id: int, limit: int = 10) -> list:
    rows = await db.get_user_orders(user_id, limit)
    return [dict(r) for r in rows]


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



