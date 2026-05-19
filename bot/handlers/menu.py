"""
DreamX Coupon Bot — Main Menu Handler
Handles navigation from the persistent reply keyboard and callback queries.
"""

from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.keyboards.main_menu import main_menu_kb, main_menu_inline_kb, get_fresh_main_menu_kb
from bot.keyboards.common import back_button
from bot.database import queries as db
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
    user = message.from_user

    user_id = user.id if user else "Unknown"
    user_name = escape_md(user.first_name or "Unknown") if user else "Unknown"

    if chat.type == "private":
        username = f"@{escape_md(user.username)}" if user and user.username else "Not set"
        text = (
            f"🆔 *Your Telegram ID*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: *{user_name}*\n"
            f"👤 Username: {username}\n"
            f"🔑 ID: `{user_id}`"
        )
    elif chat.type in ("group", "supergroup"):
        title = escape_md(chat.title or "Unknown Group")
        text = (
            f"🆔 *Telegram IDs*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Group: *{title}*\n"
            f"🔑 Group ID: `{chat.id}`\n\n"
            f"👤 Your Name: *{user_name}*\n"
            f"🔑 Your ID: `{user_id}`"
        )
    elif chat.type == "channel":
        ch_name = escape_md(chat.title or "Unknown Channel")
        text = (
            f"🆔 *Telegram IDs*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📢 Channel: *{ch_name}*\n"
            f"🔑 Channel ID: `{chat.id}`"
        )
    else:
        text = f"🔑 Chat ID: `{chat.id}`\n👤 Your ID: `{user_id}`"

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
    """Route 'Buy Vouchers' button press — show category folders."""
    from bot.keyboards.coupon_kb import buying_menu_kb

    categorized = await db.get_active_coupons_categorized()
    free_coupons = await db.get_active_free_coupons()
    free_count = len(free_coupons)

    active_coupons = await db.get_active_coupons()
    has_categories = bool(categorized["categories"])

    if not has_categories:
        categorized = None

    if not active_coupons and free_count == 0:
        await message.answer(
            "📭 *No coupons available right now\\.*\n\nCheck back later\\!",
            parse_mode="MarkdownV2",
        )
        return

    text = (
        "🛍️ *VOUCHER SHOP*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👉 *Select a product:*" if not has_categories else "👉 *Select a category:*"
    )
    await message.answer(
        text,
        parse_mode="MarkdownV2",
        reply_markup=buying_menu_kb(active_coupons, free_count, categorized_data=categorized),
    )


@router.message(F.text == "📦 My Orders")
@error_handler
async def text_my_orders(message: types.Message):
    """Route 'My Orders' button press — show paginated order history."""
    from bot.services.order_service import get_user_order_history, get_user_order_history_count
    from bot.utils.helpers import format_currency

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

    for i, o in enumerate(orders):
        num = total_orders - i
        oid = o["order_id"]

        # Pre-joined from query — zero extra DB calls!
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

        if o["status"] in ("delivered", "paid") and code_count > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=f"🔑 #{num} View Codes",
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
    """Build attractive stock status text grouped by category."""
    lines = ["📊 *STOCK STATUS*\n", "━━━━━━━━━━━━━━━━━━━━\n"]

    total_available = 0

    # Group by category
    from collections import OrderedDict
    grouped = OrderedDict()
    for c in coupons:
        cat = c.get("category") or ""
        grouped.setdefault(cat, []).append(c)

    idx = 1
    for cat_name, cat_coupons in grouped.items():
        if cat_name:
            lines.append(f"🏷️ *{escape_md(cat_name)}*\n")

        for c in cat_coupons:
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
            idx += 1

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
    # Guard: menu button or command pressed during input
    text = (message.text or "").strip()
    if text.startswith("/") or any(ord(c) > 127 for c in text):
        await state.clear()
        return

    await state.clear()

    if not text:
        await message.answer("⚠️ Please enter a valid Order ID.")
        return

    order_id = text

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


