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
    """Show the main buying menu with categories, products, and free coupons."""

    coupons = await list_active_coupons()
    free_coupons = await db.get_active_free_coupons()
    free_count = len(free_coupons)

    if not coupons and free_count == 0:
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
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛍️ *VOUCHER SHOP*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👉 *Select a product below:*"
    )
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=buying_menu_kb(coupons, free_count),
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
            f"_{escape_md(disclaimer_text[:300])}_\n"
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
