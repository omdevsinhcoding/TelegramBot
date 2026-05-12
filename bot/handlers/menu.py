"""
DreamX Coupon Bot — Main Menu Handler
Handles navigation from the persistent reply keyboard and callback queries.
"""

from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.keyboards.main_menu import main_menu_kb, main_menu_inline_kb
from bot.keyboards.common import back_button
from bot.utils.helpers import escape_md
from bot.utils.decorators import error_handler
from bot.config import Config

router = Router()


# ── FSM State for Recover Coupon by Order ID ──────────────
class RecoverStates(StatesGroup):
    waiting_order_id = State()


# ── Persistent Reply Keyboard Text Handlers ───────────────

@router.message(F.text == "🛍️ Buy Vouchers")
@error_handler
async def text_buy_vouchers(message: types.Message):
    """Route 'Buy Vouchers' button press to coupon browsing."""
    from bot.services.coupon_service import list_active_coupons
    from bot.keyboards.coupon_kb import coupons_list_kb

    coupons = await list_active_coupons()
    if not coupons:
        await message.answer(
            "📭 *No coupons available right now\\.*\n\nCheck back later\\!",
            parse_mode="MarkdownV2",
        )
        return

    text = "🛒 *Available Coupons*\n\nSelect a coupon to view details:"
    await message.answer(
        text,
        parse_mode="MarkdownV2",
        reply_markup=coupons_list_kb(coupons),
    )


@router.message(F.text == "📦 My Orders")
@error_handler
async def text_my_orders(message: types.Message):
    """Route 'My Orders' button press."""
    from bot.services.order_service import get_user_order_history
    from bot.utils.helpers import format_currency

    orders = await get_user_order_history(message.from_user.id, 10)
    if not orders:
        await message.answer(
            "📦 *My Orders*\n\nNo orders yet\\.",
            parse_mode="MarkdownV2",
        )
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
        lines.append(f"{emoji} `{oid}` — {amt} \\({st}\\)")

    text = "\n".join(lines)
    await message.answer(text, parse_mode="MarkdownV2")




@router.message(F.text == "📊 View Stock")
@error_handler
async def text_view_stock(message: types.Message):
    """Route 'View Stock' button press — show stock summary."""
    from bot.services.coupon_service import list_active_coupons

    coupons = await list_active_coupons()
    if not coupons:
        await message.answer(
            "📊 *Stock Summary*\n\nNo products available\\.",
            parse_mode="MarkdownV2",
        )
        return

    lines = ["📊 *Stock Summary*\n"]
    for c in coupons:
        title = escape_md(c["title"])
        stock = c["stock"]
        emoji = "🟢" if stock > 0 else "🔴"
        price = escape_md(f"₹{c['discounted_price']}")
        lines.append(f"{emoji} *{title}* — {price} \\({stock} left\\)")

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")


@router.message(F.text == "🎟️ Recover Coupon")
@error_handler
async def text_recover_coupon(message: types.Message, state: FSMContext):
    """Route 'Recover Coupon' — ask user for order ID to recover their coupon code."""
    await message.answer(
        "🎟️ *Recover Coupon*\n\n"
        "Enter your *Order ID* to recover your coupon code:\n\n"
        "Example: `DX\\-12345678\\-ABCDEF`\n\n"
        "_You can find this in your payment success message\\._",
        parse_mode="MarkdownV2",
    )
    await state.set_state(RecoverStates.waiting_order_id)


@router.message(RecoverStates.waiting_order_id)
@error_handler
async def msg_recover_by_order_id(message: types.Message, state: FSMContext):
    """Look up coupon code by order ID."""
    await state.clear()

    if not message.text:
        await message.answer("⚠️ Please enter a valid Order ID.")
        return

    order_id = message.text.strip()
    from bot.database import queries as db

    # Look up the order
    order = await db.get_order(order_id)
    if not order:
        await message.answer(
            "❌ *Order not found\\.*\n\n"
            "Please check the Order ID and try again\\.",
            parse_mode="MarkdownV2",
        )
        return

    # Verify this order belongs to the requesting user
    if order["user_id"] != message.from_user.id:
        await message.answer(
            "❌ *This order does not belong to you\\.*",
            parse_mode="MarkdownV2",
        )
        return

    # Check order status
    if order["status"] not in ("paid", "delivered"):
        st = escape_md(order["status"])
        await message.answer(
            f"⚠️ *Order status: {st}*\n\n"
            f"Coupon codes are only available for paid/delivered orders\\.",
            parse_mode="MarkdownV2",
        )
        return

    # Look up delivered code
    pool = await db.get_pool()
    code_row = await pool.fetchrow(
        "SELECT cc.code, c.title FROM coupon_codes cc "
        "JOIN coupons c ON cc.coupon_id = c.id "
        "WHERE cc.order_id = $1 AND cc.is_sold = TRUE",
        order_id,
    )

    if code_row:
        title = escape_md(code_row["title"])
        code = escape_md(code_row["code"])
        oid = escape_md(order_id)
        await message.answer(
            f"✅ *Coupon Recovered\\!*\n\n"
            f"📦 Order: `{oid}`\n"
            f"🏷️ Product: *{title}*\n"
            f"🔑 Code: `{code}`\n\n"
            f"_Keep this code safe\\!_",
            parse_mode="MarkdownV2",
        )
    else:
        oid = escape_md(order_id)
        await message.answer(
            f"⚠️ *No coupon code found for order* `{oid}`\\.\n\n"
            f"This may happen if codes were not yet assigned\\.\n"
            f"Please contact support\\.",
            parse_mode="MarkdownV2",
        )


