"""
DreamX Coupon Bot — Purchase Flow Handlers

Two payment gateways with DIFFERENT flows:

1. Paytm:  Dynamic QR → auto-poll Paytm status API → auto-detect payment
2. BharatPe: Static QR shown to user → user pays manually → enters UTR →
             bot verifies UTR against BharatPe transaction API
"""

import os
import json

from aiogram import Router, types, F
from aiogram.types import (
    BufferedInputFile, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.services.coupon_service import get_coupon_detail
from bot.services.order_service import (
    create_purchase_order, cancel_order, get_delivered_code,
    get_all_delivered_codes,
)
from bot.payments.upi import generate_upi_intent_url, create_qr_buffer
from bot.payments.verifier import check_upi_status, verify_payment, verify_bharatpe_utr
from bot.keyboards.coupon_kb import payment_pending_kb
from bot.keyboards.common import back_button
from bot.database import queries as db
from bot.config import Config
from bot.utils.helpers import format_currency, escape_md
from bot.utils.decorators import error_handler
from bot.utils.logger import logger

router = Router()


async def _build_success_message(order_id: str, coupon_id: int, amount: float, utr: str = "") -> str:
    """Build an attractive payment success message with all delivered coupon codes."""
    coupon = await get_coupon_detail(coupon_id)
    codes = await get_all_delivered_codes(order_id)

    coupon_title = escape_md(coupon["title"]) if coupon else "Coupon"
    amt = escape_md(format_currency(amount))
    oid = escape_md(order_id)

    # Build codes section
    if codes:
        if len(codes) == 1:
            codes_section = f"\n🔑 *Your Coupon Code:*\n`{escape_md(codes[0])}`"
        else:
            codes_list = "\n".join(f"`{escape_md(c)}`" for c in codes)
            codes_section = f"\n🔑 *Your Coupon Codes \\({len(codes)}\\):*\n{codes_list}"
    else:
        codes_section = "\n⚠️ _Codes will be available in your order history_"

    utr_line = f"🔢 *UTR:* `{escape_md(utr)}`\n" if utr else ""

    text = (
        f"🎉 *PAYMENT SUCCESSFUL\\!* 🎉\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🛍️ *Item:* {coupon_title}\n"
        f"💸 *Amount Paid:* {amt}\n"
        f"📦 *Order ID:* `{oid}`\n"
        f"{utr_line}"
        f"{codes_section}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💾 *Save your Order ID:*\n"
        f"`{oid}`\n\n"
        f"🎊 *Thank you for your purchase\\! Enjoy\\!* 🎊"
    )
    return text

# ── FSM States for BharatPe UTR Entry ────────────────────
class BharatPeStates(StatesGroup):
    waiting_utr = State()

class CustomQtyStates(StatesGroup):
    waiting_qty = State()


# ── Quantity Selection → Gateway ─────────────────────────

@router.callback_query(F.data.startswith("buy_qty:"))
@error_handler
async def cb_buy_qty(callback: types.CallbackQuery):
    """User selected a preset quantity — show gateway selection."""
    parts = callback.data.split(":")
    coupon_id = int(parts[1])
    qty = int(parts[2])
    coupon = await get_coupon_detail(coupon_id)

    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return
    if coupon["stock"] < qty:
        await callback.answer(f"Not enough stock! Only {coupon['stock']} left.", show_alert=True)
        return

    total = float(coupon["discounted_price"]) * qty
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(total))

    from bot.keyboards.coupon_kb import gateway_selection_kb
    text = (
        f"💳 *Select Payment Gateway*\n\n"
        f"🏷️ {title}\n"
        f"📦 Quantity: *{qty}*\n"
        f"💰 Total: *{amt}*\n\n"
        f"Choose your preferred payment method:"
    )
    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=gateway_selection_kb(coupon_id, qty),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_custom_qty:"))