@router.message(F.text == "🆘 Support")
@error_handler
async def text_support(message: types.Message):
    """Show support info — dynamic from admin panel."""
    import json

    settings = await db.get_bot_settings()
    custom_text = settings.get("disclaimer_text") or ""
    buttons_json = settings.get("disclaimer_buttons") or "[]"

    if custom_text:
        # Use admin-set support info
        text = f"🆘 *Support*\n\n{escape_md(custom_text)}"
    else:
        # Default support message
        text = (
            "🆘 *Support*\n\n"
            "Need help? We're here for you\\!\n\n"
            "📩 Contact us for any issues:\n"
            "• Payment problems\n"
            "• Missing coupons\n"
            "• Account questions\n\n"
            "_Use the buttons below to reach out\\._"
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


@router.message(F.text == "⚠️ Disclaimer")
@error_handler
async def text_disclaimer(message: types.Message):
    """Show disclaimer text — shown when disclaimer_mode is 'button'."""

    settings = await db.get_bot_settings()
    disclaimer_text = settings.get("disclaimer_content") or ""

    if disclaimer_text:
        text = (
            f"⚠️ *Disclaimer*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"_{escape_md(disclaimer_text)}_"
        )
    else:
        text = (
            "⚠️ *Disclaimer*\n\n"
            "_No disclaimer has been set by the admin\\._"
        )

    await message.answer(text, parse_mode="MarkdownV2")


@router.message(F.text == "📢 Our Channels")
@error_handler
async def text_channels(message: types.Message):
    """Show channel links — dynamic from admin panel."""
    import json
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    try:
        settings = await db.get_bot_settings()
        channels_json = settings.get("channels_list") or "[]"
    except Exception:
        channels_json = "[]"

    try:
        channels = json.loads(channels_json)
    except Exception:
        channels = []

    text = (
        "📢 *Our Channels*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔔 Stay updated with latest deals\\!\n"
        "📌 Follow us for exclusive offers\n\n"
    )

    if channels:
        text += "👇 *Join our channels below:*"
        buttons = []
        for ch in channels:
            name = ch.get("name", "Channel")
            url = ch.get("url", "")
            if url:
                buttons.append([InlineKeyboardButton(text=f"📢 {name}", url=url)])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    else:
        text += "_No channels configured yet\\._"
        kb = None

    await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


# ── Inline button callbacks (from /start welcome) ────────

@router.callback_query(F.data == "show_support")
@error_handler
async def cb_show_support(callback: types.CallbackQuery):
    """Show support info from inline button."""
    import json

    settings = await db.get_bot_settings()
    custom_text = settings.get("disclaimer_text") or ""
    buttons_json = settings.get("disclaimer_buttons") or "[]"

    if custom_text:
        text = f"🆘 *Support*\n\n{escape_md(custom_text)}"
    else:
        text = (
            "🆘 *Support*\n\n"
            "Need help? We're here for you\\!\n\n"
            "📩 Contact us for any issues:\n"
            "• Payment problems\n"
            "• Missing coupons\n"
            "• Account questions\n\n"
            "_Use the buttons below to reach out\\._"
        )

    try:
        btn_list = json.loads(buttons_json)
    except Exception:
        btn_list = []

    buttons = []
    for b in btn_list:
        try:
            buttons.append([InlineKeyboardButton(text=b["text"], url=b["url"])])
        except Exception:
            pass

    buttons.append([back_button("back_home")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "show_channels")
@error_handler
async def cb_show_channels(callback: types.CallbackQuery):
    """Show channels info from inline button."""
    import json

    try:
        settings = await db.get_bot_settings()
        channels_json = settings.get("channels_list") or "[]"
    except Exception:
        channels_json = "[]"

    try:
        channels = json.loads(channels_json)
    except Exception:
        channels = []

    text = (
        "📢 *Our Channels*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔔 Stay updated with latest deals\\!\n"
        "📌 Follow us for exclusive offers\n\n"
    )

    buttons = []
    if channels:
        text += "👇 *Join our channels below:*"
        for ch in channels:
            name = ch.get("name", "Channel")
            url = ch.get("url", "")
            if url:
                buttons.append([InlineKeyboardButton(text=f"📢 {name}", url=url)])
    else:
        text += "_No channels configured yet\\._"

    buttons.append([back_button("back_home")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "referral_menu")
@error_handler
async def cb_referral_menu(callback: types.CallbackQuery):
    """Show referral info from inline button — same as static '🎁 Refer & Earn'."""
    settings = await db.get_referral_settings()

    if not settings or not settings.get("is_active"):
        await callback.answer("🎁 Referral program is currently inactive.", show_alert=True)
        return

    user_id = callback.from_user.id
    ref_code = await db.get_or_create_referral_code(user_id)
    ref_count = await db.get_referral_count(user_id)
    earnings = await db.get_user_referral_earnings(user_id)
    wallet = await db.get_user_wallet(user_id)

    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={ref_code}"

    mode = settings["mode"]
    # Dynamic earning badge for header
    earn_badge = ""

    if mode == "code_reward":
        rewards = await db.get_referral_rewards()
        active_rewards = [r for r in rewards if r["is_active"]]
        if active_rewards:
            how_it_works = (
                f"✨ *How it works:*\n"
                f"1️⃣ Share your link\n"
                f"2️⃣ Friends join the bot\n"
                f"3️⃣ Reach milestones to claim free coupons\\!\n\n"
                f"🎁 *Available Rewards:*\n"
            )
            for r in active_rewards:
                title_esc = escape_md(r["title"])
                needed = r["referrals_needed"]
                if ref_count >= needed:
                    how_it_works += f"✅ {title_esc} — {needed} refs \\(unlocked\\!\\)\n"
                else:
                    how_it_works += f"🔒 {title_esc} — {needed} refs\n"
            earn_badge = f"🎁 *{len(active_rewards)} rewards available\\!*"
        else:
            how_it_works = (
                f"✨ *How it works:*\n"
                f"1️⃣ Share your link\n"
                f"2️⃣ Friends join the bot\n"
                f"3️⃣ Earn free coupons\\!\n"
            )
    elif mode == "wallet_reward":
        reward_amt = float(settings.get("reward_amount", 10.0) or 10.0)
        how_it_works = (
            f"✨ *How it works:*\n"
            f"1️⃣ Share your link\n"
            f"2️⃣ Friends join the bot\n"
            f"3️⃣ Get 💵 *₹{escape_md(str(reward_amt))}* per referral\\!\n\n"
            f"💰 Reward goes straight to your wallet\\!\n"
        )
        earn_badge = f"💵 *Earn up to ₹{escape_md(str(reward_amt))} per referral\\!*"
    else:  # commission
        pct = settings["commission_percent"]
        how_it_works = (
            f"✨ *How it works:*\n"
            f"1️⃣ Share your link\n"
            f"2️⃣ Friends join \\& buy\n"
            f"3️⃣ Earn 💰 *{escape_md(str(pct))}%* commission\n"
        )
        earn_badge = f"💰 *Earn {escape_md(str(pct))}% commission per sale\\!*"

    from bot.utils.helpers import format_currency
    link_esc = escape_md(link)
    ref_code_esc = escape_md(ref_code)
    earnings_esc = escape_md(format_currency(earnings))
    wallet_esc = escape_md(format_currency(wallet))

    # Get pending credits for code_reward mode
    pending_credits = 0
    if mode == "code_reward":
        pending_credits = await db.get_referral_pending_credits(user_id)

    text = (
        f"🤝 *REFER \\& EARN*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )
    if earn_badge:
        text += f"\n{earn_badge}\n"
    text += (
        f"\n{how_it_works}\n"
        f"🔗 *Your Referral Link:*\n"
        f"`{link_esc}`\n\n"
        f"🔑 *Code:* `{ref_code_esc}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Your Stats*\n\n"
        f"👥 Referrals: *{ref_count}*\n"
    )
    if mode == "code_reward":
        text += f"🎟️ Pending Credits: *{pending_credits}*\n"
    text += (
        f"💸 Earnings: *{earnings_esc}*\n"
        f"💰 Wallet: *{wallet_esc}*\n\n"
        f"💡 _Wallet balance can be used to purchase coupons\\!_ 💳\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    buttons = []

    # 🎁 Claim Rewards — show when user has pending credits (even if stock = 0)
    if mode == "code_reward" and pending_credits > 0:
        buttons.append([InlineKeyboardButton(
            text=f"🎁 Claim Rewards ({pending_credits} credits)",
            callback_data="ref_claim_rewards"
        )])

    # Allow manual entry if no referrer
    referrer = await db.get_referrer_of(user_id)
    if not referrer:
        buttons.append([InlineKeyboardButton(text="🔗 Enter Referral Code", callback_data="ref_enter_code")])

    buttons.append([InlineKeyboardButton(text="📋 My Referral History", callback_data="ref_history")])
    buttons.append([back_button("back_home")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.message(F.text == "👑 Admin Panel")
@error_handler
async def text_admin_panel(message: types.Message):
    """Route 'Admin Panel' button press — opens admin panel inline view."""
    if not Config.is_admin(message.from_user.id):
        await message.answer("⛔ Access denied. Admins only.")
        return

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
    """Back to home — edit current message with welcome + inline buttons."""

    user = callback.from_user
    first = escape_md(user.first_name or "there")

    try:
        total_stock = await db.get_total_stock()
    except Exception:
        total_stock = 0

    # Get settings
    try:
        settings = await db.get_bot_settings()
        support_text = settings.get("disclaimer_text") or ""
        ch_inline = settings.get("channels_inline_enabled")
        if ch_inline is None: ch_inline = True
    except Exception:
        support_text = ""
        ch_inline = True

    support_line = ""
    if support_text:
        first_line = support_text.split("\n")[0][:60]
        support_line = f"🆘 Support: _{escape_md(first_line)}_\n"

    # Get wallet/reward balance
    try:
        wallet_bal = await db.get_wallet_balance(user.id)
    except Exception:
        wallet_bal = 0.0

    wallet_line = f"💰 Reward Balance: *₹{escape_md(f'{wallet_bal:.2f}')}*\n"

    welcome = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 *WELCOME, {first}\\!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚀 *Instant Delivery System*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ Verified Vouchers\n"
        f"⚡ Auto Payment Verification\n"
        f"📦 Available Stock: *{total_stock}* coupons\n"
        f"{wallet_line}"
        f"{support_line}"
        f"━━━━━━━━━━━━━━━━━━"
    )

    inline_rows = [
        [
            InlineKeyboardButton(text="🛍️ Stock Status", callback_data="stock_status"),
            InlineKeyboardButton(text="🛒 Buy Now", callback_data="browse_coupons"),
        ],
        [
            InlineKeyboardButton(text="📁 My Orders", callback_data="my_orders"),
            InlineKeyboardButton(text="🆘 Support", callback_data="show_support"),
        ],
    ]
    bottom_row = [InlineKeyboardButton(text="🤝 Refer & Earn", callback_data="referral_menu")]
    if ch_inline:
        bottom_row.append(InlineKeyboardButton(text="📢 Join Channels", callback_data="show_channels"))
    inline_rows.append(bottom_row)

    inline_kb = InlineKeyboardMarkup(inline_keyboard=inline_rows)

    try:
        await callback.message.edit_text(welcome, parse_mode="MarkdownV2", reply_markup=inline_kb)
    except Exception:
        # If can't edit (e.g., photo message), delete and send new
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(welcome, parse_mode="MarkdownV2", reply_markup=inline_kb)

    await callback.answer()


@router.callback_query(F.data == "main_menu")
@error_handler
async def cb_main_menu(callback: types.CallbackQuery):
    """Legacy main_menu callback — same as back_home."""
    await cb_back_home(callback)


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
    
    categorized = await db.get_active_coupons_categorized()
    has_categories = bool(categorized["categories"])
    if not has_categories:
        categorized = None

    text = (
        "🛍️ *VOUCHER SHOP*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👉 *Select a product:*" if not has_categories else "👉 *Select a category:*"
    )
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=buying_menu_kb(coupons, free_count, page, categorized_data=categorized),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat_view:"))
@error_handler
async def cb_category_view(callback: types.CallbackQuery):
    """Legacy cat_view: redirect to new browse_cat: handler."""
    cat_id = callback.data.split(":")[1]
    from bot.handlers.coupons import cb_browse_category
    callback.data = f"browse_cat:{cat_id}"
    await cb_browse_category(callback)


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


@router.callback_query(F.data == "stock_status")
@error_handler
async def cb_stock_status(callback: types.CallbackQuery):
    """Show stock status from inline button."""
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
        await callback.message.answer(
            text, parse_mode="MarkdownV2", reply_markup=stock_status_kb()
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

    # Ensure user is registered in DB (prevents FK violation in free_coupon_claims)
    await db.upsert_user(
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.full_name,
    )

    # Try to claim
    codes = await db.claim_free_coupon(fc_id, user_id)
    if codes:
        title = escape_md(fc["title"])
        codes_text = "\n".join(f"   `{escape_md(c)}`" for c in codes)

        unclaimed = fc.get("unclaimed_codes", 0) - len(codes)
        remaining = ""
        if unclaimed > 0:
            remaining = f"\n📊 _{unclaimed} codes remaining_"

        # Create a giveaway order so it appears in Order History
        from bot.utils.helpers import generate_order_id
        order_id = generate_order_id()
        oid_esc = ""
        try:
            # Use coupon_id=0 placeholder for free coupons (they use free_coupon_codes table)
            # We need a valid coupon_id for FK — try to find one, else skip
            pool = await db.get_pool()
            # Use a dummy coupon_id — create a lightweight order
            await pool.execute("""
                INSERT INTO orders (order_id, user_id, coupon_id, amount, quantity, status, source, paid_at, expires_at)
                VALUES ($1, $2, (SELECT id FROM coupons LIMIT 1), 0, $3, 'delivered', 'giveaway', NOW(), NOW() + interval '1 year')
            """, order_id, user_id, len(codes))

            # Link codes: store them in coupon_codes for this order so View Codes works
            for c in codes:
                try:
                    await pool.execute(
                        "INSERT INTO coupon_codes (coupon_id, code, is_sold, sold_to, order_id, sold_at) "
                        "VALUES ((SELECT id FROM coupons LIMIT 1), $1, TRUE, $2, $3, NOW())",
                        c, user_id, order_id
                    )
                except Exception:
                    pass

            oid_esc = escape_md(order_id)
        except Exception as e:
            from bot.utils.logger import logger
            logger.warning(f"Failed to create giveaway order (non-critical): {e}")

        # Track promotional loss for giveaway
        try:
            # Estimate value: use discounted price if linked to a coupon, else 0
            estimated_value = 0
            giveaway_admin = fc.get("created_by")
            await db.record_promotional_loss(
                loss_type="giveaway",
                amount=estimated_value,
                admin_id=giveaway_admin,
                user_id=user_id,
                reference=f"giveaway_{fc_id}_claim",
                details={
                    "giveaway_id": fc_id,
                    "giveaway_title": fc["title"],
                    "codes_count": len(codes),
                    "codes": codes[:5],  # Store up to 5 codes for reference
                }
            )
        except Exception:
            pass

        order_line = ""
        if oid_esc:
            order_line = f"📦 Order ID: `{oid_esc}`\n\n"

        text = (
            f"🎊🎉 *YOU WON\\!* 🎉🎊\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎁 *GIVEAWAY REWARD\\!*\n\n"
            f"🏷️ Prize: *{title}*\n\n"
            f"🔑 *Your Code\\(s\\):*\n{codes_text}\n"
            f"{remaining}\n\n"
            f"{order_line}"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 _Saved to your 📦 Order History\\!_\n"
            f"_View your codes anytime from My Orders\\._\n\n"
            f"🌟 _Share with friends for more wins\\!_ 🚀"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [back_button("free_coupons_list")],
        ])
        await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
        await callback.answer("🎉 You won! Check your codes!")
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


@router.callback_query(F.data == "check_join_status")
@error_handler
async def cb_check_join_status_fallback(callback: types.CallbackQuery):
    """Fallback handler for check_join_status when force channel is disabled.

    The middleware normally handles this callback, but if force_channel is removed
    while a user still has the old 'Join Channel' prompt, this prevents a hanging button.
    """
    await callback.answer("✅ You're all set! You can use the bot.", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
