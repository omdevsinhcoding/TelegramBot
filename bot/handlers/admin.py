"""
DreamX Coupon Bot — Admin Panel Handlers
Full admin CRUD for coupons, users, orders, analytics, broadcasts.
"""

from aiogram import Router, types, F
from aiogram.filters import Command
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
)
from bot.keyboards.common import back_button, admin_cancel_button
from bot.utils.helpers import format_currency, format_datetime, escape_md
from bot.utils.decorators import admin_only, error_handler
from bot.utils.logger import logger

router = Router()


async def _safe_edit_or_send(message: types.Message, text: str, reply_markup=None, parse_mode="MarkdownV2"):
    """Try to edit the message text; if it fails (e.g. document/photo message), delete and send new."""
    try:
        await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)


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
    giveaway_max_claims = State()       # file upload state
    giveaway_manual_codes = State()     # manual text input
    giveaway_add_codes = State()
    # Bot Settings
    force_channel_input = State()
    # Referral
    ref_commission_input = State()
    ref_reward_amount_input = State()
    ref_reward_count_input = State()  # for setting referrals_needed on a coupon reward
    # Payment settings
    payment_field_input = State()
    payment_qr_upload = State()
    # User management
    user_search_input = State()
    user_change_referrer = State()
    user_wallet_edit = State()
    # Disclaimer (support text + support buttons)
    disclaimer_text_input = State()
    disclaimer_buttons_input = State()
    # Disclaimer content (separate from support)
    disclaimer_content_input = State()
    # Ban message
    ban_message_text_input = State()
    ban_message_buttons_input = State()
    # Admin management
    add_admin_input = State()
    # Dynamic config
    dynamic_config_input = State()
    # Channels management
    channels_input = State()
    # Bot name
    bot_name_input = State()


# ── Universal Cancel — inline ❌ button + /cancel fallback ──

@router.callback_query(F.data == "admin_fsm_cancel")
async def cb_admin_fsm_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Cancel any active admin FSM operation via inline ❌ button."""
    await state.clear()
    await callback.message.edit_text(
        "❌ *Operation cancelled\\.*",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_panel")]
        ]),
    )
    await callback.answer("Cancelled!")


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Fallback: cancel via /cancel command."""
    current = await state.get_state()
    if current is None:
        await message.answer("ℹ️ Nothing to cancel.")
        return
    await state.clear()
    await message.answer(
        "❌ *Operation cancelled\\.*",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_panel")]
        ]),
    )


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

    await _safe_edit_or_send(
        callback.message, text, reply_markup=admin_panel_kb()
    )
    await callback.answer()


# ── Manage Coupons ────────────────────────────────────────

@router.callback_query(F.data == "admin_coupons")
@admin_only
@error_handler
async def cb_admin_coupons(callback: types.CallbackQuery):
    coupons = await list_all_coupons()
    text = "📦 *Manage Coupons*\n\nSelect a coupon to edit or add a new one:"
    await _safe_edit_or_send(
        callback.message, text, reply_markup=admin_coupons_kb(coupons)
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

    await _safe_edit_or_send(
        callback.message, text,
        reply_markup=admin_coupon_edit_kb(coupon_id, coupon["is_active"])
    )
    await callback.answer()


# ── Add Coupon Flow ───────────────────────────────────────

@router.callback_query(F.data == "admin_coupon_add")
@admin_only
@error_handler
async def cb_add_coupon_start(callback: types.CallbackQuery, state: FSMContext):
    # Check if at least one payment gateway is enabled
    ps = await db.get_payment_settings()
    has_gateway = (
        ps.get("gateway_paytm_enabled", False) or
        ps.get("gateway_bharatpe_enabled", False) or
        ps.get("gateway_razorpay_enabled", False)
    )
    if not has_gateway:
        await callback.message.edit_text(
            "⚠️ *Cannot Add Coupon*\n\n"
            "No payment gateway is currently enabled\\.\n\n"
            "Please go to *💳 Payments* and enable at least one "
            "payment gateway \\(Paytm, BharatPe, or Razorpay\\) "
            "before adding coupons\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Go to Payments", callback_data="admin_payments")],
                [back_button("admin_coupons")],
            ]),
        )
        await callback.answer("⚠️ No gateway enabled!", show_alert=True)
        return

    await callback.message.edit_text(
        "📝 *Step 1/6* — Enter the *coupon title*:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
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
        try:
            await db.add_coupon_codes_bulk(coupon_id, codes)
        except Exception as e:
            logger.error(f"Bulk code insert failed: {e}")
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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button(f"admin_coupon_edit:{coupon_id}"), admin_cancel_button()]
        ]),
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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button(f"admin_coupon_edit:{coupon_id}"), admin_cancel_button()]
        ]),
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
    try:
        await db.add_coupon_codes_bulk(coupon_id, codes)
    except Exception as e:
        logger.error(f"Bulk code insert failed: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer(f"❌ Error adding codes: {escape_md(str(e)[:100])}", parse_mode="MarkdownV2", reply_markup=kb)
        return

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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button(f"admin_coupon_edit:{coupon_id}"), admin_cancel_button()]
        ]),
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

    # Add codes to database (bulk insert)
    try:
        await db.add_coupon_codes_bulk(coupon_id, codes)
    except Exception as e:
        logger.error(f"Bulk file code insert failed: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer(f"❌ Error adding codes from file: {escape_md(str(e)[:100])}", parse_mode="MarkdownV2", reply_markup=kb)
        return

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


# ── View/Download Coupon Codes ────────────────────────────

@router.callback_query(F.data.startswith("admin_view_codes:"))
@admin_only
@error_handler
async def cb_admin_view_codes(callback: types.CallbackQuery):
    """View code stats + download remaining unsold codes as .txt file."""
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    stats = await db.get_coupon_code_stats(coupon_id)
    total = stats["total"]
    sold = stats["sold"]
    unsold = stats["unsold"]
    title = escape_md(coupon["title"])

    text = (
        f"📥 *View Codes — Coupon \\#{coupon_id}*\n\n"
        f"🏷️ {title}\n\n"
        f"📊 *Code Statistics:*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total Codes: *{total}*\n"
        f"✅ Sold: *{sold}*\n"
        f"📭 Unsold/Remaining: *{unsold}*\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    buttons = []
    if unsold > 0:
        buttons.append([InlineKeyboardButton(
            text=f"📄 Download {unsold} Unsold Codes (.txt)",
            callback_data=f"admin_download_codes:{coupon_id}"
        )])
    buttons.append([back_button(f"admin_coupon_edit:{coupon_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_download_codes:"))
@admin_only
@error_handler
async def cb_admin_download_codes(callback: types.CallbackQuery):
    """Download all unsold coupon codes as a .txt file."""
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    codes = await db.get_coupon_unsold_codes_list(coupon_id)
    if not codes:
        await callback.answer("No unsold codes available.", show_alert=True)
        return

    # Create .txt file content
    file_content = "\n".join(codes)
    safe_title = "".join(c for c in coupon["title"] if c.isalnum() or c in (' ', '-', '_')).strip()[:40]
    filename = f"unsold_codes_{safe_title}_{coupon_id}.txt"

    from aiogram.types import BufferedInputFile
    file_buf = BufferedInputFile(
        file_content.encode("utf-8"),
        filename=filename
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    await callback.message.answer_document(
        document=file_buf,
        caption=(
            f"📄 *Unsold Codes — {escape_md(coupon['title'])}*\n\n"
            f"📦 Total: *{len(codes)}* codes\n"
            f"📁 File: `{escape_md(filename)}`"
        ),
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await callback.answer(f"📄 {len(codes)} codes exported!")
    logger.info(f"Admin {callback.from_user.id} downloaded {len(codes)} unsold codes for coupon {coupon_id}")


# ── View Orders ───────────────────────────────────────────

@router.callback_query(F.data == "admin_orders")
@admin_only
@error_handler
async def cb_admin_orders(callback: types.CallbackQuery):
    """Show recent purchasers grouped by user."""
    users = await db.get_recent_order_users(15)

    lines = ["🧾 *Recent Purchasers*\n"]
    if not users:
        lines.append("_No orders yet\\._")
    else:
        for u in users:
            name = escape_md(u["full_name"] or "Unknown")
            uid = u["user_id"]
            orders = u["order_count"]
            paid = u["paid_count"]
            spent = escape_md(format_currency(float(u["total_spent"])))
            lines.append(
                f"👤 *{name}* \\(`{uid}`\\)\n"
                f"   📦 Orders: *{orders}* \\| ✅ Paid: *{paid}* \\| 💰 {spent}"
            )

    text = "\n".join(lines)

    buttons = []
    for u in users[:10]:
        name = u["full_name"] or str(u["user_id"])
        btn_text = f"👤 {name} ({u['order_count']} orders)"
        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"admin_order_user:{u['user_id']}"
        )])

    buttons.append([InlineKeyboardButton(text="🔍 Search Order ID", callback_data="admin_order_search")])
    buttons.append([back_button("admin_panel")])

    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_order_user:"))
@admin_only
@error_handler
async def cb_admin_order_user(callback: types.CallbackQuery):
    """Show all orders for a specific user (from orders panel)."""
    user_id = int(callback.data.split(":")[1])
    orders = await db.get_user_all_orders(user_id, 20)
    user = await db.get_user(user_id)

    user_name = escape_md((user["full_name"] if user else "Unknown") or "Unknown")
    status_emoji = {
        "pending": "🟡", "paid": "🟢", "delivered": "✅",
        "expired": "⏰", "cancelled": "❌", "refunded": "🔄"
    }

    # Calculate stats
    total = len(orders) if orders else 0
    paid_count = sum(1 for o in orders if o["status"] in ("paid", "delivered")) if orders else 0
    total_spent = sum(float(o["amount"]) for o in orders if o["status"] in ("paid", "delivered")) if orders else 0

    lines = [
        f"📦 *Orders for* {user_name}",
        f"👤 ID: `{user_id}`",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📊 Total: *{total}* \\| ✅ Paid: *{paid_count}* \\| 💰 {escape_md(format_currency(total_spent))}",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]

    buttons = []
    pool = await db.get_pool()

    if not orders:
        lines.append("_No orders found\\._")
    else:
        for i, o in enumerate(orders[:15]):
            emoji = status_emoji.get(o["status"], "❓")
            oid = escape_md(o["order_id"])
            title = escape_md(o.get("coupon_title") or "Unknown")
            amt = escape_md(format_currency(float(o["amount"])))
            qty = o.get("quantity") or 1
            st = escape_md(o["status"])
            created = o.get("created_at")
            date_str = escape_md(str(created)[:16]) if created else "N/A"

            # Source badge
            source = o.get("source", "purchase") or "purchase"
            source_label = ""
            if source == "referral_reward":
                source_label = "🏆 "
            elif source == "giveaway":
                source_label = "🎁 "

            # Code count
            code_count = await pool.fetchval(
                "SELECT COUNT(*) FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE", o["order_id"]
            ) or 0
            code_info = f"🔑 {code_count} code\\(s\\)" if code_count > 0 else ""

            lines.append(
                f"\n{emoji} *\\#{i+1}* {source_label}{title}\n"
                f"   📅 {date_str}\n"
                f"   💰 {amt} x{qty} \\| 📋 {st}\n"
                f"   🆔 `{oid}`"
            )
            if code_info:
                lines.append(f"   {code_info}")

            # Per-order buttons
            btn_row = []
            if code_count > 0:
                btn_row.append(InlineKeyboardButton(
                    text=f"🔑 #{i+1} Codes",
                    callback_data=f"admin_view_order_codes:{o['order_id']}"
                ))
            btn_row.append(InlineKeyboardButton(
                text=f"📋 #{i+1} Detail",
                callback_data=f"admin_order_detail:{o['order_id']}"
            ))
            if btn_row:
                buttons.append(btn_row)

    text = "\n".join(lines)

    buttons.append([InlineKeyboardButton(text="👤 View User Profile", callback_data=f"admin_user_inspect:{user_id}")])
    buttons.append([back_button("admin_orders")])

    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_order_search")
@admin_only
@error_handler
async def cb_admin_order_search(callback: types.CallbackQuery, state: FSMContext):
    """Prompt admin to enter an order ID to search."""
    await state.set_state(AdminStates.user_search_input)
    await state.update_data(search_type="order_id")
    await callback.message.edit_text(
        "🔍 *Search Order*\n\n"
        "Send the *Order ID* to look up:\n"
        "\\(e\\.g\\. `DX\\-12345678\\-ABCDEF`\\)",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_orders"), admin_cancel_button()]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_order_detail:"))
@admin_only
@error_handler
async def cb_admin_order_detail(callback: types.CallbackQuery):
    """Show full details of any order."""
    order_id = callback.data.split(":", 1)[1]
    order = await db.get_order_by_id_admin(order_id)

    if not order:
        await callback.answer("❌ Order not found.", show_alert=True)
        return

    status_emoji = {
        "pending": "🟡", "paid": "🟢", "delivered": "✅",
        "expired": "⏰", "cancelled": "❌", "refunded": "🔄"
    }

    emoji = status_emoji.get(order["status"], "❓")
    oid = escape_md(order["order_id"])
    title = escape_md(order.get("coupon_title") or "Unknown")
    amt = escape_md(format_currency(float(order["amount"])))
    qty = order.get("quantity") or 1
    st = escape_md(order["status"])
    uid = order["user_id"]
    uname = escape_md(order.get("full_name") or "Unknown")

    # Extra details
    created = order.get("created_at")
    date_str = escape_md(str(created)[:19]) if created else "N/A"
    paid_at = order.get("paid_at")
    paid_str = escape_md(str(paid_at)[:19]) if paid_at else "N/A"

    # Source badge
    source = order.get("source", "purchase") or "purchase"
    if source == "referral_reward":
        source_badge = "🏆 Referral Reward"
    elif source == "giveaway":
        source_badge = "🎁 Giveaway"
    else:
        source_badge = "🛍️ Purchase"

    # Get gateway info
    pool = await db.get_pool()
    txn_row = await pool.fetchrow(
        "SELECT gateway, utr FROM transactions WHERE order_id = $1 ORDER BY created_at DESC LIMIT 1",
        order_id
    )
    gateway = escape_md((txn_row["gateway"] if txn_row else "N/A") or "N/A")
    utr = escape_md((txn_row["utr"] if txn_row else "") or "")

    # Get code count
    code_count = await pool.fetchval(
        "SELECT COUNT(*) FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE", order_id
    ) or 0

    utr_line = f"🔢 UTR: `{utr}`\n" if utr else ""

    text = (
        f"📋 *Order Details*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Order: `{oid}`\n"
        f"{emoji} Status: *{st}*\n"
        f"📌 Source: *{source_badge}*\n\n"
        f"🏷️ Item: *{title}*\n"
        f"📦 Qty: *{qty}*\n"
        f"💰 Amount: *{amt}*\n\n"
        f"━━━ *Payment* ━━━\n"
        f"💳 Gateway: *{gateway}*\n"
        f"{utr_line}"
        f"📅 Created: {date_str}\n"
        f"✅ Paid At: {paid_str}\n\n"
        f"━━━ *User* ━━━\n"
        f"👤 Name: *{uname}*\n"
        f"🆔 ID: `{uid}`\n"
        f"🔑 Codes: *{code_count}*\n"
    )

    buttons = []
    if code_count > 0:
        buttons.append([InlineKeyboardButton(text="🔑 View Codes", callback_data=f"admin_view_order_codes:{order_id}")])
    buttons.append([
        InlineKeyboardButton(text="👤 View User", callback_data=f"admin_user_inspect:{uid}"),
        InlineKeyboardButton(text="📦 User Orders", callback_data=f"admin_user_orders:{uid}")
    ])
    buttons.append([back_button("admin_orders")])

    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
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
        "💡 *Tip:* Don't send `/start` — use the button below to\n"
        "broadcast a proper restart message with a button link\\."
    )
    await callback.message.edit_text(text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📲 Quick: Broadcast Restart Message", callback_data="bc_quick_restart")],
            [admin_cancel_button()],
        ]))
    await state.set_state(AdminStates.broadcast_message)
    await callback.answer()


