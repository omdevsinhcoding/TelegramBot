"""
DreamX Coupon Bot — Keyboard Layouts (Common)
Reusable button builders.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def back_button(callback_data: str = "main_menu") -> InlineKeyboardButton:
    return InlineKeyboardButton(text="◀️ Back", callback_data=callback_data)


def refresh_button(callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🔄 Refresh", callback_data=callback_data)


def cancel_button(callback_data: str = "main_menu") -> InlineKeyboardButton:
    return InlineKeyboardButton(text="❌ Cancel", callback_data=callback_data)


def admin_cancel_button() -> InlineKeyboardButton:
    """Cancel button for admin FSM flows — clears state and returns to admin panel."""
    return InlineKeyboardButton(text="❌ Cancel", callback_data="admin_fsm_cancel")


def confirm_button(callback_data: str, text: str = "✅ Confirm") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)
