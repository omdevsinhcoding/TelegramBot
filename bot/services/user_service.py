"""
DreamX Coupon Bot — User Service
Business logic for user operations.
"""

from bot.database import queries as db
from bot.utils.logger import logger


async def register_user(telegram_id: int, username: str | None, full_name: str | None):
    """Register or update a user in the database."""
    await db.upsert_user(telegram_id, username, full_name)
    logger.info(f"User registered/updated: {telegram_id} (@{username})")


async def get_user_profile(telegram_id: int) -> dict | None:
    """Get user profile data."""
    row = await db.get_user(telegram_id)
    if row:
        return dict(row)
    return None


async def is_user_banned(telegram_id: int) -> bool:
    """Check if user is banned."""
    user = await db.get_user(telegram_id)
    return user and user["is_banned"]