@router.callback_query(F.data == "bc_quick_restart")
@admin_only
@error_handler
async def cb_bc_quick_restart(callback: types.CallbackQuery, state: FSMContext):
    """Pre-fill a 'please restart your bot' broadcast with a /start button."""
    # Get bot username to build the deep link
    bot_me = await callback.message.bot.get_me()
    bot_username = bot_me.username

    restart_text = (
        "🔄 *Bot Update!*\n\n"
        "We've made improvements to the bot\\. "
        "Please tap the button below to restart and get the latest experience\\! 🚀"
    )
    bc_data = {
        "type": "text",
        "text": restart_text,
    }
    bc_buttons = [
        {"text": "🚀 Restart Bot", "url": f"https://t.me/{bot_username}?start=restart"}
    ]
    await state.clear()
    await state.update_data(bc_data=bc_data, bc_buttons=bc_buttons)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Send Now", callback_data="bc_send_now")],
        [InlineKeyboardButton(text="✏️ Edit Message", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")],
    ])
    await callback.message.edit_text(
        "📲 *Quick Restart Broadcast*\n\n"
        "This will send the following message to ALL users with a *\"Restart Bot\"* button:\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔄 *Bot Update\\!*\n\n"
        "We've made improvements to the bot\\. "
        "Please tap the button below to restart and get the latest experience\\! 🚀\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 Button: *Restart Bot* → `t\.me/{escape_md(bot_username)}?start=restart`",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
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
        # ── Guard: block slash-commands from being treated as broadcast text ──
        # e.g. if admin sends /start, it would trigger the start handler instead.
        # We intercept it here and warn the admin.
        raw_text = message.text.strip()
        if raw_text.startswith("/"):
            await message.answer(
                "⚠️ <b>Cannot broadcast a bot command</b> (e.g. <code>/start</code>).\n\n"
                "If you want to tell users to restart the bot, send a normal text message like:\n"
                "<i>\"Please press /start or tap the button below to restart the bot!\"</i>\n\n"
                "Then attach a button with the bot link if needed.",
                parse_mode="HTML",
            )
            return
        bc_data["type"] = "text"
        bc_data["text"] = raw_text
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
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
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
    await _safe_edit_or_send(
        callback.message, text, reply_markup=admin_giveaways_kb(giveaways)
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

    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_giveaway_add")
@admin_only
@error_handler
async def cb_giveaway_add_start(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [back_button("admin_giveaways")],
    ])
    await callback.message.edit_text(
        "🎁 *Step 1/3* — Enter the *giveaway title*:",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await state.set_state(AdminStates.giveaway_title)
    await callback.answer()


@router.message(AdminStates.giveaway_title)
@error_handler
async def msg_giveaway_title(message: types.Message, state: FSMContext):

    title = message.text.strip() if message.text else ""
    if not title:
        await message.answer("⚠️ Please enter a valid title.")
        return

    await state.update_data(giveaway_title=title)
    await message.answer(
        f"✅ Title: *{escape_md(title)}*\n\n"
        f"🔢 *Step 2/3* — How many codes *per user*?\n"
        f"\\(e\\.g\\. `1` \\= 1 code per user, `3` \\= 3 codes per user\\)",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
    )
    await state.set_state(AdminStates.giveaway_code)


@router.message(AdminStates.giveaway_code)
@error_handler
async def msg_giveaway_codes_per_user(message: types.Message, state: FSMContext):

    try:
        cpu = int(message.text.strip())
        if cpu < 1:
            cpu = 1
    except (ValueError, AttributeError):
        await message.answer("⚠️ Enter a valid number (minimum 1).")
        return

    await state.update_data(codes_per_user=cpu)

    # Step 3 — Choose code source method
    buttons = [
        [InlineKeyboardButton(text="📦 Select from Existing Coupons", callback_data="giveaway_src_existing")],
        [InlineKeyboardButton(text="📝 Paste Codes Manually", callback_data="giveaway_src_manual")],
        [InlineKeyboardButton(text="📄 Upload .txt File", callback_data="giveaway_src_file")],
        [admin_cancel_button()],
    ]
    await message.answer(
        f"✅ Codes per user: *{cpu}*\n\n"
        f"📄 *Step 3/3* — How to add codes?\n"
        f"Choose a method below:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# ── Step 3: Re-show method choices (back from sub-steps) ──

@router.callback_query(F.data == "giveaway_step3")
@admin_only
@error_handler
async def cb_giveaway_step3(callback: types.CallbackQuery, state: FSMContext):
    """Go back to giveaway step 3 — choose code input method."""
    data = await state.get_data()
    cpu = data.get("codes_per_user", 1)
    # Clear any sub-step FSM state, keep data
    await state.set_state(None)
    buttons = [
        [InlineKeyboardButton(text="📦 Select from Existing Coupons", callback_data="giveaway_src_existing")],
        [InlineKeyboardButton(text="📝 Paste Codes Manually", callback_data="giveaway_src_manual")],
        [InlineKeyboardButton(text="📄 Upload .txt File", callback_data="giveaway_src_file")],
        [admin_cancel_button()],
    ]
    await callback.message.edit_text(
        f"📄 *Step 3/3* — How to add codes?\n"
        f"Codes per user: *{cpu}*\n\n"
        f"Choose a method below:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


# ── Step 3A: Select from existing coupons ────────────────

@router.callback_query(F.data == "giveaway_src_existing")
@admin_only
@error_handler
async def cb_giveaway_src_existing(callback: types.CallbackQuery, state: FSMContext):
    """Show coupons with available codes to select from."""
    coupons = await db.get_coupons_with_codes()

    if not coupons:
        await callback.answer("❌ No coupons with available codes found.", show_alert=True)
        return

    buttons = []
    for c in coupons:
        btn_text = f"📦 {c['title']} ({c['available_codes']} codes)"
        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"giveaway_pick_coupon:{c['id']}"
        )])
    buttons.append([back_button("giveaway_step3")])

    await callback.message.edit_text(
        "📦 *Select a Coupon*\n\n"
        "Choose a coupon to use its codes for the giveaway:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("giveaway_pick_coupon:"))
@admin_only
@error_handler
async def cb_giveaway_pick_coupon(callback: types.CallbackQuery, state: FSMContext):
    """Use codes from an existing coupon for the giveaway."""
    coupon_id = int(callback.data.split(":")[1])
    code_rows = await db.get_coupon_unsold_codes(coupon_id, 500)
    codes = [r["code"] for r in code_rows if r["code"]]

    if not codes:
        await callback.answer("❌ No unsold codes found in this coupon.", show_alert=True)
        return

    data = await state.get_data()
    await state.clear()

    title = data.get("giveaway_title", "Giveaway")
    cpu = data.get("codes_per_user", 1)

    try:
        gid = await db.create_free_coupon(title, cpu, callback.from_user.id)
        await db.add_giveaway_codes(gid, codes)

        await db.add_admin_log(
            callback.from_user.id, "add_giveaway", "giveaway", str(gid),
            f"Title: {title}, Codes: {len(codes)}, Per User: {cpu}, Source: coupon #{coupon_id}"
        )

        max_users = len(codes) // max(cpu, 1)
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_giveaways")]])
        await callback.message.edit_text(
            f"✅ *Giveaway \\#{escape_md(str(gid))} created\\!*\n\n"
            f"📝 Title: *{escape_md(title)}*\n"
            f"📦 Codes loaded: *{len(codes)}*\n"
            f"👤 Codes per user: *{cpu}*\n"
            f"👥 Max users: *\\~{max_users}*",
            parse_mode="MarkdownV2", reply_markup=kb,
        )
    except Exception as e:
        logger.error(f"Giveaway creation error: {e}")
        await callback.message.edit_text(
            f"❌ Error creating giveaway: {escape_md(str(e))}",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_giveaways")]]),
        )
    await callback.answer()


# ── Step 3B: Manual paste ─────────────────────────────────

@router.callback_query(F.data == "giveaway_src_manual")
@admin_only
@error_handler
async def cb_giveaway_src_manual(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [back_button("giveaway_step3"), admin_cancel_button()],
    ])
    await callback.message.edit_text(
        "📝 *Paste Codes*\n\n"
        "Send coupon codes, *one per line*:\n\n"
        "Example:\n"
        "`CODE123`\n"
        "`CODE456`\n"
        "`CODE789`",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await state.set_state(AdminStates.giveaway_manual_codes)
    await callback.answer()


@router.message(AdminStates.giveaway_manual_codes)
@error_handler
async def msg_giveaway_manual_codes(message: types.Message, state: FSMContext):
    """Receive manually pasted codes."""

    if not message.text:
        await message.answer("⚠️ Please send codes as text, one per line.")
        return

    codes = [line.strip() for line in message.text.strip().splitlines() if line.strip()]
    if not codes:
        await message.answer("⚠️ No valid codes found. Send one code per line.")
        return

    await _finalize_giveaway(message, state, codes)


# ── Step 3C: File upload ──────────────────────────────────

@router.callback_query(F.data == "giveaway_src_file")
@admin_only
@error_handler
async def cb_giveaway_src_file(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [back_button("giveaway_step3"), admin_cancel_button()],
    ])
    await callback.message.edit_text(
        "📄 *Upload File*\n\n"
        "Send a *\\.txt file* with codes \\(one per line\\)\\.",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await state.set_state(AdminStates.giveaway_max_claims)
    await callback.answer()


@router.message(AdminStates.giveaway_max_claims)
@error_handler
async def msg_giveaway_codes_input(message: types.Message, state: FSMContext):
    """Receive codes from file upload."""

    codes = []

    if message.document:
        # File upload — handle both BytesIO and raw bytes
        import io
        try:
            file = await message.bot.get_file(message.document.file_id)
            file_bytes = await message.bot.download_file(file.file_path)
            if isinstance(file_bytes, io.BytesIO):
                content = file_bytes.read().decode("utf-8", errors="ignore")
            else:
                content = file_bytes.decode("utf-8", errors="ignore")
            codes = [line.strip() for line in content.splitlines() if line.strip()]
        except Exception as e:
            logger.error(f"File download error: {e}")
            await message.answer(f"❌ Error reading file: {escape_md(str(e))}", parse_mode="MarkdownV2")
            return
    elif message.text:
        # Also accept text in this state as fallback
        codes = [line.strip() for line in message.text.strip().splitlines() if line.strip()]

    if not codes:
        await message.answer("⚠️ No codes found. Send a .txt file with codes (one per line).")
        return

    await _finalize_giveaway(message, state, codes)


async def _finalize_giveaway(message: types.Message, state: FSMContext, codes: list):
    """Common finalization for all giveaway code input methods."""
    data = await state.get_data()
    await state.clear()

    title = data.get("giveaway_title", "Giveaway")
    cpu = data.get("codes_per_user", 1)

    try:
        gid = await db.create_free_coupon(title, cpu, message.from_user.id)
        await db.add_giveaway_codes(gid, codes)

        await db.add_admin_log(
            message.from_user.id, "add_giveaway", "giveaway", str(gid),
            f"Title: {title}, Codes: {len(codes)}, Per User: {cpu}"
        )

        max_users = len(codes) // max(cpu, 1)
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_giveaways")]])
        await message.answer(
            f"✅ *Giveaway \\#{escape_md(str(gid))} created\\!*\n\n"
            f"📝 Title: *{escape_md(title)}*\n"
            f"📦 Codes loaded: *{len(codes)}*\n"
            f"👤 Codes per user: *{cpu}*\n"
            f"👥 Max users: *\\~{max_users}*",
            parse_mode="MarkdownV2", reply_markup=kb,
        )
    except Exception as e:
        logger.error(f"Giveaway creation error: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_giveaways")]])
        await message.answer(
            f"❌ Error creating giveaway: {escape_md(str(e))}",
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


@router.callback_query(F.data.startswith("admin_giveaway_viewcodes:"))
@admin_only
@error_handler
async def cb_giveaway_viewcodes(callback: types.CallbackQuery):
    """View/download unclaimed giveaway codes as .txt (non-destructive)."""
    gid = int(callback.data.split(":")[1])
    g = await db.get_free_coupon(gid)
    if not g:
        await callback.answer("Giveaway not found.", show_alert=True)
        return

    codes = await db.get_giveaway_unclaimed_codes_list(gid)
    title = g["title"]
    total = g.get("total_codes", 0)
    unclaimed = len(codes)
    claimed = total - unclaimed

    if not codes:
        await callback.answer("No unclaimed codes left in this giveaway.", show_alert=True)
        return

    # Create .txt file content
    file_content = "\n".join(codes)
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:40]
    filename = f"unclaimed_codes_{safe_title}_{gid}.txt"

    from aiogram.types import BufferedInputFile
    file_buf = BufferedInputFile(
        file_content.encode("utf-8"),
        filename=filename
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_giveaway_view:{gid}")]])
    await callback.message.answer_document(
        document=file_buf,
        caption=(
            f"📄 *Unclaimed Codes — {escape_md(title)}*\n\n"
            f"📦 Total: *{total}* \\| ✅ Claimed: *{claimed}* \\| 📭 Unclaimed: *{unclaimed}*\n"
            f"📁 File: `{escape_md(filename)}`"
        ),
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await callback.answer(f"📄 {unclaimed} codes exported!")
    logger.info(f"Admin {callback.from_user.id} downloaded {unclaimed} unclaimed codes for giveaway {gid}")


@router.callback_query(F.data == "admin_giveaway_toggle_all")
@admin_only
@error_handler
async def cb_giveaway_toggle_all(callback: types.CallbackQuery):
    """Enable or disable ALL giveaways at once."""
    giveaways = await db.get_all_free_coupons()
    any_active = any(g["is_active"] for g in giveaways)
    # If any are active → disable all; otherwise enable all
    new_status = not any_active
    await db.set_all_free_coupons_active(new_status)
    action = "enabled 🟢" if new_status else "disabled 🔴"
    await callback.answer(f"All giveaways {action}", show_alert=True)
    await db.add_admin_log(
        callback.from_user.id, "toggle_all_giveaways", "giveaway", None,
        f"Set all giveaways to {'active' if new_status else 'inactive'}"
    )
    await cb_admin_giveaways(callback)


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
    kb = InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]])
    await callback.message.edit_text(
        "📄 Send more codes \\(one per line\\) or upload a \\.txt file:",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await state.set_state(AdminStates.giveaway_add_codes)
    await callback.answer()


@router.message(AdminStates.giveaway_add_codes)
@error_handler
async def msg_giveaway_add_more_codes(message: types.Message, state: FSMContext):
    """Receive additional codes for existing giveaway."""

    codes = []
    if message.document:
        import io
        try:
            file = await message.bot.get_file(message.document.file_id)
            file_bytes = await message.bot.download_file(file.file_path)
            if isinstance(file_bytes, io.BytesIO):
                content = file_bytes.read().decode("utf-8", errors="ignore")
            else:
                content = file_bytes.decode("utf-8", errors="ignore")
            codes = [line.strip() for line in content.splitlines() if line.strip()]
        except Exception as e:
            logger.error(f"File download error: {e}")
            await message.answer(f"❌ Error reading file: {escape_md(str(e))}", parse_mode="MarkdownV2")
            return
    elif message.text:
        codes = [line.strip() for line in message.text.strip().splitlines() if line.strip()]

    if not codes:
        await message.answer("⚠️ No codes found. Send codes one per line or upload a .txt file.")
        return

    data = await state.get_data()
    gid = data["add_codes_giveaway_id"]
    await state.clear()

    try:
        await db.add_giveaway_codes(gid, codes)
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_giveaways")]])
        await message.answer(
            f"✅ Added *{len(codes)}* codes to Giveaway \\#{escape_md(str(gid))}\\!",
            parse_mode="MarkdownV2", reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Add codes error: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_giveaways")]])
        await message.answer(
            f"❌ Error adding codes: {escape_md(str(e))}",
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
    reward_amt = settings.get("reward_amount", 10.0) or 10.0
    active = "🟢 Active" if settings["is_active"] else "🔴 Disabled"

    # Mode labels
    mode_labels = {
        "code_reward": "🎁 Coupon Reward",
        "commission": "💰 Purchase Commission",
        "wallet_reward": "💵 Instant Wallet Reward",
    }
    current_label = mode_labels.get(mode, mode)
    pct_esc = escape_md(str(pct))
    amt_esc = escape_md(f"₹{float(reward_amt):.1f}")

    text = (
        f"🤝 *Referral Settings*\n\n"
        f"Status: {active}\n"
        f"Mode: {current_label}\n\n"
    )

    if mode == "commission":
        text += f"💰 Commission: {pct_esc}% per purchase\n"
    elif mode == "wallet_reward":
        text += f"💵 Reward: {amt_esc} per referral\n"
    else:
        rewards = await db.get_referral_rewards()
        if rewards:
            text += "🎁 *Reward Coupons:*\n"
            for r in rewards:
                si = "🟢" if r["is_active"] else "🔴"
                text += f"{si} {escape_md(r['title'])} — {r['referrals_needed']} referrals\n"
        else:
            text += "⚠️ No reward coupons configured yet\n"

    # Build keyboard — 3 mode selection buttons
    buttons = []

    # Mode selector row
    for m_key, m_label in mode_labels.items():
        check = "✅ " if m_key == mode else ""
        buttons.append([InlineKeyboardButton(
            text=f"{check}{m_label}",
            callback_data=f"admin_ref_set_mode:{m_key}"
        )])

    # Mode-specific settings
    if mode == "commission":
        buttons.append([InlineKeyboardButton(text="✏️ Edit Commission %", callback_data="admin_ref_edit_commission")])
    elif mode == "wallet_reward":
        buttons.append([InlineKeyboardButton(text="✏️ Edit Reward Amount", callback_data="admin_ref_edit_reward_amount")])
    elif mode == "code_reward":
        buttons.append([InlineKeyboardButton(text="➕ Add Reward Coupon", callback_data="admin_ref_add_reward")])
        rewards = await db.get_referral_rewards()
        for r in rewards:
            si = "🟢" if r["is_active"] else "🔴"
            buttons.append([InlineKeyboardButton(
                text=f"{si} {r['title'][:25]} ({r['referrals_needed']} refs)",
                callback_data=f"admin_ref_reward_view:{r['id']}"
            )])

    toggle_text = "🔴 Disable Referrals" if settings["is_active"] else "🟢 Enable Referrals"
    buttons.append([InlineKeyboardButton(text=toggle_text, callback_data="admin_ref_toggle_active")])
    buttons.append([back_button("admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ref_set_mode:"))
@admin_only
@error_handler
async def cb_ref_set_mode(callback: types.CallbackQuery):
    """Set referral mode from 3-button selector."""
    new_mode = callback.data.split(":")[1]
    valid_modes = ("code_reward", "commission", "wallet_reward")
    if new_mode not in valid_modes:
        await callback.answer("Invalid mode.", show_alert=True)
        return

    # Skip if already on this mode
    settings = await db.get_referral_settings()
    if settings and settings["mode"] == new_mode:
        await callback.answer("Already on this mode.", show_alert=True)
        return

    await db.update_referral_settings(mode=new_mode)
    mode_names = {"code_reward": "🎁 Coupon Reward", "commission": "💰 Purchase Commission", "wallet_reward": "💵 Instant Wallet Reward"}
    await callback.answer(f"Mode set to {mode_names[new_mode]}!", show_alert=True)
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
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_referral_settings"), admin_cancel_button()]
        ]),
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


@router.callback_query(F.data == "admin_ref_edit_reward_amount")
@admin_only
@error_handler
async def cb_ref_edit_reward_amount(callback: types.CallbackQuery, state: FSMContext):
    settings = await db.get_referral_settings()
    current = settings.get("reward_amount", 10.0) or 10.0
    await callback.message.edit_text(
        f"💵 *Edit Wallet Reward Amount*\n\n"
        f"Current: ₹{escape_md(str(float(current)))}\n\n"
        f"Enter new reward amount \\(e\\.g\\. 10 or 25\\.5\\):",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_referral_settings"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.ref_reward_amount_input)
    await callback.answer()


@router.message(AdminStates.ref_reward_amount_input)
@error_handler
async def msg_ref_reward_amount_input(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.strip())
        if val <= 0 or val > 100000:
            raise ValueError
        await db.update_referral_settings(reward_amount=val)
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_referral_settings")]])
        await message.answer(f"✅ Reward amount updated to ₹{val}", reply_markup=kb)
    except ValueError:
        await message.answer("⚠️ Please enter a valid amount (e.g. 10 or 25.5).")


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
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_referral_settings"), admin_cancel_button()]
        ]),
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
    bot_name = (settings.get("bot_name") or "DreamX Store") if settings else "DreamX Store"
    
    dyn = await db.get_dynamic_config()
    
    timeout_val = dyn["payment_timeout_seconds"]
    min_recharge = dyn["bharatpe_min_recharge"]
    poll_val = dyn["payment_poll_interval"]
    reservation_on = dyn.get("reservation_enabled", True)
    waitlist_on = dyn.get("waitlist_enabled", True)
    
    res_icon = "🟢 ON" if reservation_on else "🔴 OFF"
    wl_icon = "🟢 ON" if waitlist_on else "🔴 OFF"
    
    text = (
        f"⚙️ *Bot Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏷️ *Bot Name:* `{escape_md(bot_name)}`\n\n"
        f"━━━ *Dynamic Config* ━━━\n"
        f"⏱️ Payment Timeout: *{timeout_val}s* \\({timeout_val // 60} min\\)\n"
        f"💰 Min Recharge \\(BharatPe\\): *₹{min_recharge:.0f}*\n"
        f"🔄 Expiry Poll Interval: *{poll_val}s*\n\n"
        f"━━━ *System Controls* ━━━\n"
        f"🔒 Reservation System: *{res_icon}*\n"
        f"   _When ON: stock is locked per order \\(prevents overselling\\)_\n"
        f"   _When OFF: first\\-paid\\-first\\-served, no locking_\n\n"
        f"📋 Waitlist System: *{wl_icon}*\n"
        f"   _When ON: out\\-of\\-stock users join a queue & get notified_\n"
        f"   _When OFF: users see simple out\\-of\\-stock message_\n"
    )
    
    res_toggle_text = "🔴 Disable Reservation" if reservation_on else "🟢 Enable Reservation"
    wl_toggle_text = "🔴 Disable Waitlist" if waitlist_on else "🟢 Enable Waitlist"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✏️ Bot Name: {bot_name}", callback_data="admin_change_bot_name")],
        [InlineKeyboardButton(text="⏱️ Payment Timeout", callback_data="admin_dynconf:payment_timeout_seconds"),
         InlineKeyboardButton(text="💰 Min Recharge", callback_data="admin_dynconf:bharatpe_min_recharge")],
        [InlineKeyboardButton(text="🔄 Poll Interval", callback_data="admin_dynconf:payment_poll_interval")],
        [InlineKeyboardButton(text=res_toggle_text, callback_data="admin_toggle_reservation")],
        [InlineKeyboardButton(text=wl_toggle_text, callback_data="admin_toggle_waitlist")],
        [InlineKeyboardButton(text="👮 Manage Admins", callback_data="admin_manage_admins")],
        [back_button("admin_panel")],
    ])

    await callback.message.edit_text(
        text, parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer()


# ── Reservation System Toggle ─────────────────────────────

@router.callback_query(F.data == "admin_toggle_reservation")
@admin_only
@error_handler
async def cb_admin_toggle_reservation(callback: types.CallbackQuery):
    """Toggle the stock reservation system on/off."""
    dyn = await db.get_dynamic_config()
    current = dyn.get("reservation_enabled", True)
    new_val = not current
    await db.update_bot_settings(reservation_enabled=new_val)
    status = "🟢 Enabled" if new_val else "🔴 Disabled"
    await db.add_admin_log(
        callback.from_user.id, "toggle_reservation", "bot_settings", "reservation_enabled",
        f"Reservation system {'enabled' if new_val else 'disabled'}"
    )
    logger.info(f"Admin {callback.from_user.id} toggled reservation system: {status}")
    await callback.answer(f"Reservation System: {status}", show_alert=True)
    await cb_admin_bot_settings(callback)


# ── Waitlist Toggle ───────────────────────────────────────

@router.callback_query(F.data == "admin_toggle_waitlist")
@admin_only
@error_handler
async def cb_admin_toggle_waitlist(callback: types.CallbackQuery):
    """Toggle the waitlist system on/off."""
    dyn = await db.get_dynamic_config()
    current = dyn.get("waitlist_enabled", True)
    new_val = not current
    await db.update_bot_settings(waitlist_enabled=new_val)
    status = "🟢 Enabled" if new_val else "🔴 Disabled"
    await db.add_admin_log(
        callback.from_user.id, "toggle_waitlist", "bot_settings", "waitlist_enabled",
        f"Waitlist system {'enabled' if new_val else 'disabled'}"
    )
    logger.info(f"Admin {callback.from_user.id} toggled waitlist system: {status}")
    await callback.answer(f"Waitlist System: {status}", show_alert=True)
    await cb_admin_bot_settings(callback)




# ── Force Join Channel Management (Dedicated Page) ───────

@router.callback_query(F.data == "admin_force_join")
@admin_only
@error_handler
async def cb_admin_force_join(callback: types.CallbackQuery):
    """Dedicated Force Join management page — shows all channels, add/remove."""
    settings = await db.get_bot_settings()
    force_channel_raw = settings.get("force_channel") if settings else None
    apply_admins = settings.get("force_join_apply_admins", False) if settings else False

    channels = [ch.strip() for ch in force_channel_raw.split(",") if ch.strip()] if force_channel_raw else []

    # Verify each channel
    bot = callback.bot
    ch_lines = []
    for i, ch in enumerate(channels):
        try:
            chat_id = int(ch) if ch.lstrip("-").isdigit() else ch
            chat_info = await bot.get_chat(chat_id)
            title = escape_md(chat_info.title or ch)
            ch_lines.append(f"  {i+1}\\. ✅ *{title}* — `{escape_md(ch)}`")
        except Exception:
            ch_lines.append(f"  {i+1}\\. ❌ `{escape_md(ch)}` — _bot not admin_")

    status = "🟢 Active" if channels else "🔴 Disabled"
    count = len(channels)
    admin_icon = "🟢 Yes" if apply_admins else "🔴 No"

    if ch_lines:
        ch_text = "\n".join(ch_lines)
    else:
        ch_text = "  _No channels configured_"

    text = (
        f"🔐 *Force Join Channels*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Users must join these channels/groups\n"
        f"before they can use the bot\\.\n\n"
        f"Status: {status} \\({count} channel{'s' if count != 1 else ''}\\)\n"
        f"👮 Apply to Admins: {admin_icon}\n\n"
        f"📋 *Configured Channels:*\n"
        f"{ch_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Bot must be *admin* in each channel\\!"
    )

    # Admin toggle button text
    admin_toggle_text = "👮 Admins: 🟢 Must Join — tap to skip" if apply_admins else "👮 Admins: 🔴 Skipped — tap to enforce"

    buttons = [
        [InlineKeyboardButton(text="➕ Add Channel(s)", callback_data="admin_fj_add")],
        [InlineKeyboardButton(text=admin_toggle_text, callback_data="admin_fj_toggle_admins")],
    ]

    # Remove buttons for each channel
    for i, ch in enumerate(channels):
        short = ch[:25] + "..." if len(ch) > 25 else ch
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ Remove {short}",
            callback_data=f"admin_fj_remove:{i}"
        )])

    if channels:
        buttons.append([InlineKeyboardButton(text="🔴 Remove All Channels", callback_data="admin_fj_clear")])

    buttons.append([back_button("admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


# Legacy redirect — old "admin_toggle_force_join" from Bot Settings
@router.callback_query(F.data == "admin_toggle_force_join")
@admin_only
@error_handler
async def cb_admin_toggle_force_join_legacy(callback: types.CallbackQuery):
    """Redirect to the new force join page."""
    await cb_admin_force_join(callback)


@router.callback_query(F.data == "admin_fj_add")
@admin_only
@error_handler
async def cb_admin_fj_add(callback: types.CallbackQuery, state: FSMContext):
    """Ask admin to send channel IDs to add."""
    await callback.message.edit_text(
        "📢 *Add Force Join Channel\\(s\\)*\n\n"
        "Send the *Channel/Group ID* or *@username*\n\n"
        "You can add multiple at once \\(comma\\-separated\\):\n\n"
        "Examples:\n"
        "• `@MyChannel`\n"
        "• `\\-1001234567890`\n"
        "• `@Channel1, @Channel2, \\-100123`\n\n"
        "💡 Use /id command in your channel to get the ID\\.\n\n"
        "⚠️ *IMPORTANT*: Bot MUST be admin in each channel\\!",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_force_join"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.force_channel_input)
    await callback.answer()


@router.message(AdminStates.force_channel_input)
@error_handler
async def msg_force_channel_input(message: types.Message, state: FSMContext):
    val = message.text.strip() if message.text else ""
    if not val:
        await message.answer("⚠️ Please send a channel ID or @username\\.", parse_mode="MarkdownV2")
        return

    new_channels = [ch.strip() for ch in val.split(",") if ch.strip()]
    valid = []
    errors = []
    
    for ch in new_channels:
        try:
            chat_id = int(ch) if ch.lstrip("-").isdigit() else ch
            chat_info = await message.bot.get_chat(chat_id)
            # Try to generate invite link (ensures bot is admin)
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
    
    # Merge with existing channels (don't duplicate)
    settings = await db.get_bot_settings()
    existing_raw = settings.get("force_channel") if settings else None
    existing = [ch.strip() for ch in existing_raw.split(",") if ch.strip()] if existing_raw else []
    
    # Normalize for dedup
    for v in valid:
        if v not in existing:
            existing.append(v)
    
    save_val = ",".join(existing)
    await db.update_bot_settings(force_channel=save_val)
    await state.clear()
    
    result = f"✅ Force Join updated\\!\n\nTotal channels: *{len(existing)}*"
    added = escape_md(", ".join(valid))
    result += f"\nAdded: `{added}`"
    if errors:
        skipped = escape_md(", ".join(e.split(":")[0] for e in errors))
        result += f"\n\n⚠️ Skipped invalid: {skipped}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_force_join")]])
    await message.answer(result, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data.startswith("admin_fj_remove:"))