@error_handler
async def cb_buy_custom_qty(callback: types.CallbackQuery, state: FSMContext):
    """User wants custom quantity — ask for number."""
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    await state.update_data(custom_qty_coupon_id=coupon_id)
    title = escape_md(coupon["title"])
    await callback.message.edit_text(
        f"✏️ *Custom Quantity*\n\n"
        f"🏷️ {title}\n"
        f"📦 Available: {coupon['stock']}\n"
        f"💰 Price: ₹{coupon['discounted_price']}/unit\n\n"
        f"Enter the quantity you want to buy:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(CustomQtyStates.waiting_qty)
    await callback.answer()


@router.message(CustomQtyStates.waiting_qty)
@error_handler
async def msg_custom_qty(message: types.Message, state: FSMContext):
    """Receive custom quantity number."""
    try:
        qty = int(message.text.strip())
        if qty < 1:
            await message.answer("⚠️ Quantity must be at least 1.")
            return
    except ValueError:
        await message.answer("⚠️ Enter a valid number.")
        return

    data = await state.get_data()
    coupon_id = data["custom_qty_coupon_id"]
    await state.clear()

    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await message.answer("Coupon not found.")
        return
    if coupon["stock"] < qty:
        await message.answer(f"⚠️ Not enough stock! Only {coupon['stock']} available.")
        return

    total = float(coupon["discounted_price"]) * qty
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(total))

    from bot.keyboards.coupon_kb import gateway_selection_kb
    text = (
        f"💳 *Select Payment Gateway*\n\n"
        f"🏷️ {title}\n"
        f"📦 Quantity: *{qty}*\n"
        f"💰 Total: *{amt}*\n\n"
        f"Choose your preferred payment method:"
    )
    await message.answer(
        text, parse_mode="MarkdownV2",
        reply_markup=gateway_selection_kb(coupon_id, qty),
    )


# Legacy handler for old buy_coupon callback (backward compat)
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

    from bot.keyboards.coupon_kb import gateway_selection_kb
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(float(coupon["discounted_price"])))
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



# ══════════════════════════════════════════════════════════════
# PAYTM GATEWAY — Dynamic QR + Auto-Poll
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pay_gateway:paytm:"))
@error_handler
async def cb_pay_paytm(callback: types.CallbackQuery):
    """Paytm selected — create order, generate dynamic QR, auto-poll detects payment."""
    parts = callback.data.split(":")
    coupon_id = int(parts[2])
    qty = int(parts[3]) if len(parts) > 3 else 1
    coupon = await get_coupon_detail(coupon_id)

    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return
    if coupon["stock"] < qty:
        await callback.answer(f"Not enough stock! Only {coupon['stock']} left.", show_alert=True)
        return

    user_id = callback.from_user.id
    amount = float(coupon["discounted_price"]) * qty

    # Create order with Paytm gateway
    order_info = await create_purchase_order(user_id, coupon_id, amount, "paytm")
    order_id = order_info["order_id"]
    txn_ref = order_info["txn_ref"]

    # Generate dynamic QR for Paytm
    upi_url = await generate_upi_intent_url(amount, txn_ref, f"Order {order_id}", "paytm")
    qr_buf = create_qr_buffer(upi_url, amount, txn_ref)

    timeout_min = Config.PAYMENT_TIMEOUT // 60
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(amount))
    oid = escape_md(order_id)
    ref = escape_md(txn_ref)

    caption = (
        f"💳 *Payment Required — Paytm*\n\n"
        f"🏷️ {title}\n"
        f"💰 Amount: *{amt}*\n"
        f"🧾 Order: `{oid}`\n"
        f"🔖 Ref: `{ref}`\n\n"
        f"⏰ Expires in {timeout_min} minutes\n\n"
        f"Scan the QR code with any UPI app to pay\\.\n\n"
        f"_Payment will be auto\\-detected\\. "
        f"You can also click Check Payment below\\._"
    )

    try:
        await callback.message.delete()
    except Exception:
        pass

    msg = await callback.message.answer_photo(
        photo=BufferedInputFile(qr_buf.read(), filename="payment_qr.png"),
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=payment_pending_kb(order_id),
    )
    await db.update_order_qr_message_id(order_id, msg.message_id)
    await callback.answer()
    logger.info(f"QR generated [paytm] for user {user_id}, order={order_id}, txn={txn_ref}, amount={amount}")


