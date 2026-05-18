"""
DreamX Coupon Bot — Wallet Handlers
"""

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.services.wallet_service import get_balance, get_history
from bot.keyboards.wallet_kb import wallet_menu_kb, topup_amounts_kb
from bot.keyboards.common import back_button
from bot.utils.helpers import format_currency, format_datetime, escape_md
from bot.utils.decorators import error_handler

router = Router()


class WalletStates(StatesGroup):
    waiting_custom_amount = State()


@router.callback_query(F.data == "wallet_menu")
@error_handler
async def cb_wallet(callback: types.CallbackQuery):
    balance = await get_balance(callback.from_user.id)
    bal_str = escape_md(format_currency(balance))
    text = (
        f"💰 *Your Wallet*\n\n"
        f"💎 Balance: *{bal_str}*\n\n"
        f"Choose an option:"
    )
    await callback.message.edit_text(
        text, parse_mode="MarkdownV2", reply_markup=wallet_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "wallet_topup")
@error_handler
async def cb_topup(callback: types.CallbackQuery):
    text = "➕ *Top\\-Up Wallet*\n\nSelect an amount or enter custom:"
    await callback.message.edit_text(
        text, parse_mode="MarkdownV2", reply_markup=topup_amounts_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "wallet_history")
@error_handler
async def cb_history(callback: types.CallbackQuery):
    from aiogram.types import InlineKeyboardMarkup

    history = await get_history(callback.from_user.id, 10)

    if not history:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("wallet_menu")]])
        await callback.message.edit_text(
            "📜 *Transaction History*\n\nNo transactions yet\\.",
            parse_mode="MarkdownV2", reply_markup=kb,
        )
        await callback.answer()
        return

    lines = ["📜 *Transaction History*\n"]
    for h in history:
        emoji = "➕" if h["txn_type"] in ("topup", "refund", "admin_credit", "referral_reward", "referral_commission") else "➖"
        ttype = escape_md(h["txn_type"].upper())
        amt = escape_md(format_currency(h["amount"]))
        bal = escape_md(format_currency(h["balance_after"]))
        dt = escape_md(format_datetime(h["created_at"]))
        lines.append(
            f"{emoji} {ttype} — {amt}\n"
            f"   Balance: {bal} │ {dt}"
        )

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("wallet_menu")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "topup_custom")
@error_handler
async def cb_topup_custom(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💬 Enter the amount you want to add \\(min ₹10, max ₹10,000\\):",
        parse_mode="MarkdownV2",
    )
    await state.set_state(WalletStates.waiting_custom_amount)
    await callback.answer()


@router.message(WalletStates.waiting_custom_amount)
@error_handler
async def msg_custom_amount(message: types.Message, state: FSMContext):
    # Guard: menu button or command pressed during input
    text = (message.text or "").strip()
    if text.startswith("/") or any(ord(c) > 127 for c in text):
        await state.clear()
        return

    try:
        amount = float(text)
        if amount < 10 or amount > 10000:
            await message.answer("⚠️ Amount must be between ₹10 and ₹10,000.")
            return
    except ValueError:
        await message.answer("⚠️ Please enter a valid number.")
        return

    await state.clear()

    # Redirect to payment flow for topup
    from bot.handlers.purchase import initiate_topup_payment
    await initiate_topup_payment(message, amount)


@router.callback_query(F.data.startswith("topup_amt:"))
@error_handler
async def cb_topup_amount(callback: types.CallbackQuery):
    """Handle preset wallet top-up amount buttons."""
    amount = float(callback.data.split(":")[1])
    from bot.handlers.purchase import initiate_topup_payment
    await initiate_topup_payment(callback.message, amount)
    await callback.answer()