@admin_only
@error_handler
async def cb_admin_fj_remove(callback: types.CallbackQuery):
    """Remove a specific channel from force join list by index."""
    idx = int(callback.data.split(":")[1])
    
    settings = await db.get_bot_settings()
    force_channel_raw = settings.get("force_channel") if settings else None
    channels = [ch.strip() for ch in force_channel_raw.split(",") if ch.strip()] if force_channel_raw else []
    
    if idx < 0 or idx >= len(channels):
        await callback.answer("Channel not found.", show_alert=True)
        return
    
    removed = channels.pop(idx)
    save_val = ",".join(channels) if channels else None
    await db.update_bot_settings(force_channel=save_val)
    
    await callback.answer(f"✅ Removed: {removed}", show_alert=True)
    await cb_admin_force_join(callback)


@router.callback_query(F.data == "admin_fj_clear")
@admin_only
@error_handler
async def cb_admin_fj_clear(callback: types.CallbackQuery):
    """Remove ALL force join channels."""
    await db.update_bot_settings(force_channel=None)
    await callback.answer("✅ All force join channels removed!", show_alert=True)
    await cb_admin_force_join(callback)


@router.callback_query(F.data == "admin_fj_toggle_admins")
@admin_only
@error_handler
async def cb_admin_fj_toggle_admins(callback: types.CallbackQuery):
    """Toggle whether force join also applies to admins."""
    settings = await db.get_bot_settings()
    current = settings.get("force_join_apply_admins", False) if settings else False
    new_val = not current
    await db.update_bot_settings(force_join_apply_admins=new_val)
    status = "enforced for admins too" if new_val else "skipped for admins"
    await callback.answer(f"👮 Force Join {status}!", show_alert=True)
    await cb_admin_force_join(callback)


