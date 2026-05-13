"""
DreamX Coupon Bot — Main Menu Handler
Handles navigation from the persistent reply keyboard and callback queries.
"""

from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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


# ── /id Command — works in private, group, and channel ────

from aiogram.filters import Command

@router.message(Command("id"))
@error_handler
async def cmd_id(message: types.Message):
    """Show the chat/channel/group ID. Works in private, group, supergroup."""
    chat = message.chat

    if chat.type in ("group", "supergroup"):
        title = escape_md(chat.title or "Unknown Group")
        text = (
            f"👥 *Group Info*\n\n"
            f"📝 Name: *{title}*\n"
            f"🆔 Group ID: `{chat.id}`"
        )
    else:
        # Private chat
        user = message.from_user
        name = escape_md(user.full_name or "Unknown")
        username = f"@{escape_md(user.username)}" if user.username else "Not set"
        text = (
            f"👤 *Your Info*\n\n"
            f"📝 Name: *{name}*\n"
            f"👤 Username: {username}\n"
            f"🆔 User ID: `{user.id}`"
        )

    await message.answer(text, parse_mode="MarkdownV2")


@router.channel_post(Command("id"))
@error_handler
async def cmd_id_channel(message: types.Message):
    """Show channel ID when /id is posted in a channel."""
    chat = message.chat
    title = escape_md(chat.title or "Unknown Channel")
    text = (
        f"📢 *Channel Info*\n\n"
        f"📝 Name: *{title}*\n"
        f"🆔 Channel ID: `{chat.id}`"
    )
    await message.answer(text, parse_mode="MarkdownV2")


# ── Persistent Reply Keyboard Text Handlers ───────────────

@router.message(F.text == "🛍️ Buy Vouchers")
@error_handler
async def text_buy_vouchers(message: types.Message):
    """Route 'Buy Vouchers' button press — show categorized buying menu."""
    from bot.services.coupon_service import list_active_coupons
    from bot.keyboards.coupon_kb import buying_menu_kb
    from bot.database import queries as db

    coupons = await list_active_coupons()
    free_coupons = await db.get_active_free_coupons()
    free_count = len(free_coupons)

    if not coupons and free_count == 0:
        await message.answer(
            "📭 *No coupons available right now\\.*\n\nCheck back later\\!",
            parse_mode="MarkdownV2",
        )
        return

    text = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛍️ *VOUCHER SHOP*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👉 *Select a product below:*"
    )
    await message.answer(
        text,
        parse_mode="MarkdownV2",
        reply_markup=buying_menu_kb(coupons, free_count),
    )


@router.message(F.text == "📦 My Orders")
@error_handler
async def text_my_orders(message: types.Message):
    """Route 'My Orders' button press — show paginated order history."""
    from bot.services.order_service import get_user_order_history, get_user_order_history_count
    from bot.utils.helpers import format_currency
    from bot.database import queries as db

    total_orders = await get_user_order_history_count(message.from_user.id)
    orders = await get_user_order_history(message.from_user.id, 5, 0)

    if not orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
        await message.answer(
            "📦 *My Orders*\n\nNo orders yet\\.",
            parse_mode="MarkdownV2", reply_markup=kb,
        )
        return

    lines = [
        "📦 *ORDER HISTORY*",
        "",
        f"📊 Total: {total_orders} orders",
    ]

    buttons = []
    pool = await db.get_pool()

    for i, o in enumerate(orders):
        num = total_orders - i
        oid = o["order_id"]

        coupon_row = await pool.fetchrow("SELECT title FROM coupons WHERE id = $1", o["coupon_id"])
        coupon_title = coupon_row["title"] if coupon_row else "Unknown"

        code_count = await pool.fetchval(
            "SELECT COUNT(*) FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE", oid
        ) or 0

        amt = f"₹{float(o['amount']):.1f}"
        qty = o.get("quantity", 1) or 1
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

        if o["status"] in ("delivered", "paid") and code_count > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=f"📋 #{num} View Codes",
                    callback_data=f"view_codes:{oid}"
                )
            ])

    text = "\n".join(lines)

    nav_buttons = []
    if total_orders > 5:
        nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data="my_orders:page:2"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([back_button("back_home")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)




@router.message(F.text == "📊 View Stock")
@error_handler
async def text_view_stock(message: types.Message):
    """Route 'View Stock' button press — show attractive stock status (Image 2 style)."""
    from bot.services.coupon_service import list_active_coupons
    from bot.keyboards.coupon_kb import stock_status_kb

    coupons = await list_active_coupons()
    if not coupons:
        await message.answer(
            "📊 *STOCK STATUS*\n\n━━━━━━━━━━━━━━━━━━━━\n\nNo products available\\.",
            parse_mode="MarkdownV2",
        )
        return

    text = _build_stock_status_text(coupons)
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=stock_status_kb())


