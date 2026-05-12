"""
DreamX Coupon Bot — Purchase Flow Handlers
Buy coupon → generate QR → verify → deliver.
"""

from aiogram import Router, types, F
from aiogram.types import BufferedInputFile

from bot.services.coupon_service import get_coupon_detail
from bot.services.order_service import (
    create_purchase_order, cancel_order, get_delivered_code
)
from bot.payments.upi import generate_upi_intent_url, create_qr_buffer
from bot.keyboards.coupon_kb import payment_pending_kb
from bot.keyboards.common import back_button
from bot.database import queries as db
from bot.config import Config
from bot.utils.helpers import format_currency, format_datetime
from bot.utils.decorators import error_handler
from bot.utils.logger import logger

router = Router()


@router.callback_query(F.data.startswith("buy_coupon:"))
@error_handler
async def cb_buy_coupon(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)

    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    if coupon["stock"] <= 0:
        await callback.answer("Sorry, this coupon is out of stock!", show_alert=True)
        return

    user_id = callback.from_user.id
    amount = float(coupon["discounted_price"])

    # Create order
    order_info = await create_purchase_order(user_id, coupon_id, amount)
    order_id = order_info["order_id"]
    txn_ref = order_info["txn_ref"]

    # Generate QR
    upi_url = generate_upi_intent_url(amount, txn_ref, f"Order {order_id}")
    qr_buf = create_qr_buffer(upi_url, amount, txn_ref)

    timeout_min = Config.PAYMENT_TIMEOUT // 60

    caption = (
        f"💳 *Payment Required*\n\n"
        f"🏷️ {coupon['title']}\n"
        f"💰 Amount: *{format_currency(amount)}*\n"
        f"🧾 Order: `{order_id}`\n"
        f"🔖 Ref: `{txn_ref}`\n\n"
        f"⏰ Expires in {timeout_min} minutes\n\n"
        f"Scan the QR code with any UPI app to pay\\."
    )
    caption = caption.replace(".", "\\.").replace("-", "\\-").replace("!", "\\!")

    await callback.message.delete()
    await callback.message.answer_photo(
        photo=BufferedInputFile(qr_buf.read(), filename="payment_qr.png"),
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=payment_pending_kb(order_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("check_pay:"))
@error_handler
async def cb_check_payment(callback: types.CallbackQuery):
    order_id = callback.data.split(":")[1]
    order = await db.get_order(order_id)

    if not order:
        await callback.answer("Order not found.", show_alert=True)
        return

    if order["status"] == "paid" or order["status"] == "delivered":
        coupon = await get_coupon_detail(order["coupon_id"])
        code_row = await get_delivered_code(order_id, order["coupon_id"])
        code_text = f"\n\n🔑 Code: `{code_row['code']}`" if code_row else ""

        text = (
            f"✅ *Payment Successful\\!*\n\n"
            f"🏷️ {coupon['title'] if coupon else 'Coupon'}\n"
            f"💰 Amount: {format_currency(float(order['amount']))}\n"
            f"📦 Order: `{order_id}`"
            f"{code_text}\n\n"
            f"Thank you for your purchase\\! 🎉"
        )

        from aiogram.types import InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
        await callback.message.edit_caption(caption=text, parse_mode="MarkdownV2", reply_markup=kb)
        await callback.answer("Payment verified! ✅", show_alert=True)

    elif order["status"] == "expired":
        await callback.answer("This order has expired. Please create a new order.", show_alert=True)

    elif order["status"] == "cancelled":
        await callback.answer("This order was cancelled.", show_alert=True)

    else:
        await callback.answer("⏳ Payment not yet received. Please complete the payment.", show_alert=True)


@router.callback_query(F.data.startswith("cancel_order:"))
@error_handler
async def cb_cancel_order(callback: types.CallbackQuery):
    order_id = callback.data.split(":")[1]
    success = await cancel_order(order_id)

    if success:
        from aiogram.types import InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
        await callback.message.edit_caption(
            caption=f"❌ Order `{order_id}` has been cancelled\\.",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )
        await callback.answer("Order cancelled.", show_alert=True)
    else:
        await callback.answer("Cannot cancel this order.", show_alert=True)


# ── My Orders ─────────────────────────────────────────────

@router.callback_query(F.data == "my_orders")
@error_handler
async def cb_my_orders(callback: types.CallbackQuery):
    from bot.services.order_service import get_user_order_history
    from aiogram.types import InlineKeyboardMarkup

    orders = await get_user_order_history(callback.from_user.id, 10)

    if not orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
        await callback.message.edit_text(
            "📦 *My Orders*\n\nNo orders yet\\.",
            parse_mode="MarkdownV2", reply_markup=kb,
        )
        await callback.answer()
        return

    status_emoji = {
        "pending": "🟡", "paid": "🟢", "delivered": "✅",
        "expired": "⏰", "cancelled": "❌", "refunded": "🔄"
    }

    lines = ["📦 *My Orders*\n"]
    for o in orders:
        emoji = status_emoji.get(o["status"], "❓")
        lines.append(
            f"{emoji} `{o['order_id']}` — {format_currency(float(o['amount']))} "
            f"\\({o['status']}\\)"
        )

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ── Top-Up Payment Flow ──────────────────────────────────

async def initiate_topup_payment(message: types.Message, amount: float):
    """Create a top-up payment (called from wallet handler)."""
    from bot.utils.helpers import generate_order_id
    from bot.payments.upi import generate_unique_txn_id
    from datetime import datetime, timezone, timedelta

    user_id = message.from_user.id
    order_id = generate_order_id()
    txn_ref = generate_unique_txn_id()  # TXN_{timestamp}_{random} — used as Paytm ORDERID
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=Config.PAYMENT_TIMEOUT)

    await db.create_order(order_id, user_id, 0, amount, expires_at)
    await db.create_transaction(
        txn_ref, order_id, user_id, amount,
        Config.PAYTM_MID or Config.BHARATPE_MERCHANT_ID, "paytm"
    )

    upi_url = generate_upi_intent_url(amount, txn_ref, f"Wallet TopUp {order_id}")
    qr_buf = create_qr_buffer(upi_url, amount, txn_ref)

    timeout_min = Config.PAYMENT_TIMEOUT // 60

    caption = (
        f"💳 *Wallet Top\\-Up*\n\n"
        f"💰 Amount: *{format_currency(amount)}*\n"
        f"🧾 Order: `{order_id}`\n"
        f"🔖 Ref: `{txn_ref}`\n\n"
        f"⏰ Expires in {timeout_min} minutes\n\n"
        f"Scan the QR code to add funds\\."
    )

    await message.answer_photo(
        photo=BufferedInputFile(qr_buf.read(), filename="topup_qr.png"),
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=payment_pending_kb(order_id),
    )


# ── Top-Up Amount Selection ──────────────────────────────

@router.callback_query(F.data.startswith("topup_amt:"))
@error_handler
async def cb_topup_amount(callback: types.CallbackQuery):
    amount = float(callback.data.split(":")[1])
    await callback.message.delete()
    await initiate_topup_payment(callback.message, amount)
    await callback.answer()
