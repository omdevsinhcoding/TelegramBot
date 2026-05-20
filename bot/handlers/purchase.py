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
    create_purchase_order, cancel_order,
    get_all_delivered_codes, complete_order, OutOfStockError,
)
from bot.payments.upi import generate_upi_intent_url, create_qr_buffer
from bot.payments.verifier import check_upi_status, verify_payment, verify_bharatpe_utr
from bot.keyboards.coupon_kb import payment_pending_kb
from bot.keyboards.common import back_button
from bot.database import queries as db
from bot.utils.helpers import format_currency, escape_md, safe_edit_or_send
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

    # Build codes section — limit inline display to avoid Telegram 4096 char limit
    MAX_INLINE_CODES = 10
    if codes:
        if len(codes) == 1:
            codes_section = f"\n🔑 *Your Coupon Code:*\n`{escape_md(codes[0])}`"
        elif len(codes) <= MAX_INLINE_CODES:
            codes_list = "\n".join(f"`{escape_md(c)}`" for c in codes)
            codes_section = f"\n🔑 *Your Coupon Codes \\({len(codes)}\\):*\n{codes_list}"
        else:
            # Too many codes — show first few + direct to My Orders
            preview = "\n".join(f"`{escape_md(c)}`" for c in codes[:MAX_INLINE_CODES])
            remaining = len(codes) - MAX_INLINE_CODES
            codes_section = (
                f"\n🔑 *Your Coupon Codes \\({len(codes)}\\):*\n{preview}\n"
                f"\n_\\.\\.\\.and {remaining} more_\n"
                f"📦 *Go to My Orders → View Codes to see all {len(codes)} codes*"
            )
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

# ── Stock Check Helper (reservation-aware) ───────────────

async def _check_stock_or_reserved(coupon, qty: int, user_id: int, callback_or_message) -> bool:
    """Check if stock is available. If reserved by another user, show wait message.
    
    Args:
        coupon: dict with coupon data (already fetched).
    Returns True if stock is OK (proceed), False if blocked (stop).
    """
    coupon_id = coupon["id"]
    stock = coupon["stock"]
    
    if stock >= qty:
        return True  # Stock available, no extra DB query needed
    
    # Stock not enough — check reservation info and admin flags
    dyn = await db.get_dynamic_config()
    use_reservation = dyn.get("reservation_enabled", True)
    use_waitlist = dyn.get("waitlist_enabled", True)

    if use_reservation:
        # Only check reservation info if reservation system is on
        res = await db.get_reservation_info(coupon_id)
        if res["reserved_qty"] > 0 and res["wait_minutes"] > 0:
            if use_waitlist:
                await db.add_to_waitlist(user_id, coupon_id)
                msg = (
                    f"⏳ Reserved by another buyer.\n"
                    f"🔔 You're on the waitlist!\n"
                    f"⏰ Available in ~{res['wait_minutes']} min"
                )
            else:
                msg = f"❌ Out of stock. Only {stock} available right now."
        else:
            msg = f"❌ Not enough stock! Only {stock} available."
    else:
        # Reservation disabled — simple out-of-stock message
        if use_waitlist:
            await db.add_to_waitlist(user_id, coupon_id)
            msg = (
                f"❌ Out of stock!\n"
                f"🔔 You're on the waitlist — we'll notify you when it's back!"
            )
        else:
            msg = f"❌ Out of stock! Only {stock} available right now."
    
    if hasattr(callback_or_message, 'data'):
        await callback_or_message.answer(msg, show_alert=True)
    else:
        await callback_or_message.answer(msg)
    
    return False


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
    if not await _check_stock_or_reserved(coupon, qty, callback.from_user.id, callback):
        return

    total = float(coupon["discounted_price"]) * qty
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(total))
    wallet = await db.get_wallet_balance(callback.from_user.id)
    ps = await db.get_payment_settings()

    from bot.keyboards.coupon_kb import gateway_selection_kb
    text = (
        f"💳 *Select Payment Gateway*\n\n"
        f"🏷️ {title}\n"
        f"📦 Quantity: *{qty}*\n"
        f"💰 Total: *{amt}*\n\n"
        f"Choose your preferred payment method:"
    )
    await safe_edit_or_send(
        callback.message, text,
        reply_markup=gateway_selection_kb(coupon_id, qty, wallet_balance=wallet, total=total, payment_settings=ps),
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
    price_str = escape_md(f"₹{coupon['discounted_price']}")
    stock_str = escape_md(str(coupon["stock"]))
    await safe_edit_or_send(
        callback.message,
        f"✏️ *Custom Quantity*\n\n"
        f"🏷️ {title}\n"
        f"📦 Available: {stock_str}\n"
        f"💰 Price: {price_str}/unit\n\n"
        f"Enter the quantity you want to buy:",
    )
    await state.set_state(CustomQtyStates.waiting_qty)
    await callback.answer()


@router.message(CustomQtyStates.waiting_qty)
@error_handler
async def msg_custom_qty(message: types.Message, state: FSMContext):
    """Receive custom quantity number."""
    # Guard: menu button or command pressed during input
    text = (message.text or "").strip()
    if text.startswith("/") or any(ord(c) > 127 for c in text):
        await state.clear()
        await message.answer("⚠️ Quantity selection cancelled\\.", parse_mode="MarkdownV2")
        return

    try:
        qty = int(text)
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
    if not await _check_stock_or_reserved(coupon, qty, message.from_user.id, message):
        return

    total = float(coupon["discounted_price"]) * qty
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(total))
    wallet = await db.get_wallet_balance(message.from_user.id)
    ps = await db.get_payment_settings()

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
        reply_markup=gateway_selection_kb(coupon_id, qty, wallet_balance=wallet, total=total, payment_settings=ps),
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
    if not await _check_stock_or_reserved(coupon, 1, callback.from_user.id, callback):
        return

    total = float(coupon["discounted_price"])
    wallet = await db.get_wallet_balance(callback.from_user.id)
    ps = await db.get_payment_settings()
    from bot.keyboards.coupon_kb import gateway_selection_kb
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(total))
    text = (
        f"💳 *Select Payment Gateway*\n\n"
        f"🏷️ {title}\n"
        f"💰 Amount: *{amt}*\n\n"
        f"Choose your preferred payment method:"
    )
    await safe_edit_or_send(
        callback.message, text,
        reply_markup=gateway_selection_kb(coupon_id, wallet_balance=wallet, total=total, payment_settings=ps),
    )
    await callback.answer()


