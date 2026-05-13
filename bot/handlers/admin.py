"""
DreamX Coupon Bot — Admin Panel Handlers
Full admin CRUD for coupons, users, orders, analytics, broadcasts.
"""

from aiogram import Router, types, F
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
from bot.utils.helpers import format_currency, format_datetime, escape_md
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
    add_coupon_codes = State()     # ask for coupon codes directly after price
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

    revenue = escape_md(format_currency(float(stats["total_revenue"])))
    text = (
        f"👑 *Admin Panel*\n\n"
        f"👥 Total Users: *{user_count}*\n"
        f"📊 Total Orders: *{stats['total_orders']}*\n"
        f"💰 Revenue: *{revenue}*\n"
        f"🟢 Paid: {stats['total_paid']} │ "
        f"🟡 Pending: {stats['total_pending']} │ "
        f"⏰ Expired: {stats['total_expired']}"
    )

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
    text = "📦 *Manage Coupons*\n\nSelect a coupon to edit or add a new one:"
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
    title = escape_md(coupon["title"])
    desc = escape_md(coupon["description"] or "N/A")
    orig = escape_md(f"₹{coupon['original_price']}")
    sale = escape_md(f"₹{coupon['discounted_price']}")
    text = (
        f"✏️ *Edit Coupon \\#{coupon_id}*\n\n"
        f"📝 Title: {title}\n"
        f"💬 Desc: {desc}\n"
        f"💰 Original: {orig}\n"
        f"🔥 Sale: {sale}\n"
        f"📦 Stock: {coupon['stock']}\n"
        f"Status: {status}"
    )

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
    await callback.message.edit_text(
        "📝 *Step 1/6* — Enter the *coupon title*:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.add_title)
    await callback.answer()


@router.message(AdminStates.add_title)
@error_handler
async def msg_add_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(title=title)
    logger.info(f"Admin {message.from_user.id} — add coupon title: {title}")
    await message.answer(
        f"✅ Title set: *{escape_md(title)}*\n\n"
        f"📝 *Step 2/6* — Enter a *short description*:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.add_description)


@router.message(AdminStates.add_description)
@error_handler
async def msg_add_desc(message: types.Message, state: FSMContext):
    desc = message.text.strip()
    await state.update_data(description=desc)
    logger.info(f"Admin {message.from_user.id} — add coupon desc: {desc}")
    await message.answer(
        f"✅ Description set\\.\n\n"
        f"💰 *Step 3/6* — Enter the *original price* \\(₹\\):",
        parse_mode="MarkdownV2",
    )
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
    logger.info(f"Admin {message.from_user.id} — original price: ₹{price}")
    await message.answer(
        f"✅ Original price: *{escape_md(format_currency(price))}*\n\n"
        f"🔥 *Step 4/6* — Enter the *discounted price* \\(₹\\):",
        parse_mode="MarkdownV2",
    )
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
    logger.info(f"Admin {message.from_user.id} — discounted price: ₹{price}")
    await message.answer(
        f"✅ Sale price: *{escape_md(format_currency(price))}*\n\n"
        f"🔑 *Step 5/5* — Send *coupon codes* \\(one per line\\)\\.\n\n"
        f"Or type *skip* to add codes later:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.add_coupon_codes)


@router.message(AdminStates.add_coupon_codes)
@error_handler
async def msg_add_coupon_codes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    title = data["title"]
    description = data["description"]
    original_price = data["original_price"]
    discounted_price = data["discounted_price"]

    # Initial stock is 0 until codes are added
    stock = 0

    # Create the coupon first
    coupon_id = await add_coupon(
        title, description, original_price, discounted_price, stock
    )

    # Add coupon codes if provided
    codes_text = message.text.strip()
    codes_added = 0
    if codes_text.lower() != "skip":
        codes = [c.strip() for c in codes_text.split("\n") if c.strip()]
        for code in codes:
            await db.add_coupon_code(coupon_id, code)
        codes_added = len(codes)
        # Update stock to match actual codes
        if codes_added > 0:
            stock = codes_added
            await edit_coupon(coupon_id, stock=stock)
            logger.info(f"Admin {message.from_user.id} — added {codes_added} codes to coupon {coupon_id}")

    await db.add_admin_log(
        message.from_user.id, "add_coupon", "coupon", str(coupon_id),
        f"Title: {title}, Price: ₹{discounted_price}, Stock: {stock}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_coupons")]])

    codes_line = ""
    if codes_added > 0:
        codes_line = f"\n🔑 Codes added: *{codes_added}*"
    else:
        codes_line = "\n🔑 No codes added \\(add later from edit menu\\)"

    await message.answer(
        f"✅ *Coupon \\#{coupon_id} created\\!*\n\n"
        f"📝 Title: *{escape_md(title)}*\n"
        f"💰 Price: *{escape_md(format_currency(discounted_price))}*\n"
        f"📦 Stock: *{stock}*"
        f"{codes_line}",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
    logger.info(f"Coupon #{coupon_id} created by admin {message.from_user.id}: {title}")


# ── Edit Field ────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin_edit_field:"))
@admin_only
@error_handler
async def cb_edit_field(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    coupon_id = int(parts[1])
    field = parts[2]

    field_labels = {"title": "title", "price": "discounted price", "desc": "description"}
    label = field_labels.get(field, field)

    await state.update_data(edit_coupon_id=coupon_id, edit_field=field)
    await callback.message.edit_text(
        f"✏️ Enter the new *{escape_md(label)}*:",
        parse_mode="MarkdownV2",
    )
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
        try:
            update["discounted_price"] = float(value)
        except ValueError:
            await message.answer("⚠️ Enter a valid number.")
            return

    await edit_coupon(coupon_id, **update)
    await db.add_admin_log(
        message.from_user.id, "edit_coupon", "coupon", str(coupon_id),
        f"Field: {field}, Value: {value}"
    )
    logger.info(f"Admin {message.from_user.id} edited coupon {coupon_id}: {field} = {value}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    await message.answer(
        f"✅ Coupon \\#{coupon_id} updated\\! Field: *{escape_md(field)}*",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


# ── Toggle / Delete ───────────────────────────────────────

@router.callback_query(F.data.startswith("admin_coupon_toggle:"))
@admin_only
@error_handler
async def cb_toggle(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    new_status = await toggle_coupon(coupon_id)
    status_text = "enabled 🟢" if new_status else "disabled 🔴"
    logger.info(f"Admin {callback.from_user.id} toggled coupon {coupon_id}: {status_text}")
    await callback.answer(f"Coupon {status_text}", show_alert=True)
    # Refresh edit view
    await cb_admin_coupon_edit(callback)


@router.callback_query(F.data.startswith("admin_coupon_del:"))
@admin_only
@error_handler
async def cb_delete_confirm(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        f"⚠️ Are you sure you want to *delete coupon \\#{coupon_id}*\\?",
        parse_mode="MarkdownV2",
        reply_markup=confirm_delete_kb(coupon_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_coupon_del_confirm:"))
@admin_only
@error_handler
async def cb_delete_exec(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    try:
        pool = await db.get_pool()
        # Delete in FK order: transactions → orders → coupon_codes → coupon
        # 1. Delete transactions that reference orders for this coupon
        await pool.execute(
            "DELETE FROM transactions WHERE order_id IN (SELECT order_id FROM orders WHERE coupon_id = $1)",
            coupon_id,
        )
        # 2. Delete orders referencing this coupon
        await pool.execute("DELETE FROM orders WHERE coupon_id = $1", coupon_id)
        # 3. Delete coupon codes (also has ON DELETE CASCADE but be explicit)
        await pool.execute("DELETE FROM coupon_codes WHERE coupon_id = $1", coupon_id)
        # 4. Delete the coupon itself
        await remove_coupon(coupon_id)
        await db.add_admin_log(
            callback.from_user.id, "delete_coupon", "coupon", str(coupon_id)
        )
        logger.info(f"Admin {callback.from_user.id} deleted coupon {coupon_id}")
        await callback.answer("Coupon deleted.", show_alert=True)
    except Exception as e:
        logger.error(f"Failed to delete coupon {coupon_id}: {e}")
        await callback.answer(f"Delete failed: {str(e)[:100]}", show_alert=True)
        return
    await cb_admin_coupons(callback)


# ── Add Coupon Codes ──────────────────────────────────────

@router.callback_query(F.data.startswith("admin_add_codes:"))
@admin_only
@error_handler
async def cb_add_codes(callback: types.CallbackQuery, state: FSMContext):
    coupon_id = int(callback.data.split(":")[1])
    await state.update_data(codes_coupon_id=coupon_id)
    await callback.message.edit_text(
        "🔑 Send coupon codes, *one per line*:",
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
    pool = await db.get_pool()
    count_row = await pool.fetchrow(
        "SELECT COUNT(*) as cnt FROM coupon_codes WHERE coupon_id = $1 AND is_sold = FALSE",
        coupon_id
    )
    new_stock = count_row["cnt"] if count_row else len(codes)
    await edit_coupon(coupon_id, stock=new_stock)
    await db.add_admin_log(
        message.from_user.id, "add_codes", "coupon", str(coupon_id),
        f"Added {len(codes)} codes, new stock: {new_stock}"
    )
    logger.info(f"Admin {message.from_user.id} added {len(codes)} codes to coupon {coupon_id}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    await message.answer(
        f"✅ Added *{len(codes)}* codes to coupon \\#{coupon_id}\\!\n"
        f"📦 Updated stock: *{new_stock}*",
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
        tid = escape_md(str(u["telegram_id"]))
        uname = escape_md(u["username"] or "N/A")
        bal = escape_md(str(u["wallet_balance"]))
        lines.append(
            f"• `{tid}` — @{uname} │ ₹{bal}{ban}"
        )
    if len(users) > 20:
        remaining = len(users) - 20
        lines.append(f"\n_\\.\\.\\.and {remaining} more_")

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
        oid = escape_md(o["order_id"])
        amt = escape_md(str(o["amount"]))
        st = escape_md(o["status"])
        lines.append(
            f"{emoji} `{oid}` — ₹{amt} \\({st}\\)"
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
        ref = escape_md(t["txn_ref"])
        amt = escape_md(str(t["amount"]))
        st = escape_md(t["status"])
        lines.append(f"• `{ref}` — ₹{amt} \\({st}\\)")
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

    revenue = escape_md(format_currency(float(stats["total_revenue"])))
    text = (
        f"📊 *Sales Analytics*\n\n"
        f"👥 Total Users: *{user_count}*\n"
        f"📦 Total Orders: *{stats['total_orders']}*\n"
        f"🟢 Paid: *{stats['total_paid']}*\n"
        f"🟡 Pending: *{stats['total_pending']}*\n"
        f"⏰ Expired: *{stats['total_expired']}*\n"
        f"💰 Total Revenue: *{revenue}*"
    )

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
    for log in logs:
        action = escape_md(log["action"])
        target = escape_md(log["target_type"] or "")
        tid = escape_md(log["target_id"] or "")
        dt = escape_md(format_datetime(log["created_at"]))
        # Show details if available
        details = ""
        if log.get("details"):
            details = f"\n   📄 {escape_md(str(log['details']))}"
        lines.append(
            f"• {action} │ {target} `{tid}` │ {dt}{details}"
        )
    if not logs:
        lines.append("No logs yet\\.")

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ── Broadcast ─────────────────────────────────────────────

@router.callback_query(F.data == "admin_broadcast")
@admin_only
@error_handler
async def cb_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📢 *Broadcast*\n\nSend the message you want to broadcast to all users:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.broadcast_message)
    await callback.answer()


@router.message(AdminStates.broadcast_message)
@error_handler
async def msg_broadcast(message: types.Message, state: FSMContext):
    await state.clear()

    # Handle None text (e.g. if user sends a sticker/photo instead of text)
    if not message.text:
        await message.answer("⚠️ Please send a text message for broadcast.")
        return

    text = message.text.strip()
    if not text:
        await message.answer("⚠️ Broadcast message cannot be empty.")
        return

    # Use message.bot instead of DI-injected bot parameter
    bot_instance = message.bot

    users = await db.get_all_users()
    total = len(users)
    bid = await db.create_broadcast(message.from_user.id, text, total)
    await db.update_broadcast(bid, 0, 0, "running")
    logger.info(f"Admin {message.from_user.id} started broadcast #{bid} to {total} users")

    # Send progress message
    progress_msg = await message.answer(
        f"📢 Broadcasting to {total} users\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    sent = 0
    failed = 0
    for u in users:
        try:
            await bot_instance.send_message(u["telegram_id"], text)
            sent += 1
        except Exception as e:
            logger.debug(f"Broadcast to {u['telegram_id']} failed: {e}")
            failed += 1

    await db.update_broadcast(bid, sent, failed, "completed")
    await db.add_admin_log(
        message.from_user.id, "broadcast", None, str(bid),
        f"Sent: {sent}, Failed: {failed}, Total: {total}"
    )
    logger.info(f"Broadcast #{bid} completed: sent={sent}, failed={failed}, total={total}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    try:
        await progress_msg.delete()
    except Exception:
        pass
    await message.answer(
        f"📢 *Broadcast Complete*\n\n"
        f"✅ Sent: {sent}\n❌ Failed: {failed}\n📊 Total: {total}",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
