"""
DreamX Coupon Bot — Admin Panel Keyboards
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.keyboards.common import back_button


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Manage Coupons", callback_data="admin_coupons")],
        [InlineKeyboardButton(text="🎁 Manage Giveaways", callback_data="admin_giveaways")],
        [InlineKeyboardButton(text="👥 View Users", callback_data="admin_users")],
        [InlineKeyboardButton(text="🧾 View Orders", callback_data="admin_orders")],
        [InlineKeyboardButton(text="💳 View Payments", callback_data="admin_payments")],
        [InlineKeyboardButton(text="📊 Sales Analytics", callback_data="admin_analytics")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🤝 Referral Settings", callback_data="admin_referral_settings")],
        [InlineKeyboardButton(text="📋 Admin Logs", callback_data="admin_logs")],
        [InlineKeyboardButton(text="🏠 Back to Home", callback_data="back_home")],
    ])


def admin_coupons_kb(coupons: list) -> InlineKeyboardMarkup:
    buttons = []
    for c in coupons:
        status = "🟢" if c["is_active"] else "🔴"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {c['title']} (Stock: {c['stock']})",
                callback_data=f"admin_coupon_edit:{c['id']}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Add New Coupon", callback_data="admin_coupon_add")
    ])
    buttons.append([back_button("admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_coupon_edit_kb(coupon_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Disable" if is_active else "🟢 Enable"
    toggle_data = f"admin_coupon_toggle:{coupon_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Title", callback_data=f"admin_edit_field:{coupon_id}:title")],
        [InlineKeyboardButton(text="💰 Edit Price", callback_data=f"admin_edit_field:{coupon_id}:price")],
        [InlineKeyboardButton(text="📝 Edit Description", callback_data=f"admin_edit_field:{coupon_id}:desc")],
        [InlineKeyboardButton(text="📂 Edit Category", callback_data=f"admin_edit_field:{coupon_id}:category")],
        [InlineKeyboardButton(text="🔑 Add Codes", callback_data=f"admin_add_codes:{coupon_id}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
        [InlineKeyboardButton(text="🗑️ Delete Coupon", callback_data=f"admin_coupon_del:{coupon_id}")],
        [back_button("admin_coupons")],
    ])


def confirm_delete_kb(coupon_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes, Delete", callback_data=f"admin_coupon_del_confirm:{coupon_id}"),
            InlineKeyboardButton(text="❌ No, Cancel", callback_data=f"admin_coupon_edit:{coupon_id}"),
        ]
    ])


def admin_giveaways_kb(giveaways: list) -> InlineKeyboardMarkup:
    """Admin giveaway management keyboard."""
    buttons = []
    for g in giveaways:
        status = "🟢" if g["is_active"] else "🔴"
        claimed = g["claimed_count"]
        max_c = g["max_claims"] if g["max_claims"] > 0 else "∞"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {g['title']} ({claimed}/{max_c} claimed)",
                callback_data=f"admin_giveaway_view:{g['id']}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Add New Giveaway", callback_data="admin_giveaway_add")
    ])
    buttons.append([back_button("admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_giveaway_view_kb(giveaway_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """View/edit a specific giveaway."""
    toggle_text = "🔴 Disable" if is_active else "🟢 Enable"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=f"admin_giveaway_toggle:{giveaway_id}")],
        [InlineKeyboardButton(text="🗑️ Delete Giveaway", callback_data=f"admin_giveaway_del:{giveaway_id}")],
        [back_button("admin_giveaways")],
    ])