# ══════════════════════════════════════════════════════════════
# BHARATPE GATEWAY — Static QR + Manual UTR Verification
# Mirrors the PHP recharge.php → upi.php flow exactly
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pay_gateway:bharatpe:"))
@error_handler
async def cb_pay_bharatpe(callback: types.CallbackQuery, state: FSMContext):
    """BharatPe selected — show static QR image, ask user to pay & enter UTR."""
    parts = callback.data.split(":")
    coupon_id = int(parts[2])
    qty = int(parts[3]) if len(parts) > 3 else 1
    coupon = await get_coupon_detail(coupon_id)

    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return
    if coupon["stock"] < qty:
        await callback.answer(f"Not enough stock! Only {coupon['stock']} left.", show_alert=True)
        return

    user_id = callback.from_user.id
    amount = float(coupon["discounted_price"]) * qty

    # Create order with BharatPe gateway
    order_info = await create_purchase_order(user_id, coupon_id, amount, "bharatpe")
    order_id = order_info["order_id"]

    timeout_min = Config.PAYMENT_TIMEOUT // 60
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(amount))
    oid = escape_md(order_id)

    # Get payment settings from DB
    ps = await db.get_payment_settings()
    bp_upi = ps.get("bharatpe_upi_id", "")

    upi_line = ""
    if bp_upi:
        upi_esc = escape_md(bp_upi)
        upi_line = f"\n📱 UPI ID: `{upi_esc}` _\\(tap to copy\\)_\n"

    caption = (
        f"💳 *Payment Required — Bharat Pay*\n\n"
        f"🏷️ {title}\n"
        f"💰 Amount: *{amt}*\n"
        f"🧾 Order: `{oid}`\n"
        f"{upi_line}\n"
        f"📱 *Steps:*\n"
        f"1️⃣ Scan the QR with any UPI app\n"
        f"2️⃣ Pay *{amt}*\n"
        f"3️⃣ After payment, send your *UTR number* here\n\n"
        f"⏰ Expires in {timeout_min} minutes\n\n"
        f"_Waiting for your UTR number\\.\\.\\._"
    )

    try:
        await callback.message.delete()
    except Exception:
        pass

    # Send the BharatPe QR image from DB settings
    qr_path = ps.get("bharatpe_qr_path", "")
    if qr_path and os.path.exists(qr_path):
        photo = FSInputFile(qr_path)
    else:
        # Fallback — try from project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        fallback = os.path.join(project_root, "bharatpe_qr.png")
        if os.path.exists(fallback):
            photo = FSInputFile(fallback)
        else:
            await callback.message.answer(
                "⚠️ BharatPe QR image not configured\\. Please contact admin\\.",
                parse_mode="MarkdownV2",
            )
            await callback.answer("QR image missing.", show_alert=True)
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancel_order:{order_id}")],
    ])

    msg = await callback.message.answer_photo(
        photo=photo,
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await db.update_order_qr_message_id(order_id, msg.message_id)
    await callback.answer()

    # Set FSM state — waiting for UTR input
    await state.set_state(BharatPeStates.waiting_utr)
    await state.update_data(order_id=order_id, coupon_id=coupon_id, amount=amount)

    logger.info(f"BharatPe static QR shown for user {user_id}, order={order_id}, amount={amount}")


# ── BharatPe UTR Submission ──────────────────────────────
@router.message(BharatPeStates.waiting_utr)
@error_handler
async def msg_bharatpe_utr(message: types.Message, state: FSMContext):
    """User submitted UTR number — verify against BharatPe API."""
    data = await state.get_data()
    order_id = data.get("order_id")
    coupon_id = data.get("coupon_id")
    amount = data.get("amount")

    if not order_id or not message.text:
        await message.answer("⚠️ Please enter a valid UTR number.")
        return

    utr = message.text.strip()

    # Validate UTR format (alphanumeric, max 12 chars — mirrors PHP validation)
    import re
    if not re.match(r'^[a-zA-Z0-9]+$', utr):
        await message.answer("⚠️ Symbol not allowed\\. UTR must be alphanumeric\\.", parse_mode="MarkdownV2")
        return

    if len(utr) > 12:
        await message.answer("⚠️ UTR cannot be more than 12 digits\\.", parse_mode="MarkdownV2")
        return

    if utr[0] == '0':
        await message.answer("⚠️ Invalid UTR entered\\.", parse_mode="MarkdownV2")
        return

    # Check order still valid
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        await state.clear()
        await message.answer("⚠️ This order is no longer pending\\. Please create a new order\\.", parse_mode="MarkdownV2")
        return

    # Check if UTR was already used
    pool = await db.get_pool()
    existing = await pool.fetchrow(
        "SELECT order_id FROM transactions WHERE utr = $1 AND status = 'success'", utr
    )
    if existing:
        await message.answer("⚠️ This UTR has already been used\\.", parse_mode="MarkdownV2")
        return

    # Show "checking" message
    checking_msg = await message.answer(
        "🔄 *Checking your payment\\.\\.\\.*\n\nPlease wait while we verify your UTR\\.",
        parse_mode="MarkdownV2",
    )

    # Verify UTR against BharatPe API
    is_paid, details = await verify_bharatpe_utr(utr, amount)

    if is_paid:
        # Payment verified! Clear FSM state
        await state.clear()

        # Store UTR in the transaction record (non-critical — don't let this block order completion)
        txn_ref = utr  # fallback
        try:
            txn_row = await pool.fetchrow(
                "SELECT txn_ref FROM transactions WHERE order_id = $1 ORDER BY created_at DESC LIMIT 1",
                order_id,
            )
            if txn_row:
                txn_ref = txn_row["txn_ref"]
                await pool.execute(
                    "UPDATE transactions SET utr = $1, raw_response = $2 WHERE txn_ref = $3",
                    utr, json.dumps(details), txn_ref,
                )
        except Exception as e:
            logger.error(f"Non-critical: failed to save UTR/response for {order_id}: {e}")

        # Complete order (reduce stock + deliver coupon)
        from bot.services.order_service import complete_order
        success = await complete_order(order_id, txn_ref, message.from_user.id)

        if success:
            text = await _build_success_message(order_id, coupon_id, amount, utr)

            try:
                await checking_msg.delete()
            except Exception:
                pass
            
            # Delete the QR code message
            try:
                if order.get("qr_message_id"):
                    await message.bot.delete_message(message.chat.id, order["qr_message_id"])
            except Exception as e:
                logger.error(f"Could not delete QR message: {e}")

            kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
            await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
            # Re-send main menu keyboard so user can continue without /start
            from bot.keyboards.main_menu import main_menu_kb
            await message.answer("👇 Use buttons below to continue:", reply_markup=main_menu_kb(message.from_user.id))

            logger.info(f"BharatPe VERIFIED: order={order_id}, UTR={utr}, amount={amount}")
        else:
            try:
                await checking_msg.delete()
            except Exception:
                pass
            await message.answer(
                "⚠️ Payment verified but order completion failed\\. Please contact support\\.",
                parse_mode="MarkdownV2",
            )
    else:
        # UTR not found or amount mismatch
        try:
            await checking_msg.delete()
        except Exception:
            pass

        min_amt = escape_md(format_currency(Config.BHARATPE_MIN_RECHARGE))
        await message.answer(
            f"❌ *Payment Not Found*\n\n"
            f"UTR `{escape_md(utr)}` was not found or amount doesn't match\\.\n\n"
            f"Please make sure:\n"
            f"• You paid the exact amount\n"
            f"• Minimum payment is {min_amt}\n"
            f"• You entered the correct UTR\n\n"
            f"_Try entering your UTR again, or cancel the order\\._",
            parse_mode="MarkdownV2",
        )
        # DON'T clear state — let user retry with correct UTR


# ══════════════════════════════════════════════════════════════
# CHECK PAYMENT (Paytm only — BharatPe uses UTR)
# ══════════════════════════════════════════════════════════════

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
        text = await _build_success_message(order_id, order["coupon_id"], float(order["amount"]))

        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
        
        # Delete QR message if stored
        try:
            if order.get("qr_message_id"):
                await callback.message.bot.delete_message(callback.message.chat.id, order["qr_message_id"])
        except Exception:
            pass

        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
        # Re-send main menu keyboard
        from bot.keyboards.main_menu import main_menu_kb
        await callback.message.answer("👇 Use buttons below to continue:", reply_markup=main_menu_kb(callback.from_user.id))
        await callback.answer("Payment verified! ✅", show_alert=True)
        return

    if order["status"] == "expired":
        await callback.answer("This order has expired. Please create a new order.", show_alert=True)
        return

    if order["status"] == "cancelled":
        await callback.answer("This order was cancelled.", show_alert=True)
        return

    # Check if order expired but status not yet updated by background task
    from datetime import datetime, timezone
    if order.get("expires_at") and order["expires_at"] < datetime.now(timezone.utc):
        await db.update_order_status(order_id, "expired")
        await callback.answer("This order has expired. Please create a new order.", show_alert=True)
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

        # Only Paytm supports status polling — BharatPe uses UTR
        if gateway == "bharatpe":
            await callback.answer(
                "📝 Please send your UTR number in the chat to verify payment.",
                show_alert=True,
            )
            return

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
                        f"🎉 *WOOHOO\\! PAYMENT SUCCESSFUL\\!* 🎉\n\n"
                        f"🛍️ *Item:* {coupon_title}\n"
                        f"💸 *Amount Paid:* {amt}\n"
                        f"📦 *Order ID:* `{oid}`\n"
                        f"{code_text}\n\n"
                        f"💾 *Please save your Order ID for future reference:*\n"
                        f"`{oid}`\n\n"
                        f"🎊 *Thank you for your purchase\\! Enjoy\\!* 🎊"
                    )

                    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
                    
                    # Delete QR message if stored
                    try:
                        if order.get("qr_message_id"):
                            await callback.message.bot.delete_message(callback.message.chat.id, order["qr_message_id"])
                    except Exception:
                        pass
                        
                    try:
                        await callback.message.delete()
                    except Exception:
                        pass
                    await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
                    # Re-send main menu keyboard
                    from bot.keyboards.main_menu import main_menu_kb
                    await callback.message.answer("👇 Use buttons below to continue:", reply_markup=main_menu_kb(callback.from_user.id))
                    await callback.answer("Payment verified! ✅", show_alert=True)
                    return

    # Still pending
    await callback.answer("⏳ Payment not yet received. Please complete the payment and try again.", show_alert=True)


