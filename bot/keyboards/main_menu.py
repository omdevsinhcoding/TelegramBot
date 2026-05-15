"""
DreamX Coupon Bot — Main Menu Keyboard
Persistent ReplyKeyboard buttons embedded at the bottom of the chat.
"""

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from bot.config import Config


def main_menu_kb(user_id: int, disclaimer_mode: str = "button", channels_static: bool = True) -> ReplyKeyboardMarkup:
    """Build a persistent Reply keyboard (static buttons at bottom of chat).

    Args:
        disclaimer_mode: 'button' shows ⚠️ Disclaimer button, others hide it.
        channels_static: if False, hides 📢 Our Channels from keyboard.
    """
    buttons = [
        [
            KeyboardButton(text="🛍️ Buy Vouchers"),
            KeyboardButton(text="📦 My Orders"),
        ],
        [
            KeyboardButton(text="📊 View Stock"),
            KeyboardButton(text="🎟️ Recover Coupon"),
        ],
        [
            KeyboardButton(text="🎁 Refer & Earn"),
            KeyboardButton(text="🆘 Support"),
        ],
    ]

    # Build the conditional row
    row = []
    if disclaimer_mode == "button":
        row.append(KeyboardButton(text="⚠️ Disclaimer"))
    if channels_static:
        row.append(KeyboardButton(text="📢 Our Channels"))
    if row:
        buttons.append(row)

    if Config.is_admin(user_id):
        buttons.append([
            KeyboardButton(text="👑 Admin Panel"),
        ])

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder="Choose an option...",
    )


async def get_fresh_main_menu_kb(user_id: int) -> ReplyKeyboardMarkup:
    """Build main menu keyboard with FRESH settings from DB.

    Always fetches the latest disclaimer_mode and channels_static_enabled
    so the user sees an updated keyboard on every interaction — no /start needed.
    """
    from bot.database import queries as db

    try:
        settings = await db.get_bot_settings()
        disclaimer_mode = settings.get("disclaimer_mode") or "button"
        ch_static = settings.get("channels_static_enabled")
        if ch_static is None:
            ch_static = True
    except Exception:
        disclaimer_mode = "button"
        ch_static = True

    return main_menu_kb(user_id, disclaimer_mode, ch_static)


def main_menu_inline_kb(user_id: int) -> InlineKeyboardMarkup:
    """Inline keyboard fallback used inside callback-based views."""
    buttons = [
        [InlineKeyboardButton(text="🛍️ Buy Vouchers", callback_data="browse_coupons")],
        [InlineKeyboardButton(text="📦 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton(text="ℹ️ Help & Support", callback_data="help_menu")],
    ]
    if Config.is_admin(user_id):
        buttons.append(
            [InlineKeyboardButton(text="👑 Admin Panel", callback_data="admin_panel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)
