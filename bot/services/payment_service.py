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

import asyncio

from aiogram import Bot

from bot.config import Config
from bot.database import queries as db
from bot.services.order_service import complete_order, expire_orders
from bot.payments.verifier import check_upi_status, verify_payment, is_payment_failed
from bot.utils.helpers import escape_md
from bot.utils.logger import logger


async def poll_payment_status(bot: Bot):
    """Background coroutine — polls pending transactions every N seconds."""
    logger.info(
        f"Payment polling service started. "
        f"Interval={Config.POLL_INTERVAL}s, Timeout={Config.PAYMENT_TIMEOUT}s"
    )

    while True:
        try:
            # Expire stale orders first
            await expire_orders()

            # Get all pending transactions
            pending = await db.get_pending_transactions()

            for txn in pending:
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
                    continue

                # Query payment gateway (mirrors check_upi_status from user's script)
                response = await check_upi_status(order_id, gateway)

                # Check for API errors
                if response.get("STATUS") == "API_ERROR" or "error" in response:
                    continue

                # Check if payment definitively failed (TXN_FAILURE)
                if is_payment_failed(response):
                    await db.update_order_status(order_id, "cancelled")
                    await db.update_transaction(txn_ref, "failed", str(response))
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
                    continue

                # Verify payment success (mirrors the full verification from user's script)
                is_paid, details = verify_payment(response, amount, order_id, gateway)

                if is_paid:
                    success = await complete_order(order_id, txn_ref, user_id)
                    if success:
                        # Build success message with UTR and TXN ID
                        utr = details.get("utr", "N/A") if details else "N/A"
                        txn_id = details.get("txn_id", "N/A") if details else "N/A"

                        # Check if there's a delivered coupon code
                        code_row = await db.get_available_code(order["coupon_id"])
                        code_text = ""
                        if code_row:
                            code_val = escape_md(code_row["code"])
                            code_text = f"\n\n🔑 Your coupon code:\n`{code_val}`"

                        try:
                            oid = escape_md(order_id)
                            utr_esc = escape_md(utr)
                            txn_esc = escape_md(txn_id)
                            amt_esc = escape_md(f"₹{amount:.2f}")
                            await bot.send_message(
                                user_id,
                                f"✅ *Payment Successful\\!*\n\n"
                                f"📦 Order: `{oid}`\n"
                                f"💰 Amount: {amt_esc}\n"
                                f"🔢 UTR: `{utr_esc}`\n"
                                f"🔗 TXN ID: `{txn_esc}`"
                                f"{code_text}\n\n"
                                f"Thank you for your purchase\\! 🎉",
                                parse_mode="MarkdownV2",
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify user {user_id}: {e}")

                        logger.info(
                            f"Payment verified: order={order_id}, UTR={utr}, TXNID={txn_id}"
                        )

                # Small delay between transaction checks
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Payment polling error: {e}")

        await asyncio.sleep(Config.POLL_INTERVAL)
