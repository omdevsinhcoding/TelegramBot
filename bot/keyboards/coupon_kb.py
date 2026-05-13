"""
DreamX Coupon Bot — Coupon Keyboards
Supports categorized view, pagination, free coupons, and stock status.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.keyboards.common import back_button, refresh_button

ITEMS_PER_PAGE = 8  # Max items before showing pagination


def buying_menu_kb(coupons: list, free_coupon_count: int = 0, page: int = 0) -> InlineKeyboardMarkup:
    """Build the buying menu shown on /start or Buy Vouchers.

    Shows a flat list of all coupons with prices and stock — no numbering.
    Adds Free Coupons button at bottom, and paginates if needed.
    """
    buttons = []

    # Pagination
    total_items = len(coupons)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = coupons[start:end]

    for c in page_items:
        stock = c["stock"]
        disc = c.get("discounted_price", 0)

        if stock <= 0:
            label = f"🛍️ {c['title']} | ₹{disc} | ❌ Sold Out"
        else:
            label = f"🛍️ {c['title']} | ₹{disc} | 📦 {stock}"

        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"coupon_detail:{c['id']}" if stock > 0 else "noop"
            )
        ])

    # Pagination buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Previous", callback_data=f"buy_page:{page - 1}"))
    if end < total_items:
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"buy_page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    # Free Coupons button
    if free_coupon_count > 0:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎁 Free Coupons ({free_coupon_count})",
                callback_data="free_coupons_list"
            )
        ])

    # Back to Home
    buttons.append([
        InlineKeyboardButton(text="🏠 Back to Home", callback_data="back_home")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def free_coupons_list_kb(free_coupons: list) -> InlineKeyboardMarkup:
    """Show available free coupons / giveaways."""
    buttons = []

    for fc in free_coupons:
        remaining = fc["max_claims"] - fc["claimed_count"] if fc["max_claims"] > 0 else "∞"

        if fc["max_claims"] > 0:
            label = f"🎁 {fc['title']} | 🎯 {remaining} left"
            # If it's a limited giveaway
            if fc["claimed_count"] >= fc["max_claims"]:
                label = f"❌ {fc['title']} | Ended"
        else:
            label = f"🎁 {fc['title']} | Free"

        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"claim_free:{fc['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="◀️ Back to Menu", callback_data="browse_coupons")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def coupons_list_kb(coupons: list, page: int = 0) -> InlineKeyboardMarkup:
    """Simple coupon list (used from callback browse_coupons)."""
    buttons = []

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = coupons[start:end]

    for c in page_items:
        if c["stock"] > 0:
            stock_label = f"📦 {c['stock']}"
        else:
            stock_label = "❌ Sold Out"
        buttons.append([
            InlineKeyboardButton(
                text=f"🛍️ {c['title']} | ₹{c['discounted_price']} | {stock_label}",
                callback_data=f"coupon_detail:{c['id']}" if c["stock"] > 0 else "noop"
            )
        ])

    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Previous", callback_data=f"coupon_page:{page - 1}"))
    if end < len(coupons):
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"coupon_page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([refresh_button("browse_coupons"), back_button("back_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def coupon_detail_kb(coupon_id: int, in_stock: bool, stock: int = 0, price: float = 0) -> InlineKeyboardMarkup:
    """Show quantity selection with attractive compact layout."""
    buttons = []
    if in_stock and stock > 0:
        # First row: 1 Qty (full width)
        if stock >= 1:
            buttons.append([
                InlineKeyboardButton(
                    text=f"🛍️ 1 Qty • ₹{price:.1f}",
                    callback_data=f"buy_qty:{coupon_id}:1"
                )
            ])

        # Second row: 3 & 5 side by side (compact)
        row2 = []
        if stock >= 3:
            row2.append(InlineKeyboardButton(
                text=f"📦 3 Qty • ₹{price*3:.1f}",
                callback_data=f"buy_qty:{coupon_id}:3"
            ))
        if stock >= 5:
            row2.append(InlineKeyboardButton(
                text=f"📦 5 Qty • ₹{price*5:.1f}",
                callback_data=f"buy_qty:{coupon_id}:5"
            ))
        if row2:
            buttons.append(row2)

        # Third row: 10 (full width)
        if stock >= 10:
            buttons.append([
                InlineKeyboardButton(
                    text=f"🎁 10 Qty • ₹{price*10:.1f} [₹{price:.1f}/ea]",
                    callback_data=f"buy_qty:{coupon_id}:10"
                )
            ])

        # Custom Qty
        buttons.append([
            InlineKeyboardButton(text="✏️ Custom Qty", callback_data=f"buy_custom_qty:{coupon_id}")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="🔴 Out of Stock", callback_data="noop")
        ])
    buttons.append([
        InlineKeyboardButton(text="◀️ Back to Shop", callback_data="browse_coupons")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_pending_kb(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Check Payment", callback_data=f"check_pay:{order_id}")],
        [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancel_order:{order_id}")],
    ])


def gateway_selection_kb(coupon_id: int, qty: int = 1, wallet_balance: float = 0.0, total: float = 0.0) -> InlineKeyboardMarkup:
    """Show payment gateway options with reward wallet."""
    buttons = []

    # Reward Wallet button — always visible (shows balance)
    wallet_label = f"💰 Reward Wallet: ₹{wallet_balance:.1f}"
    if wallet_balance >= total and total > 0:
        # Enough balance — make it clickable to pay
        buttons.append([InlineKeyboardButton(
            text=wallet_label,
            callback_data=f"pay_gateway:wallet:{coupon_id}:{qty}"
        )])
    else:
        # Not enough — show balance info with proper callback
        buttons.append([InlineKeyboardButton(
            text=wallet_label,
            callback_data="wallet_insufficient"
        )])

    buttons.append([InlineKeyboardButton(text="✅ Pay via Paytm", callback_data=f"pay_gateway:paytm:{coupon_id}:{qty}")])
    buttons.append([InlineKeyboardButton(text="🏦 Pay via BharatPe", callback_data=f"pay_gateway:bharatpe:{coupon_id}:{qty}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="browse_coupons")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def stock_status_kb() -> InlineKeyboardMarkup:
    """Keyboard for stock status view."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="refresh_stock")],
        [
            InlineKeyboardButton(text="🛒 Buy Menu", callback_data="browse_coupons"),
            InlineKeyboardButton(text="🏠 Back to Home", callback_data="back_home"),
        ],
    ])