# ── Bot Name Change ──────────────────────────────────────

@router.callback_query(F.data == "admin_change_bot_name")
@admin_only
@error_handler
async def cb_admin_change_bot_name(callback: types.CallbackQuery, state: FSMContext):
    settings = await db.get_bot_settings()
    current = (settings.get("bot_name") or "DreamX Store") if settings else "DreamX Store"

    await callback.message.edit_text(
        f"✏️ *Change Bot Name*\n\n"
        f"Current name: `{escape_md(current)}`\n\n"
        f"Send the new bot name\\.\n"
        f"This name will appear on:\n"
        f"• Payment QR codes\n"
        f"• Bot settings panel\n\n"
        f"_Max 64 characters_",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_bot_settings"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.bot_name_input)
    await callback.answer()


@router.message(AdminStates.bot_name_input)
@error_handler
async def msg_bot_name_input(message: types.Message, state: FSMContext):
    new_name = (message.text or "").strip()
    if not new_name:
        await message.answer("⚠️ Please enter a valid name.")
        return
    if len(new_name) > 64:
        await message.answer("⚠️ Name is too long. Max 64 characters.")
        return

    await db.update_bot_settings(bot_name=new_name)
    await state.clear()

    await db.add_admin_log(
        message.from_user.id, "change_bot_name", "settings", None,
        f"Changed bot name to: {new_name}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_bot_settings")]])
    await message.answer(
        f"✅ Bot name updated to: *{escape_md(new_name)}*\n\n"
        f"The new name will now appear on payment QR codes and other dynamic areas\\.",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


# ══════════════════════════════════════════════════════════
# DYNAMIC CONFIG EDITOR
# ══════════════════════════════════════════════════════════

DYNCONF_LABELS = {
    "payment_timeout_seconds": ("⏱️ Payment Timeout", "seconds", "How long to wait before expiring orders (in seconds). Example: 600 = 10 minutes"),
    "bharatpe_min_recharge": ("💰 Min Recharge", "INR", "Minimum BharatPe payment amount in INR. Example: 10"),
    "payment_poll_interval": ("🔄 Poll Interval", "seconds", "How often to check for expired orders (in seconds). Example: 30"),
}

@router.callback_query(F.data.startswith("admin_dynconf:"))
@admin_only
@error_handler
async def cb_admin_dynconf(callback: types.CallbackQuery, state: FSMContext):
    """Ask admin for new value of a dynamic config field."""
    field = callback.data.split(":")[1]
    if field not in DYNCONF_LABELS:
        await callback.answer("Invalid setting.", show_alert=True)
        return

    label, unit, hint = DYNCONF_LABELS[field]
    dyn = await db.get_dynamic_config()
    current = dyn.get(field, "?")

    await state.update_data(dynconf_field=field)
    await callback.message.edit_text(
        f"✏️ *Edit: {label}*\n\n"
        f"Current value: `{escape_md(str(current))}` {escape_md(unit)}\n\n"
        f"💡 {escape_md(hint)}\n\n"
        f"Send the new value:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_bot_settings"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.dynamic_config_input)
    await callback.answer()


@router.message(AdminStates.dynamic_config_input)
@error_handler
async def msg_dynconf_input(message: types.Message, state: FSMContext):
    """Process dynamic config value input."""
    data = await state.get_data()
    field = data.get("dynconf_field")
    await state.clear()

    if not field or field not in DYNCONF_LABELS:
        await message.answer("❌ Invalid config field.")
        return

    raw = message.text.strip()
    try:
        if field == "bharatpe_min_recharge":
            val = float(raw)
        else:
            val = int(raw)
        if val <= 0:
            raise ValueError("Must be positive")
    except (ValueError, TypeError):
        await message.answer("❌ Invalid number. Please enter a positive number.")
        return

    # Get old value for audit
    dyn = await db.get_dynamic_config()
    old_val = dyn.get(field, "?")

    await db.update_bot_settings(**{field: val})

    label = DYNCONF_LABELS[field][0]
    await db.add_admin_log(
        message.from_user.id, "config_change", "bot_settings", field,
        f"Changed {label}: {old_val} → {val}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_bot_settings")]])
    await message.answer(
        f"✅ *{escape_md(label)}* updated\\!\n\n"
        f"Old: `{escape_md(str(old_val))}`\n"
        f"New: `{escape_md(str(val))}`",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
    logger.info(f"Admin {message.from_user.id} changed {field}: {old_val} → {val}")


# ══════════════════════════════════════════════════════════
# ADMIN MANAGEMENT
# ══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_manage_admins")
@admin_only
@error_handler
async def cb_admin_manage_admins(callback: types.CallbackQuery):
    """Show admin list with add/remove options."""
    from bot.config import Config

    # Seed admins from .env
    seed_ids = Config.ADMIN_IDS
    # DB admins
    db_admins = await db.get_all_admins()

    lines = ["👮 *Admin Management*", "━━━━━━━━━━━━━━━━━━━━", ""]
    lines.append("*Seed Admins* \\(from \\.env — cannot remove\\):")
    for sid in seed_ids:
        lines.append(f"  🔒 `{sid}`")

    lines.append("")
    if db_admins:
        lines.append("*Dynamic Admins* \\(added via panel\\):")
        for adm in db_admins:
            tid = adm["telegram_id"]
            added_by = adm["added_by"]
            lines.append(f"  👤 `{tid}` — added by `{added_by}`")
    else:
        lines.append("_No dynamic admins added yet_")

    text = "\n".join(lines)

    buttons = [
        [InlineKeyboardButton(text="➕ Add Admin", callback_data="admin_add_admin")],
    ]
    # Remove buttons for DB admins only
    for adm in db_admins:
        tid = adm["telegram_id"]
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ Remove {tid}",
            callback_data=f"admin_remove_admin:{tid}"
        )])

    buttons.append([back_button("admin_bot_settings")])

    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_add_admin")