# ══════════════════════════════════════════════════════════════
# WALLET GATEWAY — Pay from Reward Wallet
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pay_gateway:wallet:"))
@error_handler
async def cb_pay_wallet(callback: types.CallbackQuery):
    """Pay using reward wallet balance."""
    parts = callback.data.split(":")
    coupon_id = int(parts[2])
    qty = int(parts[3]) if len(parts) > 3 else 1
    coupon = await get_coupon_detail(coupon_id)

    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return
    if not await _check_stock_or_reserved(coupon, qty, callback.from_user.id, callback):
        return

    user_id = callback.from_user.id
    amount = float(coupon["discounted_price"]) * qty

    # Ensure user exists in DB before creating order (prevents FK violation)
    await db.upsert_user(user_id, callback.from_user.username, callback.from_user.full_name)

    wallet = await db.get_wallet_balance(user_id)

    if wallet < amount:
        await callback.answer(
            f"⚠️ Insufficient wallet balance! Need ₹{amount:.1f}, have ₹{wallet:.1f}",
            show_alert=True,
        )
        return

    # Deduct wallet balance
    old_balance = wallet
    new_balance = wallet - amount
    await db.update_wallet_balance(user_id, new_balance)

    try:
        await db.add_wallet_transaction(
            user_id, -amount, "purchase",
            bal_before=old_balance, bal_after=new_balance,
            reference=f"coupon_{coupon_id}_qty{qty}",
        )
    except Exception as e:
        logger.warning(f"Wallet transaction log failed (non-critical): {e}")

    # Create order (with stock reservation)
    try:
        order_info = await create_purchase_order(user_id, coupon_id, amount, "wallet", qty)
    except OutOfStockError:
        # Refund wallet — stock was claimed by another user
        await db.update_wallet_balance(user_id, old_balance)
        res = await db.get_reservation_info(coupon_id)
        await db.add_to_waitlist(user_id, coupon_id)
        wait = f" Check back in ~{res['wait_minutes']} min." if res['wait_minutes'] else ""
        await callback.answer(
            f"⚠️ Reserved by another buyer! Wallet refunded.{wait} 🔔 We'll notify you!",
            show_alert=True,
        )
        return
    order_id = order_info["order_id"]
    txn_ref = order_info["txn_ref"]

    # Complete order — delivers codes + marks paid
    success = await complete_order(order_id, txn_ref, user_id, bot=callback.bot)

    if success:
        title = escape_md(coupon["title"])
        amt = escape_md(format_currency(amount))
        bal = escape_md(f"₹{new_balance:.1f}")

        # Use existing success message builder
        success_text = await _build_success_message(order_id, coupon_id, amount)
        success_text += f"\n\n💰 *Wallet Balance:* {bal}"
    else:
        # Refund wallet if order failed
        await db.update_wallet_balance(user_id, old_balance)
        success_text = (
            f"❌ *Order Failed*\n\n"
            f"Your wallet balance has been refunded\\.\n"
            f"Please try again or contact support\\."
        )

    try:
        await callback.message.delete()
    except Exception:
        pass

    from bot.keyboards.main_menu import get_fresh_main_menu_kb
    await callback.message.answer(
        success_text,
        parse_mode="MarkdownV2",
        reply_markup=await get_fresh_main_menu_kb(user_id),
    )
    await callback.answer()
    logger.info(f"Wallet payment: user={user_id}, order={order_id}, amount={amount}, balance_left={new_balance}")

