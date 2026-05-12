"""
DreamX Coupon Bot — Admin Panel Handlers
Full admin CRUD for coupons, users, orders, analytics, broadcasts.
"""

from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup

from bot.config import Config
from bot.database import queries as db
from bot.services.coupon_service import (
    list_all_coupons, get_coupon_detail, add_coupon,
    edit_coupon, remove_coupon, toggle_coupon,
)
from bot.keyboards.admin_kb import (
    admin_panel_kb, admin_coupons_kb,
    admin_coupon_edit_kb, confirm_delete_kb,
)
from bot.keyboards.common import back_button
from bot.utils.helpers import format_currency, format_datetime
from bot.utils.decorators import admin_only, error_handler
from bot.utils.logger import logger

router = Router()


# ── FSM States ────────────────────────────────────────────

class AdminStates(StatesGroup):
    # Add coupon flow
    add_title = State()
    add_description = State()
    add_original_price = State()
    add_discounted_price = State()
    add_stock = State()
    # Edit fields
    edit_field_value = State()
    # Add codes
    add_codes_input = State()
    # Broadcast
    broadcast_message = State()


# ── Admin Panel Entry ─────────────────────────────────────

@router.callback_query(F.data == "admin_panel")
@admin_only
@error_handler
async def cb_admin_panel(callback: types.CallbackQuery):
    user_count = await db.get_user_count()
    stats = await db.get_sales_stats()

    text = (
        f"👑 *Admin Panel*\n\n"
        f"👥 Total Users: *{user_count}*\n"
        f"📊 Total Orders: *{stats['total_orders']}*\n"
        f"💰 Revenue: *{format_currency(float(stats['total_revenue']))}*\n"
        f"🟢 Paid: {stats['total_paid']} │ 🟡 Pending: {stats['total_pending']} │ ⏰ Expired: {stats['total_expired']}"
    )
    text = text.replace(".", "\\.").replace("-", "\\-").replace("|", "\\|")

    await callback.message.edit_text(
        text, parse_mode="MarkdownV2", reply_markup=admin_panel_kb()
    )
    await callback.answer()


# ── Manage Coupons ────────────────────────────────────────

