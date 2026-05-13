"""
DreamX Coupon Bot — Coupon Browsing & Detail Handlers
"""

from aiogram import Router, types, F

from bot.services.coupon_service import list_active_coupons, get_coupon_detail
from bot.keyboards.coupon_kb import buying_menu_kb, coupon_detail_kb
from bot.keyboards.common import back_button
from bot.utils.helpers import format_currency, escape_md
from bot.utils.decorators import error_handler

router = Router()


@router.callback_query(F.data == "browse_coupons")
@error_handler
async def cb_browse(callback: types.CallbackQuery):
    """Show the main buying menu with categories, products, and free coupons."""
    from bot.database import queries as db

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

    text = "📁 *Select a Category below:*"
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

    stock_text = f"📦 Stock: {coupon['stock']}" if coupon["stock"] > 0 else "🔴 Out of Stock"
    discount_pct = 0
    if coupon["original_price"] > 0:
        discount_pct = int(
            (1 - coupon["discounted_price"] / coupon["original_price"]) * 100
        )

    title = escape_md(coupon["title"])
    desc = escape_md(coupon["description"] or "No description")
    orig_price = escape_md(f"₹{coupon['original_price']:.2f}")
    sale_price = escape_md(f"₹{coupon['discounted_price']:.2f}")
    cat = escape_md(coupon.get("category") or "General")

    text = (
        f"🏷️ *{title}*\n\n"
        f"{desc}\n\n"
        f"📂 Category: *{cat}*\n"
        f"💰 Original Price: ~{orig_price}~\n"
        f"🔥 Sale Price: *{sale_price}*\n"
        f"💎 Discount: *{discount_pct}% OFF*\n"
        f"{stock_text}\n"
    )

    in_stock = coupon["stock"] > 0
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=coupon_detail_kb(coupon_id, in_stock),
    )
    await callback.answer()