def _build_stock_status_text(coupons: list) -> str:
    """Build attractive stock status text matching Image 2 reference."""
    lines = ["📊 *STOCK STATUS*\n", "━━━━━━━━━━━━━━━━━━━━\n"]

    total_available = 0
    for idx, c in enumerate(coupons, 1):
        title = escape_md(c["title"])
        stock = c["stock"]
        orig = c.get("original_price", 0)
        disc = c.get("discounted_price", 0)

        total_available += stock

        if stock > 0:
            status_icon = "✅"
        else:
            status_icon = "❌"

        # Price display
        price_line = f"💰 {escape_md(f'₹{disc}')}"
        if orig > disc and orig > 0:
            price_line = f"💰 ~{escape_md(f'₹{orig}')}~ {escape_md(f'₹{disc}')}"

        stock_text = escape_md(f"{stock} available")

        lines.append(
            f"{idx}\\. {status_icon} *{title}*\n"
            f"   {price_line} \\| 📦 {stock_text}\n"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    lines.append(f"📦 *Total Available: {total_available} coupons*")

    return "\n".join(lines)


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
    """Show bot disclaimer — dynamic from admin panel."""
    import json
    from bot.database import queries as db

    settings = await db.get_bot_settings()
    custom_text = settings.get("disclaimer_text") or ""
    buttons_json = settings.get("disclaimer_buttons") or "[]"

    if custom_text:
        # Use admin-set disclaimer
        text = f"⚠️ *Disclaimer*\n\n{escape_md(custom_text)}"
    else:
        # Default disclaimer
        text = (
            "⚠️ *Disclaimer*\n\n"
            "• All coupons are sold as\\-is\\.\n"
            "• Verify details before purchasing\\.\n"
            "• No refunds once a coupon code is delivered\\.\n"
            "• We are not responsible for expired or invalid codes\\.\n"
            "• Contact support for any disputes\\.\n\n"
            "By using this bot, you agree to these terms\\."
        )

    # Parse inline buttons
    try:
        btn_list = json.loads(buttons_json)
    except Exception:
        btn_list = []

    kb = None
    if btn_list:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for b in btn_list:
            try:
                buttons.append([InlineKeyboardButton(text=b["text"], url=b["url"])])
            except Exception:
                pass
        if buttons:
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


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
        f"Stay updated with latest deals \\& offers\\!{support_line}\n\n"
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
        f"📊 Total Orders: *{escape_md(str(stats['total_orders']))}*\n"
        f"💰 Revenue: *{revenue}*\n"
        f"🟢 Paid: {escape_md(str(stats['total_paid']))} \\| 🟡 Pending: {escape_md(str(stats['total_pending']))} \\| ⏰ Expired: {escape_md(str(stats['total_expired']))}"
    )

    await message.answer(
        text, parse_mode="MarkdownV2", reply_markup=admin_panel_kb()
    )


# ── Callback-based Navigation ────────────────────────────

@router.callback_query(F.data == "back_home")
@error_handler
async def cb_back_home(callback: types.CallbackQuery):
    """Back to home — just delete the inline message, DON'T resend welcome.
    The persistent reply keyboard is already there at the bottom."""
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "main_menu")
@error_handler
async def cb_main_menu(callback: types.CallbackQuery):
    """Legacy main_menu callback — redirect to back_home behavior."""
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("buy_page:"))
@error_handler
async def cb_buy_page(callback: types.CallbackQuery):
    """Handle pagination in buying menu."""
    page = int(callback.data.split(":")[1])
    from bot.services.coupon_service import list_active_coupons
    from bot.keyboards.coupon_kb import buying_menu_kb
    from bot.database import queries as db

    coupons = await list_active_coupons()
    free_coupons = await db.get_active_free_coupons()
    free_count = len(free_coupons)

    text = "🛒 *Available Coupons:*"
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=buying_menu_kb(coupons, free_count, page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat_view:"))
@error_handler
async def cb_category_view(callback: types.CallbackQuery):
    """Categories removed — redirect to browse."""
    await callback.answer("Categories have been removed. Showing all coupons.", show_alert=True)
    from bot.handlers.coupons import cb_browse
    callback.data = "browse_coupons"
    await cb_browse(callback)


@router.callback_query(F.data.startswith("coupon_page:"))
@error_handler
async def cb_coupon_page(callback: types.CallbackQuery):
    """Handle pagination in simple coupon list."""
    page = int(callback.data.split(":")[1])
    from bot.services.coupon_service import list_active_coupons
    from bot.keyboards.coupon_kb import coupons_list_kb

    coupons = await list_active_coupons()
    text = "🛒 *Available Coupons*\n\nSelect a coupon to view details:"
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=coupons_list_kb(coupons, page),
    )
    await callback.answer()


