"""
DreamX Coupon Bot — Purchase Flow Handlers
Buy coupon → generate unique QR per user → auto-detect/manual verify → deliver.
"""

from aiogram import Router, types, F
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from bot.services.coupon_service import get_coupon_detail
from bot.services.order_service import (
    create_purchase_order, cancel_order, get_delivered_code
)
from bot.payments.upi import generate_upi_intent_url, create_qr_buffer
from bot.payments.verifier import check_upi_status, verify_payment
from bot.keyboards.coupon_kb import payment_pending_kb
from bot.keyboards.common import back_button
from bot.database import queries as db
from bot.config import Config
from bot.utils.helpers import format_currency, escape_md
from bot.utils.decorators import error_handler
from bot.utils.logger import logger

router = Router()


# ── Buy Coupon → Show Gateway Selection ──────────────────

@router.callback_query(F.data.startswith("buy_coupon:"))
@error_handler
async def cb_buy_coupon(callback: types.CallbackQuery):
    """User clicked Buy Now — show payment gateway options."""
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)

    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    if coupon["stock"] <= 0:
        await callback.answer("Sorry, this coupon is out of stock!", show_alert=True)
        return

    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(float(coupon["discounted_price"])))

    from bot.keyboards.coupon_kb import gateway_selection_kb

    text = (
        f"💳 *Select Payment Gateway*\n\n"
        f"🏷️ {title}\n"
        f"💰 Amount: *{amt}*\n\n"
        f"Choose your preferred payment method:"
    )
    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=gateway_selection_kb(coupon_id),
    )
    await callback.answer()


# ── Gateway Selected → Create Order + Generate QR ────────

@router.callback_query(F.data.startswith("pay_gateway:"))
@error_handler
async def cb_pay_gateway(callback: types.CallbackQuery):
    """User selected a payment gateway — create order and generate unique QR."""
    parts = callback.data.split(":")
    gateway = parts[1]       # "paytm" or "bharatpe"
    coupon_id = int(parts[2])

    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    if coupon["stock"] <= 0:
        await callback.answer("Sorry, this coupon is out of stock!", show_alert=True)
        return

    user_id = callback.from_user.id
    amount = float(coupon["discounted_price"])

    # Create order — generates unique order_id + unique txn_ref per user
    order_info = await create_purchase_order(user_id, coupon_id, amount, gateway)
    order_id = order_info["order_id"]
    txn_ref = order_info["txn_ref"]

    # Generate UNIQUE dynamic QR for the selected gateway
    upi_url = generate_upi_intent_url(amount, txn_ref, f"Order {order_id}", gateway)
    qr_buf = create_qr_buffer(upi_url, amount, txn_ref)

    timeout_min = Config.PAYMENT_TIMEOUT // 60

    gateway_name = "Paytm" if gateway == "paytm" else "BharatPe"
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(amount))
    oid = escape_md(order_id)
    ref = escape_md(txn_ref)
    gw = escape_md(gateway_name)

    caption = (
        f"💳 *Payment Required*\n\n"
        f"🏷️ {title}\n"
        f"💰 Amount: *{amt}*\n"
        f"🧾 Order: `{oid}`\n"
        f"🔖 Ref: `{ref}`\n"
        f"🏦 Gateway: *{gw}*\n\n"
        f"⏰ Expires in {timeout_min} minutes\n\n"
        f"Scan the QR code with any UPI app to pay\\.\n\n"
        f"_Payment will be auto\\-detected\\. "
        f"You can also click Check Payment below\\._"
    )

    # Delete the gateway selection message
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer_photo(
        photo=BufferedInputFile(qr_buf.read(), filename="payment_qr.png"),
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=payment_pending_kb(order_id),
    )
    await callback.answer()
    logger.info(f"QR generated [{gateway}] for user {user_id}, order={order_id}, txn={txn_ref}, amount={amount}")


# ── Check Payment (Manual Verification) ──────────────────

