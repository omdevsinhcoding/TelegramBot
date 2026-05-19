"""
DreamX Coupon Bot — Coupon Browsing & Detail Handlers
"""

from aiogram import Router, types, F

from bot.services.coupon_service import list_active_coupons, get_coupon_detail
from bot.keyboards.coupon_kb import buying_menu_kb, coupon_detail_kb
from bot.keyboards.common import back_button
from bot.database import queries as db
from bot.utils.helpers import format_currency, escape_md
from bot.utils.decorators import error_handler

router = Router()


@router.callback_query(F.data == "browse_coupons")
@error_handler
async def cb_browse(callback: types.CallbackQuery):
    """Show the shop — categories as clickable folders."""

    categorized = await db.get_active_coupons_categorized()
    free_coupons = await db.get_active_free_coupons()
    free_count = len(free_coupons)

    active_coupons = await db.get_active_coupons()
    has_categories = bool(categorized["categories"])

    if not has_categories:
        categorized = None

    if not active_coupons and free_count == 0:
        from aiogram.types import InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
        await callback.message.edit_text(
            "📭 *No coupons available right now\\.*\n\nCheck back later\\!",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )
        await callback.answer()
        return

    text = (
        "🛍️ *VOUCHER SHOP*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👉 *Select a product:*" if not has_categories else "👉 *Select a category:*"
    )
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=buying_menu_kb(active_coupons, free_count, categorized_data=categorized),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("browse_cat:"))
@error_handler
async def cb_browse_category(callback: types.CallbackQuery):
    """User clicked a category folder — show products inside."""
    cat_id = int(callback.data.split(":")[1])
    cat = await db.get_category(cat_id)
    if not cat:
        await callback.answer("Category not found.", show_alert=True)
        return

    coupons = await db.get_active_coupons_in_category(cat["name"])

    if not coupons:
        # Empty category — show a clean empty state, not an error
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Back to Shop", callback_data="browse_coupons")]
        ])
        await callback.message.edit_text(
            f"📁 *{escape_md(cat['name'])}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📭 *This category is currently empty\\.*\n\n"
            f"_No products available here yet\\._",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )
        await callback.answer()
        return

    from bot.keyboards.coupon_kb import category_coupons_kb
    text = (
        f"📁 *{escape_md(cat['name'])}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👉 *Select a product:*"
    )
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=category_coupons_kb(coupons, cat["name"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat_page:"))
@error_handler
async def cb_category_page(callback: types.CallbackQuery):
    """Handle pagination within a category view."""
    # Use rsplit with maxsplit=1 to safely extract page from the end
    # This handles category names that contain colons (e.g., "A:B")
    raw = callback.data[len("cat_page:"):]  # strip prefix
    last_colon = raw.rfind(":")
    if last_colon == -1:
        await callback.answer("Invalid page data.", show_alert=True)
        return
    cat_name = raw[:last_colon]
    try:
        page = int(raw[last_colon + 1:])
    except ValueError:
        await callback.answer("Invalid page number.", show_alert=True)
        return

    coupons = await db.get_active_coupons_in_category(cat_name)
    if not coupons:
        await callback.answer("No products available.", show_alert=True)
        return

    from bot.keyboards.coupon_kb import category_coupons_kb
    text = (
        f"📁 *{escape_md(cat_name)}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👉 *Select a product:*"
    )
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=category_coupons_kb(coupons, cat_name, page),
    )
    await callback.answer()

@router.callback_query(F.data.startswith("coupon_detail:"))
@error_handler
async def cb_coupon_detail(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)

    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    title = escape_md(coupon["title"])
    sale_price = escape_md(f"₹{coupon['discounted_price']:.1f}")
    stock_num = coupon["stock"]
    stock = escape_md(str(stock_num))

    # Get reservation info
    res = await db.get_reservation_info(coupon_id)

    # Get product description if any
    desc = coupon.get("description") or ""
    desc_block = ""
    if desc:
        desc_block = f"│ 📝 {escape_md(desc)}\n"

    # Stock line with reservation awareness
    if stock_num > 0:
        stock_line = f"│ 📦 Stock: *{stock}* available\n"
    elif res["reserved_qty"] > 0 and res["wait_minutes"] > 0:
        stock_line = (
            f"│ 📦 Stock: *0* available\n"
            f"│ ⏳ _Reserved by another buyer_\n"
            f"│ 🔔 _Available in ~{res['wait_minutes']} min_\n"
        )
    else:
        stock_line = f"│ 📦 Stock: *0* available\n"

    text = (
        f"┌─────────────────────────┐\n"
        f"│ 🛍️ *{title}*\n"
        f"├─────────────────────────┤\n"
        f"│ 💎 Price: *{sale_price}* / unit\n"
        f"{stock_line}"
        f"{desc_block}"
        f"└─────────────────────────┘\n"
    )

    # Check disclaimer mode — if 'description', append disclaimer to product detail
    try:
        settings = await db.get_bot_settings()
        disclaimer_mode = settings.get("disclaimer_mode") or "button"
        disclaimer_text = settings.get("disclaimer_content") or ""
    except Exception:
        disclaimer_mode = "button"
        disclaimer_text = ""

    if disclaimer_mode == "description" and disclaimer_text:
        text += (
            f"\n⚠️ *Disclaimer:*\n"
            f"_{escape_md(disclaimer_text)}_\n"
        )

    # If out of stock but reserved, add waitlist button
    if stock_num <= 0 and res["reserved_qty"] > 0:
        text += f"\n🔔 *Tap below to get notified when available\\!*"
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Notify Me", callback_data=f"waitlist_join:{coupon_id}")],
            [InlineKeyboardButton(text="◀️ Back to Shop", callback_data="browse_coupons")],
        ])
    else:
        text += f"\n🔢 *Select Quantity:*"
        kb = coupon_detail_kb(
            coupon_id, stock_num > 0,
            stock=stock_num,
            price=float(coupon["discounted_price"])
        )

    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("waitlist_join:"))
@error_handler
async def cb_waitlist_join(callback: types.CallbackQuery):
    """User taps 'Notify Me' — add to waitlist for this coupon."""
    coupon_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    await db.add_to_waitlist(user_id, coupon_id)
    
    res = await db.get_reservation_info(coupon_id)
    wait = f"~{res['wait_minutes']} minute(s)" if res["wait_minutes"] > 0 else "soon"
    
    await callback.answer(
        f"🔔 You're on the waitlist!\n\n"
        f"We'll message you when this coupon becomes available.\n"
        f"⏰ Expected: {wait}",
        show_alert=True,
    )
