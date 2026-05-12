"""
DreamX Coupon Bot — Decorators
Access control and error handling decorators.
"""

import functools
from aiogram import types
from bot.config import Config
from bot.utils.logger import logger


def admin_only(handler):
    """Decorator to restrict handler to admin users only."""

    @functools.wraps(handler)
    async def wrapper(event, *args, **kwargs):
        user_id = None
        if isinstance(event, types.Message):
            user_id = event.from_user.id
        elif isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id

        if user_id is None or not Config.is_admin(user_id):
            if isinstance(event, types.CallbackQuery):
                await event.answer("⛔ Access denied. Admins only.", show_alert=True)
            elif isinstance(event, types.Message):
                await event.answer("⛔ You don't have permission to use this command.")
            logger.warning(f"Unauthorized admin access attempt by user {user_id}")
            return

        return await handler(event, *args, **kwargs)

    return wrapper


def error_handler(handler):
    """Decorator to catch and log exceptions in handlers."""

    @functools.wraps(handler)
    async def wrapper(event, *args, **kwargs):
        try:
            return await handler(event, *args, **kwargs)
        except Exception as e:
            logger.exception(f"Error in handler {handler.__name__}: {e}")
            try:
                if isinstance(event, types.CallbackQuery):
                    await event.answer(
                        "❌ Something went wrong. Please try again.",
                        show_alert=True,
                    )
                elif isinstance(event, types.Message):
                    await event.answer("❌ An error occurred. Please try again later.")
            except Exception:
                pass

    return wrapper
