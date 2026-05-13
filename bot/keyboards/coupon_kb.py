"""
DreamX Coupon Bot — Coupon Keyboards
Supports categorized view, pagination, free coupons, and stock status.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.keyboards.common import back_button, refresh_button

ITEMS_PER_PAGE = 8  # Max items before showing pagination


def buying_menu_kb(coupons: list, free_coupon_count: int = 0, page: int = 0) -> InlineKeyboardMarkup:
    """Build the buying menu shown on /start or Buy Vouchers.

    Groups coupons by category, shows individual products with prices/stock,
    adds Free Coupons button at bottom, and paginates if needed.
    """
    buttons = []

    # Group by category
    categories = {}
    uncategorized = []
    for c in coupons:
        cat = c.get("category") or ""
        if cat.strip():
            categories.setdefault(cat, []).append(c)
        else:
            uncategorized.append(c)

    # Build flat item list: categories first, then uncategorized products
    all_items = []

    # Add category headers
    for cat_name, cat_coupons in sorted(categories.items()):
        stock_total = sum(c["stock"] for c in cat_coupons)
        all_items.append({
            "type": "category",
            "name": cat_name,
            "count": len(cat_coupons),
            "stock": stock_total,
        })

    # Add individual products (numbered)
    idx = 1
    for c in uncategorized:
        all_items.append({
            "type": "product",
            "idx": idx,
            "coupon": c,
        })
        idx += 1

    # Also add categorized products individually
    for cat_name, cat_coupons in sorted(categories.items()):
        for c in cat_coupons:
            all_items.append({
                "type": "product",
                "idx": idx,
                "coupon": c,
            })
            idx += 1

    # Pagination
    total_items = len(all_items)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = all_items[start:end]


    for item in page_items:
        if item["type"] == "category":
            buttons.append([
                InlineKeyboardButton(
                    text=f"📂 {item['name']} ({item['count']}) | 📦 {item['stock']}",
                    callback_data=f"cat_view:{item['name']}:0"
                )
            ])
        elif item["type"] == "product":
            c = item["coupon"]
            idx_num = item["idx"]
            stock = c["stock"]

            # Build label matching the reference image style
            orig = c.get("original_price", 0)
            disc = c.get("discounted_price", 0)

            if stock <= 0:
                stock_label = "❌ Out"
                label = f"{idx_num}. {c['title']} | ₹{disc} | {stock_label}"
            else:
                if orig > disc and orig > 0:
                    label = f"{idx_num}. {c['title']} | ₹{disc} | 📦 {stock}"
                else:
                    label = f"{idx_num}. {c['title']} | ₹{disc} | 📦 {stock}"

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


def category_view_kb(cat_name: str, coupons: list, page: int = 0) -> InlineKeyboardMarkup:
    """Show coupons within a specific category."""
    buttons = []

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = coupons[start:end]

    for idx, c in enumerate(page_items, start=start + 1):
        stock = c["stock"]
        disc = c.get("discounted_price", 0)

        if stock <= 0:
            label = f"{idx}. {c['title']} | ₹{disc} | ❌ Out"
            cb = "noop"
        else:
            label = f"{idx}. {c['title']} | ₹{disc} | 📦 {stock}"
            cb = f"coupon_detail:{c['id']}"

        buttons.append([InlineKeyboardButton(text=label, callback_data=cb)])

    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Previous", callback_data=f"cat_view:{cat_name}:{page - 1}"))
    if end < len(coupons):
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"cat_view:{cat_name}:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(text="◀️ Back to Menu", callback_data="browse_coupons")
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
        stock_label = f"📦 {c['stock']}" if c["stock"] > 0 else "❌ Out"
        buttons.append([
            InlineKeyboardButton(
                text=f"{c['title']} | ₹{c['discounted_price']} | {stock_label}",
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
    """Show quantity selection like the reference image."""
    buttons = []
    if in_stock and stock > 0:
        # Quantity options
        qty_options = []
        if stock >= 1:
            qty_options.append((1, price))
        if stock >= 5:
            qty_options.append((5, price * 5))
        if stock >= 10:
            qty_options.append((10, price * 10))

        for qty, total in qty_options:
            if qty == 1:
                label = f"🛍️ 1 Qty • ₹{total:.1f}"
            else:
                label = f"🛍️ {qty} Qty • ₹{total:.1f} [₹{price:.1f}/ea]"
            buttons.append([
                InlineKeyboardButton(text=label, callback_data=f"buy_qty:{coupon_id}:{qty}")
            ])

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


def gateway_selection_kb(coupon_id: int, qty: int = 1) -> InlineKeyboardMarkup:
    """Show payment gateway options after quantity is selected."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pay via Paytm", callback_data=f"pay_gateway:paytm:{coupon_id}:{qty}")],
        [InlineKeyboardButton(text="🏦 Pay via BharatPe", callback_data=f"pay_gateway:bharatpe:{coupon_id}:{qty}")],
        [back_button("browse_coupons")],
    ])


def stock_status_kb() -> InlineKeyboardMarkup:
    """Keyboard for stock status view."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="refresh_stock")],
        [
            InlineKeyboardButton(text="🛒 Buy Menu", callback_data="browse_coupons"),
            InlineKeyboardButton(text="🏠 Back to Home", callback_data="back_home"),
        ],
    ])