@router.callback_query(F.data.startswith("check_pay:"))
@error_handler
async def cb_check_payment(callback: types.CallbackQuery):
    """User clicked Check Payment — immediately verify with Paytm."""
    order_id = callback.data.split(":")[1]
    order = await db.get_order(order_id)

    if not order:
        await callback.answer("Order not found.", show_alert=True)
        return

    # Already completed
    if order["status"] in ("paid", "delivered"):
        coupon = await get_coupon_detail(order["coupon_id"])
        code_row = await get_delivered_code(order_id, order["coupon_id"])
        code_text = ""
        if code_row:
            code_val = escape_md(code_row["code"])
            code_text = f"\n\n🔑 Code: `{code_val}`"

        coupon_title = escape_md(coupon["title"]) if coupon else "Coupon"
        amt = escape_md(format_currency(float(order["amount"])))
        oid = escape_md(order_id)

        text = (
            f"✅ *Payment Successful\\!*\n\n"
            f"🏷️ {coupon_title}\n"
            f"💰 Amount: {amt}\n"
            f"📦 Order: `{oid}`"
            f"{code_text}\n\n"
            f"💾 *Save this Order ID to recover your coupon later:*\n"
            f"`{oid}`\n\n"
            f"Thank you for your purchase\\! 🎉"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
        try:
            await callback.message.edit_caption(caption=text, parse_mode="MarkdownV2", reply_markup=kb)
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
        await callback.answer("Payment verified! ✅", show_alert=True)
        return

    if order["status"] == "expired":
        await callback.answer("This order has expired. Please create a new order.", show_alert=True)
        return

    if order["status"] == "cancelled":
        await callback.answer("This order was cancelled.", show_alert=True)
        return

    # Status is pending — do a LIVE check with Paytm right now
    pool = await db.get_pool()
    txn_row = await pool.fetchrow(
        "SELECT txn_ref, gateway, amount FROM transactions WHERE order_id = $1 ORDER BY created_at DESC LIMIT 1",
        order_id,
    )

    if txn_row:
        txn_ref = txn_row["txn_ref"]
        gateway = txn_row["gateway"]
        amount = float(txn_row["amount"])

        response = await check_upi_status(txn_ref, gateway)

        if response.get("STATUS") != "API_ERROR" and "error" not in response:
            is_paid, details = verify_payment(response, amount, txn_ref, gateway)
            if is_paid:
                # Payment received! Complete the order
                from bot.services.order_service import complete_order
                success = await complete_order(order_id, txn_ref, order["user_id"])
                if success:
                    coupon = await get_coupon_detail(order["coupon_id"])
                    code_row = await get_delivered_code(order_id, order["coupon_id"])
                    code_text = ""
                    if code_row:
                        code_val = escape_md(code_row["code"])
                        code_text = f"\n\n🔑 Code: `{code_val}`"

                    coupon_title = escape_md(coupon["title"]) if coupon else "Coupon"
                    amt = escape_md(format_currency(float(order["amount"])))
                    oid = escape_md(order_id)

                    text = (
                        f"✅ *Payment Successful\\!*\n\n"
                        f"🏷️ {coupon_title}\n"
                        f"💰 Amount: {amt}\n"
                        f"📦 Order: `{oid}`"
                        f"{code_text}\n\n"
                        f"💾 *Save this Order ID to recover your coupon later:*\n"
                        f"`{oid}`\n\n"
                        f"Thank you for your purchase\\! 🎉"
                    )

                    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
                    try:
                        await callback.message.edit_caption(
                            caption=text, parse_mode="MarkdownV2", reply_markup=kb
                        )
                    except Exception:
                        try:
                            await callback.message.delete()
                        except Exception:
                            pass
                        await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
                    await callback.answer("Payment verified! ✅", show_alert=True)
                    return

    # Still pending
    await callback.answer("⏳ Payment not yet received. Please complete the payment and try again.", show_alert=True)


# ── Cancel Order ─────────────────────────────────────────

@router.callback_query(F.data.startswith("cancel_order:"))
@error_handler
async def cb_cancel_order(callback: types.CallbackQuery):
    """Cancel a pending order — delete QR message and send cancellation details."""
    order_id = callback.data.split(":")[1]
    order = await db.get_order(order_id)

    if not order:
        await callback.answer("Order not found.", show_alert=True)
        return

    # Already completed — cannot cancel
    if order["status"] in ("paid", "delivered"):
        await callback.answer(
            "❌ Cannot cancel — payment already received.",
            show_alert=True,
        )
        return

    if order["status"] in ("expired", "cancelled"):
        await callback.answer(
            f"This order is already {order['status']}.",
            show_alert=True,
        )
        return

    # Pending order — check with gateway first if payment was received
    pool = await db.get_pool()
    txn_row = await pool.fetchrow(
        "SELECT txn_ref, gateway, amount FROM transactions WHERE order_id = $1 ORDER BY created_at DESC LIMIT 1",
        order_id,
    )

    if txn_row:
        txn_ref = txn_row["txn_ref"]
        gateway = txn_row["gateway"]
        amount = float(txn_row["amount"])

        try:
            response = await check_upi_status(txn_ref, gateway)
            if response.get("STATUS") != "API_ERROR" and "error" not in response:
                is_paid, details = verify_payment(response, amount, txn_ref, gateway)
                if is_paid:
                    # Payment was received! Complete the order instead
                    from bot.services.order_service import complete_order
                    success = await complete_order(order_id, txn_ref, order["user_id"])
                    if success:
                        coupon = await get_coupon_detail(order["coupon_id"])
                        code_row = await get_delivered_code(order_id, order["coupon_id"])
                        code_text = ""
                        if code_row:
                            code_val = escape_md(code_row["code"])
                            code_text = f"\n\n🔑 Code: `{code_val}`"

                        coupon_title = escape_md(coupon["title"]) if coupon else "Coupon"
                        amt = escape_md(format_currency(float(order["amount"])))
                        oid = escape_md(order_id)

                        text = (
                            f"✅ *Payment Already Received\\!*\n\n"
                            f"🏷️ {coupon_title}\n"
                            f"💰 Amount: {amt}\n"
                            f"📦 Order: `{oid}`"
                            f"{code_text}\n\n"
                            f"💾 *Save this Order ID to recover your coupon later:*\n"
                            f"`{oid}`\n\n"
                            f"Your order has been placed\\! 🎉"
                        )

                        # Delete QR message, send success message
                        try:
                            await callback.message.delete()
                        except Exception:
                            pass
                        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
                        await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
                        await callback.answer("Payment was already received! ✅", show_alert=True)
                        return
        except Exception as e:
            logger.error(f"Error checking payment before cancel: {e}")

    # No payment received — safe to cancel
    success = await cancel_order(order_id)

    if success:
        # Get coupon details for cancellation message
        coupon = await get_coupon_detail(order["coupon_id"])
        coupon_title = escape_md(coupon["title"]) if coupon else "Unknown Product"
        amt = escape_md(format_currency(float(order["amount"])))
        oid = escape_md(order_id)

        cancellation_text = (
            f"❌ *Order Cancelled*\n\n"
            f"📦 Order ID: `{oid}`\n"
            f"🏷️ Product: {coupon_title}\n"
            f"💰 Amount: {amt}\n\n"
            f"Your order has been cancelled as per your request\\.\n"
            f"You can place a new order anytime from the menu\\."
        )

        # Delete the QR photo message
        try:
            await callback.message.delete()
        except Exception:
            pass

        # Send a NEW clean cancellation message
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍️ Browse Coupons", callback_data="browse_coupons")],
            [back_button("main_menu")],
        ])
        await callback.message.answer(
            cancellation_text, parse_mode="MarkdownV2", reply_markup=kb
        )
        await callback.answer("Order cancelled.", show_alert=True)
    else:
        await callback.answer("Cannot cancel this order.", show_alert=True)


# ── My Orders ─────────────────────────────────────────────

@router.callback_query(F.data == "my_orders")
@error_handler
async def cb_my_orders(callback: types.CallbackQuery):
    from bot.services.order_service import get_user_order_history

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
        amt = escape_md(format_currency(float(o["amount"])))
        oid = escape_md(o["order_id"])
        st = escape_md(o["status"])
        lines.append(
            f"{emoji} `{oid}` — {amt} \\({st}\\)"
        )

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()