@admin_only
@error_handler
async def cb_admin_add_admin(callback: types.CallbackQuery, state: FSMContext):
    """Ask for Telegram ID of new admin."""
    await callback.message.edit_text(
        "👮 *Add New Admin*\n\n"
        "Send the *Telegram ID* of the user you want to add as admin\\.\n\n"
        "💡 The user can find their ID using @userinfobot",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_manage_admins"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.add_admin_input)
    await callback.answer()


@router.message(AdminStates.add_admin_input)
@error_handler
async def msg_add_admin_input(message: types.Message, state: FSMContext):
    """Process new admin Telegram ID."""
    await state.clear()
    raw = message.text.strip()

    if not raw.lstrip("-").isdigit():
        await message.answer("❌ Please enter a valid Telegram ID (numbers only).")
        return

    new_admin_id = int(raw)
    from bot.config import Config, refresh_admin_cache

    if Config.is_admin(new_admin_id):
        await message.answer("⚠️ This user is already an admin.")
        return

    success = await db.add_admin(new_admin_id, message.from_user.id)
    if success:
        # Refresh cache
        db_ids = await db.get_db_admin_ids()
        refresh_admin_cache(db_ids)

        await db.add_admin_log(
            message.from_user.id, "add_admin", "admin", str(new_admin_id),
            f"Added {new_admin_id} as admin"
        )
        logger.info(f"Admin {message.from_user.id} added {new_admin_id} as admin")

        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_manage_admins")]])
        await message.answer(
            f"✅ *Admin Added\\!*\n\nTelegram ID: `{new_admin_id}`",
            parse_mode="MarkdownV2", reply_markup=kb,
        )
    else:
        await message.answer("❌ Failed to add admin. They may already exist.")


@router.callback_query(F.data.startswith("admin_remove_admin:"))
@admin_only
@error_handler
async def cb_admin_remove_admin(callback: types.CallbackQuery):
    """Remove a dynamic admin."""
    tid = int(callback.data.split(":")[1])
    from bot.config import Config, refresh_admin_cache

    # Cannot remove seed admins
    if Config.is_seed_admin(tid):
        await callback.answer("🔒 Cannot remove seed admin (.env)", show_alert=True)
        return

    success = await db.remove_admin(tid)
    if success:
        # Refresh cache
        db_ids = await db.get_db_admin_ids()
        refresh_admin_cache(db_ids)

        await db.add_admin_log(
            callback.from_user.id, "remove_admin", "admin", str(tid),
            f"Removed {tid} from admins"
        )
        logger.info(f"Admin {callback.from_user.id} removed {tid} from admins")
        await callback.answer(f"✅ Removed admin {tid}", show_alert=True)
    else:
        await callback.answer("❌ Admin not found.", show_alert=True)

    # Refresh the page
    await cb_admin_manage_admins(callback)


# ══════════════════════════════════════════════════════════
# PAYMENT SETTINGS (Dynamic from Admin Panel)
# ══════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_payments")
@admin_only
@error_handler
async def cb_admin_payments(callback: types.CallbackQuery):
    """Show current payment gateway configuration with enable/disable toggles."""
    ps = await db.get_payment_settings()

    paytm_mid = escape_md(ps["paytm_mid"] or "Not Set")
    paytm_upi = escape_md(ps["paytm_upi_id"] or "Not Set")
    bp_mid = escape_md(ps["bharatpe_merchant_id"] or "Not Set")
    bp_token = escape_md((ps["bharatpe_token"] or "Not Set")[:20] + "..." if ps["bharatpe_token"] and len(ps["bharatpe_token"]) > 20 else ps["bharatpe_token"] or "Not Set")
    bp_upi = escape_md(ps["bharatpe_upi_id"] or "Not Set")
    bp_qr = "✅ Uploaded" if ps["bharatpe_qr_path"] else "❌ Not Set"
    payee = escape_md(ps["upi_payee_name"] or "Not Set")

    # Gateway toggles
    paytm_on = ps.get("gateway_paytm_enabled", True)
    bp_on = ps.get("gateway_bharatpe_enabled", True)
    rp_on = ps.get("gateway_razorpay_enabled", False)

    paytm_status = "🟢 ON" if paytm_on else "🔴 OFF"
    bp_status = "🟢 ON" if bp_on else "🔴 OFF"
    rp_status = "🟢 ON" if rp_on else "🔴 OFF"

    rp_key = escape_md(ps.get("razorpay_key_id") or "Not Set")
    rp_secret = escape_md("•••••" if ps.get("razorpay_key_secret") else "Not Set")

    text = (
        f"💳 *Payment Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Gateway Status:*\n"
        f"  ✅ Paytm: *{paytm_status}*\n"
        f"  🏦 BharatPe: *{bp_status}*\n"
        f"  💳 Razorpay: *{rp_status}*\n\n"
        f"━━━ *Paytm* ━━━\n"
        f"🏢 MID: `{paytm_mid}`\n"
        f"📱 UPI ID: `{paytm_upi}`\n\n"
        f"━━━ *BharatPe* ━━━\n"
        f"🏢 Merchant ID: `{bp_mid}`\n"
        f"🔑 Token: `{bp_token}`\n"
        f"📱 UPI ID: `{bp_upi}`\n"
        f"📷 QR Image: {bp_qr}\n\n"
        f"━━━ *Razorpay* ━━━\n"
        f"🔑 Key ID: `{rp_key}`\n"
        f"🔐 Secret: `{rp_secret}`\n\n"
        f"━━━ *General* ━━━\n"
        f"👤 Payee Name: `{payee}`\n"
    )

    # Toggle buttons
    paytm_toggle = "🔴 Disable Paytm" if paytm_on else "🟢 Enable Paytm"
    bp_toggle = "🔴 Disable BharatPe" if bp_on else "🟢 Enable BharatPe"
    rp_toggle = "🔴 Disable Razorpay" if rp_on else "🟢 Enable Razorpay"

    buttons = [
        # Gateway toggles
        [InlineKeyboardButton(text=paytm_toggle, callback_data="admin_gw_toggle:gateway_paytm_enabled"),
         InlineKeyboardButton(text=bp_toggle, callback_data="admin_gw_toggle:gateway_bharatpe_enabled")],
        [InlineKeyboardButton(text=rp_toggle, callback_data="admin_gw_toggle:gateway_razorpay_enabled")],
        # Paytm settings
        [InlineKeyboardButton(text="🏢 Paytm MID", callback_data="admin_pay_edit:paytm_mid"),
         InlineKeyboardButton(text="📱 Paytm UPI", callback_data="admin_pay_edit:paytm_upi_id")],
        # BharatPe settings
        [InlineKeyboardButton(text="🏢 BP Merchant", callback_data="admin_pay_edit:bharatpe_merchant_id"),
         InlineKeyboardButton(text="🔑 BP Token", callback_data="admin_pay_edit:bharatpe_token")],
        [InlineKeyboardButton(text="📱 BP UPI ID", callback_data="admin_pay_edit:bharatpe_upi_id")],
        [InlineKeyboardButton(text="📷 Upload BP QR Image", callback_data="admin_pay_upload_qr")],
        # Razorpay settings
        [InlineKeyboardButton(text="🔑 Razorpay Key ID", callback_data="admin_pay_edit:razorpay_key_id"),
         InlineKeyboardButton(text="🔐 Razorpay Secret", callback_data="admin_pay_edit:razorpay_key_secret")],
        # General
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
    "razorpay_key_id": "Razorpay Key ID",
    "razorpay_key_secret": "Razorpay Key Secret",
}


@router.callback_query(F.data.startswith("admin_gw_toggle:"))
@admin_only
@error_handler
async def cb_admin_gw_toggle(callback: types.CallbackQuery):
    """Toggle a payment gateway on/off."""
    field = callback.data.split(":")[1]
    allowed = ("gateway_paytm_enabled", "gateway_bharatpe_enabled", "gateway_razorpay_enabled")
    if field not in allowed:
        await callback.answer("Invalid gateway.", show_alert=True)
        return

    settings = await db.get_bot_settings()
    current = settings.get(field, False)
    new_val = not current

    await db.update_bot_settings(**{field: new_val})

    gw_name = field.replace("gateway_", "").replace("_enabled", "").title()
    status = "🟢 Enabled" if new_val else "🔴 Disabled"

    await db.add_admin_log(
        callback.from_user.id, "gateway_toggle", "payment", field,
        f"{gw_name} gateway {'enabled' if new_val else 'disabled'}"
    )
    await callback.answer(f"{gw_name}: {status}")

    # Refresh the payments page
    await cb_admin_payments(callback)


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
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_payments"), admin_cancel_button()]
        ]),
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
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_payments"), admin_cancel_button()]
        ]),
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
        [InlineKeyboardButton(text=f"📋 All Users ({user_count})", callback_data="admin_users_all:1")],
        [admin_cancel_button()],
    ]
    await callback.message.edit_text(text, parse_mode="MarkdownV2",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_users_all:"))
@admin_only
@error_handler
async def cb_admin_users_all(callback: types.CallbackQuery):
    """Paginated list of ALL users."""
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1
    per_page = 15
    offset = (page - 1) * per_page

    total = await db.get_user_count()
    users = await db.get_users_paginated(per_page, offset)

    if not users and page == 1:
        await callback.answer("No users found.", show_alert=True)
        return

    total_pages = (total + per_page - 1) // per_page  # ceiling division

    buttons = []
    for u in users:
        name = u["full_name"] or u["username"] or str(u["telegram_id"])
        banned = "🚫 " if u.get("is_banned") else ""
        buttons.append([InlineKeyboardButton(
            text=f"{banned}{name[:25]} ({u['telegram_id']})",
            callback_data=f"admin_user_inspect:{u['telegram_id']}"
        )])

    # Pagination nav
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"admin_users_all:{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_users_all:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([back_button("admin_users")])

    await callback.message.edit_text(
        f"👥 *All Users* — Page {page}/{total_pages}\n"
        f"📊 Total: *{total}* users\n\n"
        f"Tap a user to inspect:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_users_recent")
@admin_only
@error_handler
async def cb_admin_users_recent(callback: types.CallbackQuery):
    """Redirect old 'recent' button to page 1 of all users."""
    callback.data = "admin_users_all:1"
    await cb_admin_users_all(callback)



@router.message(AdminStates.user_search_input)
@error_handler
async def msg_user_search(message: types.Message, state: FSMContext):
    data = await state.get_data()
    query = message.text.strip()
    search_type = data.get("search_type", "user")
    await state.clear()

    # Order ID search
    if search_type == "order_id":
        order = await db.get_order_by_id_admin(query)
        if not order:
            kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_orders")]])
            await message.answer(
                f"❌ No order found for `{escape_md(query)}`",
                parse_mode="MarkdownV2", reply_markup=kb
            )
            return

        # Show order detail inline
        status_emoji = {
            "pending": "🟡", "paid": "🟢", "delivered": "✅",
            "expired": "⏰", "cancelled": "❌", "refunded": "🔄"
        }
        emoji = status_emoji.get(order["status"], "❓")
        oid = escape_md(order["order_id"])
        title = escape_md(order.get("coupon_title") or "Unknown")
        amt = escape_md(format_currency(float(order["amount"])))
        qty = order.get("quantity") or 1
        st = escape_md(order["status"])
        uid = order["user_id"]
        uname = escape_md(order.get("full_name") or "Unknown")

        text = (
            f"📋 *Order Found*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 Order: `{oid}`\n"
            f"{emoji} Status: *{st}*\n\n"
            f"🏷️ Item: *{title}*\n"
            f"📦 Qty: *{qty}*\n"
            f"💰 Amount: *{amt}*\n\n"
            f"👤 User: *{uname}* \\(`{uid}`\\)\n"
        )

        buttons = [
            [InlineKeyboardButton(text="👤 View User", callback_data=f"admin_user_inspect:{uid}"),
             InlineKeyboardButton(text="📦 User Orders", callback_data=f"admin_order_user:{uid}")],
            [back_button("admin_orders")],
        ]
        await message.answer(text, parse_mode="MarkdownV2",
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return

    # User search (default)
    results = await db.search_user(query)

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
    user = await db.get_user(user_id)

    user_name = escape_md((user["full_name"] if user else "Unknown") or "Unknown")

    if not orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_user_inspect:{user_id}")]])
        await callback.message.edit_text(
            f"📦 *Orders for* {user_name}\n"
            f"👤 ID: `{user_id}`\n\n"
            f"_No orders found\\._",
            parse_mode="MarkdownV2", reply_markup=kb
        )
        await callback.answer()
        return

    status_emoji = {
        "pending": "🟡", "paid": "🟢", "delivered": "✅",
        "expired": "⏰", "cancelled": "❌", "refunded": "🔄"
    }

    # Calculate stats
    total = len(orders)
    paid_count = sum(1 for o in orders if o["status"] in ("paid", "delivered"))
    total_spent = sum(float(o["amount"]) for o in orders if o["status"] in ("paid", "delivered"))

    lines = [
        f"📦 *Orders for* {user_name}",
        f"👤 ID: `{user_id}`",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📊 Total: *{total}* \\| ✅ Paid: *{paid_count}* \\| 💰 {escape_md(format_currency(total_spent))}",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]

    buttons = []
    pool = await db.get_pool()

    for i, o in enumerate(orders[:15]):
        emoji = status_emoji.get(o["status"], "❓")
        oid = o["order_id"]
        oid_esc = escape_md(oid)

        # Get coupon title
        coupon_row = await pool.fetchrow("SELECT title FROM coupons WHERE id = $1", o["coupon_id"])
        coupon_title = coupon_row["title"] if coupon_row else "Unknown"
        title_esc = escape_md(coupon_title)

        amt = escape_md(format_currency(float(o["amount"])))
        qty = o.get("quantity") or 1
        st = escape_md(o["status"])
        created = o.get("created_at")
        date_str = escape_md(str(created)[:16]) if created else "N/A"

        # Source badge
        source = o.get("source", "purchase") or "purchase"
        source_label = ""
        if source == "referral_reward":
            source_label = "🏆 "
        elif source == "giveaway":
            source_label = "🎁 "

        # Get code count
        code_count = await pool.fetchval(
            "SELECT COUNT(*) FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE", oid
        ) or 0

        code_info = f"🔑 {code_count} code\\(s\\)" if code_count > 0 else ""

        lines.append(
            f"\n{emoji} *\\#{i+1}* {source_label}{title_esc}\n"
            f"   📅 {date_str}\n"
            f"   💰 {amt} x{qty} \\| 📋 {st}\n"
            f"   🆔 `{oid_esc}`"
        )
        if code_info:
            lines.append(f"   {code_info}")

        # Add per-order buttons for paid/delivered orders
        btn_row = []
        if code_count > 0:
            btn_row.append(InlineKeyboardButton(
                text=f"🔑 #{i+1} Codes",
                callback_data=f"admin_view_order_codes:{oid}"
            ))
        btn_row.append(InlineKeyboardButton(
            text=f"📋 #{i+1} Detail",
            callback_data=f"admin_order_detail:{oid}"
        ))
        if btn_row:
            buttons.append(btn_row)

    if total > 15:
        lines.append(f"\n_\\.\\.\\.showing 15 of {total} orders_")

    text = "\n".join(lines)

    buttons.append([InlineKeyboardButton(text="👤 Back to Profile", callback_data=f"admin_user_inspect:{user_id}")])
    buttons.append([back_button("admin_users")])

    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_view_order_codes:"))
@admin_only
@error_handler
async def cb_admin_view_order_codes(callback: types.CallbackQuery):
    """Admin views coupon codes for a specific order."""
    order_id = callback.data.split(":", 1)[1]
    pool = await db.get_pool()

    codes = await pool.fetch(
        "SELECT code FROM coupon_codes WHERE order_id = $1 AND is_sold = TRUE", order_id
    )

    if not codes:
        await callback.answer("No codes found for this order.", show_alert=True)
        return

    order = await db.get_order(order_id)
    user_id = order["user_id"] if order else 0

    oid_esc = escape_md(order_id)
    lines = [
        f"🔑 *Codes for Order*",
        f"🆔 `{oid_esc}`",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]
    for i, c in enumerate(codes, 1):
        code_esc = escape_md(c["code"])
        lines.append(f"{i}\\. `{code_esc}`")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"\n📦 Total: *{len(codes)}* code\\(s\\)")

    buttons = [
        [InlineKeyboardButton(text="📋 Order Detail", callback_data=f"admin_order_detail:{order_id}")],
    ]
    if user_id:
        buttons.append([InlineKeyboardButton(text="👤 User Orders", callback_data=f"admin_user_orders:{user_id}")])
    buttons.append([back_button("admin_orders")])

    await callback.message.edit_text(
        "\n".join(lines), parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
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
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button(f"admin_user_inspect:{user_id}"), admin_cancel_button()]
        ]),
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
        [back_button(f"admin_user_inspect:{user_id}"), admin_cancel_button()],
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
    try:
        txn_type = "admin_credit" if delta >= 0 else "admin_debit"
        await db.add_wallet_transaction(
            user_id, delta, txn_type,
            bal_before=current, bal_after=new_balance,
            description=f"Admin adjustment by {message.from_user.id}",
        )
    except Exception as e:
        logger.warning(f"Wallet transaction log failed (non-critical): {e}")

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

    # Notify the user about wallet update
    try:
        delta_str = escape_md(format_currency(abs(delta)))
        bal_str = escape_md(format_currency(new_balance))
        if delta >= 0:
            user_msg = (
                f"🎉 *Reward Wallet Credited\\!*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 Amount Added: *\\+{delta_str}*\n"
                f"💎 New Balance: *{bal_str}*\n\n"
                f"You can use this balance to\n"
                f"purchase coupons directly\\! 🛍️\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🛒 Head to *Voucher Shop* to start shopping\\!"
            )
        else:
            user_msg = (
                f"📢 *Wallet Balance Updated*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"➖ Amount Deducted: *{delta_str}*\n"
                f"💎 Remaining Balance: *{bal_str}*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Contact support if you have questions\\."
            )
        await message.bot.send_message(
            user_id, user_msg, parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning(f"Could not notify user {user_id} about wallet update: {e}")

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


# ── Support Settings (support text + inline buttons) ──────

@router.callback_query(F.data == "admin_support_settings")
@admin_only
@error_handler
async def cb_admin_support_settings(callback: types.CallbackQuery):
    """Show support info management — text + inline buttons."""
    import json
    settings = await db.get_bot_settings()
    current_text = settings.get("disclaimer_text") or ""
    buttons_json = settings.get("disclaimer_buttons") or "[]"

    try:
        buttons_list = json.loads(buttons_json)
    except Exception:
        buttons_list = []

    if current_text:
        preview = escape_md(current_text[:200])
        if len(current_text) > 200:
            preview += "\\.\\.\\."
    else:
        preview = "_No support info set \\— using default_"

    btn_preview = ""
    if buttons_list:
        btn_lines = [f"  • {escape_md(b.get('text',''))} → {escape_md(b.get('url',''))}" for b in buttons_list]
        btn_preview = "\n📎 *Inline Buttons:*\n" + "\n".join(btn_lines)
    else:
        btn_preview = "\n📎 _No inline buttons_"

    text = (
        f"🆘 *Support Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 *Support Text:*\n{preview}\n"
        f"{btn_preview}\n\n"
        f"💡 _This is what users see when they click '🆘 Support'_"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Text", callback_data="admin_support_edit_text")],
        [InlineKeyboardButton(text="📎 Edit Buttons", callback_data="admin_support_edit_btns")],
        [InlineKeyboardButton(text="🗑️ Reset to Default", callback_data="admin_support_reset")],
        [back_button("admin_panel")],
    ])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_support_edit_text")
