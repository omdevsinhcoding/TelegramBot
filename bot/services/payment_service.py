"""
DreamX Coupon Bot — Payment Polling Service
Background task that polls payment status for pending orders.

Mirrors the user's poll_payment_status() logic:
  - Poll every PAYMENT_CHECK_INTERVAL seconds
  - Timeout after MAX_PENDING_TIME_MIN minutes
  - On TXN_SUCCESS: verify amount + MID + ORDERID, extract UTR/TXNID
  - On TXN_FAILURE: stop polling, mark failed
  - On timeout: mark expired
"""

import json
import asyncio
import traceback

from aiogram import Bot

from bot.config import Config
from bot.database import queries as db
from bot.services.order_service import complete_order, expire_orders
from bot.payments.verifier import check_upi_status, verify_payment, is_payment_failed
from bot.utils.helpers import escape_md
from bot.utils.logger import logger


async def poll_payment_status(bot: Bot):
    """Background coroutine — polls pending transactions every N seconds.
    
    IMPORTANT: This loop must NEVER crash. All errors are caught and logged.
    Individual transaction failures don't affect other transactions.
    """
    logger.info(
        f"Payment polling service started. "
        f"Interval={Config.POLL_INTERVAL}s, Timeout={Config.PAYMENT_TIMEOUT}s"
    )

    while True:
        try:
            # Expire stale orders first
            try:
                await expire_orders()
            except Exception as e:
                logger.error(f"Error expiring orders: {e}")

            # Get all pending transactions
            try:
                pending = await db.get_pending_transactions()
            except Exception as e:
                logger.error(f"Error fetching pending transactions: {e}")
                await asyncio.sleep(Config.POLL_INTERVAL)
                continue

            for txn in pending:
                # Each transaction is processed independently — one failure doesn't affect others
                try:
                    await _process_pending_transaction(bot, txn)
                except Exception as e:
                    logger.error(
                        f"Error processing txn {txn.get('txn_ref', '?')}: {e}\n"
                        f"{traceback.format_exc()}"
                    )

                # Small delay between transaction checks
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Payment polling loop error: {e}\n{traceback.format_exc()}")

        await asyncio.sleep(Config.POLL_INTERVAL)


async def _process_pending_transaction(bot: Bot, txn):
    """Process a single pending transaction. Raises exceptions to caller for logging."""
    txn_ref = txn["txn_ref"]
    order_id = txn["order_id"]
    amount = float(txn["amount"])
    gateway = txn["gateway"]
    user_id = txn["user_id"]

    # Check order still pending
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        if order and order["status"] == "expired":
            await db.update_transaction(txn_ref, "expired")
            try:
                # Delete QR message if stored
                if order.get("qr_message_id"):
                    await bot.delete_message(user_id, order["qr_message_id"])
            except Exception:
                pass
            try:
                oid = escape_md(order_id)
                await bot.send_message(
                    user_id,
                    f"⏰ *Payment Expired*\n\n"
                    f"Order `{oid}` has expired\\.\n"
                    f"Please create a new order\\.",
                    parse_mode="MarkdownV2",
                )
            except Exception:
                pass
        return

    # Skip BharatPe — it uses manual UTR verification, not auto-polling
    if gateway == "bharatpe":
        return

    # Query payment gateway using txn_ref (Paytm ORDERID = txn_ref)
    response = await check_upi_status(txn_ref, gateway)

    # Check for API errors
    if response.get("STATUS") == "API_ERROR" or "error" in response:
        return

    # Check if payment definitively failed (TXN_FAILURE)
    if is_payment_failed(response):
        await db.update_order_status(order_id, "cancelled")
        try:
            await db.update_transaction(txn_ref, "failed", json.dumps(response, default=str))
        except Exception as e:
            logger.error(f"Non-critical: failed to save failure response for {order_id}: {e}")
        try:
            oid = escape_md(order_id)
            await bot.send_message(
                user_id,
                f"❌ *Payment Failed*\n\n"
                f"Order `{oid}` payment was declined\\.\n"
                f"Please try again with a new order\\.",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass
        logger.info(f"Payment FAILED for order {order_id}")
        return

    # Verify payment success (Paytm ORDERID = txn_ref)
    is_paid, details = verify_payment(response, amount, txn_ref, gateway)

    if is_paid:
        success = await complete_order(order_id, txn_ref, user_id)
        if success:
            # Build success message with UTR and TXN ID
            utr = details.get("utr", "N/A") if details else "N/A"
            txn_id = details.get("txn_id", "N/A") if details else "N/A"

            # Get the delivered coupon code for THIS order (already sold by complete_order)
            try:
                pool = await db.get_pool()
                code_row = await pool.fetchrow(
                    "SELECT code FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE",
                    order_id,
                )
            except Exception:
                code_row = None

            code_text = ""
            if code_row:
                code_val = escape_md(code_row["code"])
                code_text = f"\n\n🔑 Your coupon code:\n`{code_val}`"

            try:
                # Delete QR message if stored
                if order.get("qr_message_id"):
                    await bot.delete_message(user_id, order["qr_message_id"])
            except Exception:
                pass

            try:
                oid = escape_md(order_id)
                utr_esc = escape_md(utr)
                txn_esc = escape_md(txn_id)
                amt_esc = escape_md(f"₹{amount:.2f}")
                
                # Fetch coupon title for eye-catchy message
                pool = await db.get_pool()
                coupon_row = await pool.fetchrow("SELECT title FROM coupons WHERE id = $1", order["coupon_id"])
                coupon_title = escape_md(coupon_row["title"]) if coupon_row else "Coupon"
                
                await bot.send_message(
                    user_id,
                    f"🎉 *WOOHOO\\! PAYMENT SUCCESSFUL\\!* 🎉\n\n"
                    f"🛍️ *Item:* {coupon_title}\n"
                    f"💸 *Amount Paid:* {amt_esc}\n"
                    f"📦 *Order ID:* `{oid}`\n"
                    f"🔢 *UTR:* `{utr_esc}`\n"
                    f"🔗 *TXN ID:* `{txn_esc}`\n"
                    f"{code_text}\n\n"
                    f"💾 *Please save your Order ID for future reference:*\n"
                    f"`{oid}`\n\n"
                    f"🎊 *Thank you for your purchase\\! Enjoy\\!* 🎊",
                    parse_mode="MarkdownV2",
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")

            logger.info(
                f"Payment verified: order={order_id}, UTR={utr}, TXNID={txn_id}"
            )