@router.callback_query(F.data == "refresh_stock")
@error_handler
async def cb_refresh_stock(callback: types.CallbackQuery):
    """Refresh stock status view."""
    from bot.services.coupon_service import list_active_coupons
    from bot.keyboards.coupon_kb import stock_status_kb

    coupons = await list_active_coupons()
    if not coupons:
        text = "📊 *STOCK STATUS*\n\n━━━━━━━━━━━━━━━━━━━━\n\nNo products available\\."
    else:
        text = _build_stock_status_text(coupons)

    try:
        await callback.message.edit_text(
            text, parse_mode="MarkdownV2", reply_markup=stock_status_kb()
        )
    except Exception:
        pass  # Message not modified (same content)
    await callback.answer("Stock refreshed ✅")


# ── Free Coupon / Giveaway Handlers ──────────────────────

@router.callback_query(F.data == "free_coupons_list")
@error_handler
async def cb_free_coupons_list(callback: types.CallbackQuery):
    """Show list of available free coupons / giveaways."""
    from bot.database import queries as db
    from bot.keyboards.coupon_kb import free_coupons_list_kb

    free_coupons = await db.get_active_free_coupons()
    if not free_coupons:
        await callback.answer("No free coupons available right now.", show_alert=True)
        return

    text = "🎁 *Free Coupons \\& Giveaways*\n\nClaim your free coupons below:"
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=free_coupons_list_kb(free_coupons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("claim_free:"))
@error_handler
async def cb_claim_free_coupon(callback: types.CallbackQuery):
    """User tries to claim a free coupon."""
    from bot.database import queries as db

    fc_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Get giveaway info
    fc = await db.get_free_coupon(fc_id)
    if not fc:
        await callback.answer("This giveaway no longer exists.", show_alert=True)
        return

    if not fc["is_active"]:
        await callback.answer("This giveaway has been disabled.", show_alert=True)
        return

    # Check if already claimed
    already_claimed = await db.has_user_claimed(fc_id, user_id)
    if already_claimed:
        await callback.answer("You've already claimed this coupon! 🎟️", show_alert=True)
        return

    # Check if limit reached
    if fc["max_claims"] > 0 and fc["claimed_count"] >= fc["max_claims"]:
        await callback.answer(
            "🚫 Giveaway ended! All coupons have been claimed.",
            show_alert=True
        )
        return

    # Try to claim
    codes = await db.claim_free_coupon(fc_id, user_id)
    if codes:
        title = escape_md(fc["title"])
        codes_text = "\n".join(f"`{escape_md(c)}`" for c in codes)

        unclaimed = fc.get("unclaimed_codes", 0) - len(codes)
        remaining = ""
        if unclaimed > 0:
            remaining = f"\n📊 {unclaimed} codes remaining"

        text = (
            f"🎉 *Congratulations\\!*\n\n"
            f"You claimed: *{title}*\n\n"
            f"🔑 Your coupon code\\(s\\):\n{codes_text}\n"
            f"{remaining}\n\n"
            f"_Save these codes\\!_"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [back_button("free_coupons_list")],
        ])
        await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
        await callback.answer("Coupon claimed! 🎉")
    else:
        await callback.answer(
            "Could not claim coupon. It may have ended or you already claimed it.",
            show_alert=True
        )


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
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer("🔴 This item is sold out.", show_alert=True)


@router.callback_query(F.data == "wallet_insufficient")
async def cb_wallet_insufficient(callback: types.CallbackQuery):
    await callback.answer(
        "⚠️ Insufficient wallet balance!\nEarn more via referrals or use other payment methods.",
        show_alert=True,
    )