@admin_only
@error_handler
async def cb_admin_support_edit_text(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.disclaimer_text_input)
    await callback.message.edit_text(
        "✏️ *Edit Support Text*\n\n"
        "Send the new support text \\(e\\.g\\. username, contact info\\)\\.\n"
        "Use plain text \\— formatting will be applied automatically\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_support_settings"), admin_cancel_button()]
        ]),
    )
    await callback.answer()


@router.message(AdminStates.disclaimer_text_input)
@error_handler
async def msg_support_text(message: types.Message, state: FSMContext):
    text = message.text.strip() if message.text else ""
    await state.clear()
    if not text:
        await message.answer("⚠️ Text cannot be empty.")
        return
    await db.update_bot_settings(disclaimer_text=text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_support_settings")]])
    await message.answer("✅ Support text updated\\!", parse_mode="MarkdownV2", reply_markup=kb)
    logger.info(f"Admin {message.from_user.id} updated support text")


@router.callback_query(F.data == "admin_support_edit_btns")
@admin_only
@error_handler
async def cb_admin_support_edit_btns(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.disclaimer_buttons_input)
    await callback.message.edit_text(
        "📎 *Edit Support Buttons*\n\n"
        "Send inline buttons, *one per line* in this format:\n\n"
        "`Button Text \\| https://example\\.com`\n\n"
        "Example:\n"
        "`📺 Watch Video \\| https://t\\.me/channel/123`\n"
        "`💬 Support \\| https://t\\.me/supportbot`\n\n"
        "Send *clear* to remove all buttons\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_support_settings"), admin_cancel_button()]
        ]),
    )
    await callback.answer()


