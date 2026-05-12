"""
DreamX Coupon Bot — Coupon Keyboards
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.keyboards.common import back_button, refresh_button


def coupons_list_kb(coupons: list) -> InlineKeyboardMarkup:
    buttons = []
    for c in coupons:
        stock_label = f"({c['stock']} left)" if c["stock"] > 0 else "(Out of Stock)"
        emoji = "🟢" if c["stock"] > 0 else "🔴"
        buttons.append([
            InlineKeyboardButton(
                text=f"{emoji} {c['title']} — ₹{c['discounted_price']} {stock_label}",
                callback_data=f"coupon_detail:{c['id']}"
            )
        ])
    buttons.append([refresh_button("browse_coupons"), back_button("main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def coupon_detail_kb(coupon_id: int, in_stock: bool) -> InlineKeyboardMarkup:
    buttons = []
    if in_stock:
        buttons.append([
            InlineKeyboardButton(text="🛒 Buy Now", callback_data=f"buy_coupon:{coupon_id}")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="🔴 Out of Stock", callback_data="noop")
        ])
    buttons.append([back_button("browse_coupons")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_pending_kb(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Check Payment", callback_data=f"check_pay:{order_id}")],
        [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancel_order:{order_id}")],
    ])
