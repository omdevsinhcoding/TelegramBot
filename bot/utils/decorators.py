"""
DreamX Coupon Bot — Decorators
Access control and error handling decorators.
"""

import functools
import traceback
from aiogram import types
from bot.config import Config
from bot.utils.logger import logger


def admin_only(handler):
    """Decorator to restrict handler to admin users only.
    
    Properly passes through *args and **kwargs (including FSMContext 'state',
    'bot', etc.) so that decorated handlers receive all their parameters.
    """

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
    """Decorator to catch and log exceptions in handlers.
    
    IMPORTANT: This decorator ensures that unhandled exceptions in handlers
    do NOT crash the bot. Errors are logged with full tracebacks and
    a user-friendly message is sent back.
    
    Properly passes through *args and **kwargs (including FSMContext 'state',
    'bot', etc.) so that decorated handlers receive all their parameters.
    """

    @functools.wraps(handler)
    async def wrapper(event, *args, **kwargs):
        try:
            return await handler(event, *args, **kwargs)
        except Exception as e:
            # Log full traceback for debugging
            logger.error(
                f"Error in handler {handler.__name__}: {e}\n"
                f"{traceback.format_exc()}"
            )
            # Send user-friendly error message
            try:
                if isinstance(event, types.CallbackQuery):
                    await event.answer(
                        "❌ Something went wrong. Please try again.",
                        show_alert=True,
                    )
                elif isinstance(event, types.Message):
                    await event.answer(
                        "❌ An error occurred. Please try again later.\n"
                        "If you made a payment, contact support with your Order ID."
                    )
            except Exception:
                pass  # Can't even send error message — just log it

    return wrapper
