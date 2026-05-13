"""
DreamX Coupon Bot — Admin Panel Handlers
Full admin CRUD for coupons, users, orders, analytics, broadcasts.
"""

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import Config
from bot.database import queries as db
from bot.services.coupon_service import (
    list_all_coupons, get_coupon_detail, add_coupon,
    edit_coupon, remove_coupon, toggle_coupon,
)
from bot.keyboards.admin_kb import (
    admin_panel_kb, admin_coupons_kb,
    admin_coupon_edit_kb, confirm_delete_kb,
    admin_giveaways_kb, admin_giveaway_view_kb,
    admin_bot_settings_kb
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
    upload_codes_file = State()
    # Broadcast
    broadcast_message = State()
    broadcast_buttons = State()
    # Giveaway flow
    giveaway_title = State()
    giveaway_code = State()
    giveaway_max_claims = State()
    giveaway_add_codes = State()
    # Bot Settings
    force_channel_input = State()
    # Referral
    ref_commission_input = State()
    ref_reward_count_input = State()  # for setting referrals_needed on a coupon reward
    # Payment settings
    payment_field_input = State()
    payment_qr_upload = State()
    # User management
    user_search_input = State()
    user_change_referrer = State()
    user_wallet_edit = State()
    # Disclaimer
    disclaimer_text_input = State()
    disclaimer_buttons_input = State()


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
        f"📊 Total Orders: *{escape_md(str(stats['total_orders']))}*\n"
        f"💰 Revenue: *{revenue}*\n"
        f"🟢 Paid: {escape_md(str(stats['total_paid']))} \\| "
        f"🟡 Pending: {escape_md(str(stats['total_pending']))} \\| "
        f"⏰ Expired: {escape_md(str(stats['total_expired']))}"
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
        f"📦 Stock: {escape_md(str(coupon['stock']))}\n"
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
        "🔑 Send coupon codes, *one per line*\\.\n\n"
        "_Or use 📄 Upload File button for bulk upload\\._",
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


# ── Upload Codes File ─────────────────────────────────────

@router.callback_query(F.data.startswith("admin_upload_codes:"))
@admin_only
@error_handler
async def cb_upload_codes(callback: types.CallbackQuery, state: FSMContext):
    coupon_id = int(callback.data.split(":")[1])
    await state.update_data(upload_codes_coupon_id=coupon_id)
    await state.set_state(AdminStates.upload_codes_file)
    await callback.message.edit_text(
        "📄 *Upload Codes File*\n\n"
        "Send a *\\.txt* file with one code per line\\.\n"
        "The bot will extract all codes and add them to stock\\.",
        parse_mode="MarkdownV2",
    )
    await callback.answer()


@router.message(AdminStates.upload_codes_file, F.document)
@error_handler
async def msg_upload_codes_file(message: types.Message, state: FSMContext):
    import io
    data = await state.get_data()
    coupon_id = data["upload_codes_coupon_id"]
    await state.clear()

    doc = message.document
    if not doc.file_name.endswith(".txt"):
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer("⚠️ Please send a *.txt* file only.", reply_markup=kb)
        return

    # Download file content
    file = await message.bot.get_file(doc.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    
    # Read and parse codes
    if isinstance(file_bytes, io.BytesIO):
        content = file_bytes.read().decode("utf-8", errors="ignore")
    else:
        content = file_bytes.decode("utf-8", errors="ignore")
    
    codes = [c.strip() for c in content.split("\n") if c.strip()]
    
    if not codes:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer("⚠️ No codes found in the file.", reply_markup=kb)
        return

    # Add codes to database
    for code in codes:
        await db.add_coupon_code(coupon_id, code)

    # Update stock
    pool = await db.get_pool()
    count_row = await pool.fetchrow(
        "SELECT COUNT(*) as cnt FROM coupon_codes WHERE coupon_id = $1 AND is_sold = FALSE",
        coupon_id
    )
    new_stock = count_row["cnt"] if count_row else len(codes)
    await edit_coupon(coupon_id, stock=new_stock)
    await db.add_admin_log(
        message.from_user.id, "upload_codes", "coupon", str(coupon_id),
        f"Uploaded {len(codes)} codes from file, new stock: {new_stock}"
    )
    logger.info(f"Admin {message.from_user.id} uploaded {len(codes)} codes from file to coupon {coupon_id}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    await message.answer(
        f"✅ Uploaded *{len(codes)}* codes from file\\!\n"
        f"📦 Updated stock: *{new_stock}*",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


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
    await state.clear()
    text = (
        "📢 *Broadcast*\n\n"
        "Send me what you want to broadcast:\n\n"
        "📝 *Text* — Just type a message\n"
        "📸 *Photo* — Send an image \\(with optional caption\\)\n"
        "📎 *File* — Send any document\n\n"
        "_You can add inline buttons in the next step_"
    )
    await callback.message.edit_text(text, parse_mode="MarkdownV2")
    await state.set_state(AdminStates.broadcast_message)
    await callback.answer()


@router.message(AdminStates.broadcast_message)
@error_handler
async def msg_broadcast_content(message: types.Message, state: FSMContext):
    """Receive broadcast content (text, photo, or document)."""
    bc_data = {}

    if message.photo:
        bc_data["type"] = "photo"
        bc_data["file_id"] = message.photo[-1].file_id
        bc_data["caption"] = message.caption or ""
    elif message.document:
        bc_data["type"] = "document"
        bc_data["file_id"] = message.document.file_id
        bc_data["caption"] = message.caption or ""
    elif message.video:
        bc_data["type"] = "video"
        bc_data["file_id"] = message.video.file_id
        bc_data["caption"] = message.caption or ""
    elif message.text:
        bc_data["type"] = "text"
        bc_data["text"] = message.text.strip()
    else:
        await message.answer("⚠️ Unsupported content type. Send text, photo, or file.")
        return

    await state.update_data(bc_data=bc_data)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Send Now (No Buttons)", callback_data="bc_send_now")],
        [InlineKeyboardButton(text="➕ Add Inline Buttons", callback_data="bc_add_buttons")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")],
    ])
    await message.answer(
        "✅ Content received\\!\n\n"
        "Do you want to add inline buttons to this broadcast?",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


@router.callback_query(F.data == "bc_add_buttons")
@admin_only
@error_handler
async def cb_bc_add_buttons(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "➕ *Add Inline Buttons*\n\n"
        "Send buttons in this format \\(one per line\\):\n"
        "`Button Text \\| https://link\\.com`\n\n"
        "Example:\n"
        "`Join Channel \\| https://t\\.me/channel`\n"
        "`Visit Website \\| https://example\\.com`\n\n"
        "_Send them now:_",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.broadcast_buttons)
    await callback.answer()


@router.message(AdminStates.broadcast_buttons)
@error_handler
async def msg_broadcast_buttons(message: types.Message, state: FSMContext):
    """Parse button definitions and store them."""
    if not message.text:
        await message.answer("⚠️ Please send button definitions as text.")
        return

    buttons_data = []
    for line in message.text.strip().splitlines():
        line = line.strip()
        if "|" in line:
            parts = line.split("|", 1)
            btn_text = parts[0].strip()
            btn_url = parts[1].strip()
            if btn_text and btn_url:
                buttons_data.append({"text": btn_text, "url": btn_url})

    if not buttons_data:
        await message.answer(
            "⚠️ No valid buttons found\\. Use format: `Button Text \\| URL`",
            parse_mode="MarkdownV2",
        )
        return

    await state.update_data(bc_buttons=buttons_data)

    preview = "\n".join(f"• {b['text']} → {b['url']}" for b in buttons_data)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Send Now", callback_data="bc_send_now")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")],
    ])
    await message.answer(
        f"✅ {len(buttons_data)} button(s) added:\n\n{preview}\n\nReady to send?",
        reply_markup=kb,
    )


