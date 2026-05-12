"""
DreamX Coupon Bot — Wallet Keyboards
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.keyboards.common import back_button, refresh_button


def wallet_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Top-Up Wallet", callback_data="wallet_topup")],
        [InlineKeyboardButton(text="📜 Transaction History", callback_data="wallet_history")],
        [refresh_button("wallet_menu"), back_button("main_menu")],
    ])


def topup_amounts_kb() -> InlineKeyboardMarkup:
    amounts = [50, 100, 200, 500, 1000]
    buttons = []
    row = []
    for a in amounts:
        row.append(InlineKeyboardButton(text=f"₹{a}", callback_data=f"topup_amt:{a}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton(text="💬 Custom Amount", callback_data="topup_custom")
    ])
    buttons.append([back_button("wallet_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
