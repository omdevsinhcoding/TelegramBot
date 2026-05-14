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
    stock = escape_md(str(coupon["stock"]))

    # Get product description if any
    desc = coupon.get("description") or ""
    desc_block = ""
    if desc:
        desc_block = f"│ 📝 {escape_md(desc)}\n"

    text = (
        f"┌─────────────────────────┐\n"
        f"│ 🛍️ *{title}*\n"
        f"├─────────────────────────┤\n"
        f"│ 💎 Price: *{sale_price}* / unit\n"
        f"│ 📦 Stock: *{stock}* available\n"
        f"{desc_block}"
        f"└─────────────────────────┘\n"
    )

    # Check disclaimer mode — if 'description', append disclaimer to product detail
    from bot.database import queries as db
    try:
        settings = await db.get_bot_settings()
        disclaimer_mode = settings.get("disclaimer_mode") or "button"
        disclaimer_text = settings.get("disclaimer_text") or ""
    except Exception:
        disclaimer_mode = "button"
        disclaimer_text = ""

    if disclaimer_mode == "description" and disclaimer_text:
        text += (
            f"\n⚠️ *Disclaimer:*\n"
            f"_{escape_md(disclaimer_text[:300])}_\n"
        )

    text += f"\n🔢 *Select Quantity:*"

    in_stock = coupon["stock"] > 0
    await callback.message.edit_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=coupon_detail_kb(
            coupon_id, in_stock,
            stock=coupon["stock"],
            price=float(coupon["discounted_price"])
        ),
    )
    await callback.answer()