@router.message(AdminStates.disclaimer_buttons_input)
@error_handler
async def msg_support_buttons(message: types.Message, state: FSMContext):
    import json
    text = message.text.strip() if message.text else ""
    await state.clear()

    if text.lower() == "clear":
        await db.update_bot_settings(disclaimer_buttons="[]")
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_support_settings")]])
        await message.answer("✅ All support buttons removed\\!", parse_mode="MarkdownV2", reply_markup=kb)
        return

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
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_support_settings")]])
    await message.answer(
        f"✅ Saved *{len(buttons)}* inline button\\(s\\)\\!",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
    logger.info(f"Admin {message.from_user.id} updated support buttons: {len(buttons)}")


@router.callback_query(F.data == "admin_support_reset")
@admin_only
@error_handler
async def cb_admin_support_reset(callback: types.CallbackQuery):
    await db.update_bot_settings(disclaimer_text="", disclaimer_buttons="[]")
    await callback.answer("✅ Support info reset to default!", show_alert=True)
    await cb_admin_support_settings(callback)


# ── Disclaimer Settings (separate from Support) ──────────

@router.callback_query(F.data == "admin_disclaimer_settings")
@admin_only
@error_handler
async def cb_admin_disclaimer_settings(callback: types.CallbackQuery):
    """Manage disclaimer text + display mode (button/description/disabled)."""
    settings = await db.get_bot_settings()
    disclaimer_content = settings.get("disclaimer_content") or ""
    disclaimer_mode = settings.get("disclaimer_mode") or "button"

    if disclaimer_content:
        preview = escape_md(disclaimer_content[:200])
        if len(disclaimer_content) > 200:
            preview += "\\.\\.\\."
    else:
        preview = "_No disclaimer text set yet_"

    if disclaimer_mode == "button":
        mode_text = "🔘 *Button* — Dedicated '⚠️ Disclaimer' button in user menu"
    elif disclaimer_mode == "description":
        mode_text = "📝 *Description* — Shows with product details when purchasing"
    else:
        mode_text = "🚫 *Disabled* — Disclaimer hidden from users"

    text = (
        f"⚠️ *Disclaimer Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 *Disclaimer Text:*\n{preview}\n\n"
        f"━━━ *Display Mode* ━━━\n"
        f"{mode_text}\n"
    )

    NEXT_LABEL = {
        "button": "📝 Switch → Description Mode",
        "description": "🚫 Switch → Disabled",
        "disabled": "🔘 Switch → Button Mode",
    }
    mode_toggle = NEXT_LABEL.get(disclaimer_mode, "🔘 Switch → Button Mode")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Disclaimer Text", callback_data="admin_discl_edit_content")],
        [InlineKeyboardButton(text=mode_toggle, callback_data="admin_discl_toggle_mode")],
        [InlineKeyboardButton(text="🗑️ Clear Disclaimer", callback_data="admin_discl_clear")],
        [back_button("admin_panel")],
    ])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_discl_toggle_mode")
@admin_only
@error_handler
async def cb_admin_discl_toggle_mode(callback: types.CallbackQuery):
    """Cycle disclaimer mode: button → description → disabled → button."""
    settings = await db.get_bot_settings()
    current = settings.get("disclaimer_mode") or "button"
    NEXT_MODE = {"button": "description", "description": "disabled", "disabled": "button"}
    new_mode = NEXT_MODE.get(current, "button")
    await db.update_bot_settings(disclaimer_mode=new_mode)

    await db.add_admin_log(
        callback.from_user.id, "disclaimer_mode_change", "bot_settings", "disclaimer_mode",
        f"Changed disclaimer mode: {current} → {new_mode}"
    )

    ALERTS = {
        "button": "🔘 Mode: Button — Disclaimer shows as menu button",
        "description": "📝 Mode: Description — Shows in product details",
        "disabled": "🚫 Mode: Disabled — Disclaimer hidden from users",
    }
    await callback.answer(ALERTS.get(new_mode, "Mode updated"), show_alert=True)
    await cb_admin_disclaimer_settings(callback)


@router.callback_query(F.data == "admin_discl_edit_content")
@admin_only
@error_handler
async def cb_admin_discl_edit_content(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.disclaimer_content_input)
    await callback.message.edit_text(
        "✏️ *Edit Disclaimer Text*\n\n"
        "Send the disclaimer text you want to show users\\.\n"
        "Use plain text \\— formatting will be applied automatically\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_disclaimer_settings"), admin_cancel_button()]
        ]),
    )
    await callback.answer()