@router.message(F.text == "⚠️ Disclaimer")
@error_handler
async def text_disclaimer(message: types.Message):
    """Show bot disclaimer."""
    text = (
        "⚠️ *Disclaimer*\n\n"
        "• All coupons are sold as\\-is\\.\n"
        "• Verify details before purchasing\\.\n"
        "• No refunds once a coupon code is delivered\\.\n"
        "• We are not responsible for expired or invalid codes\\.\n"
        "• Contact support for any disputes\\.\n\n"
        "By using this bot, you agree to these terms\\."
    )
    await message.answer(text, parse_mode="MarkdownV2")


@router.message(F.text == "📢 Our Channels")
@error_handler
async def text_channels(message: types.Message):
    """Show channel links."""
    support = Config.SUPPORT_USERNAME
    support_line = ""
    if support:
        support_line = f"\n💬 Support: @{escape_md(support)}"
    text = (
        f"📢 *Our Channels*\n\n"
        f"Stay updated with latest deals & offers\\!{support_line}\n\n"
        f"Follow us for exclusive discounts 🔥"
    )
    await message.answer(text, parse_mode="MarkdownV2")


@router.message(F.text == "👑 Admin Panel")
@error_handler
async def text_admin_panel(message: types.Message):
    """Route 'Admin Panel' button press — opens admin panel inline view."""
    if not Config.is_admin(message.from_user.id):
        await message.answer("⛔ Access denied. Admins only.")
        return

    from bot.database import queries as db
    from bot.keyboards.admin_kb import admin_panel_kb
    from bot.utils.helpers import format_currency

    user_count = await db.get_user_count()
    stats = await db.get_sales_stats()

    revenue = escape_md(format_currency(float(stats["total_revenue"])))
    text = (
        f"👑 *Admin Panel*\n\n"
        f"👥 Total Users: *{user_count}*\n"
        f"📊 Total Orders: *{stats['total_orders']}*\n"
        f"💰 Revenue: *{revenue}*\n"
        f"🟢 Paid: {stats['total_paid']} │ 🟡 Pending: {stats['total_pending']} │ ⏰ Expired: {stats['total_expired']}"
    )

    await message.answer(
        text, parse_mode="MarkdownV2", reply_markup=admin_panel_kb()
    )


# ── Callback-based Navigation ────────────────────────────

@router.callback_query(F.data == "main_menu")
@error_handler
async def cb_main_menu(callback: types.CallbackQuery):
    user = callback.from_user
    first = escape_md(user.first_name or "User")
    text = (
        f"🌟 *DreamX Store*\n\n"
        f"Welcome back, *{first}*\\! 👋\n\n"
        f"Use the menu buttons below 👇"
    )
    # Delete old inline message and send a fresh text with reply keyboard
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        text,
        parse_mode="MarkdownV2",
        reply_markup=main_menu_kb(user.id),
    )
    await callback.answer()


@router.callback_query(F.data == "help_menu")
@error_handler
async def cb_help(callback: types.CallbackQuery):
    text = (
        "ℹ️ *Help & Support*\n\n"
        "🛒 *Buy Coupons* — Browse & purchase deals\n"
        "💰 *Direct Payment* — Pay via UPI instantly\n"
        "📦 *My Orders* — Track your purchases\n"
        "🎟️ *Recover Coupon* — Get your code by Order ID\n\n"
        "💬 Need help\\? Contact support\\.\n"
        "🔒 All payments are verified & secure\\."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer("This item is currently unavailable.", show_alert=True)