# ── Cancel Order ─────────────────────────────────────────

@router.callback_query(F.data.startswith("cancel_order:"))
@error_handler
async def cb_cancel_order(callback: types.CallbackQuery, state: FSMContext):
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

        # Only check Paytm status before cancel (BharatPe requires UTR)
        if gateway == "paytm":
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

                            try:
                                await callback.message.delete()
                            except Exception:
                                pass
                            kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
                            await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
                            await callback.answer("Payment was already received! ✅", show_alert=True)
                            return
            except Exception as e:
                logger.error(f"Error checking payment before cancel: {e}")

    # No payment received — safe to cancel
    success = await cancel_order(order_id)

    # Clear BharatPe FSM state if active
    await state.clear()

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
            [back_button("back_home")],
        ])
        await callback.message.answer(
            cancellation_text, parse_mode="MarkdownV2", reply_markup=kb
        )
        await callback.answer("Order cancelled.", show_alert=True)
    else:
        await callback.answer("Cannot cancel this order.", show_alert=True)


# ── My Orders ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("my_orders"))
@error_handler
async def cb_my_orders(callback: types.CallbackQuery):
    from bot.services.order_service import get_user_order_history, get_user_order_history_count
    
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 1
    limit = 5
    offset = (page - 1) * limit

    total_orders = await get_user_order_history_count(callback.from_user.id)
    orders = await get_user_order_history(callback.from_user.id, limit, offset)

    if not orders and page == 1:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
        try:
            await callback.message.edit_text(
                "📦 *My Orders*\n\nNo orders yet\\.",
                parse_mode="MarkdownV2", reply_markup=kb,
            )
        except Exception:
            await callback.message.answer(
                "📦 *My Orders*\n\nNo orders yet\\.",
                parse_mode="MarkdownV2", reply_markup=kb,
            )
        await callback.answer()
        return

    # Build attractive order history matching the reference screenshot
    lines = [
        "📦 *ORDER HISTORY*",
        "",
        f"📊 Total: {total_orders} orders",
    ]

    buttons = []
    pool = await db.get_pool()

    for i, o in enumerate(orders):
        # Order number calculation (overall #)
        num = total_orders - offset - i
        oid = o["order_id"]

        # Get coupon title
        coupon_row = await pool.fetchrow("SELECT title FROM coupons WHERE id = $1", o["coupon_id"])
        coupon_title = coupon_row["title"] if coupon_row else "Unknown"

        # Get code count for this order
        code_count = await pool.fetchval(
            "SELECT COUNT(*) FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE", oid
        ) or 0

        amt = f"₹{float(o['amount']):.1f}"
        qty = o.get("quantity", 1) or 1

        # Format date
        created = o["created_at"]
        date_str = created.strftime("%Y-%m-%d %H:%M:%S") if created else ""

        oid_esc = escape_md(oid)
        title_esc = escape_md(coupon_title)
        amt_esc = escape_md(amt)
        date_esc = escape_md(date_str)

        lines.append(f"\n━━━━ \\#*{num}* ━━━━")
        lines.append(f"🏷️ {title_esc}")
        lines.append(f"🕐 {date_esc}")
        lines.append(f"🛍️ Qty: {qty} • 💰 {amt_esc}")
        lines.append(f"🆔 `{oid_esc}`")
        if code_count > 0:
            lines.append(f"📦 {code_count} coupon\\(s\\) \\- tap to view")
        else:
            lines.append(f"📦 Status: {escape_md(o['status'])}")

        # Add View Codes button for delivered/paid orders
        if o["status"] in ("delivered", "paid") and code_count > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=f"📋 #{num} View Codes",
                    callback_data=f"view_codes:{oid}"
                )
            ])

    text = "\n".join(lines)
    
    # Pagination
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"my_orders:page:{page-1}"))
    if offset + limit < total_orders:
        nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"my_orders:page:{page+1}"))
        
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([back_button("back_home")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("view_codes:"))
@error_handler
async def cb_view_codes(callback: types.CallbackQuery):
    """View coupon codes for a specific order."""
    order_id = callback.data.split(":")[1]

    pool = await db.get_pool()
    codes = await pool.fetch(
        "SELECT code FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE", order_id
    )

    if not codes:
        await callback.answer("No codes found for this order.", show_alert=True)
        return

    oid_esc = escape_md(order_id)
    lines = [
        f"🔑 *Codes for Order* `{oid_esc}`\n",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for i, c in enumerate(codes, 1):
        code_esc = escape_md(c["code"])
        lines.append(f"{i}\\. `{code_esc}`")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"\n_💾 Save these codes\\!_")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Back to Orders", callback_data="my_orders")],
        [back_button("back_home")],
    ])
    await callback.message.edit_text("\n".join(lines), parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()