@router.message(AdminStates.disclaimer_content_input)
@error_handler
async def msg_disclaimer_content(message: types.Message, state: FSMContext):
    text = message.text.strip() if message.text else ""
    await state.clear()
    if not text:
        await message.answer("⚠️ Text cannot be empty.")
        return
    await db.update_bot_settings(disclaimer_content=text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_disclaimer_settings")]])
    await message.answer("✅ Disclaimer text updated\\!", parse_mode="MarkdownV2", reply_markup=kb)
    logger.info(f"Admin {message.from_user.id} updated disclaimer content")


@router.callback_query(F.data == "admin_discl_clear")
@admin_only
@error_handler
async def cb_admin_discl_clear(callback: types.CallbackQuery):
    await db.update_bot_settings(disclaimer_content="")
    await callback.answer("✅ Disclaimer text cleared!", show_alert=True)
    await cb_admin_disclaimer_settings(callback)


# ── Channels Management ──────────────────────────────────

@router.callback_query(F.data == "admin_channels_settings")
@admin_only
@error_handler
async def cb_admin_channels_settings(callback: types.CallbackQuery):
    """Manage channel links shown in '📢 Our Channels'."""
    import json
    settings = await db.get_bot_settings()
    channels_json = settings.get("channels_list") or "[]"
    ch_static = settings.get("channels_static_enabled")
    ch_inline = settings.get("channels_inline_enabled")
    if ch_static is None: ch_static = True
    if ch_inline is None: ch_inline = True

    try:
        channels = json.loads(channels_json)
    except Exception:
        channels = []

    if channels:
        ch_lines = []
        for i, ch in enumerate(channels, 1):
            name = escape_md(ch.get("name", "Channel"))
            url = escape_md(ch.get("url", ""))
            ch_lines.append(f"  {i}\\. {name} → {url}")
        ch_preview = "\n".join(ch_lines)
    else:
        ch_preview = "_No channels configured yet_"

    static_icon = "🟢" if ch_static else "🔴"
    inline_icon = "🟢" if ch_inline else "🔴"

    text = (
        f"📢 *Channels Management*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 *Current Channels:*\n{ch_preview}\n\n"
        f"━━━ *Button Visibility* ━━━\n"
        f"📌 Static \\(keyboard\\): {static_icon}\n"
        f"💬 Inline \\(floating\\): {inline_icon}\n"
    )

    static_label = "🔴 Hide from Keyboard" if ch_static else "🟢 Show in Keyboard"
    inline_label = "🔴 Hide from Inline" if ch_inline else "🟢 Show in Inline"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Channels", callback_data="admin_channels_edit")],
        [InlineKeyboardButton(text=static_label, callback_data="admin_ch_toggle_static")],
        [InlineKeyboardButton(text=inline_label, callback_data="admin_ch_toggle_inline")],
        [InlineKeyboardButton(text="🗑️ Clear All", callback_data="admin_channels_clear")],
        [back_button("admin_panel")],
    ])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_channels_edit")
@admin_only
@error_handler
async def cb_admin_channels_edit(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.channels_input)
    await callback.message.edit_text(
        "📢 *Edit Channel Links*\n\n"
        "Send channels, *one per line* in this format:\n\n"
        "`Channel Name \\| https://t\\.me/channel`\n\n"
        "Example:\n"
        "`📢 Main Channel \\| https://t\\.me/dreamxdeals`\n"
        "`🎁 Offers Channel \\| https://t\\.me/dreamxoffers`\n"
        "`💬 Discussion Group \\| https://t\\.me/dreamxchat`\n\n"
        "Send *clear* to remove all channels\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_channels_settings"), admin_cancel_button()]
        ]),
    )
    await callback.answer()


@router.message(AdminStates.channels_input)
@error_handler
async def msg_channels_input(message: types.Message, state: FSMContext):
    import json
    text = message.text.strip() if message.text else ""
    await state.clear()

    if text.lower() == "clear":
        await db.update_bot_settings(channels_list="[]")
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_channels_settings")]])
        await message.answer("✅ All channels removed\\!", parse_mode="MarkdownV2", reply_markup=kb)
        return

    channels = []
    for line in text.split("\n"):
        line = line.strip()
        if "|" not in line:
            continue
        parts = line.split("|", 1)
        name = parts[0].strip()
        url = parts[1].strip()
        if name and url:
            channels.append({"name": name, "url": url})

    if not channels:
        await message.answer("⚠️ No valid channels found\\. Use format: `Name \\| URL`", parse_mode="MarkdownV2")
        return

    await db.update_bot_settings(channels_list=json.dumps(channels))

    await db.add_admin_log(
        message.from_user.id, "channels_update", "bot_settings", "channels_list",
        f"Updated channels list: {len(channels)} channels"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_channels_settings")]])
    await message.answer(
        f"✅ Saved *{len(channels)}* channel\\(s\\)\\!",
        parse_mode="MarkdownV2", reply_markup=kb,
    )
    logger.info(f"Admin {message.from_user.id} updated channels: {len(channels)}")


@router.callback_query(F.data == "admin_channels_clear")
@admin_only
@error_handler
async def cb_admin_channels_clear(callback: types.CallbackQuery):
    await db.update_bot_settings(channels_list="[]")
    await callback.answer("✅ All channels cleared!", show_alert=True)
    await cb_admin_channels_settings(callback)


@router.callback_query(F.data == "admin_ch_toggle_static")
@admin_only
@error_handler
async def cb_admin_ch_toggle_static(callback: types.CallbackQuery):
    """Toggle channels button in static keyboard."""
    settings = await db.get_bot_settings()
    current = settings.get("channels_static_enabled")
    if current is None: current = True
    new_val = not current
    await db.update_bot_settings(channels_static_enabled=new_val)
    await db.add_admin_log(
        callback.from_user.id, "channels_static_toggle", "bot_settings", "channels_static_enabled",
        f"Static keyboard channel button {'shown' if new_val else 'hidden'}"
    )
    status = "🟢 Shown" if new_val else "🔴 Hidden"
    await callback.answer(f"📌 Static keyboard: {status}", show_alert=True)
    await cb_admin_channels_settings(callback)


@router.callback_query(F.data == "admin_ch_toggle_inline")
@admin_only
@error_handler
async def cb_admin_ch_toggle_inline(callback: types.CallbackQuery):
    """Toggle channels button in inline/floating buttons."""
    settings = await db.get_bot_settings()
    current = settings.get("channels_inline_enabled")
    if current is None: current = True
    new_val = not current
    await db.update_bot_settings(channels_inline_enabled=new_val)
    await db.add_admin_log(
        callback.from_user.id, "channels_inline_toggle", "bot_settings", "channels_inline_enabled",
        f"Inline channel button {'shown' if new_val else 'hidden'}"
    )
    status = "🟢 Shown" if new_val else "🔴 Hidden"
    await callback.answer(f"💬 Inline button: {status}", show_alert=True)
    await cb_admin_channels_settings(callback)


# ── Ban Message Management ───────────────────────────────

@router.callback_query(F.data == "admin_ban_message")
@admin_only
@error_handler
async def cb_admin_ban_message(callback: types.CallbackQuery):
    """Show current ban message and management options."""
    import json
    settings = await db.get_bot_settings()
    current_text = settings.get("ban_message") or ""
    buttons_json = settings.get("ban_buttons") or "[]"

    try:
        buttons_list = json.loads(buttons_json)
    except Exception:
        buttons_list = []

    # Preview
    if current_text:
        preview = escape_md(current_text[:300])
        if len(current_text) > 300:
            preview += "\\.\\.\\."
    else:
        preview = "_No custom ban message \\— using default_"

    btn_preview = ""
    if buttons_list:
        btn_lines = [f"  • {escape_md(b.get('text',''))} → {escape_md(b.get('url',''))}" for b in buttons_list]
        btn_preview = "\n📎 *Inline Buttons:*\n" + "\n".join(btn_lines)
    else:
        btn_preview = "\n📎 _No inline buttons_"

    text = (
        f"🚫 *Ban Message Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"This message is shown to banned users\n"
        f"when they try to use the bot\\.\n\n"
        f"📝 *Current Message:*\n{preview}\n"
        f"{btn_preview}\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Message", callback_data="admin_ban_msg_edit_text")],
        [InlineKeyboardButton(text="📎 Edit Buttons", callback_data="admin_ban_msg_edit_btns")],
        [InlineKeyboardButton(text="🗑️ Reset to Default", callback_data="admin_ban_msg_reset")],
        [InlineKeyboardButton(text="👁️ Preview", callback_data="admin_ban_msg_preview")],
        [back_button("admin_panel")],
    ])
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_ban_msg_edit_text")
@admin_only
@error_handler
async def cb_admin_ban_msg_edit_text(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.ban_message_text_input)
    await callback.message.edit_text(
        "✏️ *Edit Ban Message*\n\n"
        "Send the message that banned users will see\\.\n"
        "Use plain text \\— formatting will be applied automatically\\.\n\n"
        "💡 *Tip:* Include contact info or appeal instructions\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
    )
    await callback.answer()


@router.message(AdminStates.ban_message_text_input)
@error_handler
async def msg_ban_message_text(message: types.Message, state: FSMContext):

    text = message.text.strip() if message.text else ""
    await state.clear()

    if not text:
        await message.answer("⚠️ Text cannot be empty.")
        return

    await db.update_bot_settings(ban_message=text)
    await message.answer(
        "✅ Ban message updated\\!",
        parse_mode="MarkdownV2",
    )
    logger.info(f"Admin {message.from_user.id} updated ban message")


@router.callback_query(F.data == "admin_ban_msg_edit_btns")
@admin_only
@error_handler
async def cb_admin_ban_msg_edit_btns(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.ban_message_buttons_input)
    await callback.message.edit_text(
        "📎 *Edit Ban Message Buttons*\n\n"
        "Send inline buttons, *one per line* in this format:\n\n"
        "`Button Text \\| https://example\\.com`\n\n"
        "Example:\n"
        "`📩 Appeal Ban \\| https://t\\.me/supportbot`\n"
        "`📜 Rules \\| https://t\\.me/rules`\n\n"
        "Send *clear* to remove all buttons\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
    )
    await callback.answer()


@router.message(AdminStates.ban_message_buttons_input)
@error_handler
async def msg_ban_message_buttons(message: types.Message, state: FSMContext):
    import json


    text = message.text.strip() if message.text else ""
    await state.clear()

    if text.lower() == "clear":
        await db.update_bot_settings(ban_buttons="[]")
        await message.answer("✅ All ban buttons removed\\!", parse_mode="MarkdownV2")
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

    await db.update_bot_settings(ban_buttons=json.dumps(buttons))
    await message.answer(
        f"✅ Saved *{len(buttons)}* inline button\\(s\\)\\!",
        parse_mode="MarkdownV2",
    )
    logger.info(f"Admin {message.from_user.id} updated ban buttons: {len(buttons)}")


@router.callback_query(F.data == "admin_ban_msg_reset")
@admin_only
@error_handler
async def cb_admin_ban_msg_reset(callback: types.CallbackQuery):
    await db.update_bot_settings(ban_message="", ban_buttons="[]")
    await callback.answer("✅ Ban message reset to default!", show_alert=True)
    await cb_admin_ban_message(callback)


@router.callback_query(F.data == "admin_ban_msg_preview")
@admin_only
@error_handler
async def cb_admin_ban_msg_preview(callback: types.CallbackQuery):
    """Preview the ban message as banned users would see it."""
    import json
    settings = await db.get_bot_settings()
    ban_text = settings.get("ban_message") or ""
    ban_btns_json = settings.get("ban_buttons") or "[]"

    if ban_text:
        display = escape_md(ban_text)
    else:
        display = "⛔ *You are banned from using this bot\\.*\n\nContact support if you think this is a mistake\\."

    try:
        btns = json.loads(ban_btns_json)
    except Exception:
        btns = []

    kb_buttons = []
    for b in btns:
        try:
            kb_buttons.append([InlineKeyboardButton(text=b["text"], url=b["url"])])
        except Exception:
            pass
    kb_buttons.append([back_button("admin_ban_message")])

    await callback.message.edit_text(
        f"👁️ *Ban Message Preview:*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{display}",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons),
    )
    await callback.answer()