@router.callback_query(F.data == "bc_send_now")
@admin_only
@error_handler
async def cb_bc_send_now(callback: types.CallbackQuery, state: FSMContext):
    """Execute the broadcast to all users."""
    data = await state.get_data()
    await state.clear()

    bc_data = data.get("bc_data")
    if not bc_data:
        await callback.answer("No broadcast content found.", show_alert=True)
        return

    bc_buttons = data.get("bc_buttons", [])

    # Build inline keyboard from buttons
    reply_markup = None
    if bc_buttons:
        kb_buttons = []
        for b in bc_buttons:
            kb_buttons.append([InlineKeyboardButton(text=b["text"], url=b["url"])])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    bot_instance = callback.message.bot
    users = await db.get_all_users()
    total = len(users)

    bc_text = bc_data.get("text") or bc_data.get("caption") or "(media)"
    bid = await db.create_broadcast(callback.from_user.id, bc_text[:200], total)
    await db.update_broadcast(bid, 0, 0, "running")
    logger.info(f"Admin {callback.from_user.id} started broadcast #{bid} to {total} users")

    progress_msg = await callback.message.edit_text(
        f"📢 Broadcasting to {total} users\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    sent = 0
    failed = 0
    msg_type = bc_data["type"]

    import asyncio
    for u in users:
        try:
            uid = u["telegram_id"]
            if msg_type == "text":
                await bot_instance.send_message(uid, bc_data["text"], reply_markup=reply_markup)
            elif msg_type == "photo":
                await bot_instance.send_photo(
                    uid, bc_data["file_id"],
                    caption=bc_data.get("caption"), reply_markup=reply_markup
                )
            elif msg_type == "document":
                await bot_instance.send_document(
                    uid, bc_data["file_id"],
                    caption=bc_data.get("caption"), reply_markup=reply_markup
                )
            elif msg_type == "video":
                await bot_instance.send_video(
                    uid, bc_data["file_id"],
                    caption=bc_data.get("caption"), reply_markup=reply_markup
                )
            sent += 1
        except Exception as e:
            logger.debug(f"Broadcast to {u['telegram_id']} failed: {e}")
            failed += 1

        # Rate limit: small delay every 20 messages
        if (sent + failed) % 20 == 0:
            await asyncio.sleep(1)

    await db.update_broadcast(bid, sent, failed, "completed")
    await db.add_admin_log(
        callback.from_user.id, "broadcast", None, str(bid),
        f"Type: {msg_type}, Sent: {sent}, Failed: {failed}, Total: {total}"
    )
    logger.info(f"Broadcast #{bid} completed: sent={sent}, failed={failed}, total={total}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    try:
        await progress_msg.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"📢 *Broadcast Complete*\n\n"
        f"📊 Type: {escape_md(msg_type)}\n"
        f"✅ Sent: {sent}\n❌ Failed: {failed}\n📊 Total: {total}",
        parse_mode="MarkdownV2", reply_markup=kb,
    )








# ── Giveaway Management (Multi-Code) ─────────────────────

@router.callback_query(F.data == "admin_giveaways")
@admin_only
@error_handler
async def cb_admin_giveaways(callback: types.CallbackQuery):
    giveaways = await db.get_all_free_coupons()
    text = "🎁 *Manage Giveaways*\n\nSelect a giveaway or add new:"
    await callback.message.edit_text(
        text, parse_mode="MarkdownV2", reply_markup=admin_giveaways_kb(giveaways)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_giveaway_view:"))
@admin_only
@error_handler
async def cb_admin_giveaway_view(callback: types.CallbackQuery):
    gid = int(callback.data.split(":")[1])
    g = await db.get_free_coupon(gid)
    if not g:
        await callback.answer("Giveaway not found.", show_alert=True)
        return

    status = "🟢 Active" if g["is_active"] else "🔴 Disabled"
    title = escape_md(g["title"])
    total = g.get("total_codes", 0)
    unclaimed = g.get("unclaimed_codes", 0)
    claimed = total - unclaimed
    cpu = g.get("codes_per_user", 1)

    text = (
        f"🎁 *Giveaway \\#{gid}*\n\n"
        f"📝 Title: {title}\n"
        f"📦 Total Codes: {total}\n"
        f"✅ Claimed: {claimed}\n"
        f"📭 Unclaimed: {unclaimed}\n"
        f"👤 Codes/User: {cpu}\n"
        f"👥 Users Claimed: {g['claimed_count']}\n"
        f"Status: {status}"
    )

    kb = admin_giveaway_view_kb(gid, g["is_active"])
    # Add reclaim button if there are unclaimed codes
    if unclaimed > 0:
        from aiogram.types import InlineKeyboardButton
        kb.inline_keyboard.insert(-1, [
            InlineKeyboardButton(
                text=f"📥 Reclaim {unclaimed} Codes",
                callback_data=f"admin_giveaway_reclaim:{gid}"
            )
        ])
        kb.inline_keyboard.insert(-1, [
            InlineKeyboardButton(
                text="📄 Add More Codes",
                callback_data=f"admin_giveaway_addcodes:{gid}"
            )
        ])

    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_giveaway_add")
@admin_only
@error_handler
async def cb_giveaway_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎁 *Step 1/3* — Enter the *giveaway title*:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.giveaway_title)
    await callback.answer()


@router.message(AdminStates.giveaway_title)
@error_handler
async def msg_giveaway_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(giveaway_title=title)
    await message.answer(
        f"✅ Title: *{escape_md(title)}*\n\n"
        f"🔢 *Step 2/3* — How many codes *per user*?\n"
        f"\\(e\\.g\\. `1` = 1 code per user, `3` = 3 codes per user\\)",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.giveaway_code)


@router.message(AdminStates.giveaway_code)
@error_handler
async def msg_giveaway_codes_per_user(message: types.Message, state: FSMContext):
    try:
        cpu = int(message.text.strip())
        if cpu < 1:
            cpu = 1
    except ValueError:
        await message.answer("⚠️ Enter a valid number (minimum 1).")
        return
    await state.update_data(codes_per_user=cpu)
    await message.answer(
        f"✅ Codes per user: *{cpu}*\n\n"
        f"📄 *Step 3/3* — Now send the coupon codes:\n\n"
        f"• *Paste codes* \\(one per line\\)\n"
        f"• OR *upload a \\.txt file* with codes\n\n"
        f"Each line = 1 unique code",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.giveaway_max_claims)


@router.message(AdminStates.giveaway_max_claims)
@error_handler
async def msg_giveaway_codes_input(message: types.Message, state: FSMContext):
    """Receive codes either as text (one per line) or as a .txt file upload."""
    codes = []

    if message.document:
        # File upload
        file = await message.bot.get_file(message.document.file_id)
        import io
        buf = io.BytesIO()
        await message.bot.download_file(file.file_path, buf)
        buf.seek(0)
        content = buf.read().decode("utf-8", errors="ignore")
        codes = [line.strip() for line in content.splitlines() if line.strip()]
    elif message.text:
        codes = [line.strip() for line in message.text.strip().splitlines() if line.strip()]

    if not codes:
        await message.answer("⚠️ No codes found. Send codes one per line or upload a .txt file.")
        return

    data = await state.get_data()
    await state.clear()

    title = data["giveaway_title"]
    cpu = data.get("codes_per_user", 1)

    gid = await db.create_free_coupon(title, cpu, message.from_user.id)
    await db.add_giveaway_codes(gid, codes)

    await db.add_admin_log(
        message.from_user.id, "add_giveaway", "giveaway", str(gid),
        f"Title: {title}, Codes: {len(codes)}, Per User: {cpu}"
    )

    max_users = len(codes) // max(cpu, 1)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_giveaways")]])
    await message.answer(
        f"✅ *Giveaway \\#{gid} created\\!*\n\n"
        f"📝 Title: *{escape_md(title)}*\n"
        f"📦 Codes loaded: *{len(codes)}*\n"
        f"👤 Codes per user: *{cpu}*\n"
        f"👥 Max users: *{max_users}*",
        parse_mode="MarkdownV2", reply_markup=kb,
    )




@router.callback_query(F.data.startswith("admin_giveaway_reclaim:"))
@admin_only
@error_handler
async def cb_giveaway_reclaim(callback: types.CallbackQuery):
    gid = int(callback.data.split(":")[1])
    codes = await db.reclaim_unclaimed_codes(gid)
    if not codes:
        await callback.answer("No unclaimed codes to reclaim.", show_alert=True)
        return

    # Send codes as a text file
    import io
    content = "\n".join(codes)
    buf = io.BytesIO(content.encode("utf-8"))
    buf.name = f"reclaimed_codes_giveaway_{gid}.txt"

    from aiogram.types import BufferedInputFile
    file = BufferedInputFile(buf.getvalue(), filename=buf.name)
    await callback.message.answer_document(
        file,
        caption=f"📥 Reclaimed {len(codes)} unclaimed codes from Giveaway #{gid}"
    )
    await callback.answer(f"Reclaimed {len(codes)} codes!", show_alert=True)


@router.callback_query(F.data.startswith("admin_giveaway_toggle:"))
@admin_only
@error_handler
async def cb_giveaway_toggle(callback: types.CallbackQuery):
    gid = int(callback.data.split(":")[1])
    new_status = await db.toggle_free_coupon(gid)
    status_text = "enabled 🟢" if new_status else "disabled 🔴"
    await callback.answer(f"Giveaway {status_text}", show_alert=True)
    await cb_admin_giveaway_view(callback)


@router.callback_query(F.data.startswith("admin_giveaway_del:"))
@admin_only
@error_handler
async def cb_giveaway_delete(callback: types.CallbackQuery):
    gid = int(callback.data.split(":")[1])
    await db.delete_free_coupon(gid)
    await db.add_admin_log(
        callback.from_user.id, "delete_giveaway", "giveaway", str(gid)
    )
    await callback.answer("Giveaway deleted.", show_alert=True)
    await cb_admin_giveaways(callback)


@router.callback_query(F.data.startswith("admin_giveaway_addcodes:"))
@admin_only
@error_handler
async def cb_giveaway_add_more_codes(callback: types.CallbackQuery, state: FSMContext):
    gid = int(callback.data.split(":")[1])
    await state.update_data(add_codes_giveaway_id=gid)
    await callback.message.edit_text(
        "📄 Send more codes \\(one per line\\) or upload a \\.txt file:",
        parse_mode="MarkdownV2",
    )
    await state.set_state(AdminStates.giveaway_add_codes)
    await callback.answer()


@router.message(AdminStates.giveaway_add_codes)
@error_handler
async def msg_giveaway_add_more_codes(message: types.Message, state: FSMContext):
    """Receive additional codes for existing giveaway."""
    codes = []
    if message.document:
        file = await message.bot.get_file(message.document.file_id)
        import io
        buf = io.BytesIO()
        await message.bot.download_file(file.file_path, buf)
        buf.seek(0)
        content = buf.read().decode("utf-8", errors="ignore")
        codes = [line.strip() for line in content.splitlines() if line.strip()]
    elif message.text:
        codes = [line.strip() for line in message.text.strip().splitlines() if line.strip()]

    if not codes:
        await message.answer("⚠️ No codes found.")
        return

    data = await state.get_data()
    gid = data["add_codes_giveaway_id"]
    await state.clear()

    await db.add_giveaway_codes(gid, codes)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_giveaways")]])
    await message.answer(
        f"✅ Added *{len(codes)}* codes to Giveaway \\#{gid}\\!",
        parse_mode="MarkdownV2", reply_markup=kb
    )


# ── Referral Settings ────────────────────────────────────

@router.callback_query(F.data == "admin_referral_settings")
@admin_only
@error_handler
async def cb_admin_referral_settings(callback: types.CallbackQuery):
    settings = await db.get_referral_settings()
    if not settings:
        await callback.answer("No referral settings found.", show_alert=True)
        return

    mode = settings["mode"]
    pct = settings["commission_percent"]
    active = "🟢 Active" if settings["is_active"] else "🔴 Disabled"

    mode_label = "💰 Balance Commission" if mode == "balance" else "🎁 Code Reward"
    pct_esc = escape_md(str(pct))
    text = (
        f"🤝 *Referral Settings*\n\n"
        f"Status: {active}\n"
        f"Mode: {mode_label}\n\n"
    )
    if mode == "balance":
        text += f"💰 Commission: {pct_esc}% per purchase\n"
    else:
        # Show configured reward coupons
        rewards = await db.get_referral_rewards()
        if rewards:
            text += "🎁 *Reward Coupons:*\n"
            for r in rewards:
                status_icon = "🟢" if r["is_active"] else "🔴"
                title_esc = escape_md(r["title"])
                text += f"{status_icon} {title_esc} — {r['referrals_needed']} referrals\n"
        else:
            text += "⚠️ No reward coupons configured yet\n"

    # Build keyboard
    buttons = []
    if mode == "balance":
        buttons.append([InlineKeyboardButton(text="✏️ Edit Commission %", callback_data="admin_ref_edit_commission")])
    else:
        buttons.append([InlineKeyboardButton(text="➕ Add Reward Coupon", callback_data="admin_ref_add_reward")])
        rewards = await db.get_referral_rewards()
        for r in rewards:
            status_icon = "🟢" if r["is_active"] else "🔴"
            buttons.append([InlineKeyboardButton(
                text=f"{status_icon} {r['title'][:25]} ({r['referrals_needed']} refs)",
                callback_data=f"admin_ref_reward_view:{r['id']}"
            )])
    buttons.append([InlineKeyboardButton(text="🔄 Switch Mode", callback_data="admin_ref_toggle_mode")])
    toggle_text = "🔴 Disable Referrals" if settings["is_active"] else "🟢 Enable Referrals"
    buttons.append([InlineKeyboardButton(text=toggle_text, callback_data="admin_ref_toggle_active")])
    buttons.append([back_button("admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_ref_toggle_mode")
@admin_only
@error_handler
async def cb_ref_toggle_mode(callback: types.CallbackQuery):
    settings = await db.get_referral_settings()
    new_mode = "code_reward" if settings["mode"] == "balance" else "balance"
    await db.update_referral_settings(mode=new_mode)
    await callback.answer(f"Mode switched to {new_mode}!", show_alert=True)
    await cb_admin_referral_settings(callback)


@router.callback_query(F.data == "admin_ref_toggle_active")
@admin_only
@error_handler
async def cb_ref_toggle_active(callback: types.CallbackQuery):
    settings = await db.get_referral_settings()
    new_val = not settings["is_active"]
    await db.update_referral_settings(is_active=new_val)
    status = "enabled" if new_val else "disabled"
    await callback.answer(f"Referral system {status}!", show_alert=True)
    await cb_admin_referral_settings(callback)


@router.callback_query(F.data == "admin_ref_edit_commission")
@admin_only
@error_handler
async def cb_ref_edit_commission(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "\u270f\ufe0f *Edit Commission Percentage*\n\nEnter new commission percentage \\(e\\.g\\. 10\\.5\\):",
        parse_mode="MarkdownV2"
    )
    await state.set_state(AdminStates.ref_commission_input)
    await callback.answer()


@router.message(AdminStates.ref_commission_input)
@error_handler
async def msg_ref_commission_input(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.strip())
        if val < 0 or val > 100:
            raise ValueError
        await db.update_referral_settings(commission_percent=val)
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_referral_settings")]])
        await message.answer(f"\u2705 Commission updated to {val}%", reply_markup=kb)
    except ValueError:
        await message.answer("\u26a0\ufe0f Please enter a valid percentage between 0 and 100.")


# ── Reward Coupon Management (Code Reward Mode) ──────────

@router.callback_query(F.data == "admin_ref_add_reward")
@admin_only
@error_handler
async def cb_ref_add_reward(callback: types.CallbackQuery):
    """Show all available coupons for admin to pick as a reward."""
    coupons = await list_all_coupons()
    existing_rewards = await db.get_referral_rewards()
    existing_ids = {r["coupon_id"] for r in existing_rewards}

    available = [c for c in coupons if c["id"] not in existing_ids]

    if not available:
        await callback.answer("All coupons are already set as rewards!", show_alert=True)
        return

    buttons = []
    for c in available:
        stock_icon = "📦" if c["stock"] > 0 else "❌"
        buttons.append([InlineKeyboardButton(
            text=f"{stock_icon} {c['title'][:30]} | ₹{c['discounted_price']} | {c['stock']}",
            callback_data=f"admin_ref_pick_coupon:{c['id']}"
        )])
    buttons.append([back_button("admin_referral_settings")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "🎁 *Select a Coupon as Referral Reward*\n\n"
        "Pick which coupon users will get when they complete referrals:",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ref_pick_coupon:"))
@admin_only
@error_handler
async def cb_ref_pick_coupon(callback: types.CallbackQuery, state: FSMContext):
    """Admin picked a coupon — now ask how many referrals needed."""
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    await state.update_data(ref_reward_coupon_id=coupon_id)
    title_esc = escape_md(coupon["title"])
    await callback.message.edit_text(
        f"🎁 *Setting Reward: {title_esc}*\n\n"
        f"How many referrals should a user need to claim this coupon?\n\n"
        f"Enter a number \\(e\\.g\\. 3, 5, 10\\):",
        parse_mode="MarkdownV2"
    )
    await state.set_state(AdminStates.ref_reward_count_input)
    await callback.answer()


@router.message(AdminStates.ref_reward_count_input)
@error_handler
async def msg_ref_reward_count(message: types.Message, state: FSMContext):
    """Handle both new reward count and edit reward count."""
    try:
        val = int(message.text.strip())
        if val < 1:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Please enter a valid positive number.")
        return

    data = await state.get_data()
    await state.clear()

    if "edit_reward_id" in data:
        reward_id = data["edit_reward_id"]
        await db.update_referral_reward_count(reward_id, val)
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_referral_settings")]])
        await message.answer(f"✅ Referral count updated to {val}", reply_markup=kb)
    elif "ref_reward_coupon_id" in data:
        coupon_id = data["ref_reward_coupon_id"]
        await db.add_referral_reward(coupon_id, val)
        coupon = await get_coupon_detail(coupon_id)
        title = coupon["title"] if coupon else "Unknown"
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_referral_settings")]])
        await message.answer(
            f"✅ Reward added\\!\n\n"
            f"🏷️ {escape_md(title)} — needs {val} referrals to claim",
            parse_mode="MarkdownV2", reply_markup=kb
        )


@router.callback_query(F.data.startswith("admin_ref_reward_view:"))
@admin_only
@error_handler
async def cb_ref_reward_view(callback: types.CallbackQuery):
    """View/manage a specific referral reward."""
    reward_id = int(callback.data.split(":")[1])
    reward = await db.get_referral_reward(reward_id)
    if not reward:
        await callback.answer("Reward not found.", show_alert=True)
        return

    status = "🟢 Active" if reward["is_active"] else "🔴 Disabled"
    title_esc = escape_md(reward["title"])
    text = (
        f"🎁 *Referral Reward*\n\n"
        f"🏷️ Coupon: {title_esc}\n"
        f"👥 Referrals needed: {reward['referrals_needed']}\n"
        f"📦 Stock: {reward['stock']}\n"
        f"Status: {status}"
    )

    toggle_text = "🔴 Disable" if reward["is_active"] else "🟢 Enable"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Change Referral Count", callback_data=f"admin_ref_reward_edit:{reward_id}")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"admin_ref_reward_toggle:{reward_id}")],
        [InlineKeyboardButton(text="🗑️ Remove Reward", callback_data=f"admin_ref_reward_del:{reward_id}")],
        [back_button("admin_referral_settings")],
    ])

    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ref_reward_edit:"))
@admin_only
@error_handler
async def cb_ref_reward_edit(callback: types.CallbackQuery, state: FSMContext):
    """Edit the referral count for a reward."""
    reward_id = int(callback.data.split(":")[1])
    await state.update_data(edit_reward_id=reward_id)
    await callback.message.edit_text(
        "✏️ *Edit Referral Count*\n\nEnter the new number of referrals needed:",
        parse_mode="MarkdownV2"
    )
    await state.set_state(AdminStates.ref_reward_count_input)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ref_reward_toggle:"))
@admin_only
@error_handler
async def cb_ref_reward_toggle(callback: types.CallbackQuery):
    reward_id = int(callback.data.split(":")[1])
    new_status = await db.toggle_referral_reward(reward_id)
    status_text = "enabled 🟢" if new_status else "disabled 🔴"
    await callback.answer(f"Reward {status_text}", show_alert=True)
    await cb_ref_reward_view(callback)


@router.callback_query(F.data.startswith("admin_ref_reward_del:"))
@admin_only
@error_handler
async def cb_ref_reward_del(callback: types.CallbackQuery):
    reward_id = int(callback.data.split(":")[1])
    await db.remove_referral_reward(reward_id)
    await callback.answer("Reward removed!", show_alert=True)
    await cb_admin_referral_settings(callback)




# ── Bot Settings ─────────────────────────────────────────

@router.callback_query(F.data == "admin_bot_settings")
@admin_only
@error_handler
async def cb_admin_bot_settings(callback: types.CallbackQuery):
    settings = await db.get_bot_settings()
    force_channel = settings.get("force_channel") if settings else None
    
    status = "🟢 Active" if force_channel else "🔴 Disabled"
    chan = escape_md(force_channel) if force_channel else "None"
    
    text = (
        f"⚙️ *Bot Settings*\n\n"
        f"📢 *Force Join Channel*\n"
        f"Status: {status}\n"
        f"Channel: `{chan}`\n\n"
        f"Users must join this channel before using the bot\\."
    )
    
    await callback.message.edit_text(
        text, parse_mode="MarkdownV2", reply_markup=admin_bot_settings_kb(force_channel)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_toggle_force_join")
@admin_only
@error_handler
async def cb_admin_toggle_force_join(callback: types.CallbackQuery, state: FSMContext):
    settings = await db.get_bot_settings()
    force_channel = settings.get("force_channel") if settings else None
    
    if force_channel:
        await db.update_bot_settings(force_channel=None)
        await callback.answer("Force Join Channel removed!", show_alert=True)
        await cb_admin_bot_settings(callback)
    else:
        await callback.message.edit_text(
            "📢 Send the *Channel/Group ID* or *Username*\n\n"
            "Examples:\n"
            "• `@MyChannel`\n"
            "• `\\-1001234567890`\n\n"
            "💡 Use /id command in your channel to get the ID\\.\n\n"
            "⚠️ *IMPORTANT*: Bot MUST be admin in the channel\\!",
            parse_mode="MarkdownV2"
        )
        await state.set_state(AdminStates.force_channel_input)
        await callback.answer()


@router.message(AdminStates.force_channel_input)
@error_handler
async def msg_force_channel_input(message: types.Message, state: FSMContext):
    val = message.text.strip()
    
    channels = [ch.strip() for ch in val.split(",") if ch.strip()]
    valid = []
    errors = []
    
    for ch in channels:
        try:
            chat_id = int(ch) if ch.lstrip("-").isdigit() else ch
            await message.bot.get_chat(chat_id)
            try:
                await message.bot.export_chat_invite_link(chat_id)
            except Exception:
                pass
            valid.append(ch)
        except Exception as e:
            errors.append(f"{ch}: {e}")
    
    if not valid:
        err_msg = escape_md(str(errors[0]).split(":")[-1].strip() if errors else "Unknown")
        await message.answer(
            f"❌ Could not verify any channel\\.\n\n"
            f"Make sure the bot is *admin* in the channel and the ID is correct\\.\n\n"
            f"Error: `{err_msg}`\n\nTry again:",
            parse_mode="MarkdownV2"
        )
        return
    
    save_val = ",".join(valid)
    await db.update_bot_settings(force_channel=save_val)
    await state.clear()
    
    result = f"✅ Force Join updated\\!\n\nChannels: `{escape_md(save_val)}`"
    if errors:
        skipped = escape_md(", ".join(e.split(":")[0] for e in errors))
        result += f"\n\n⚠️ Skipped invalid: {skipped}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_bot_settings")]])
    await message.answer(result, parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════
# PAYMENT SETTINGS (Dynamic from Admin Panel)
# ══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_payments")
@admin_only
@error_handler
async def cb_admin_payments(callback: types.CallbackQuery):
    """Show current payment gateway configuration."""
    ps = await db.get_payment_settings()

    paytm_mid = escape_md(ps["paytm_mid"] or "Not Set")
    paytm_upi = escape_md(ps["paytm_upi_id"] or "Not Set")
    bp_mid = escape_md(ps["bharatpe_merchant_id"] or "Not Set")
    bp_token = escape_md((ps["bharatpe_token"] or "Not Set")[:20] + "..." if ps["bharatpe_token"] and len(ps["bharatpe_token"]) > 20 else ps["bharatpe_token"] or "Not Set")
    bp_upi = escape_md(ps["bharatpe_upi_id"] or "Not Set")
    bp_qr = "✅ Uploaded" if ps["bharatpe_qr_path"] else "❌ Not Set"
    payee = escape_md(ps["upi_payee_name"] or "Not Set")

    text = (
        f"💳 *Payment Settings*\n\n"
        f"━━━ *Paytm* ━━━\n"
        f"🏢 MID: `{paytm_mid}`\n"
        f"📱 UPI ID: `{paytm_upi}`\n\n"
        f"━━━ *BharatPe* ━━━\n"
        f"🏢 Merchant ID: `{bp_mid}`\n"
        f"🔑 Token: `{bp_token}`\n"
        f"📱 UPI ID: `{bp_upi}`\n"
        f"📷 QR Image: {bp_qr}\n\n"
        f"━━━ *General* ━━━\n"
        f"👤 Payee Name: `{payee}`\n"
    )

    buttons = [
        [InlineKeyboardButton(text="🏢 Paytm MID", callback_data="admin_pay_edit:paytm_mid"),
         InlineKeyboardButton(text="📱 Paytm UPI", callback_data="admin_pay_edit:paytm_upi_id")],
        [InlineKeyboardButton(text="🏢 BP Merchant", callback_data="admin_pay_edit:bharatpe_merchant_id"),
         InlineKeyboardButton(text="🔑 BP Token", callback_data="admin_pay_edit:bharatpe_token")],
        [InlineKeyboardButton(text="📱 BP UPI ID", callback_data="admin_pay_edit:bharatpe_upi_id")],
        [InlineKeyboardButton(text="📷 Upload BP QR Image", callback_data="admin_pay_upload_qr")],
        [InlineKeyboardButton(text="👤 Payee Name", callback_data="admin_pay_edit:upi_payee_name")],
        [back_button("admin_panel")],
    ]

    await callback.message.edit_text(text, parse_mode="MarkdownV2",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


PAYMENT_FIELD_LABELS = {
    "paytm_mid": "Paytm Merchant ID",
    "paytm_upi_id": "Paytm UPI ID",
    "bharatpe_merchant_id": "BharatPe Merchant ID",
    "bharatpe_token": "BharatPe Token",
    "bharatpe_upi_id": "BharatPe UPI ID",
    "upi_payee_name": "UPI Payee Name",
}


@router.callback_query(F.data.startswith("admin_pay_edit:"))
@admin_only
@error_handler
async def cb_admin_pay_edit(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    label = PAYMENT_FIELD_LABELS.get(field, field)
    await state.set_data({"payment_field": field})
    await state.set_state(AdminStates.payment_field_input)
    await callback.message.edit_text(
        f"✏️ *Edit {escape_md(label)}*\n\nSend the new value:",
        parse_mode="MarkdownV2"
    )
    await callback.answer()


@router.message(AdminStates.payment_field_input)
@error_handler
async def msg_payment_field_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data["payment_field"]
    value = message.text.strip()
    await db.update_bot_settings(**{field: value})
    await state.clear()
    label = PAYMENT_FIELD_LABELS.get(field, field)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_payments")]])
    await message.answer(f"✅ {label} updated\\!", parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data == "admin_pay_upload_qr")
@admin_only
@error_handler
async def cb_admin_pay_upload_qr(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.payment_qr_upload)
    await callback.message.edit_text(
        "📷 *Upload BharatPe QR Image*\n\nSend the QR code image as a photo:",
        parse_mode="MarkdownV2"
    )
    await callback.answer()


@router.message(AdminStates.payment_qr_upload, F.photo)
@error_handler
async def msg_payment_qr_upload(message: types.Message, state: FSMContext):
    import os
    # Create data directory
    qr_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "qr")
    os.makedirs(qr_dir, exist_ok=True)

    # Delete old QR if exists
    ps = await db.get_payment_settings()
    old_path = ps.get("bharatpe_qr_path")
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except Exception:
            pass

    # Download new QR
    photo = message.photo[-1]  # Largest size
    file = await message.bot.get_file(photo.file_id)
    save_path = os.path.join(qr_dir, f"bharatpe_qr_{photo.file_unique_id}.jpg")
    await message.bot.download_file(file.file_path, save_path)

    # Save path to DB
    await db.update_bot_settings(bharatpe_qr_path=save_path)
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_payments")]])
    await message.answer("✅ BharatPe QR image uploaded\\!", parse_mode="MarkdownV2", reply_markup=kb)


# ══════════════════════════════════════════════════════════
# USER MANAGEMENT
# ══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_users")
@admin_only
@error_handler
async def cb_admin_users(callback: types.CallbackQuery, state: FSMContext):
    user_count = await db.get_user_count()
    text = (
        f"👥 *User Management*\n\n"
        f"📊 Total Users: *{user_count}*\n\n"
        f"🔍 Send a *Telegram ID* or *@username* to search:"
    )
    await state.set_state(AdminStates.user_search_input)
    buttons = [
        [InlineKeyboardButton(text="📋 List Recent Users", callback_data="admin_users_recent")],
        [back_button("admin_panel")],
    ]
    await callback.message.edit_text(text, parse_mode="MarkdownV2",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data == "admin_users_recent")
@admin_only
@error_handler
async def cb_admin_users_recent(callback: types.CallbackQuery):
    users = await db.get_all_users()
    recent = users[:15]  # Show last 15

    if not recent:
        await callback.answer("No users found.", show_alert=True)
        return

    buttons = []
    for u in recent:
        name = u["full_name"] or u["username"] or str(u["telegram_id"])
        banned = "🚫 " if u.get("is_banned") else ""
        buttons.append([InlineKeyboardButton(
            text=f"{banned}{name[:25]} ({u['telegram_id']})",
            callback_data=f"admin_user_inspect:{u['telegram_id']}"
        )])
    buttons.append([back_button("admin_users")])

    await callback.message.edit_text(
        "👥 *Recent Users*\n\nTap a user to inspect:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.message(AdminStates.user_search_input)
@error_handler
async def msg_user_search(message: types.Message, state: FSMContext):
    query = message.text.strip()
    results = await db.search_user(query)
    await state.clear()

    if not results:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_users")]])
        await message.answer(
            f"❌ No users found for *{escape_md(query)}*",
            parse_mode="MarkdownV2", reply_markup=kb
        )
        return

    buttons = []
    for u in results[:10]:
        name = u["full_name"] or u["username"] or str(u["telegram_id"])
        banned = "🚫 " if u.get("is_banned") else ""
        buttons.append([InlineKeyboardButton(
            text=f"{banned}{name[:25]} ({u['telegram_id']})",
            callback_data=f"admin_user_inspect:{u['telegram_id']}"
        )])
    buttons.append([back_button("admin_users")])

    await message.answer(
        f"🔍 *Search Results for* `{escape_md(query)}`:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("admin_user_inspect:"))
@admin_only
@error_handler
async def cb_admin_user_inspect(callback: types.CallbackQuery):
    """Full user profile card with order statistics."""
    user_id = int(callback.data.split(":")[1])
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("User not found.", show_alert=True)
        return

    name = escape_md(user["full_name"] or "Unknown")
    uname = f"@{escape_md(user['username'])}" if user.get("username") else "Not set"
    joined = escape_md(str(user.get("joined_at", "Unknown"))[:19])
    banned = "🚫 *BANNED*" if user.get("is_banned") else "✅ Active"
    wallet = escape_md(format_currency(float(user.get("wallet_balance") or 0)))
    earnings = escape_md(format_currency(float(user.get("referral_earnings") or 0)))
    ref_code = escape_md(user.get("referral_code") or "None")

    # Get referrer info
    referrer = await db.get_referrer_of(user_id)
    if referrer:
        ref_by = f"{escape_md(referrer['full_name'] or 'Unknown')} \\(`{referrer['telegram_id']}`\\)"
    else:
        ref_by = "None"

    ref_count = await db.get_referral_count(user_id)

    # Get order statistics
    stats = await db.get_user_order_stats(user_id)
    total_spent = escape_md(format_currency(float(stats["total_spent"])))

    text = (
        f"👤 *User Profile*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 Name: *{name}*\n"
        f"👤 Username: {uname}\n"
        f"🆔 ID: `{user_id}`\n"
        f"📅 Joined: {joined}\n"
        f"🔰 Status: {banned}\n\n"
        f"━━━ *Financial* ━━━\n"
        f"💰 Wallet: *{wallet}*\n"
        f"💸 Referral Earnings: *{earnings}*\n"
        f"🏦 Total Spent: *{total_spent}*\n\n"
        f"━━━ *Order Stats* ━━━\n"
        f"📦 Total: *{escape_md(str(stats['total_orders']))}* \\| "
        f"✅ Paid: *{escape_md(str(stats['total_paid']))}*\n"
        f"🟡 Pending: *{escape_md(str(stats['total_pending']))}* \\| "
        f"❌ Cancelled: *{escape_md(str(stats['total_cancelled']))}*\n"
        f"⏰ Expired: *{escape_md(str(stats['total_expired']))}* \\| "
        f"📬 Delivered: *{escape_md(str(stats['total_delivered']))}*\n\n"
        f"━━━ *Referral* ━━━\n"
        f"🔑 Code: `{ref_code}`\n"
        f"👥 Referrals Made: *{ref_count}*\n"
        f"🔗 Referred By: {ref_by}\n"
    )

    ban_text = "🔓 Unban User" if user.get("is_banned") else "🚫 Ban User"
    ban_data = f"admin_user_unban:{user_id}" if user.get("is_banned") else f"admin_user_ban:{user_id}"

    buttons = [
        [InlineKeyboardButton(text="📦 View Orders", callback_data=f"admin_user_orders:{user_id}"),
         InlineKeyboardButton(text="👥 View Referrals", callback_data=f"admin_user_referrals:{user_id}")],
        [InlineKeyboardButton(text="💰 Edit Wallet", callback_data=f"admin_user_wallet:{user_id}"),
         InlineKeyboardButton(text="🔄 Change Referrer", callback_data=f"admin_user_chg_ref:{user_id}")],
        [InlineKeyboardButton(text=ban_text, callback_data=ban_data)],
        [back_button("admin_users")],
    ]

    await callback.message.edit_text(text, parse_mode="MarkdownV2",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user_orders:"))
@admin_only
@error_handler
async def cb_admin_user_orders(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    orders = await db.get_user_orders(user_id)

    if not orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_user_inspect:{user_id}")]])
        await callback.message.edit_text(
            f"📦 *No orders found for user* `{user_id}`",
            parse_mode="MarkdownV2", reply_markup=kb
        )
        await callback.answer()
        return

    lines = [f"📦 *Orders for user* `{user_id}`\n"]
    for o in orders[:15]:
        status_icon = {"paid": "✅", "delivered": "✅", "pending": "🟡", "expired": "⏰", "cancelled": "❌"}.get(o["status"], "❓")
        amt = format_currency(float(o["amount"]))
        date = str(o.get("created_at", ""))[:10]
        oid = o["order_id"][:12]
        lines.append(f"{status_icon} `{escape_md(oid)}` — {escape_md(amt)} — {escape_md(date)}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_user_inspect:{user_id}")]])
    await callback.message.edit_text(
        "\n".join(lines), parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user_referrals:"))
@admin_only
@error_handler
async def cb_admin_user_referrals(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    referrals = await db.get_user_referrals(user_id)

    if not referrals:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_user_inspect:{user_id}")]])
        await callback.message.edit_text(
            f"👥 *No referrals found for user* `{user_id}`",
            parse_mode="MarkdownV2", reply_markup=kb
        )
        await callback.answer()
        return

    lines = [f"👥 *Referrals by user* `{user_id}`\n"]
    for r in referrals[:15]:
        name = escape_md(r.get("full_name") or r.get("username") or "Unknown")
        status = "✅" if r["status"] == "purchased" else "👤"
        comm = escape_md(format_currency(float(r["commission"])))
        lines.append(f"{status} {name} — {comm}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_user_inspect:{user_id}")]])
    await callback.message.edit_text(
        "\n".join(lines), parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer()


# ── Ban / Unban ──────────────────────────────────────────

@router.callback_query(F.data.startswith("admin_user_ban:"))
@admin_only
@error_handler
async def cb_admin_user_ban(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    # Prevent banning any admin (including self)
    if Config.is_admin(user_id):
        await callback.answer("⚠️ Cannot ban an admin account!", show_alert=True)
        return
    await db.ban_user(user_id, True)
    await callback.answer(f"🚫 User {user_id} has been BANNED!", show_alert=True)
    await cb_admin_user_inspect(callback)


@router.callback_query(F.data.startswith("admin_user_unban:"))
@admin_only
@error_handler
async def cb_admin_user_unban(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    await db.ban_user(user_id, False)
    await callback.answer(f"✅ User {user_id} has been UNBANNED!", show_alert=True)
    await cb_admin_user_inspect(callback)


# ── Change Referrer ──────────────────────────────────────

@router.callback_query(F.data.startswith("admin_user_chg_ref:"))
@admin_only
@error_handler
async def cb_admin_user_chg_ref(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await state.set_data({"change_ref_for": user_id})
    await state.set_state(AdminStates.user_change_referrer)
    await callback.message.edit_text(
        f"🔄 *Change Referrer for user* `{user_id}`\n\n"
        f"Send the *Telegram ID* of the new referrer:",
        parse_mode="MarkdownV2"
    )
    await callback.answer()


@router.message(AdminStates.user_change_referrer)
@error_handler
async def msg_user_change_referrer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data["change_ref_for"]

    try:
        referrer_id = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Please send a valid Telegram ID (number).")
        return

    # Verify referrer exists
    referrer = await db.get_user(referrer_id)
    if not referrer:
        await message.answer("❌ That user is not in the database.")
        return

    if referrer_id == user_id:
        await message.answer("❌ A user cannot refer themselves.")
        return

    await db.set_user_referrer(user_id, referrer_id)
    await state.clear()

    ref_name = escape_md(referrer["full_name"] or str(referrer_id))
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_user_inspect:{user_id}")]])
    await message.answer(
        f"✅ Referrer updated\\!\n\nUser `{user_id}` is now referred by *{ref_name}* \\(`{referrer_id}`\\)",
        parse_mode="MarkdownV2", reply_markup=kb
    )


# ── Admin Wallet Management ─────────────────────────────

@router.callback_query(F.data.startswith("admin_user_wallet:"))
@admin_only
@error_handler
async def cb_admin_user_wallet(callback: types.CallbackQuery, state: FSMContext):
    """Show wallet edit options for user."""
    user_id = int(callback.data.split(":")[1])
    balance = await db.get_wallet_balance(user_id)
    bal_str = escape_md(f"₹{balance:.1f}")

    await state.set_data({"wallet_edit_user": user_id})
    await state.set_state(AdminStates.user_wallet_edit)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [back_button(f"admin_user_inspect:{user_id}")],
    ])
    await callback.message.edit_text(
        f"💰 *Edit Wallet for user* `{user_id}`\n\n"
        f"Current Balance: *{bal_str}*\n\n"
        f"Send the amount to *add* to the wallet:\n"
        f"• Positive number \\= add \\(e\\.g\\. `50`\\)\n"
        f"• Negative number \\= deduct \\(e\\.g\\. `\\-20`\\)\n"
        f"• `set:100` \\= set exact balance to ₹100",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
    await callback.answer()


@router.message(AdminStates.user_wallet_edit)
@admin_only
@error_handler
async def msg_admin_wallet_edit(message: types.Message, state: FSMContext):
    """Process wallet edit input."""
    data = await state.get_data()
    user_id = data["wallet_edit_user"]
    text = message.text.strip()

    current = await db.get_wallet_balance(user_id)

    if text.lower().startswith("set:"):
        # Set exact balance
        try:
            new_balance = float(text[4:].strip())
        except ValueError:
            await message.answer("⚠️ Invalid amount. Use format: `set:100`")
            return
        delta = new_balance - current
    else:
        # Add/deduct
        try:
            delta = float(text)
        except ValueError:
            await message.answer("⚠️ Invalid amount. Send a number like `50` or `-20`.")
            return
        new_balance = current + delta

    if new_balance < 0:
        await message.answer("⚠️ Balance cannot go below ₹0.")
        return

    await db.update_wallet_balance(user_id, new_balance)
    await db.add_wallet_transaction(
        user_id, delta, "admin_adjust",
        bal_before=current, bal_after=new_balance,
        description=f"Admin adjustment by {message.from_user.id}",
    )

    await state.clear()

    action = "added" if delta >= 0 else "deducted"
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_user_inspect:{user_id}")]])
    await message.answer(
        f"✅ Wallet updated\\!\n\n"
        f"👤 User: `{user_id}`\n"
        f"💰 Previous: *{escape_md(format_currency(current))}*\n"
        f"{'➕' if delta >= 0 else '➖'} {action.title()}: *{escape_md(format_currency(abs(delta)))}*\n"
        f"💎 New Balance: *{escape_md(format_currency(new_balance))}*",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
    logger.info(f"Admin {message.from_user.id} adjusted wallet for {user_id}: {delta:+.1f}, new={new_balance:.1f}")


# ── Analytics ────────────────────────────────────────────

@router.callback_query(F.data == "admin_analytics")
@admin_only
@error_handler
async def cb_admin_analytics(callback: types.CallbackQuery):
    stats = await db.get_sales_stats()
    user_count = await db.get_user_count()

    revenue = escape_md(format_currency(float(stats["total_revenue"])))
    text = (
        f"📊 *Analytics Dashboard*\n\n"
        f"👥 Total Users: *{user_count}*\n"
        f"📦 Total Orders: *{escape_md(str(stats['total_orders']))}*\n"
        f"💰 Total Revenue: *{revenue}*\n\n"
        f"✅ Paid: *{escape_md(str(stats['total_paid']))}*\n"
        f"🟡 Pending: *{escape_md(str(stats['total_pending']))}*\n"
        f"⏰ Expired: *{escape_md(str(stats['total_expired']))}*\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


# ── Disclaimer Management ────────────────────────────────

@router.callback_query(F.data == "admin_disclaimer")
@admin_only
@error_handler
async def cb_admin_disclaimer(callback: types.CallbackQuery):
    """Show current disclaimer and management options."""
    import json
    settings = await db.get_bot_settings()
    current_text = settings.get("disclaimer_text") or ""
    buttons_json = settings.get("disclaimer_buttons") or "[]"

    try:
        buttons_list = json.loads(buttons_json)
    except Exception:
        buttons_list = []

    # Preview
    if current_text:
        preview = escape_md(current_text[:200])
        if len(current_text) > 200:
            preview += "\\.\\.\\."
    else:
        preview = "_No disclaimer set \\— using default_"

    btn_preview = ""
    if buttons_list:
        btn_lines = [f"  • {escape_md(b.get('text',''))} → {escape_md(b.get('url',''))}" for b in buttons_list]
        btn_preview = "\n📎 *Inline Buttons:*\n" + "\n".join(btn_lines)
    else:
        btn_preview = "\n📎 _No inline buttons_"

    text = (
        f"📜 *Disclaimer Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 *Current Text:*\n{preview}\n"
        f"{btn_preview}\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Text", callback_data="admin_discl_edit_text")],
        [InlineKeyboardButton(text="📎 Edit Buttons", callback_data="admin_discl_edit_btns")],
        [InlineKeyboardButton(text="🗑️ Reset to Default", callback_data="admin_discl_reset")],
        [back_button("admin_panel")],
    ])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_discl_edit_text")
@admin_only
@error_handler
async def cb_admin_discl_edit_text(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.disclaimer_text_input)
    await callback.message.edit_text(
        "✏️ *Edit Disclaimer Text*\n\n"
        "Send the new disclaimer text\\.\n"
        "Use plain text \\— formatting will be applied automatically\\.\n\n"
        "_Send /cancel to abort\\._",
        parse_mode="MarkdownV2",
    )
    await callback.answer()


@router.message(AdminStates.disclaimer_text_input)
@error_handler
async def msg_disclaimer_text(message: types.Message, state: FSMContext):
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Cancelled.")
        return

    text = message.text.strip() if message.text else ""
    await state.clear()

    if not text:
        await message.answer("⚠️ Text cannot be empty.")
        return

    await db.update_bot_settings(disclaimer_text=text)
    await message.answer(
        "✅ Disclaimer text updated\\!",
        parse_mode="MarkdownV2",
    )
    logger.info(f"Admin {message.from_user.id} updated disclaimer text")


@router.callback_query(F.data == "admin_discl_edit_btns")
@admin_only
@error_handler
async def cb_admin_discl_edit_btns(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.disclaimer_buttons_input)
    await callback.message.edit_text(
        "📎 *Edit Disclaimer Buttons*\n\n"
        "Send inline buttons, *one per line* in this format:\n\n"
        "`Button Text \\| https://example\\.com`\n\n"
        "Example:\n"
        "`📺 Watch Video \\| https://t\\.me/channel/123`\n"
        "`💬 Support \\| https://t\\.me/supportbot`\n\n"
        "Send *clear* to remove all buttons\\.\n"
        "Send /cancel to abort\\.",
        parse_mode="MarkdownV2",
    )
    await callback.answer()


@router.message(AdminStates.disclaimer_buttons_input)
@error_handler
async def msg_disclaimer_buttons(message: types.Message, state: FSMContext):
    import json

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Cancelled.")
        return

    text = message.text.strip() if message.text else ""
    await state.clear()

    if text.lower() == "clear":
        await db.update_bot_settings(disclaimer_buttons="[]")
        await message.answer("✅ All disclaimer buttons removed\\!", parse_mode="MarkdownV2")
        return

    # Parse buttons
    buttons = []
    for line in text.split("\n"):
        line = line.strip()
        if "|" not in line:
            continue
        parts = line.split("|", 1)
        label = parts[0].strip()
        url = parts[1].strip()
        if label and url:
            buttons.append({"text": label, "url": url})

    if not buttons:
        await message.answer("⚠️ No valid buttons found. Use format: `Label | URL`", parse_mode="MarkdownV2")
        return

    await db.update_bot_settings(disclaimer_buttons=json.dumps(buttons))
    await message.answer(
        f"✅ Saved *{len(buttons)}* inline button\\(s\\)\\!",
        parse_mode="MarkdownV2",
    )
    logger.info(f"Admin {message.from_user.id} updated disclaimer buttons: {len(buttons)}")


@router.callback_query(F.data == "admin_discl_reset")
@admin_only
@error_handler
async def cb_admin_discl_reset(callback: types.CallbackQuery):
    await db.update_bot_settings(disclaimer_text="", disclaimer_buttons="[]")
    await callback.answer("✅ Disclaimer reset to default!", show_alert=True)
    await cb_admin_disclaimer(callback)
