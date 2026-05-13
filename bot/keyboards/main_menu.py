"""
DreamX Coupon Bot — Main Menu Keyboard
Persistent ReplyKeyboard buttons embedded at the bottom of the chat.
"""

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from bot.config import Config


def main_menu_kb(user_id: int) -> ReplyKeyboardMarkup:
    """Build a persistent Reply keyboard (static buttons at bottom of chat).

    Layout:
      [ 🛍️ Buy Vouchers ] [ 📦 My Orders  ]
      [ 📊 View Stock   ] [ 🎟️ Recover Coupon ]
      [ 🎁 Refer & Earn ] [ ⚠️ Disclaimer   ]
      [       👑 Admin Panel (admin only)  ]
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
            KeyboardButton(text="⚠️ Disclaimer"),
        ],
    ]
    if Config.is_admin(user_id):
        buttons.append([
            KeyboardButton(text="👑 Admin Panel"),
        ])

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder="Choose an option...",
    )


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
