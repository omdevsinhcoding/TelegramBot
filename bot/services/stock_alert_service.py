"""
DreamX Coupon Bot — Stock Alert Service
Automated low-stock detection with spam-safe deduplication.

How it works:
  1. After every sale/delivery, check_stock_alerts() is called
  2. Finds coupons where stock <= threshold AND stock > 0
  3. For each, checks stock_alerts_sent to avoid duplicate alerts
  4. Sends alert to ALL admins (seed + DB)
  5. When admin adds stock above threshold, clear_stock_alerts() resets

Race-condition safe: Uses UNIQUE constraint for dedup.
Non-spammy: Each stock-level only alerts once per coupon.
"""

from aiogram import Bot
from bot.database import queries as db
from bot.utils.logger import logger


async def check_stock_alerts(bot: Bot, coupon_id: int = None):
    """Check stock levels and send alerts to admins if below threshold.
    
    Args:
        bot: aiogram Bot instance
        coupon_id: If provided, only check this specific coupon.
                   If None, check ALL active coupons (used for periodic scans).
    """
    try:
        settings = await db.get_stock_alert_settings()
        if not settings or not settings.get("is_enabled", True):
            return  # Alerts disabled

        threshold = settings.get("global_threshold", 5)
        if threshold <= 0:
            return  # Invalid threshold

        if coupon_id:
            # Check specific coupon
            coupon = await db.get_coupon(coupon_id)
            if not coupon or not coupon.get("is_active", False):
                return
            stock = coupon.get("stock", 0)
            if stock > threshold or stock <= 0:
                return  # Above threshold or out of stock
            
            # Check if already alerted at this level
            already_sent = await db.check_alert_already_sent(coupon_id, stock)
            if already_sent:
                return
            
            # Send alert
            await db.record_stock_alert(coupon_id, stock)
            await _send_alert_to_admins(bot, coupon, threshold)
        else:
            # Full scan of all active coupons
            low_stock = await db.get_low_stock_coupons(threshold)
            for coupon in low_stock:
                stock = coupon["stock"]
                if stock <= 0:
                    continue  # Skip out-of-stock (only alert low, not zero)
                
                already_sent = await db.check_alert_already_sent(coupon["id"], stock)
                if already_sent:
                    continue
                
                await db.record_stock_alert(coupon["id"], stock)
                await _send_alert_to_admins(bot, coupon, threshold)

    except Exception as e:
        logger.error(f"Stock alert check failed: {e}", exc_info=True)


async def _send_alert_to_admins(bot: Bot, coupon, threshold: int):
    """Send a low-stock alert message to all admins."""
    try:
        from bot.utils.helpers import escape_md

        title = coupon.get("title", "Unknown")
        stock = coupon.get("stock", 0)
        category = coupon.get("category", "")
        coupon_id = coupon.get("id", 0)

        # Urgency indicator
        if stock == 0:
            urgency = "🔴 OUT OF STOCK"
        elif stock <= 2:
            urgency = "🔴 CRITICAL"
        elif stock <= threshold // 2:
            urgency = "🟠 WARNING"
        else:
            urgency = "🟡 LOW STOCK"

        cat_text = f"\n📁 Category: {escape_md(category)}" if category else ""

        text = (
            f"🔔 *STOCK ALERT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{urgency}\n\n"
            f"📦 *{escape_md(title)}*{cat_text}\n"
            f"📊 Remaining Stock: *{stock}*\n"
            f"⚠️ Threshold: *{threshold}*\n\n"
            f"_Restock this product to dismiss alert_"
        )

        # Get all admin IDs
        all_admins = await db.get_all_admin_ids()
        
        for admin_id in all_admins:
            try:
                await bot.send_message(
                    admin_id, text, parse_mode="MarkdownV2"
                )
            except Exception as e:
                # Try plain text fallback
                try:
                    import re
                    plain = re.sub(r'\\(.)', r'\1', text)
                    plain = re.sub(r'[*_`~]', '', plain)
                    await bot.send_message(admin_id, plain)
                except Exception:
                    logger.warning(f"Failed to send stock alert to admin {admin_id}: {e}")

        logger.info(
            f"Stock alert sent: coupon={coupon_id} ({title}), stock={stock}, "
            f"threshold={threshold}, admins={len(all_admins)}"
        )

    except Exception as e:
        logger.error(f"Failed to send stock alert: {e}", exc_info=True)


async def on_stock_replenished(coupon_id: int, new_stock: int):
    """Called when stock is added — clears alert history if above threshold.
    
    This allows future alerts to fire again when stock drops below threshold.
    """
    try:
        settings = await db.get_stock_alert_settings()
        threshold = settings.get("global_threshold", 5) if settings else 5
        
        if new_stock > threshold:
            await db.clear_stock_alerts(coupon_id)
            logger.info(f"Stock alerts cleared for coupon {coupon_id} (stock={new_stock} > threshold={threshold})")
    except Exception as e:
        logger.warning(f"Failed to clear stock alerts for coupon {coupon_id}: {e}")
