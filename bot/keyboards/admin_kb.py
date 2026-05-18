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
            InlineKeyboardButton(text="🏷️ Categories", callback_data="admin_categories"),
            InlineKeyboardButton(text="📊 Stock Overview", callback_data="admin_stock_overview")
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
        cat_tag = f" [{c['category']}]" if c.get("category") else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {c['title']}{cat_tag} (Stock: {c['stock']})",
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
        [InlineKeyboardButton(text="🏷️ Set Category", callback_data=f"admin_set_category:{coupon_id}")],
        [InlineKeyboardButton(text="🔑 Add Codes", callback_data=f"admin_add_codes:{coupon_id}"),
         InlineKeyboardButton(text="📄 Upload File", callback_data=f"admin_upload_codes:{coupon_id}")],
        [InlineKeyboardButton(text="📥 View Codes", callback_data=f"admin_view_codes:{coupon_id}"),
         InlineKeyboardButton(text="📤 Extract Codes", callback_data=f"admin_extract_codes:{coupon_id}")],
        [InlineKeyboardButton(text="🧹 Clear All Stock", callback_data=f"admin_clear_stock:{coupon_id}")],
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


def confirm_clear_stock_kb(coupon_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes, Clear All", callback_data=f"admin_clear_stock_confirm:{coupon_id}"),
            InlineKeyboardButton(text="❌ No, Cancel", callback_data=f"admin_coupon_edit:{coupon_id}"),
        ]
    ])


# ── Category Management Keyboards ────────────────────────

def admin_categories_kb(categories: list) -> InlineKeyboardMarkup:
    buttons = []
    for cat in categories:
        vis = "👁️" if cat["is_visible"] else "🔒"
        buttons.append([
            InlineKeyboardButton(
                text=f"{vis} {cat['name']}",
                callback_data=f"admin_cat_view:{cat['id']}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Add Category", callback_data="admin_cat_add")
    ])
    buttons.append([back_button("admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_category_view_kb(cat_id: int, is_visible: bool) -> InlineKeyboardMarkup:
    vis_text = "🔒 Hide" if is_visible else "👁️ Show"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Rename", callback_data=f"admin_cat_rename:{cat_id}")],
        [InlineKeyboardButton(text=vis_text, callback_data=f"admin_cat_toggle_vis:{cat_id}")],
        [InlineKeyboardButton(text="📦 View Coupons", callback_data=f"admin_cat_coupons:{cat_id}")],
        [InlineKeyboardButton(text="🗑️ Delete Category", callback_data=f"admin_cat_delete:{cat_id}")],
        [back_button("admin_categories")],
    ])


def admin_category_select_kb(categories: list, coupon_id: int) -> InlineKeyboardMarkup:
    """Category picker for assigning a coupon to a category."""
    buttons = []
    for cat in categories:
        buttons.append([
            InlineKeyboardButton(
                text=f"🏷️ {cat['name']}",
                callback_data=f"admin_assign_cat:{coupon_id}:{cat['id']}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="❌ Remove Category", callback_data=f"admin_assign_cat:{coupon_id}:0")
    ])
    buttons.append([back_button(f"admin_coupon_edit:{coupon_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_category_select_for_add_kb(categories: list) -> InlineKeyboardMarkup:
    """Category picker during coupon add flow."""
    buttons = []
    for cat in categories:
        buttons.append([
            InlineKeyboardButton(
                text=f"🏷️ {cat['name']}",
                callback_data=f"admin_add_select_cat:{cat['id']}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="⏩ Skip (No Category)", callback_data="admin_add_select_cat:0")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_move_coupon_kb(categories: list, coupon_id: int) -> InlineKeyboardMarkup:
    """Select destination category when moving a coupon."""
    buttons = []
    for cat in categories:
        buttons.append([
            InlineKeyboardButton(
                text=f"📁 {cat['name']}",
                callback_data=f"admin_move_coupon:{coupon_id}:{cat['id']}"
            )
        ])
    buttons.append([back_button(f"admin_coupon_edit:{coupon_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Giveaway Keyboards ───────────────────────────────────

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