@router.callback_query(F.data == "admin_coupons")
@admin_only
@error_handler
async def cb_admin_coupons(callback: types.CallbackQuery):
    coupons = await list_all_coupons()
    text = "📦 *Manage Coupons*\n\nSelect a coupon to edit or add a new one\\:"
    await callback.message.edit_text(
        text, parse_mode="MarkdownV2", reply_markup=admin_coupons_kb(coupons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_coupon_edit:"))
@admin_only
@error_handler
async def cb_admin_coupon_edit(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    status = "🟢 Active" if coupon["is_active"] else "🔴 Disabled"
    text = (
        f"✏️ *Edit Coupon #{coupon_id}*\n\n"
        f"📝 Title: {coupon['title']}\n"
        f"💬 Desc: {coupon['description'] or 'N/A'}\n"
        f"💰 Original: ₹{coupon['original_price']}\n"
        f"🔥 Sale: ₹{coupon['discounted_price']}\n"
        f"📦 Stock: {coupon['stock']}\n"
        f"Status: {status}"
    )
    text = text.replace(".", "\\.").replace("-", "\\-").replace("!", "\\!").replace("#", "\\#")

    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=admin_coupon_edit_kb(coupon_id, coupon["is_active"])
    )
    await callback.answer()


# ── Add Coupon Flow ───────────────────────────────────────

@router.callback_query(F.data == "admin_coupon_add")
@admin_only
@error_handler
async def cb_add_coupon_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 Enter the *coupon title*\\:", parse_mode="MarkdownV2")
    await state.set_state(AdminStates.add_title)
    await callback.answer()


@router.message(AdminStates.add_title)
@error_handler
async def msg_add_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("📝 Enter a *short description*\\:", parse_mode="MarkdownV2")
    await state.set_state(AdminStates.add_description)


@router.message(AdminStates.add_description)
@error_handler
async def msg_add_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💰 Enter the *original price* \\(₹\\)\\:", parse_mode="MarkdownV2")
    await state.set_state(AdminStates.add_original_price)


@router.message(AdminStates.add_original_price)
@error_handler
async def msg_add_orig_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Enter a valid number.")
        return
    await state.update_data(original_price=price)
    await message.answer("🔥 Enter the *discounted price* \\(₹\\)\\:", parse_mode="MarkdownV2")
    await state.set_state(AdminStates.add_discounted_price)


@router.message(AdminStates.add_discounted_price)
@error_handler
async def msg_add_disc_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Enter a valid number.")
        return
    await state.update_data(discounted_price=price)
    await message.answer("📦 Enter the *initial stock count*\\:", parse_mode="MarkdownV2")
    await state.set_state(AdminStates.add_stock)


@router.message(AdminStates.add_stock)
@error_handler
async def msg_add_stock(message: types.Message, state: FSMContext):
    try:
        stock = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Enter a valid integer.")
        return

    data = await state.get_data()
    await state.clear()

    coupon_id = await add_coupon(
        data["title"], data["description"],
        data["original_price"], data["discounted_price"], stock
    )
    await db.add_admin_log(
        message.from_user.id, "add_coupon", "coupon", str(coupon_id)
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_coupons")]])
    await message.answer(
        f"✅ Coupon *#{coupon_id}* created successfully\\!",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


# ── Edit Field ────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin_edit_field:"))
@admin_only
@error_handler
async def cb_edit_field(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    coupon_id = int(parts[1])
    field = parts[2]

    field_labels = {"title": "title", "price": "discounted price", "desc": "description", "stock": "stock count"}
    label = field_labels.get(field, field)

    await state.update_data(edit_coupon_id=coupon_id, edit_field=field)
    await callback.message.edit_text(f"✏️ Enter the new *{label}*\\:", parse_mode="MarkdownV2")
    await state.set_state(AdminStates.edit_field_value)
    await callback.answer()


@router.message(AdminStates.edit_field_value)
@error_handler
async def msg_edit_field_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    coupon_id = data["edit_coupon_id"]
    field = data["edit_field"]
    value = message.text.strip()
    await state.clear()

    update = {}
    if field == "title":
        update["title"] = value
    elif field == "desc":
        update["description"] = value
    elif field == "price":
        update["discounted_price"] = float(value)
    elif field == "stock":
        update["stock"] = int(value)

    await edit_coupon(coupon_id, **update)
    await db.add_admin_log(message.from_user.id, "edit_coupon", "coupon", str(coupon_id))

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    await message.answer("✅ Coupon updated\\!", parse_mode="MarkdownV2", reply_markup=kb)


# ── Toggle / Delete ───────────────────────────────────────

@router.callback_query(F.data.startswith("admin_coupon_toggle:"))
@admin_only
@error_handler
async def cb_toggle(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    new_status = await toggle_coupon(coupon_id)
    status_text = "enabled 🟢" if new_status else "disabled 🔴"
    await callback.answer(f"Coupon {status_text}", show_alert=True)
    # Refresh edit view
    await cb_admin_coupon_edit(callback)


@router.callback_query(F.data.startswith("admin_coupon_del:"))
@admin_only
@error_handler
async def cb_delete_confirm(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        f"⚠️ Are you sure you want to *delete coupon #{coupon_id}*\\?",
        parse_mode="MarkdownV2",
        reply_markup=confirm_delete_kb(coupon_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_coupon_del_confirm:"))
@admin_only
@error_handler
async def cb_delete_exec(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    await remove_coupon(coupon_id)
    await db.add_admin_log(callback.from_user.id, "delete_coupon", "coupon", str(coupon_id))
    await callback.answer("Coupon deleted.", show_alert=True)
    await cb_admin_coupons(callback)


# ── Add Coupon Codes ──────────────────────────────────────

@router.callback_query(F.data.startswith("admin_add_codes:"))
@admin_only
@error_handler
async def cb_add_codes(callback: types.CallbackQuery, state: FSMContext):
    coupon_id = int(callback.data.split(":")[1])
    await state.update_data(codes_coupon_id=coupon_id)
    await callback.message.edit_text(
        "🔑 Send coupon codes, one per line\\:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.add_codes_input)
    await callback.answer()


@router.message(AdminStates.add_codes_input)
@error_handler
async def msg_add_codes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    coupon_id = data["codes_coupon_id"]
    await state.clear()

    codes = [c.strip() for c in message.text.strip().split("\n") if c.strip()]
    for code in codes:
        await db.add_coupon_code(coupon_id, code)

    # Update stock to match available codes
    await edit_coupon(coupon_id, stock=len(codes))
    await db.add_admin_log(message.from_user.id, "add_codes", "coupon", str(coupon_id))

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    await message.answer(
        f"✅ Added *{len(codes)}* codes to coupon \\#{coupon_id}\\!",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


# ── View Users ────────────────────────────────────────────

@router.callback_query(F.data == "admin_users")
@admin_only
@error_handler
async def cb_admin_users(callback: types.CallbackQuery):
    users = await db.get_all_users()
    lines = [f"👥 *Users* \\({len(users)} total\\)\n"]
    for u in users[:20]:
        ban = " 🚫" if u["is_banned"] else ""
        lines.append(
            f"• `{u['telegram_id']}` — @{u['username'] or 'N/A'} "
            f"\\| ₹{u['wallet_balance']}{ban}"
        )
    if len(users) > 20:
        lines.append(f"\n_\\.\\.\\.and {len(users) - 20} more_")

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ── View Orders ───────────────────────────────────────────

@router.callback_query(F.data == "admin_orders")
@admin_only
@error_handler
async def cb_admin_orders(callback: types.CallbackQuery):
    orders = await db.get_all_orders(20)
    status_emoji = {
        "pending": "🟡", "paid": "🟢", "delivered": "✅",
        "expired": "⏰", "cancelled": "❌", "refunded": "🔄"
    }
    lines = [f"🧾 *Recent Orders* \\({len(orders)}\\)\n"]
    for o in orders:
        emoji = status_emoji.get(o["status"], "❓")
        lines.append(
            f"{emoji} `{o['order_id']}` — ₹{o['amount']} \\({o['status']}\\)"
        )

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ── View Payments ─────────────────────────────────────────

@router.callback_query(F.data == "admin_payments")
@admin_only
@error_handler
async def cb_admin_payments(callback: types.CallbackQuery):
    txns = await db.get_pending_transactions()
    lines = [f"💳 *Pending Payments* \\({len(txns)}\\)\n"]
    for t in txns:
        lines.append(f"• `{t['txn_ref']}` — ₹{t['amount']} \\({t['status']}\\)")
    if not txns:
        lines.append("No pending payments\\.")

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ── Analytics ─────────────────────────────────────────────

@router.callback_query(F.data == "admin_analytics")
@admin_only
@error_handler
async def cb_admin_analytics(callback: types.CallbackQuery):
    stats = await db.get_sales_stats()
    user_count = await db.get_user_count()

    text = (
        f"📊 *Sales Analytics*\n\n"
        f"👥 Total Users: *{user_count}*\n"
        f"📦 Total Orders: *{stats['total_orders']}*\n"
        f"🟢 Paid: *{stats['total_paid']}*\n"
        f"🟡 Pending: *{stats['total_pending']}*\n"
        f"⏰ Expired: *{stats['total_expired']}*\n"
        f"💰 Total Revenue: *{format_currency(float(stats['total_revenue']))}*\n"
    )
    text = text.replace(".", "\\.").replace("-", "\\-")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ── Admin Logs ────────────────────────────────────────────

@router.callback_query(F.data == "admin_logs")
@admin_only
@error_handler
async def cb_admin_logs(callback: types.CallbackQuery):
    logs = await db.get_admin_logs(15)
    lines = ["📋 *Admin Logs*\n"]
    for l in logs:
        lines.append(
            f"• {l['action']} \\| {l['target_type'] or ''} "
            f"`{l['target_id'] or ''}` \\| {format_datetime(l['created_at'])}"
        )
    if not logs:
        lines.append("No logs yet\\.")

    text = "\n".join(lines)
    text = text.replace(".", "\\.").replace("-", "\\-")
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ── Broadcast ─────────────────────────────────────────────

@router.callback_query(F.data == "admin_broadcast")
@admin_only
@error_handler
async def cb_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📢 *Broadcast*\n\nSend the message you want to broadcast to all users\\:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.broadcast_message)
    await callback.answer()


@router.message(AdminStates.broadcast_message)
@error_handler
async def msg_broadcast(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    text = message.text.strip()
    users = await db.get_all_users()
    total = len(users)
    bid = await db.create_broadcast(message.from_user.id, text, total)
    await db.update_broadcast(bid, 0, 0, "running")

    sent = 0
    failed = 0
    for u in users:
        try:
            await bot.send_message(u["telegram_id"], text)
            sent += 1
        except Exception:
            failed += 1

    await db.update_broadcast(bid, sent, failed, "completed")
    await db.add_admin_log(message.from_user.id, "broadcast", None, str(bid))

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    await message.answer(
        f"📢 *Broadcast Complete*\n\n"
        f"✅ Sent: {sent}\n❌ Failed: {failed}\n📊 Total: {total}",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
