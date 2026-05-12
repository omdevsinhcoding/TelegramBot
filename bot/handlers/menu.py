"""
DreamX Coupon Bot — Main Menu Handler
Handles menu navigation callbacks.
"""

from aiogram import Router, types, F
from bot.keyboards.main_menu import main_menu_kb
from bot.utils.decorators import error_handler

router = Router()


@router.callback_query(F.data == "main_menu")
@error_handler
async def cb_main_menu(callback: types.CallbackQuery):
    user = callback.from_user
    text = (
        f"🌟 *DreamX Store*\n\n"
        f"Welcome back, *{user.first_name or 'User'}*\\! 👋\n\n"
        f"Choose an option below\\:"
    )
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=main_menu_kb(user.id),
    )
    await callback.answer()


@router.callback_query(F.data == "help_menu")
@error_handler
async def cb_help(callback: types.CallbackQuery):
    from bot.keyboards.common import back_button
    from aiogram.types import InlineKeyboardMarkup

    text = (
        "ℹ️ *Help & Support*\n\n"
        "🛒 *Buy Coupons* — Browse & purchase deals\n"
        "💰 *Wallet* — Top\\-up & view transactions\n"
        "📦 *My Orders* — Track your purchases\n\n"
        "💬 Need help\\? Contact support\\.\n"
        "🔒 All payments are verified & secure\\."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer("This item is currently unavailable.", show_alert=True)
