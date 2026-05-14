"""
DreamX Coupon Bot — Payment Service (Lightweight)

NO background polling — saves server resources.
Payment verification happens ONLY when user clicks "Check Payment".

This module only handles:
  - Expiring stale orders periodically (no API calls)
  - Cleaning up expired QR messages
"""

import asyncio
import traceback

from aiogram import Bot

from bot.database import queries as db
from bot.database.connection import wait_for_db
from bot.services.order_service import expire_orders
from bot.utils.helpers import escape_md
from bot.utils.logger import logger


async def expire_orders_loop(bot: Bot):
    """Lightweight background task — only expires stale orders.
    
    NO payment API calls. NO polling. Just:
    1. Mark expired orders (WHERE expires_at < NOW())
    2. Notify users and clean up QR messages
    
    Runs every 30 seconds — very light on server.
    """
    logger.info("Order expiry service started (lightweight, no payment polling).")

    try:
        await wait_for_db(timeout=60)
    except RuntimeError as e:
        logger.error(f"Order expiry service: {e}. Will NOT start.")
        return

    while True:
        try:
            # Get orders that are about to expire (still pending + past deadline)
            try:
                pool = await db.get_pool()
                expiring = await pool.fetch("""
                    SELECT order_id, user_id, qr_message_id
                    FROM orders
                    WHERE status = 'pending' AND expires_at < NOW()
                """)
            except Exception as e:
                logger.error(f"Error fetching expiring orders: {e}")
                try:
                    dyn = await db.get_dynamic_config()
                    poll_sec = dyn["payment_poll_interval"]
                except Exception:
                    poll_sec = 30
                await asyncio.sleep(poll_sec)
                continue

            # Expire them
            if expiring:
                try:
                    await expire_orders()
                except Exception as e:
                    logger.error(f"Error expiring orders: {e}")

                # Notify users and clean up QR messages
                for order in expiring:
                    try:
                        order_id = order["order_id"]
                        user_id = order["user_id"]
                        qr_msg_id = order.get("qr_message_id")

                        # Update related transactions
                        try:
                            await pool.execute(
                                "UPDATE transactions SET status = 'expired', updated_at = NOW() "
                                "WHERE order_id = $1 AND status IN ('initiated', 'pending')",
                                order_id,
                            )
                        except Exception:
                            pass

                        # Delete QR message
                        if qr_msg_id:
                            try:
                                await bot.delete_message(user_id, qr_msg_id)
                            except Exception:
                                pass

                        # Notify user
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

                    except Exception as e:
                        logger.error(f"Error processing expired order: {e}")

        except Exception as e:
            logger.error(f"Expiry loop error: {e}\n{traceback.format_exc()}")

        # Check every 30 seconds — lightweight, no API calls
        try:
            dyn = await db.get_dynamic_config()
            poll_sec = dyn["payment_poll_interval"]
        except Exception:
            poll_sec = 30
        await asyncio.sleep(poll_sec)