# ══════════════════════════════════════════════════════════════
# COMBO PAYMENT — Partial Wallet + Gateway
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pay_combo:"))
@error_handler
async def cb_pay_combo(callback: types.CallbackQuery, state: FSMContext):
    """Partial wallet deduction + remaining via gateway (Paytm/BharatPe/Razorpay).
    
    Flow: Deduct wallet balance first → create gateway order for remaining amount.
    On gateway payment success, complete the full order.
    On cancel/expire, refund the wallet portion.
    """
    parts = callback.data.split(":")
    gateway = parts[1]       # paytm / bharatpe / razorpay
    coupon_id = int(parts[2])
    qty = int(parts[3]) if len(parts) > 3 else 1
    coupon = await get_coupon_detail(coupon_id)

    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return
    if not await _check_stock_or_reserved(coupon, qty, callback.from_user.id, callback):
        return

    user_id = callback.from_user.id
    total_amount = float(coupon["discounted_price"]) * qty

    # Ensure user exists
    await db.upsert_user(user_id, callback.from_user.username, callback.from_user.full_name)

    wallet = await db.get_wallet_balance(user_id)
    wallet_deduct = min(wallet, total_amount)
    gateway_amount = round(total_amount - wallet_deduct, 2)

    if gateway_amount <= 0:
        # Wallet covers everything — redirect to full wallet payment
        callback.data = f"pay_gateway:wallet:{coupon_id}:{qty}"
        await cb_pay_wallet(callback)
        return

    if wallet_deduct <= 0:
        # No wallet balance — redirect to normal gateway payment
        if gateway == "paytm":
            callback.data = f"pay_gateway:paytm:{coupon_id}:{qty}"
            await cb_pay_paytm(callback)
        elif gateway == "bharatpe":
            callback.data = f"pay_gateway:bharatpe:{coupon_id}:{qty}"
            await cb_pay_bharatpe(callback, state)
        elif gateway == "razorpay":
            callback.data = f"pay_gateway:razorpay:{coupon_id}:{qty}"
            await cb_pay_razorpay(callback)
        return

    # ── Step 1: Deduct wallet portion ──
    old_balance = wallet
    new_balance = wallet - wallet_deduct
    await db.update_wallet_balance(user_id, new_balance)

    try:
        await db.add_wallet_transaction(
            user_id, -wallet_deduct, "purchase",
            bal_before=old_balance, bal_after=new_balance,
            reference=f"combo_coupon_{coupon_id}_qty{qty}",
            description=f"Partial payment: ₹{wallet_deduct:.1f} wallet + ₹{gateway_amount:.1f} {gateway}",
        )
    except Exception as e:
        logger.warning(f"Wallet transaction log failed (non-critical): {e}")

    # ── Step 2: Create order for TOTAL amount but gateway pays only remaining ──
    try:
        order_info = await create_purchase_order(user_id, coupon_id, total_amount, gateway, qty)
    except OutOfStockError:
        # Refund wallet
        await db.update_wallet_balance(user_id, old_balance)
        await callback.answer(
            f"⚠️ Out of stock! Wallet refunded ₹{wallet_deduct:.1f}",
            show_alert=True,
        )
        return

    order_id = order_info["order_id"]
    txn_ref = order_info["txn_ref"]

    # Store combo info so we know to refund wallet on cancel
    pool = await db.get_pool()
    try:
        # Store wallet deduction amount in order metadata
        await pool.execute(
            """UPDATE orders SET payment_method = $2 WHERE order_id = $1""",
            order_id, f"combo_{gateway}"
        )
        # Also update transaction amount to reflect only the gateway portion
        await pool.execute(
            """UPDATE transactions SET amount = $2 WHERE txn_ref = $1""",
            txn_ref, gateway_amount
        )
    except Exception as e:
        logger.warning(f"Combo metadata update non-critical: {e}")

    # ── Step 3: Show gateway-specific QR/link for remaining amount ──
    wallet_esc = escape_md(f"₹{wallet_deduct:.1f}")
    gateway_esc = escape_md(f"₹{gateway_amount:.1f}")

    # Fetch payment settings for gateway names
    ps = await db.get_payment_settings()

    if gateway == "paytm":
        upi_url = await generate_upi_intent_url(gateway_amount, txn_ref, f"Order {order_id}", "paytm")
        bot_name = await db.get_bot_name()
        qr_buf = create_qr_buffer(upi_url, gateway_amount, txn_ref, bot_name=bot_name)
        dyn = await db.get_dynamic_config()
        timeout_min = dyn["payment_timeout_seconds"] // 60
        title = escape_md(coupon["title"])

        paytm_gw = escape_md(ps.get("gateway_paytm_name", "Paytm"))
        caption = (
            f"💳 *COMBO Payment — {paytm_gw}*\n\n"
            f"🏷️ {title}\n"
            f"💰 Total: *{escape_md(format_currency(total_amount))}*\n"
            f"💰 Wallet Deducted: *{wallet_esc}*\n"
            f"💳 Pay via {paytm_gw}: *{gateway_esc}*\n"
            f"🧾 Order: `{escape_md(order_id)}`\n\n"
            f"⏰ Expires in {timeout_min} minutes\n\n"
            f"Scan the QR to pay *{gateway_esc}*\\.\n"
            f"_Wallet ₹{escape_md(str(wallet_deduct))} will be refunded if you cancel\\._"
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

    elif gateway == "bharatpe":
        dyn = await db.get_dynamic_config()
        timeout_min = dyn["payment_timeout_seconds"] // 60
        title = escape_md(coupon["title"])
        bp_upi = ps.get("bharatpe_upi_id", "")

        upi_line = ""
        if bp_upi:
            upi_esc = escape_md(bp_upi)
            upi_line = f"\n📱 UPI ID: `{upi_esc}` _\\(tap to copy\\)_\n"

        bp_gw = escape_md(ps.get("gateway_bharatpe_name", "BharatPe"))
        caption = (
            f"💳 *COMBO Payment — {bp_gw}*\n\n"
            f"🏷️ {title}\n"
            f"💰 Total: *{escape_md(format_currency(total_amount))}*\n"
            f"💰 Wallet Deducted: *{wallet_esc}*\n"
            f"🏦 Pay via {bp_gw}: *{gateway_esc}*\n"
            f"🧾 Order: `{escape_md(order_id)}`\n"
            f"{upi_line}\n"
            f"📱 *Steps:*\n"
            f"1️⃣ Scan the QR with any UPI app\n"
            f"2️⃣ Pay *{gateway_esc}*\n"
            f"3️⃣ Send your *UTR number* here\n\n"
            f"⏰ Expires in {timeout_min} minutes\n\n"
            f"_Wallet ₹{escape_md(str(wallet_deduct))} will be refunded if you cancel\\._"
        )

        try:
            await callback.message.delete()
        except Exception:
            pass

        qr_path = ps.get("bharatpe_qr_path", "")
        if qr_path and os.path.exists(qr_path):
            photo = FSInputFile(qr_path)
        else:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            fallback = os.path.join(project_root, "bharatpe_qr.png")
            if os.path.exists(fallback):
                photo = FSInputFile(fallback)
            else:
                # Refund wallet — can't proceed without QR
                await db.update_wallet_balance(user_id, old_balance)
                await callback.message.answer("⚠️ BharatPe QR not configured\\. Wallet refunded\\.", parse_mode="MarkdownV2")
                return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancel_order:{order_id}")],
        ])
        msg = await callback.message.answer_photo(photo=photo, caption=caption, parse_mode="MarkdownV2", reply_markup=kb)
        await db.update_order_qr_message_id(order_id, msg.message_id)
        await state.set_state(BharatPeStates.waiting_utr)
        await state.update_data(order_id=order_id, coupon_id=coupon_id, amount=gateway_amount)

    elif gateway == "razorpay":
        from bot.payments.razorpay import create_payment_link
        result = await create_payment_link(gateway_amount, order_id, f"Purchase: {coupon['title']}")

        if "error" in result:
            # Refund wallet
            await db.update_wallet_balance(user_id, old_balance)
            await callback.answer(f"❌ Razorpay error. Wallet refunded.", show_alert=True)
            return

        link_url = result["short_url"]
        link_id = result["link_id"]

        try:
            await pool.execute("UPDATE transactions SET utr = $1 WHERE txn_ref = $2", link_id, txn_ref)
        except Exception:
            pass

        dyn = await db.get_dynamic_config()
        timeout_min = dyn["payment_timeout_seconds"] // 60
        title = escape_md(coupon["title"])

        rp_gw = escape_md(ps.get("gateway_razorpay_name", "Razorpay"))
        text = (
            f"💳 *COMBO Payment — {rp_gw}*\n\n"
            f"🏷️ {title}\n"
            f"💰 Total: *{escape_md(format_currency(total_amount))}*\n"
            f"💰 Wallet Deducted: *{wallet_esc}*\n"
            f"💳 Pay via {rp_gw}: *{gateway_esc}*\n"
            f"🧾 Order: `{escape_md(order_id)}`\n\n"
            f"Click Pay Now to pay *{gateway_esc}*\n"
            f"⏰ Expires in {timeout_min} minutes\n\n"
            f"_Wallet ₹{escape_md(str(wallet_deduct))} will be refunded if you cancel\\._"
        )

        try:
            await callback.message.delete()
        except Exception:
            pass

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Pay Now", url=link_url)],
            [InlineKeyboardButton(text="🔄 Check Payment", callback_data=f"check_razorpay:{order_id}:{link_id}")],
            [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancel_order:{order_id}")],
        ])
        await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)

    await callback.answer()
    logger.info(f"Combo payment: user={user_id}, order={order_id}, wallet={wallet_deduct}, gateway={gateway}={gateway_amount}")


