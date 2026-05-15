"""
DreamX Coupon Bot — Admin Panel Keyboards
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.keyboards.common import back_button


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Coupons", callback_data="admin_coupons"),
            InlineKeyboardButton(text="🎁 Giveaways", callback_data="admin_giveaways")
        ],
        [
            InlineKeyboardButton(text="💳 Payments", callback_data="admin_payments"),
            InlineKeyboardButton(text="🧾 Orders", callback_data="admin_orders")
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="🤝 Referrals", callback_data="admin_referral_settings")
        ],
        [
            InlineKeyboardButton(text="👥 Users", callback_data="admin_users"),
            InlineKeyboardButton(text="📊 Analytics", callback_data="admin_analytics")
        ],
        [InlineKeyboardButton(text="⚙️ Bot Settings", callback_data="admin_bot_settings"),
         InlineKeyboardButton(text="🆘 Support", callback_data="admin_support_settings")],
        [InlineKeyboardButton(text="🔐 Force Join", callback_data="admin_force_join"),
         InlineKeyboardButton(text="📢 Channels", callback_data="admin_channels_settings")],
        [InlineKeyboardButton(text="⚠️ Disclaimer", callback_data="admin_disclaimer_settings"),
         InlineKeyboardButton(text="🚫 Ban Message", callback_data="admin_ban_message")],
        [
            InlineKeyboardButton(text="📋 Logs", callback_data="admin_logs"),
            InlineKeyboardButton(text="🏠 Home", callback_data="back_home")
        ],
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
        [InlineKeyboardButton(text="🔑 Add Codes", callback_data=f"admin_add_codes:{coupon_id}"),
         InlineKeyboardButton(text="📄 Upload File", callback_data=f"admin_upload_codes:{coupon_id}")],
        [InlineKeyboardButton(text="📥 View Codes", callback_data=f"admin_view_codes:{coupon_id}")],
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
        total = g.get("total_codes", 0)
        unclaimed = g.get("unclaimed_codes", 0)
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {g['title']} ({unclaimed}/{total} left)",
                callback_data=f"admin_giveaway_view:{g['id']}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Add New Giveaway", callback_data="admin_giveaway_add")
    ])
    # Disable all button
    if giveaways:
        any_active = any(g["is_active"] for g in giveaways)
        toggle_all_text = "🔴 Disable All Giveaways" if any_active else "🟢 Enable All Giveaways"
        buttons.append([
            InlineKeyboardButton(text=toggle_all_text, callback_data="admin_giveaway_toggle_all")
        ])
    buttons.append([back_button("admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_giveaway_view_kb(giveaway_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """View/edit a specific giveaway."""
    toggle_text = "🔴 Disable" if is_active else "🟢 Enable"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 View Codes", callback_data=f"admin_giveaway_viewcodes:{giveaway_id}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"admin_giveaway_toggle:{giveaway_id}")],
        [InlineKeyboardButton(text="🗑️ Delete Giveaway", callback_data=f"admin_giveaway_del:{giveaway_id}")],
        [back_button("admin_giveaways")],
    ])


def admin_referral_settings_kb(settings: dict) -> InlineKeyboardMarkup:
    """Legacy — the main referral settings keyboard is now built inline in admin.py."""
    is_active = settings["is_active"]
    mode = settings["mode"]
    toggle_text = "🔴 Disable Referrals" if is_active else "🟢 Enable Referrals"
    
    buttons = []
    if mode == "commission":
        buttons.append([InlineKeyboardButton(text="✏️ Edit Commission %", callback_data="admin_ref_edit_commission")])
    elif mode == "wallet_reward":
        buttons.append([InlineKeyboardButton(text="✏️ Edit Reward Amount", callback_data="admin_ref_edit_reward_amount")])
    else:
        buttons.append([
            InlineKeyboardButton(text="✏️ Edit Needed Count", callback_data="admin_ref_edit_needed"),
            InlineKeyboardButton(text="✏️ Edit Reward Code", callback_data="admin_ref_edit_code")
        ])
        
    buttons.append([InlineKeyboardButton(text=toggle_text, callback_data="admin_ref_toggle_active")])
    buttons.append([back_button("admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


