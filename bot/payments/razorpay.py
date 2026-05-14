"""
DreamX Coupon Bot — Razorpay Payment Module

Creates Payment Links via Razorpay API and checks their status.
No web server needed — uses Payment Link API + polling.

Razorpay Payment Link API:
  POST https://api.razorpay.com/v1/payment_links
  Auth: Basic Auth (key_id:key_secret)
"""

import aiohttp
import base64

from bot.utils.logger import logger


async def _get_auth_header() -> dict:
    """Get Razorpay Basic Auth header from DB settings."""
    from bot.database import queries as db
    ps = await db.get_payment_settings()
    key_id = ps.get("razorpay_key_id", "")
    key_secret = ps.get("razorpay_key_secret", "")

    if not key_id or not key_secret:
        raise ValueError("Razorpay credentials not configured")

    credentials = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }


async def create_payment_link(
    amount: float,
    order_id: str,
    description: str = "Coupon Purchase",
) -> dict:
    """
    Create a Razorpay Payment Link.

    Args:
        amount: Amount in INR (e.g., 199.0)
        order_id: Our internal order ID
        description: Payment description

    Returns:
        dict with 'link_id', 'short_url', 'status'
    """
    headers = await _get_auth_header()

    # Razorpay expects amount in paise (smallest unit)
    amount_paise = int(round(amount * 100))

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "description": description,
        "reference_id": order_id,
        "expire_by": 0,  # No expiry (we manage expiry ourselves)
        "notify": {"sms": False, "email": False},
        "notes": {
            "order_id": order_id,
            "source": "telegram_bot",
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.razorpay.com/v1/payment_links",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = await resp.json()

                if resp.status == 200:
                    link_id = result.get("id", "")
                    short_url = result.get("short_url", "")
                    logger.info(
                        f"Razorpay link created: {link_id}, URL: {short_url}, "
                        f"amount: ₹{amount:.2f}, order: {order_id}"
                    )
                    return {
                        "link_id": link_id,
                        "short_url": short_url,
                        "status": result.get("status", "created"),
                    }
                else:
                    error = result.get("error", {})
                    error_desc = error.get("description", str(result))
                    logger.error(f"Razorpay link creation failed: {error_desc}")
                    return {"error": error_desc}

    except Exception as e:
        logger.error(f"Razorpay API error: {e}")
        return {"error": str(e)}


async def check_payment_link_status(link_id: str) -> dict:
    """
    Check the status of a Razorpay Payment Link.

    Returns:
        dict with 'status', 'amount_paid', etc.
        status can be: 'created', 'partially_paid', 'paid', 'cancelled', 'expired'
    """
    headers = await _get_auth_header()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.razorpay.com/v1/payment_links/{link_id}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()

                if resp.status == 200:
                    status = result.get("status", "unknown")
                    amount_paid = result.get("amount_paid", 0) / 100  # Convert from paise
                    payments = result.get("payments", [])
                    
                    # Get payment details if paid
                    payment_id = ""
                    if payments:
                        payment_id = payments[0].get("payment_id", "")

                    logger.info(
                        f"Razorpay link {link_id}: status={status}, "
                        f"paid=₹{amount_paid:.2f}"
                    )
                    return {
                        "status": status,
                        "amount_paid": amount_paid,
                        "payment_id": payment_id,
                        "link_id": link_id,
                    }
                else:
                    logger.error(f"Razorpay status check failed: {result}")
                    return {"status": "error", "error": str(result)}

    except Exception as e:
        logger.error(f"Razorpay status check error: {e}")
        return {"status": "error", "error": str(e)}
