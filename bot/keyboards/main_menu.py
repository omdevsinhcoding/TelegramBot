"""
DreamX Coupon Bot — Main Menu Keyboard
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import Config


def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🛒 Buy Coupons", callback_data="browse_coupons")],
        [InlineKeyboardButton(text="💰 Wallet", callback_data="wallet_menu")],
        [InlineKeyboardButton(text="📦 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton(text="ℹ️ Help & Support", callback_data="help_menu")],
    ]
    if Config.is_admin(user_id):
        buttons.append(
            [InlineKeyboardButton(text="👑 Admin Panel", callback_data="admin_panel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)
