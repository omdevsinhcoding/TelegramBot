"""
DreamX Coupon Bot — Coupon Browsing & Detail Handlers
"""

from aiogram import Router, types, F

from bot.services.coupon_service import list_active_coupons, get_coupon_detail
from bot.keyboards.coupon_kb import coupons_list_kb, coupon_detail_kb
from bot.keyboards.common import back_button
from bot.utils.helpers import format_currency
from bot.utils.decorators import error_handler

router = Router()


@router.callback_query(F.data == "browse_coupons")
@error_handler
async def cb_browse(callback: types.CallbackQuery):
    coupons = await list_active_coupons()

    if not coupons:
        from aiogram.types import InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("main_menu")]])
        await callback.message.edit_text(
            "📭 *No coupons available right now\\.*\n\nCheck back later\\!",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )
        await callback.answer()
        return

    text = "🛒 *Available Coupons*\n\nSelect a coupon to view details\\:"
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=coupons_list_kb(coupons),
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

    text = (
        f"🏷️ *{coupon['title']}*\n\n"
        f"{coupon['description'] or 'No description'}\n\n"
        f"💰 Original Price: ~₹{coupon['original_price']:.2f}~\n"
        f"🔥 Sale Price: *₹{coupon['discounted_price']:.2f}*\n"
        f"💎 Discount: *{discount_pct}% OFF*\n"
        f"{stock_text}\n"
    )
    # Escape special chars for MarkdownV2
    text = text.replace(".", "\\.").replace("-", "\\-").replace("!", "\\!")

    in_stock = coupon["stock"] > 0
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=coupon_detail_kb(coupon_id, in_stock),
    )
    await callback.answer()
