"""
DreamX Coupon Bot — Coupon Keyboards
Supports categorized view, pagination, free coupons, and stock status.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.keyboards.common import back_button, refresh_button

ITEMS_PER_PAGE = 8  # Max items before showing pagination


def buying_menu_kb(coupons: list, free_coupon_count: int = 0, page: int = 0) -> InlineKeyboardMarkup:
    """Build the buying menu shown on /start or Buy Vouchers.

    Groups coupons by category with separator headers.
    Adds Free Coupons button at bottom, and paginates if needed.
    """
    buttons = []

    # Group coupons by category
    from collections import OrderedDict
    grouped = OrderedDict()
    for c in coupons:
        cat = c.get("category") or ""
        grouped.setdefault(cat, []).append(c)

    # Flatten back into an ordered list with category headers
    ordered_items = []  # List of (type, data): ("header", name) or ("coupon", coupon)
    for cat_name, cat_coupons in grouped.items():
        if cat_name:
            ordered_items.append(("header", cat_name))
        for c in cat_coupons:
            ordered_items.append(("coupon", c))

    # Pagination
    # Count only coupons for pagination (headers don't count)
    coupon_items = [x for x in ordered_items if x[0] == "coupon"]
    total_items = len(coupon_items)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE

    # Get items for this page (with headers inserted correctly)
    page_coupon_ids = set(id(x[1]) for x in coupon_items[start:end])
    shown_categories = set()
    for item_type, data in ordered_items:
        if item_type == "header":
            continue
        if item_type == "coupon" and id(data) in page_coupon_ids:
            # Insert header if we haven't shown it yet for this category
            coupon_cat = data.get("category") or ""
            if coupon_cat and coupon_cat not in shown_categories:
                buttons.append([InlineKeyboardButton(
                    text=f"━━ 🏷️ {coupon_cat} ━━",
                    callback_data="noop"
                )])
                shown_categories.add(coupon_cat)

            stock = data["stock"]
            disc = data.get("discounted_price", 0)
            if stock <= 0:
                label = f"🛍️ {data['title']} | ₹{disc} | ❌ Sold Out"
            else:
                label = f"🛍️ {data['title']} | ₹{disc} | 📦 {stock}"

            buttons.append([
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"coupon_detail:{data['id']}" if stock > 0 else "noop"
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


def gateway_selection_kb(coupon_id: int, qty: int = 1, wallet_balance: float = 0.0, total: float = 0.0,
                          payment_settings: dict | None = None) -> InlineKeyboardMarkup:
    """Show payment gateway options — only enabled gateways.
    
    Supports three wallet states:
    1. wallet >= total → Full wallet payment button
    2. wallet > 0 but < total → "Wallet + Gateway" combo buttons (partial wallet)
    3. wallet == 0 → Only gateway buttons
    
    Args:
        payment_settings: dict from db.get_payment_settings() with gateway_*_enabled flags
    """
    buttons = []
    ps = payment_settings or {}

    has_wallet = wallet_balance > 0 and total > 0
    can_full_pay = wallet_balance >= total
    partial_amount = min(wallet_balance, total) if has_wallet else 0
    remaining = total - partial_amount if has_wallet else total

    if can_full_pay:
        # Full wallet payment — enough balance
        wallet_label = f"💰 Pay ₹{total:.0f} from Wallet (Bal: ₹{wallet_balance:.1f})"
        buttons.append([InlineKeyboardButton(
            text=wallet_label,
            callback_data=f"pay_gateway:wallet:{coupon_id}:{qty}"
        )])

    # Only show enabled gateways
    has_gateway = False

    # Get custom gateway names (admin-configurable)
    paytm_name = ps.get("gateway_paytm_name", "Paytm")
    bharatpe_name = ps.get("gateway_bharatpe_name", "BharatPe")
    razorpay_name = ps.get("gateway_razorpay_name", "Razorpay")

    if ps.get("gateway_paytm_enabled", True):
        if has_wallet and not can_full_pay and partial_amount > 0:
            # Combo button: wallet + paytm
            label = f"✅ Wallet ₹{partial_amount:.0f} + {paytm_name} ₹{remaining:.0f}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"pay_combo:paytm:{coupon_id}:{qty}")])
        else:
            buttons.append([InlineKeyboardButton(text=f"✅ Pay via {paytm_name}", callback_data=f"pay_gateway:paytm:{coupon_id}:{qty}")])
        has_gateway = True

    if ps.get("gateway_bharatpe_enabled", True):
        if has_wallet and not can_full_pay and partial_amount > 0:
            label = f"🏦 Wallet ₹{partial_amount:.0f} + {bharatpe_name} ₹{remaining:.0f}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"pay_combo:bharatpe:{coupon_id}:{qty}")])
        else:
            buttons.append([InlineKeyboardButton(text=f"🏦 Pay via {bharatpe_name}", callback_data=f"pay_gateway:bharatpe:{coupon_id}:{qty}")])
        has_gateway = True

    if ps.get("gateway_razorpay_enabled", False):
        if has_wallet and not can_full_pay and partial_amount > 0:
            label = f"💳 Wallet ₹{partial_amount:.0f} + {razorpay_name} ₹{remaining:.0f}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"pay_combo:razorpay:{coupon_id}:{qty}")])
        else:
            buttons.append([InlineKeyboardButton(text=f"💳 Pay via {razorpay_name}", callback_data=f"pay_gateway:razorpay:{coupon_id}:{qty}")])
        has_gateway = True

    # If wallet has partial balance, also show "Pay full via gateway (skip wallet)" option
    if has_wallet and not can_full_pay and partial_amount > 0 and has_gateway:
        buttons.append([InlineKeyboardButton(
            text=f"💸 Skip Wallet — Pay Full ₹{total:.0f}",
            callback_data=f"pay_skip_wallet:{coupon_id}:{qty}"
        )])

    if not has_gateway:
        buttons.append([InlineKeyboardButton(text="⚠️ No payment options available", callback_data="noop")])

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