# ══════════════════════════════════════════════════════════════
# SKIP WALLET — Pay Full Amount via Gateway
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pay_skip_wallet:"))
@error_handler
async def cb_skip_wallet(callback: types.CallbackQuery):
    """User chose to skip wallet and pay full amount. Show normal gateways."""
    parts = callback.data.split(":")
    coupon_id = int(parts[1])
    qty = int(parts[2]) if len(parts) > 2 else 1

    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    total = float(coupon["discounted_price"]) * qty
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(total))
    ps = await db.get_payment_settings()

    from bot.keyboards.coupon_kb import gateway_selection_kb
    text = (
        f"💳 *Select Payment Gateway*\n\n"
        f"🏷️ {title}\n"
        f"📦 Quantity: *{qty}*\n"
        f"💰 Total: *{amt}*\n\n"
        f"Choose your preferred payment method:"
    )
    # Pass wallet_balance=0 to hide wallet options
    await safe_edit_or_send(
        callback.message, text,
        reply_markup=gateway_selection_kb(coupon_id, qty, wallet_balance=0, total=total, payment_settings=ps),
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
    if not await _check_stock_or_reserved(coupon, qty, callback.from_user.id, callback):
        return

    user_id = callback.from_user.id
    amount = float(coupon["discounted_price"]) * qty

    # Ensure user exists in DB before creating order (prevents FK violation)
    await db.upsert_user(user_id, callback.from_user.username, callback.from_user.full_name)

    # Create order with Paytm gateway (reserves stock atomically)
    try:
        order_info = await create_purchase_order(user_id, coupon_id, amount, "paytm", qty)
    except OutOfStockError:
        res = await db.get_reservation_info(coupon_id)
        await db.add_to_waitlist(callback.from_user.id, coupon_id)
        wait = f" Check back in ~{res['wait_minutes']} min." if res['wait_minutes'] else ""
        await callback.answer(
            f"⚠️ Reserved by another buyer!{wait} 🔔 We'll notify you when available!",
            show_alert=True,
        )
        return
    order_id = order_info["order_id"]
    txn_ref = order_info["txn_ref"]

    # Generate dynamic QR for Paytm
    upi_url = await generate_upi_intent_url(amount, txn_ref, f"Order {order_id}", "paytm")
    bot_name = await db.get_bot_name()
    qr_buf = create_qr_buffer(upi_url, amount, txn_ref, bot_name=bot_name)

    dyn = await db.get_dynamic_config()
    timeout_min = dyn["payment_timeout_seconds"] // 60
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(amount))
    oid = escape_md(order_id)
    ref = escape_md(txn_ref)
    ps = await db.get_payment_settings()
    gw_name = escape_md(ps.get("gateway_paytm_name", "Paytm"))

    caption = (
        f"💳 *Payment Required — {gw_name}*\n\n"
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
    if not await _check_stock_or_reserved(coupon, qty, callback.from_user.id, callback):
        return

    user_id = callback.from_user.id
    amount = float(coupon["discounted_price"]) * qty

    # Ensure user exists in DB before creating order (prevents FK violation)
    await db.upsert_user(user_id, callback.from_user.username, callback.from_user.full_name)

    # Create order with BharatPe gateway (reserves stock atomically)
    try:
        order_info = await create_purchase_order(user_id, coupon_id, amount, "bharatpe", qty)
    except OutOfStockError:
        res = await db.get_reservation_info(coupon_id)
        await db.add_to_waitlist(callback.from_user.id, coupon_id)
        wait = f" Check back in ~{res['wait_minutes']} min." if res['wait_minutes'] else ""
        await callback.answer(
            f"⚠️ Reserved by another buyer!{wait} 🔔 We'll notify you when available!",
            show_alert=True,
        )
        return
    order_id = order_info["order_id"]

    dyn = await db.get_dynamic_config()
    timeout_min = dyn["payment_timeout_seconds"] // 60
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

    bp_gw_name = escape_md(ps.get("gateway_bharatpe_name", "BharatPe"))

    caption = (
        f"💳 *Payment Required — {bp_gw_name}*\n\n"
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
    """User submitted UTR number — verify against BharatPe API.
    
    FIXED: UTR is NOT stored in DB until verification succeeds.
    This allows the user to retry the same UTR if BharatPe API is slow.
    Automatic retry with delay is also implemented.
    """
    import asyncio
    import re

    data = await state.get_data()
    order_id = data.get("order_id")
    coupon_id = data.get("coupon_id")
    amount = data.get("amount")

    if not order_id or not message.text:
        await message.answer("⚠️ Please enter a valid UTR number.")
        return

    utr = message.text.strip()

    # Validate UTR format (alphanumeric only)
    if not re.match(r'^[a-zA-Z0-9]+$', utr):
        # If text contains emoji or starts with /, it's a menu button/command — end session
        if utr.startswith("/") or any(ord(c) > 127 for c in utr):
            await state.clear()
            await message.answer(
                "⚠️ Payment session ended\\. Use the menu to continue\\.",
                parse_mode="MarkdownV2",
            )
            return
        # Otherwise it's a genuine invalid UTR attempt — let them retry
        await message.answer("⚠️ Symbol not allowed\\. UTR must be alphanumeric\\.", parse_mode="MarkdownV2")
        return

    if len(utr) < 6 or len(utr) > 30:
        await message.answer("⚠️ UTR must be 6–30 characters\\.", parse_mode="MarkdownV2")
        return

    # Check order still valid
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        await state.clear()
        await message.answer("⚠️ This order is no longer pending\\. Please create a new order\\.", parse_mode="MarkdownV2")
        return

    # Check if UTR was already used by a DIFFERENT order (prevents cross-order reuse)
    # But allow the SAME order to resubmit the same UTR (retry scenario)
    # IMPORTANT: Only check bharatpe/paytm gateway txns — Razorpay stores link_id in utr column
    # Also check pending/initiated to prevent concurrent submission of same UTR to multiple orders
    pool = await db.get_pool()
    existing = await pool.fetchrow(
        "SELECT order_id, status FROM transactions WHERE utr = $1 AND status IN ('success', 'initiated', 'pending') AND gateway IN ('bharatpe', 'paytm')", utr
    )
    if existing and existing["order_id"] != order_id:
        oid_esc = escape_md(existing["order_id"])
        await message.answer(
            f"🚫 *Already Claimed\\!*\n\n"
            f"This UTR has already been used for order `{oid_esc}`\\.\n"
            f"Each UTR can only be used once\\.\n\n"
            f"_If you think this is a mistake, contact support\\._",
            parse_mode="MarkdownV2",
        )
        return

    # Show "checking" message
    checking_msg = await message.answer(
        "🔄 *Checking your payment\\.\\.\\.*\n\nPlease wait while we verify your UTR\\.\n"
        "_BharatPe may take a moment to process\\._",
        parse_mode="MarkdownV2",
    )

    # DO NOT store UTR in DB yet — only store after successful verification
    # This allows the user to retry the same UTR if BharatPe API is slow

    # Verify UTR against BharatPe API — with automatic retry
    # BharatPe API can take 10-30 seconds to reflect a new payment
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds between retries
    is_paid = False
    details = None

    for attempt in range(1, MAX_RETRIES + 1):
        is_paid, details = await verify_bharatpe_utr(utr, amount)
        if is_paid:
            break
        if attempt < MAX_RETRIES:
            logger.info(f"BharatPe UTR {utr} attempt {attempt}/{MAX_RETRIES} failed, retrying in {RETRY_DELAY}s...")
            try:
                await checking_msg.edit_text(
                    f"🔄 *Checking your payment\\.\\.\\.*\n\n"
                    f"Attempt {attempt}/{MAX_RETRIES} — payment not found yet\\.\n"
                    f"_Retrying in {RETRY_DELAY} seconds\\.\\.\\._",
                    parse_mode="MarkdownV2",
                )
            except Exception:
                pass
            await asyncio.sleep(RETRY_DELAY)

    if is_paid:
        # Payment verified! Clear FSM state
        await state.clear()

        # NOW store UTR in DB (only after verification succeeds)
        txn_ref = utr
        try:
            txn_row = await pool.fetchrow(
                "SELECT txn_ref FROM transactions WHERE order_id = $1 ORDER BY created_at DESC LIMIT 1",
                order_id,
            )
            if txn_row:
                txn_ref = txn_row["txn_ref"]
                await pool.execute(
                    "UPDATE transactions SET utr = $1, raw_response = $2, status = 'success' WHERE txn_ref = $3",
                    utr, json.dumps(details), txn_ref,
                )
        except Exception as e:
            logger.error(f"Non-critical: failed to save UTR/response for {order_id}: {e}")

        # Complete order (reduce stock + deliver coupon)
        from bot.services.order_service import complete_order
        success = await complete_order(order_id, txn_ref, message.from_user.id, bot=message.bot)

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
            from bot.keyboards.main_menu import get_fresh_main_menu_kb
            await message.answer("👇 Use buttons below to continue:", reply_markup=await get_fresh_main_menu_kb(message.from_user.id))

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
        # UTR not found or amount mismatch after all retries
        try:
            await checking_msg.delete()
        except Exception:
            pass

        dyn = await db.get_dynamic_config()
        min_amt = escape_md(format_currency(dyn["bharatpe_min_recharge"]))
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
# RAZORPAY GATEWAY — Payment Link
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pay_gateway:razorpay:"))
@error_handler
async def cb_pay_razorpay(callback: types.CallbackQuery):
    """User selected Razorpay — create payment link and show to user."""
    parts = callback.data.split(":")
    coupon_id = int(parts[2])
    qty = int(parts[3]) if len(parts) > 3 else 1

    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    if not await _check_stock_or_reserved(coupon, qty, callback.from_user.id, callback):
        return

    user_id = callback.from_user.id
    amount = float(coupon["discounted_price"]) * qty

    # Ensure user exists in DB before creating order (prevents FK violation)
    await db.upsert_user(user_id, callback.from_user.username, callback.from_user.full_name)

    # Create order with Razorpay gateway (reserves stock atomically)
    try:
        order_info = await create_purchase_order(user_id, coupon_id, amount, "razorpay", qty)
    except OutOfStockError:
        res = await db.get_reservation_info(coupon_id)
        await db.add_to_waitlist(callback.from_user.id, coupon_id)
        wait = f" Check back in ~{res['wait_minutes']} min." if res['wait_minutes'] else ""
        await callback.answer(
            f"⚠️ Reserved by another buyer!{wait} 🔔 We'll notify you when available!",
            show_alert=True,
        )
        return
    order_id = order_info["order_id"]
    txn_ref = order_info["txn_ref"]

    # Create Razorpay payment link
    from bot.payments.razorpay import create_payment_link
    result = await create_payment_link(amount, order_id, f"Purchase: {coupon['title']}")

    if "error" in result:
        await callback.answer(f"❌ Error: {result['error'][:100]}", show_alert=True)
        return

    link_url = result["short_url"]
    link_id = result["link_id"]

    # Store link_id in the existing transaction record (UPDATE — avoids UNIQUE NOT NULL violation)
    try:
        pool = await db.get_pool()
        await pool.execute(
            "UPDATE transactions SET utr = $1 WHERE txn_ref = $2",
            link_id, txn_ref
        )
    except Exception as e:
        logger.warning(f"Failed to store razorpay link_id: {e}")

    dyn = await db.get_dynamic_config()
    timeout_min = dyn["payment_timeout_seconds"] // 60
    title = escape_md(coupon["title"])
    amt = escape_md(format_currency(amount))
    oid = escape_md(order_id)
    rp_ps = await db.get_payment_settings()
    rp_gw_name = escape_md(rp_ps.get("gateway_razorpay_name", "Razorpay"))

    text = (
        f"💳 *Payment Required — {rp_gw_name}*\n\n"
        f"🏷️ {title}\n"
        f"💰 Amount: *{amt}*\n"
        f"🧾 Order: `{oid}`\n\n"
        f"📱 *Steps:*\n"
        f"1️⃣ Click the payment button below\n"
        f"2️⃣ Complete payment on {rp_gw_name} page\n"
        f"3️⃣ Come back and click 'Check Payment'\n\n"
        f"⏰ Expires in {timeout_min} minutes\n\n"
        f"_After payment, click Check Payment below\\._"
    )

    try:
        await callback.message.delete()
    except Exception:
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pay Now", url=link_url)],
        [InlineKeyboardButton(text="🔄 Check Payment", callback_data=f"check_razorpay:{order_id}:{link_id}")],
        [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancel_order:{order_id}")],
    ])

    await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()

    logger.info(f"Razorpay link sent for user {user_id}, order={order_id}, link={link_id}")


@router.callback_query(F.data.startswith("check_razorpay:"))
@error_handler
async def cb_check_razorpay(callback: types.CallbackQuery):
    """Check Razorpay payment link status."""
    parts = callback.data.split(":")
    order_id = parts[1]
    link_id = parts[2] if len(parts) > 2 else ""

    if not link_id:
        await callback.answer("❌ Payment link not found.", show_alert=True)
        return

    order = await db.get_order(order_id)
    if not order or order["status"] not in ("pending",):
        await callback.answer("This order is no longer pending.", show_alert=True)
        return

    from bot.payments.razorpay import check_payment_link_status
    result = await check_payment_link_status(link_id)

    if result.get("status") == "paid":
        payment_id = result.get("payment_id", "")
        amount = float(order["amount"])
        coupon_id = order["coupon_id"]

        # Record transaction
        pool = await db.get_pool()
        try:
            await pool.execute(
                "UPDATE transactions SET status = 'success', utr = $1 WHERE order_id = $2 AND gateway = 'razorpay'",
                payment_id or link_id, order_id
            )
        except Exception:
            pass

        # Complete the order — fetch txn_ref for Razorpay
        txn_row_rz = await pool.fetchrow(
            "SELECT txn_ref FROM transactions WHERE order_id = $1 ORDER BY created_at DESC LIMIT 1",
            order_id
        )
        rz_txn_ref = txn_row_rz["txn_ref"] if txn_row_rz else payment_id
        success = await complete_order(order_id, rz_txn_ref, callback.from_user.id, bot=callback.bot)

        if success:
            text = await _build_success_message(order_id, coupon_id, amount, payment_id or link_id)
            kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
            await safe_edit_or_send(callback.message, text, reply_markup=kb)
            logger.info(f"Razorpay VERIFIED: order={order_id}, payment_id={payment_id}")
        else:
            await callback.answer("❌ Order completion failed. Contact support.", show_alert=True)

    elif result.get("status") in ("created",):
        await callback.answer("⏳ Payment not received yet. Please complete the payment first.", show_alert=True)
    elif result.get("status") in ("cancelled", "expired"):
        await callback.answer("❌ Payment link expired or cancelled.", show_alert=True)
    else:
        await callback.answer("⏳ Still processing. Try again in a moment.", show_alert=True)


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
        from bot.keyboards.main_menu import get_fresh_main_menu_kb
        await callback.message.answer("👇 Use buttons below to continue:", reply_markup=await get_fresh_main_menu_kb(callback.from_user.id))
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

    # Status is pending — POLL Paytm API with retries
    pool = await db.get_pool()
    txn_row = await pool.fetchrow(
        "SELECT txn_ref, gateway, amount FROM transactions WHERE order_id = $1 ORDER BY created_at DESC LIMIT 1",
        order_id,
    )

    if not txn_row:
        await callback.answer("⚠️ Transaction not found.", show_alert=True)
        return

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

    # Show "checking" status to user
    await callback.answer()
    oid_esc = escape_md(order_id)
    checking_msg = await callback.message.answer(
        f"🔄 *Verifying your payment\\.\\.\\.*\n\n"
        f"📦 Order: `{oid_esc}`\n"
        f"⏳ Checking with payment gateway\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    # Poll up to 3 times with 3-second gaps
    import asyncio
    MAX_ATTEMPTS = 3
    POLL_DELAY = 3  # seconds

    is_paid = False
    details = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await check_upi_status(txn_ref, gateway)

            if response.get("STATUS") != "API_ERROR" and "error" not in response:
                is_paid, details = verify_payment(response, amount, txn_ref, gateway)
                if is_paid:
                    break

                # Check if definitively failed
                from bot.payments.verifier import is_payment_failed
                if is_payment_failed(response):
                    break

            if attempt < MAX_ATTEMPTS:
                # Update checking message with attempt count
                try:
                    await checking_msg.edit_text(
                        f"🔄 *Verifying your payment\\.\\.\\.*\n\n"
                        f"📦 Order: `{oid_esc}`\n"
                        f"⏳ Attempt {attempt}/{MAX_ATTEMPTS} — rechecking in {POLL_DELAY}s\\.\\.\\.",
                        parse_mode="MarkdownV2",
                    )
                except Exception:
                    pass
                await asyncio.sleep(POLL_DELAY)

        except Exception as e:
            logger.error(f"Paytm poll attempt {attempt} failed for {order_id}: {e}")
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(POLL_DELAY)

    # Delete checking message
    try:
        await checking_msg.delete()
    except Exception:
        pass

    if is_paid:
        # Store the Paytm UTR (BANKTXNID) so it can't be reused
        if details and details.get("utr"):
            try:
                await pool.execute(
                    "UPDATE transactions SET utr = $1 WHERE txn_ref = $2",
                    details["utr"], txn_ref,
                )
            except Exception as e:
                logger.warning(f"Could not store Paytm UTR: {e}")

        # Payment received! Complete the order
        from bot.services.order_service import complete_order
        success = await complete_order(order_id, txn_ref, order["user_id"], bot=callback.bot)
        if success:
            paytm_utr = (details.get("utr", "") if details else "") or ""
            text = await _build_success_message(order_id, order["coupon_id"], float(order["amount"]), paytm_utr)

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
            from bot.keyboards.main_menu import get_fresh_main_menu_kb
            await callback.message.answer("👇 Use buttons below to continue:", reply_markup=await get_fresh_main_menu_kb(callback.from_user.id))
            return
    
    # Payment NOT received after all attempts
    amt_esc = escape_md(format_currency(amount))
    await callback.message.answer(
        f"❌ *Payment Not Received*\n\n"
        f"We checked {MAX_ATTEMPTS} times but could not find your payment\\.\n\n"
        f"📦 Order: `{oid_esc}`\n"
        f"💰 Amount: {amt_esc}\n\n"
        f"*Please ensure:*\n"
        f"• You completed the payment for the exact amount\n"
        f"• You paid using the QR code shown above\n"
        f"• Wait a minute and try Check Payment again\n\n"
        f"_If you already paid, please wait 1\\-2 minutes and try again\\._",
        parse_mode="MarkdownV2",
    )


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
                        # Store the Paytm UTR so it can't be reused
                        if details and details.get("utr"):
                            try:
                                await pool.execute(
                                    "UPDATE transactions SET utr = $1 WHERE txn_ref = $2",
                                    details["utr"], txn_ref,
                                )
                            except Exception as e:
                                logger.warning(f"Could not store Paytm UTR: {e}")

                        # Payment was received! Complete the order instead
                        from bot.services.order_service import complete_order
                        success = await complete_order(order_id, txn_ref, order["user_id"], bot=callback.bot)
                        if success:
                            text = await _build_success_message(order_id, order["coupon_id"], float(order["amount"]))

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
    success = await cancel_order(order_id, bot=callback.bot)

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

    for i, o in enumerate(orders):
        num = total_orders - offset - i
        oid = o["order_id"]

        # Pre-joined from query — no extra DB calls!
        coupon_title = o.get("coupon_title") or "Unknown"
        code_count = o.get("code_count", 0) or 0

        amt = f"₹{float(o['amount']):.1f}"
        qty = o.get("quantity", 1) or 1

        created = o["created_at"]
        date_str = created.strftime("%Y-%m-%d %H:%M:%S") if created else ""

        oid_esc = escape_md(oid)
        title_esc = escape_md(coupon_title)
        amt_esc = escape_md(amt)
        date_esc = escape_md(date_str)

        # Source badge
        source = o.get("source", "purchase") or "purchase"
        if source == "referral_reward":
            source_badge = "🏆 *Referral Reward*"
        elif source == "giveaway":
            source_badge = "🎁 *Giveaway Prize*"
        elif source == "free_coupon":
            source_badge = "🆓 *Free Coupon*"
        else:
            source_badge = "🛍️ *Purchase*"

        lines.append(f"\n━━━━ \\#*{num}* ━━━━")
        lines.append(f"{source_badge}")
        lines.append(f"🏷️ {title_esc}")
        lines.append(f"🕐 {date_esc}")
        if source == "purchase":
            lines.append(f"📦 Qty: {qty} • 💰 {amt_esc}")
        else:
            lines.append(f"📦 Qty: {qty} • 🆓 FREE")
        lines.append(f"🆔 `{oid_esc}`")
        if code_count > 0:
            lines.append(f"🔑 {code_count} code\\(s\\) \\— tap to view")
        else:
            lines.append(f"📋 Status: {escape_md(o['status'])}")

        # View Codes button
        if o["status"] in ("delivered", "paid") and code_count > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=f"🔑 #{num} View Codes",
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
    """View coupon codes for a specific order.
    
    Handles large quantities by splitting codes into multiple messages
    of CODES_PER_PAGE each to stay within Telegram's 4096 char limit.
    """
    parts = callback.data.split(":")
    order_id = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 1

    pool = await db.get_pool()
    total_codes = await pool.fetchval(
        "SELECT COUNT(*) FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE", order_id
    )

    if not total_codes:
        await callback.answer("No codes found for this order.", show_alert=True)
        return

    CODES_PER_PAGE = 50
    total_pages = (total_codes + CODES_PER_PAGE - 1) // CODES_PER_PAGE
    page = max(1, min(page, total_pages))  # clamp to valid range
    offset = (page - 1) * CODES_PER_PAGE

    codes = await pool.fetch(
        "SELECT code FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE ORDER BY id LIMIT $2 OFFSET $3",
        order_id, CODES_PER_PAGE, offset
    )

    oid_esc = escape_md(order_id)
    if total_pages > 1:
        lines = [
            f"🔑 *Codes for Order* `{oid_esc}`",
            f"📄 Page {page}/{total_pages} \\(Total: {total_codes} codes\\)\n",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
    else:
        lines = [
            f"🔑 *Codes for Order* `{oid_esc}`\n",
            "━━━━━━━━━━━━━━━━━━━━",
        ]

    for i, c in enumerate(codes, start=offset + 1):
        code_esc = escape_md(c["code"])
        lines.append(f"{i}\\. `{code_esc}`")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"\n_💾 Save these codes\\!_")

    # Build navigation buttons
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"view_codes:{order_id}:{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"view_codes:{order_id}:{page+1}"))

    buttons = []
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="◀️ Back to Orders", callback_data="my_orders")])
    buttons.append([back_button("back_home")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text("\n".join(lines), parse_mode="MarkdownV2", reply_markup=kb)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer("\n".join(lines), parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ══════════════════════════════════════════════════════════════
# WALLET TOP-UP VIA PAYMENT GATEWAY
# ══════════════════════════════════════════════════════════════

async def initiate_topup_payment(message: types.Message, amount: float):
    """Initiate a wallet top-up payment via available gateway.
    
    Called from wallet.py when user enters a custom top-up amount.
    Currently a placeholder — full gateway topup not yet implemented.
    """
    from bot.utils.helpers import escape_md, format_currency

    amt_esc = escape_md(format_currency(amount))
    await message.answer(
        f"💰 *Wallet Top\\-Up*\n\n"
        f"Amount: *{amt_esc}*\n\n"
        f"⚠️ _Direct wallet top\\-up via payment gateway is coming soon\\._\n"
        f"_For now, your wallet gets credited automatically through referral rewards\\._",
        parse_mode="MarkdownV2",
    )


