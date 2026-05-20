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
    admin_coupon_edit_kb, confirm_delete_kb, confirm_clear_stock_kb,
    admin_giveaways_kb, admin_giveaway_view_kb,
    admin_categories_kb, admin_category_view_kb,
    admin_category_select_kb, admin_category_select_for_add_kb,
)
from bot.keyboards.common import back_button, admin_cancel_button
from bot.utils.helpers import format_currency, format_datetime, escape_md
from bot.utils.decorators import admin_only, error_handler
from bot.utils.logger import logger

router = Router()


async def _safe_edit_or_send(message: types.Message, text: str, reply_markup=None, parse_mode="MarkdownV2"):
    """Try to edit the message text; if it fails (e.g. document/photo message), delete and send new.
    
    If MarkdownV2 parsing fails, retries with plain text (strip formatting).
    """
    import re

    async def _try_send(txt, pm):
        try:
            await message.edit_text(txt, parse_mode=pm, reply_markup=reply_markup)
        except Exception as edit_err:
            if "message is not modified" in str(edit_err).lower():
                return  # Same content — not an error
            try:
                await message.delete()
            except Exception:
                pass
            await message.answer(txt, parse_mode=pm, reply_markup=reply_markup)

    try:
        await _try_send(text, parse_mode)
    except Exception as e:
        error_str = str(e).lower()
        if "parse" in error_str or "can't" in error_str or "markdown" in error_str or "character" in error_str:
            # MarkdownV2 parse error — strip formatting and retry as plain text
            plain = re.sub(r'\\(.)', r'\1', text)      # remove escapes
            plain = re.sub(r'[*_`~]', '', plain)        # remove formatting chars
            logger.warning(f"MarkdownV2 parse failed, retrying plain: {str(e)[:100]}")
            try:
                await _try_send(plain, None)
            except Exception:
                pass  # Even plain text failed
        else:
            logger.error(f"_safe_edit_or_send failed: {e}")


# ── FSM States ────────────────────────────────────────────

class AdminStates(StatesGroup):
    # Add coupon flow
    add_title = State()
    add_description = State()
    add_original_price = State()
    add_discounted_price = State()
    add_select_category = State()  # category picker step
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
    ref_earning_cap_input = State()  # for setting max earning cap + duration
    ref_reward_count_input = State()  # for setting referrals_needed on a coupon reward
    manage_referral_user_input = State()  # search user to manage their referrals
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
    # Category management
    cat_add_name = State()
    cat_rename_input = State()
    # Manual extraction
    extract_qty_input = State()
    # Stock alert settings
    stock_alert_threshold_input = State()
    # Expense tracking
    expense_type_input = State()
    expense_amount_input = State()
    expense_desc_input = State()



# ── Universal Cancel — inline ❌ button + /cancel fallback ──

@router.callback_query(F.data == "admin_fsm_cancel")
async def cb_admin_fsm_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Cancel any active admin FSM operation via inline ❌ button."""
    await state.clear()
    await _safe_edit_or_send(
        callback.message,
        "❌ *Operation cancelled\\.*",
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


@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    """No-op button (e.g. page indicators)."""
    await callback.answer()

# ── Manage Coupons ────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^admin_coupons(:\d+)?$"))
@admin_only
@error_handler
async def cb_admin_coupons(callback: types.CallbackQuery):
    PER_PAGE = 20
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1

    total = await db.get_coupons_count()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PER_PAGE

    coupons = await db.get_coupons_paginated(PER_PAGE, offset)
    coupons = [dict(c) for c in coupons]

    text = (
        f"📦 *Manage Coupons* — Page {page}/{total_pages}\n"
        f"📊 Total: *{total}* products\n\n"
        f"Select a coupon to edit or add a new one:"
    )
    await _safe_edit_or_send(
        callback.message, text, reply_markup=admin_coupons_kb(coupons, page, total_pages)
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
    cat = escape_md(coupon.get("category") or "None")
    text = (
        f"✏️ *Edit Coupon \\#{coupon_id}*\n\n"
        f"📝 Title: {title}\n"
        f"💬 Desc: {desc}\n"
        f"💰 Original: {orig}\n"
        f"🔥 Sale: {sale}\n"
        f"🏷️ Category: {cat}\n"
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

    # Show category picker if categories exist, otherwise skip to codes
    categories = await db.get_all_categories()
    if categories:
        await message.answer(
            f"✅ Sale price: *{escape_md(format_currency(price))}*\n\n"
            f"🏷️ *Step 5/6* — Select a *category* for this coupon:",
            parse_mode="MarkdownV2",
            reply_markup=admin_category_select_for_add_kb(categories),
        )
        await state.set_state(AdminStates.add_select_category)
    else:
        await state.update_data(category=None)
        await message.answer(
            f"✅ Sale price: *{escape_md(format_currency(price))}*\n\n"
            f"🔑 *Step 5/5* — Send *coupon codes* \\(one per line\\)\\.\n\n"
            f"Or type *skip* to add codes later:",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
        )
        await state.set_state(AdminStates.add_coupon_codes)


@router.callback_query(F.data.startswith("admin_add_select_cat:"))
@admin_only
@error_handler
async def cb_add_select_category(callback: types.CallbackQuery, state: FSMContext):
    """Handle category selection during coupon add flow."""
    cat_id = int(callback.data.split(":")[1])

    if cat_id == 0:
        # No category selected
        await state.update_data(category=None)
    else:
        cat = await db.get_category(cat_id)
        if cat:
            await state.update_data(category=cat["name"])

    await callback.message.edit_text(
        "🔑 *Step 6/6* — Send *coupon codes* \\(one per line\\)\\.\n\n"
        "Or type *skip* to add codes later:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_cancel_button()]]),
    )
    await state.set_state(AdminStates.add_coupon_codes)
    await callback.answer()


@router.message(AdminStates.add_coupon_codes)
@error_handler
async def msg_add_coupon_codes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    title = data["title"]
    description = data["description"]
    original_price = data["original_price"]
    discounted_price = data["discounted_price"]
    category = data.get("category")

    # Initial stock is 0 until codes are added
    stock = 0

    # Create the coupon first
    coupon_id = await add_coupon(
        title, description, original_price, discounted_price, stock,
        created_by=message.from_user.id, category=category
    )

    # Add coupon codes if provided
    codes_text = message.text.strip()
    codes_added = 0
    if codes_text.lower() != "skip":
        codes = [c.strip() for c in codes_text.split("\n") if c.strip()]
        try:
            codes_added = await db.add_coupon_codes_bulk(coupon_id, codes)
        except Exception as e:
            logger.error(f"Bulk code insert failed: {e}")
        # Stock is synced inside add_coupon_codes_bulk via sync_coupon_stock
        if codes_added > 0:
            stock = codes_added
            # Log stock action + clear alerts
            try:
                await db.log_stock_action(coupon_id, message.from_user.id, 'create', codes_added)
                from bot.services.stock_alert_service import on_stock_replenished
                await on_stock_replenished(coupon_id, codes_added)
            except Exception as e:
                logger.warning(f"Stock logging failed (non-critical): {e}")
            logger.info(f"Admin {message.from_user.id} — added {codes_added} codes to coupon {coupon_id}")

    # Fetch actual stock after sync
    coupon = await get_coupon_detail(coupon_id)
    stock = coupon["stock"] if coupon else stock

    await db.add_admin_log(
        message.from_user.id, "add_coupon", "coupon", str(coupon_id),
        f"Title: {title}, Price: ₹{discounted_price}, Category: {category or 'None'}, Stock: {stock}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_coupons")]])

    codes_line = ""
    if codes_added > 0:
        codes_line = f"\n🔑 Codes added: *{codes_added}*"
    else:
        codes_line = "\n🔑 No codes added \\(add later from edit menu\\)"

    cat_line = f"\n🏷️ Category: *{escape_md(category)}*" if category else ""

    await message.answer(
        f"✅ *Coupon \\#{coupon_id} created\\!*\n\n"
        f"📝 Title: *{escape_md(title)}*\n"
        f"💰 Price: *{escape_md(format_currency(discounted_price))}*\n"
        f"📦 Stock: *{stock}*"
        f"{cat_line}"
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
        async with pool.acquire() as conn:
            async with conn.transaction():
                # PRESERVE order history — NULL out FK references instead of deleting
                # 1. Detach orders from this coupon (keep order records intact)
                await conn.execute(
                    "UPDATE orders SET coupon_id = NULL WHERE coupon_id = $1",
                    coupon_id,
                )
                # 2. Delete coupon codes (these are the actual voucher codes, not order records)
                await conn.execute("DELETE FROM coupon_codes WHERE coupon_id = $1", coupon_id)
                # 3. Detach admin extractions
                await conn.execute(
                    "DELETE FROM admin_extractions WHERE coupon_id = $1", coupon_id
                )
                # 4. Delete the coupon itself
                await conn.execute("DELETE FROM coupons WHERE id = $1", coupon_id)
        await db.add_admin_log(
            callback.from_user.id, "delete_coupon", "coupon", str(coupon_id)
        )
        logger.info(f"Admin {callback.from_user.id} deleted coupon {coupon_id} (orders preserved)")
        await callback.answer("Coupon deleted (order history preserved).", show_alert=True)
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
    if not codes:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer("⚠️ No valid codes found\\.", parse_mode="MarkdownV2", reply_markup=kb)
        return

    try:
        inserted = await db.add_coupon_codes_bulk(coupon_id, codes)
    except Exception as e:
        logger.error(f"Bulk code insert failed: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer(f"❌ Error adding codes: {escape_md(str(e)[:100])}", parse_mode="MarkdownV2", reply_markup=kb)
        return

    # Stock is already synced inside add_coupon_codes_bulk via sync_coupon_stock
    coupon = await get_coupon_detail(coupon_id)
    new_stock = coupon["stock"] if coupon else inserted
    skipped = len(codes) - inserted

    await db.add_admin_log(
        message.from_user.id, "add_codes", "coupon", str(coupon_id),
        f"Added {inserted} codes (skipped {skipped} duplicates), new stock: {new_stock}"
    )
    # Log stock action + clear alerts
    try:
        if inserted > 0:
            await db.log_stock_action(coupon_id, message.from_user.id, 'add_codes', inserted)
            from bot.services.stock_alert_service import on_stock_replenished
            await on_stock_replenished(coupon_id, new_stock)
    except Exception as e:
        logger.warning(f"Stock logging failed (non-critical): {e}")
    logger.info(f"Admin {message.from_user.id} added {inserted} codes to coupon {coupon_id} (skipped {skipped} dupes)")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    dup_note = f"\n⚠️ Skipped *{skipped}* duplicate\\(s\\)" if skipped > 0 else ""
    await message.answer(
        f"✅ Added *{inserted}* codes to coupon \\#{coupon_id}\\!\\n"
        f"📦 Updated stock: *{new_stock}*{dup_note}",
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
        content = file_bytes.read().decode("utf-8-sig", errors="ignore")
    else:
        content = file_bytes.decode("utf-8-sig", errors="ignore")
    
    # Split by any line ending (\r\n, \r, \n) and strip whitespace
    codes = [c.strip() for c in content.splitlines() if c.strip()]
    
    if not codes:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer("⚠️ No codes found in the file.", reply_markup=kb)
        return

    # Add codes to database (bulk insert with deduplication)
    try:
        inserted = await db.add_coupon_codes_bulk(coupon_id, codes)
    except Exception as e:
        logger.error(f"Bulk file code insert failed: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer(f"❌ Error adding codes from file: {escape_md(str(e)[:100])}", parse_mode="MarkdownV2", reply_markup=kb)
        return

    # Stock is already synced inside add_coupon_codes_bulk via sync_coupon_stock
    coupon = await get_coupon_detail(coupon_id)
    new_stock = coupon["stock"] if coupon else inserted
    skipped = len(codes) - inserted

    await db.add_admin_log(
        message.from_user.id, "upload_codes", "coupon", str(coupon_id),
        f"Uploaded {inserted} codes from file (skipped {skipped} duplicates), new stock: {new_stock}"
    )
    # Log stock action + clear alerts
    try:
        if inserted > 0:
            await db.log_stock_action(coupon_id, message.from_user.id, 'upload_codes', inserted)
            from bot.services.stock_alert_service import on_stock_replenished
            await on_stock_replenished(coupon_id, new_stock)
    except Exception as e:
        logger.warning(f"Stock logging failed (non-critical): {e}")
    logger.info(f"Admin {message.from_user.id} uploaded {inserted} codes from file to coupon {coupon_id} (skipped {skipped} dupes)")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    dup_note = f"\n⚠️ Skipped *{skipped}* duplicate\\(s\\)" if skipped > 0 else ""
    await message.answer(
        f"✅ Uploaded *{inserted}* codes from file\\!\n"
        f"📦 Updated stock: *{new_stock}*{dup_note}",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


# Fallback: admin sent text instead of a file in upload state
@router.message(AdminStates.upload_codes_file)
@error_handler
async def msg_upload_codes_fallback(message: types.Message, state: FSMContext):
    """Handle non-document messages during file upload state."""
    data = await state.get_data()
    coupon_id = data.get("upload_codes_coupon_id", "")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [back_button(f"admin_coupon_edit:{coupon_id}"), admin_cancel_button()]
    ])
    await message.answer(
        "⚠️ Please send a *\\.txt* file, not text\\.\n\n"
        "_Or press Cancel to go back\\._",
        parse_mode="MarkdownV2",
        reply_markup=kb,
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


# ── Category Management ──────────────────────────────────

@router.callback_query(F.data == "admin_categories")
@admin_only
@error_handler
async def cb_admin_categories(callback: types.CallbackQuery):
    """Show category management panel."""
    categories = await db.get_all_categories()
    text = "🏷️ *Coupon Categories*\n\nManage your product categories:"
    await _safe_edit_or_send(
        callback.message, text, reply_markup=admin_categories_kb(categories)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cat_add")
@admin_only
@error_handler
async def cb_cat_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🏷️ *Add Category*\n\nEnter the category name:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_categories"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.cat_add_name)
    await callback.answer()


@router.message(AdminStates.cat_add_name)
@error_handler
async def msg_cat_add_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    await state.clear()

    if not name or len(name) > 64:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_categories")]])
        await message.answer("⚠️ Category name must be 1\\-64 characters\\.", parse_mode="MarkdownV2", reply_markup=kb)
        return

    # Check for duplicates
    existing = await db.get_category_by_name(name)
    if existing:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_categories")]])
        await message.answer(f"⚠️ Category *{escape_md(name)}* already exists\\.", parse_mode="MarkdownV2", reply_markup=kb)
        return

    cat_id = await db.create_category(name)
    await db.add_admin_log(message.from_user.id, "create_category", "category", str(cat_id), f"Name: {name}")
    logger.info(f"Admin {message.from_user.id} created category: {name} (id={cat_id})")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_categories")]])
    await message.answer(
        f"✅ Category *{escape_md(name)}* created\\!",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


@router.callback_query(F.data.startswith("admin_cat_view:"))
@admin_only
@error_handler
async def cb_cat_view(callback: types.CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    cat = await db.get_category(cat_id)
    if not cat:
        await callback.answer("Category not found.", show_alert=True)
        return

    coupons = await db.get_coupons_by_category(cat["name"])
    vis = "👁️ Visible" if cat["is_visible"] else "🔒 Hidden"
    active = sum(1 for c in coupons if c["is_active"])
    total_stock = sum(c["stock"] for c in coupons)

    text = (
        f"🏷️ *Category: {escape_md(cat['name'])}*\n\n"
        f"📊 Status: {vis}\n"
        f"📦 Coupons: *{len(coupons)}* \\({active} active\\)\n"
        f"🔑 Total Stock: *{total_stock}*"
    )

    await _safe_edit_or_send(
        callback.message, text,
        reply_markup=admin_category_view_kb(cat_id, cat["is_visible"])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cat_rename:"))
@admin_only
@error_handler
async def cb_cat_rename(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split(":")[1])
    await state.update_data(rename_cat_id=cat_id)
    await callback.message.edit_text(
        "✏️ *Rename Category*\n\nEnter the new name:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button(f"admin_cat_view:{cat_id}"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.cat_rename_input)
    await callback.answer()


@router.message(AdminStates.cat_rename_input)
@error_handler
async def msg_cat_rename(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cat_id = data["rename_cat_id"]
    await state.clear()

    new_name = message.text.strip()
    if not new_name or len(new_name) > 64:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_cat_view:{cat_id}")]])
        await message.answer("⚠️ Name must be 1\\-64 characters\\.", parse_mode="MarkdownV2", reply_markup=kb)
        return

    # Get old name to update coupons
    old_cat = await db.get_category(cat_id)
    if old_cat:
        pool = await db.get_pool()
        await pool.execute(
            "UPDATE coupons SET category = $2, updated_at = NOW() WHERE category = $1",
            old_cat["name"], new_name
        )

    await db.update_category_name(cat_id, new_name)
    await db.add_admin_log(
        message.from_user.id, "rename_category", "category", str(cat_id),
        f"Renamed: {old_cat['name'] if old_cat else '?'} → {new_name}"
    )
    logger.info(f"Admin {message.from_user.id} renamed category {cat_id} to: {new_name}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_cat_view:{cat_id}")]])
    await message.answer(
        f"✅ Category renamed to *{escape_md(new_name)}*\\!",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


@router.callback_query(F.data.startswith("admin_cat_toggle_vis:"))
@admin_only
@error_handler
async def cb_cat_toggle_vis(callback: types.CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    new_vis = await db.toggle_category_visibility(cat_id)
    status = "visible 👁️" if new_vis else "hidden 🔒"
    await callback.answer(f"Category is now {status}", show_alert=True)
    await cb_cat_view(callback)


@router.callback_query(F.data.startswith("admin_cat_delete:"))
@admin_only
@error_handler
async def cb_cat_delete(callback: types.CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    cat = await db.get_category(cat_id)
    if not cat:
        await callback.answer("Category not found.", show_alert=True)
        return

    await callback.message.edit_text(
        f"⚠️ *Delete category* *{escape_md(cat['name'])}*\\?\n\n"
        f"Coupons in this category will become uncategorized\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yes, Delete", callback_data=f"admin_cat_delete_confirm:{cat_id}"),
                InlineKeyboardButton(text="❌ No, Cancel", callback_data=f"admin_cat_view:{cat_id}"),
            ]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cat_delete_confirm:"))
@admin_only
@error_handler
async def cb_cat_delete_confirm(callback: types.CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    cat = await db.get_category(cat_id)
    name = cat["name"] if cat else "Unknown"

    await db.delete_category(cat_id)
    await db.add_admin_log(callback.from_user.id, "delete_category", "category", str(cat_id), f"Name: {name}")
    logger.info(f"Admin {callback.from_user.id} deleted category: {name}")

    await callback.answer(f"Category '{name}' deleted.", show_alert=True)
    await cb_admin_categories(callback)


@router.callback_query(F.data.startswith("admin_cat_coupons:"))
@admin_only
@error_handler
async def cb_cat_coupons(callback: types.CallbackQuery):
    """Show coupons in a specific category."""
    cat_id = int(callback.data.split(":")[1])
    cat = await db.get_category(cat_id)
    if not cat:
        await callback.answer("Category not found.", show_alert=True)
        return

    coupons = await db.get_coupons_by_category(cat["name"])
    if not coupons:
        text = f"🏷️ *{escape_md(cat['name'])}*\n\nNo coupons in this category\\."
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_cat_view:{cat_id}")]])
    else:
        lines = [f"🏷️ *{escape_md(cat['name'])}* — *{len(coupons)}* coupons\n"]
        for c in coupons:
            status = "🟢" if c["is_active"] else "🔴"
            lines.append(f"{status} {escape_md(c['title'])} — Stock: *{c['stock']}*")
        text = "\n".join(lines)
        buttons = []
        for c in coupons:
            buttons.append([InlineKeyboardButton(
                text=f"✏️ {c['title']}",
                callback_data=f"admin_coupon_edit:{c['id']}"
            )])
        buttons.append([back_button(f"admin_cat_view:{cat_id}")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


# ── Set Category on Existing Coupon ──────────────────────

@router.callback_query(F.data.startswith("admin_set_category:"))
@admin_only
@error_handler
async def cb_set_category(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    categories = await db.get_all_categories()
    if not categories:
        await callback.answer("No categories exist. Create one from 🏷️ Categories first.", show_alert=True)
        return

    await callback.message.edit_text(
        "🏷️ *Select Category*\n\nChoose a category for this coupon:",
        parse_mode="MarkdownV2",
        reply_markup=admin_category_select_kb(categories, coupon_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_assign_cat:"))
@admin_only
@error_handler
async def cb_assign_category(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    coupon_id = int(parts[1])
    cat_id = int(parts[2])

    if cat_id == 0:
        await db.move_coupon_to_category(coupon_id, None)
        await callback.answer("Category removed.", show_alert=True)
    else:
        cat = await db.get_category(cat_id)
        if cat:
            await db.move_coupon_to_category(coupon_id, cat["name"])
            await callback.answer(f"Moved to: {cat['name']}", show_alert=True)

    # Refresh coupon edit view
    await cb_admin_coupon_edit(callback)


# ── Stock Management ─────────────────────────────────────

@router.callback_query(F.data == "admin_stock_overview")
@admin_only
@error_handler
async def cb_stock_overview(callback: types.CallbackQuery):
    """Category-wise stock overview for admins."""
    summary = await db.get_category_stock_summary()
    if not summary:
        text = "📊 *Stock Overview*\n\nNo coupons found\\."
    else:
        lines = ["📊 *STOCK OVERVIEW*\n", "━━━━━━━━━━━━━━━━━━━━\n"]
        grand_total = 0
        for s in summary:
            cat_name = escape_md(s["category"])
            lines.append(
                f"🏷️ *{cat_name}*\n"
                f"   📦 Coupons: {s['coupon_count']} \\({s['active_count']} active\\)\n"
                f"   🔑 Stock: *{s['total_stock']}*\n"
            )
            grand_total += s["total_stock"]
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"\n📦 *Grand Total Stock: {grand_total}*")
        text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_stock_overview")],
        [back_button("admin_panel")],
    ])
    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_clear_stock:"))
@admin_only
@error_handler
async def cb_clear_stock(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    stats = await db.get_coupon_code_stats(coupon_id)
    await callback.message.edit_text(
        f"⚠️ *Clear ALL unsold stock for:*\n\n"
        f"🏷️ {escape_md(coupon['title'])}\n"
        f"📭 Unsold codes: *{stats['unsold']}*\n\n"
        f"This will permanently delete all unsold codes\\.\n"
        f"Sold codes and order history will NOT be affected\\.",
        parse_mode="MarkdownV2",
        reply_markup=confirm_clear_stock_kb(coupon_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_clear_stock_confirm:"))
@admin_only
@error_handler
async def cb_clear_stock_confirm(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split(":")[1])
    deleted = await db.clear_coupon_stock(coupon_id, callback.from_user.id)
    logger.info(f"Admin {callback.from_user.id} cleared {deleted} codes from coupon {coupon_id}")

    await callback.answer(f"🧹 Cleared {deleted} unsold codes.", show_alert=True)
    await cb_admin_coupon_edit(callback)


# ── Manual Coupon Extraction ─────────────────────────────

@router.callback_query(F.data.startswith("admin_extract_codes:"))
@admin_only
@error_handler
async def cb_extract_codes(callback: types.CallbackQuery, state: FSMContext):
    coupon_id = int(callback.data.split(":")[1])
    coupon = await get_coupon_detail(coupon_id)
    if not coupon:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    stats = await db.get_coupon_code_stats(coupon_id)
    if stats["unsold"] == 0:
        await callback.answer("No unsold codes available to extract.", show_alert=True)
        return

    await state.update_data(extract_coupon_id=coupon_id)
    await callback.message.edit_text(
        f"📤 *Extract Codes*\n\n"
        f"🏷️ {escape_md(coupon['title'])}\n"
        f"📭 Available: *{stats['unsold']}* codes\n\n"
        f"Enter the *number* of codes to extract:",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button(f"admin_coupon_edit:{coupon_id}"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.extract_qty_input)
    await callback.answer()


@router.message(AdminStates.extract_qty_input)
@error_handler
async def msg_extract_qty(message: types.Message, state: FSMContext):
    data = await state.get_data()
    coupon_id = data["extract_coupon_id"]
    await state.clear()

    try:
        qty = int(message.text.strip())
        if qty <= 0:
            raise ValueError
    except ValueError:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer("⚠️ Enter a valid positive number.", reply_markup=kb)
        return

    # Extract codes atomically
    codes = await db.extract_coupon_codes(coupon_id, qty, message.from_user.id)
    if not codes:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
        await message.answer("⚠️ No codes available to extract.", reply_markup=kb)
        return

    coupon = await get_coupon_detail(coupon_id)
    title = coupon["title"] if coupon else "Unknown"
    new_stock = coupon["stock"] if coupon else 0

    await db.add_admin_log(
        message.from_user.id, "extract_codes", "coupon", str(coupon_id),
        f"Extracted {len(codes)} codes from {title}, remaining stock: {new_stock}"
    )
    logger.info(f"Admin {message.from_user.id} extracted {len(codes)} codes from coupon {coupon_id}")

    # Track promotional loss for extraction
    try:
        unit_price = float(coupon["discounted_price"]) if coupon else 0
        total_value = unit_price * len(codes)
        coupon_owner = coupon.get("created_by") if coupon else None
        await db.record_promotional_loss(
            loss_type="extraction",
            amount=total_value,
            admin_id=message.from_user.id,
            coupon_owner_admin_id=coupon_owner,
            coupon_id=coupon_id,
            reference=f"extract_{len(codes)}_codes",
            details={
                "coupon_title": title,
                "quantity": len(codes),
                "unit_price": unit_price,
                "codes_sample": codes[:5],
            }
        )
    except Exception:
        pass

    # Show delivery options
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📄 Download as TXT ({len(codes)} codes)",
            callback_data=f"admin_extract_download:{coupon_id}"
        )],
        [back_button(f"admin_coupon_edit:{coupon_id}")],
    ])

    # Show codes inline (up to 50, then truncate)
    if len(codes) <= 50:
        codes_display = "\n".join(f"`{escape_md(c)}`" for c in codes)
    else:
        codes_display = "\n".join(f"`{escape_md(c)}`" for c in codes[:50])
        codes_display += f"\n\n_\\.\\.\\. and {len(codes) - 50} more \\(download TXT for all\\)_"

    # Store codes temporarily for download
    await state.update_data(
        last_extracted_codes=codes,
        last_extracted_coupon_id=coupon_id,
        last_extracted_title=title,
    )

    await message.answer(
        f"✅ *Extracted {len(codes)} codes\\!*\n\n"
        f"🏷️ {escape_md(title)}\n"
        f"📦 Remaining Stock: *{new_stock}*\n\n"
        f"🔑 *Extracted Codes:*\n\n"
        f"{codes_display}",
        parse_mode="MarkdownV2", reply_markup=kb,
    )


@router.callback_query(F.data.startswith("admin_extract_download:"))
@admin_only
@error_handler
async def cb_extract_download(callback: types.CallbackQuery, state: FSMContext):
    """Download last extracted codes as TXT file."""
    data = await state.get_data()
    codes = data.get("last_extracted_codes", [])

    if not codes:
        await callback.answer("No codes to download. Extract codes first.", show_alert=True)
        return

    coupon_id = data.get("last_extracted_coupon_id", 0)
    title = data.get("last_extracted_title", "codes")

    file_content = "\n".join(codes)
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:40]
    filename = f"extracted_{safe_title}_{len(codes)}_codes.txt"

    from aiogram.types import BufferedInputFile
    file_buf = BufferedInputFile(file_content.encode("utf-8"), filename=filename)

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button(f"admin_coupon_edit:{coupon_id}")]])
    await callback.message.answer_document(
        document=file_buf,
        caption=(
            f"📤 *Extracted Codes — {escape_md(title)}*\n\n"
            f"📦 Total: *{len(codes)}* codes\n"
            f"📁 File: `{escape_md(filename)}`"
        ),
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await callback.answer(f"📄 {len(codes)} codes exported!")
    logger.info(f"Admin {callback.from_user.id} downloaded extracted codes for coupon {coupon_id}")

# ── View Orders ───────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^admin_orders(:\d+)?$"))
@admin_only
@error_handler
async def cb_admin_orders(callback: types.CallbackQuery):
    """Show recent purchasers grouped by user — paginated (10 per page, up to 100)."""
    # Parse page from callback data: admin_orders or admin_orders:2
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1

    PER_PAGE = 10
    TOTAL_FETCH = 100

    users = await db.get_recent_order_users(TOTAL_FETCH)

    if not users:
        await callback.message.edit_text(
            "🧾 *Recent Purchasers*\n\n_No orders yet\\._",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
        )
        await callback.answer()
        return

    total_users = len(users)
    total_pages = (total_users + PER_PAGE - 1) // PER_PAGE
    page = max(1, min(page, total_pages))

    start = (page - 1) * PER_PAGE
    end = min(start + PER_PAGE, total_users)
    page_users = users[start:end]

    lines = [
        f"🧾 *RECENT PURCHASERS*",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📊 Showing *{start+1}\\-{end}* of *{total_users}* users",
        f"📄 Page *{page}* / *{total_pages}*\n",
    ]

    for i, u in enumerate(page_users, start + 1):
        name = escape_md((u["full_name"] or "Unknown")[:20])
        uid = u["user_id"]
        orders = u["order_count"]
        paid = u["paid_count"]
        pending = u.get("pending_count", 0)
        spent = escape_md(format_currency(float(u["total_spent"])))

        status_dot = "🟢" if paid > 0 else "🟡"
        lines.append(
            f"{status_dot} *{i}\\. {name}*\n"
            f"   🆔 `{uid}`\n"
            f"   📦 {orders} orders \\( ✅ {paid} paid \\) 💰 {spent}"
        )

    text = "\n".join(lines)

    buttons = []
    for u in page_users:
        name = (u["full_name"] or str(u["user_id"]))[:25]
        paid_count = u["paid_count"]
        btn_text = f"👤 {name} ({paid_count} paid)"
        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"admin_order_user:{u['user_id']}"
        )])

    # Pagination buttons
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀️ Back", callback_data=f"admin_orders:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"admin_orders:{page+1}"))
    buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="🔍 Search Order ID", callback_data="admin_order_search")])
    buttons.append([back_button("admin_panel")])

    await _safe_edit_or_send(
        callback.message, text,
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
        f"📊 Total: *{total}* \\( ✅ Paid: *{paid_count}* \\) 💰 {escape_md(format_currency(total_spent))}",
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

    await _safe_edit_or_send(
        callback.message, text,
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

    await _safe_edit_or_send(
        callback.message, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()



# ── Admin Logs ────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^admin_logs(:\d+)?$"))
@admin_only
@error_handler
async def cb_admin_logs(callback: types.CallbackQuery):
    """Show admin activity logs — attractive, paginated display."""
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1

    PER_PAGE = 8
    TOTAL_FETCH = 50

    logs = await db.get_admin_logs(TOTAL_FETCH)

    if not logs:
        await callback.message.edit_text(
            "📋 *ADMIN ACTIVITY LOG*\n\n_No activity recorded yet\\._",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_panel")]])
        )
        await callback.answer()
        return

    total_logs = len(logs)
    total_pages = (total_logs + PER_PAGE - 1) // PER_PAGE
    page = max(1, min(page, total_pages))
    start = (page - 1) * PER_PAGE
    end = min(start + PER_PAGE, total_logs)
    page_logs = logs[start:end]

    # Action-specific emojis for visual appeal
    action_emojis = {
        "add": "➕", "create": "➕", "delete": "🗑️", "remove": "🗑️",
        "update": "✏️", "edit": "✏️", "toggle": "🔀", "enable": "✅",
        "disable": "❌", "broadcast": "📢", "export": "📤",
        "import": "📥", "set": "⚙️", "reset": "🔄",
    }

    lines = [
        "📋 *ADMIN ACTIVITY LOG*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 Showing *{start+1}\\-{end}* of *{total_logs}* entries",
        f"📄 Page *{page}* / *{total_pages}*",
        "",
    ]

    for log in page_logs:
        action = str(log["action"] or "")
        target = str(log["target_type"] or "")
        tid = str(log["target_id"] or "")
        dt = format_datetime(log["created_at"])

        # Pick emoji based on action keywords
        emoji = "📝"
        action_lower = action.lower()
        for keyword, em in action_emojis.items():
            if keyword in action_lower:
                emoji = em
                break

        # Format each log as a mini-card
        action_esc = escape_md(action)
        target_esc = escape_md(target)
        tid_esc = escape_md(tid)
        dt_esc = escape_md(dt)

        card = f"{emoji} *{action_esc}*"
        if target:
            card += f"\n   📁 {target_esc}"
        if tid:
            card += f" `{tid_esc}`"
        card += f"\n   🕐 {dt_esc}"

        # Show details if available (truncated)
        if log.get("details"):
            detail_text = str(log["details"])[:80]
            if len(str(log["details"])) > 80:
                detail_text += "..."
            card += f"\n   💬 _{escape_md(detail_text)}_"

        lines.append(card)
        lines.append("")  # Spacing between cards

    text = "\n".join(lines)

    # Pagination buttons
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀️ Newer", callback_data=f"admin_logs:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Older ▶️", callback_data=f"admin_logs:{page+1}"))

    buttons = []
    if nav_row:
        buttons.append(nav_row)
    buttons.append([back_button("admin_panel")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()



# ── Broadcast ───────────────────────────────────────────

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
    """Pre-fill a beautiful restart broadcast with a /start button."""
    bot_me = await callback.message.bot.get_me()
    bot_username = bot_me.username
    bot_name = await db.get_bot_name()

    restart_text = (
        "🔄 <b>Bot Updated!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "We've made some improvements 🚀\n\n"
        "Tap below to restart 👇"
    )
    bc_data = {
        "type": "text",
        "text": restart_text,
    }
    bc_buttons = [
        {"text": "🚀 Restart Bot Now", "url": f"https://t.me/{bot_username}?start=restart"}
    ]
    await state.clear()
    await state.update_data(bc_data=bc_data, bc_buttons=bc_buttons)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Send Now", callback_data="bc_send_now")],
        [InlineKeyboardButton(text="✏️ Edit Message", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")],
    ])
    await callback.message.edit_text(
        "📲 <b>Quick Restart Broadcast</b>\n\n"
        "This will send the following message to ALL users:\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔄 <b>Bot Updated!</b>\n"
        "We've made some improvements 🚀\n"
        "Tap below to restart 👇\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔗 Button: <b>🚀 Restart Bot Now</b>",
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
    # Clear state so subsequent text input doesn't re-trigger content handler
    await state.set_state(None)

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

        # Per-message delay to stay under Telegram's 30 msg/sec limit
        await asyncio.sleep(0.05)

        # Batch pause + progress update every 25 messages
        processed = sent + failed
        if processed % 25 == 0:
            await asyncio.sleep(1)
            # Update progress so admin doesn't see a frozen screen
            try:
                pct = round(processed / total * 100) if total else 0
                await progress_msg.edit_text(
                    f"📢 Broadcasting\\.\\.\\.  {pct}%\n"
                    f"✅ {sent} sent, ❌ {failed} failed \\({processed}/{total}\\)",
                    parse_mode="MarkdownV2",
                )
            except Exception:
                pass

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
            f"📦 Total: *{total}* \\( ✅ Claimed: *{claimed}* \\) 📭 Unclaimed: *{unclaimed}*\n"
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

    # Earning cap info
    max_amt = settings.get("wallet_reward_max_amount") or 0
    dur_days = settings.get("wallet_reward_duration_days") or 0

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
        if float(max_amt) > 0 and int(dur_days) > 0:
            text += (
                f"🔒 Earning Cap: ₹{escape_md(str(float(max_amt)))} "
                f"per {escape_md(str(int(dur_days)))} days\n"
            )
        else:
            text += f"⚠️ No earning cap set \\(unlimited\\)\n"
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
        buttons.append([InlineKeyboardButton(text="🔒 Edit Earning Cap", callback_data="admin_ref_edit_cap")])
    elif mode == "code_reward":
        rewards = await db.get_referral_rewards()
        active_rewards = [r for r in rewards if r["is_active"]]
        # Dynamic button: "Replace" if reward exists, "Add" if none
        add_btn_text = "🔄 Replace Reward Coupon" if active_rewards else "➕ Add Reward Coupon"
        buttons.append([InlineKeyboardButton(text=add_btn_text, callback_data="admin_ref_add_reward")])
        for r in rewards:
            si = "🟢" if r["is_active"] else "🔴"
            buttons.append([InlineKeyboardButton(
                text=f"{si} {r['title'][:25]} ({r['referrals_needed']} refs)",
                callback_data=f"admin_ref_reward_view:{r['id']}"
            )])

    toggle_text = "🔴 Disable Referrals" if settings["is_active"] else "🟢 Enable Referrals"
    buttons.append([InlineKeyboardButton(text=toggle_text, callback_data="admin_ref_toggle_active")])
    buttons.append([InlineKeyboardButton(text="🗑️ Manage / Remove Referrals", callback_data="admin_manage_referrals")])
    buttons.append([back_button("admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


# ── Referral Management (admin testing tool) ─────────────────────────────────

@router.callback_query(F.data == "admin_manage_referrals")
@admin_only
@error_handler
async def cb_admin_manage_referrals(callback: types.CallbackQuery, state: FSMContext):
    """Prompt admin to enter a user ID whose referrals they want to view/delete."""
    await state.set_state(AdminStates.manage_referral_user_input)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [back_button("admin_referral_settings"), admin_cancel_button()]
    ])
    await callback.message.edit_text(
        "🗑️ *Manage Referrals*\n\n"
        "Send the *Telegram ID* of the referrer whose referrals you want to view or delete:\n\n"
        "_Tip: Use /id in the bot to get any user's ID_",
        parse_mode="MarkdownV2",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(AdminStates.manage_referral_user_input)
@admin_only
@error_handler
async def msg_manage_referral_user_input(message: types.Message, state: FSMContext):
    """Show all referral relationships for the entered user (BOTH directions)."""
    await state.clear()
    text = message.text.strip()
    try:
        user_id = int(text)
    except ValueError:
        await message.answer(
            "\u274c Invalid ID. Send a numeric Telegram user ID.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [back_button("admin_manage_referrals")]
            ])
        )
        return

    user_row = await db.get_user(user_id)
    user_name = ""
    if user_row:
        user_name = user_row.get("full_name") or user_row.get("username") or str(user_id)
    else:
        user_name = str(user_id)

    lines = []
    buttons = []

    # ── SECTION 1: Who referred THIS user (incoming) ──
    referrer_of = await db.get_referrer_of(user_id)
    if referrer_of:
        ref_id = referrer_of["telegram_id"]
        ref_name = escape_md(str(referrer_of.get("full_name") or referrer_of.get("username") or ref_id)[:25])
        lines.append(f"\U0001f4e5 *Referred by:* `{ref_id}` \\({ref_name}\\)")
        buttons.append([InlineKeyboardButton(
            text=f"\U0001f5d1\ufe0f Remove referrer ({ref_id}) \u2014 let user re-refer",
            callback_data=f"admin_del_ref:{ref_id}:{user_id}"
        )])
    else:
        lines.append("\U0001f4e5 *Referred by:* _None \u2014 can enter a referral code_")

    lines.append("")

    # ── SECTION 2: People THIS user referred (outgoing) ──
    refs = await db.get_referrals_for_user(user_id)
    if refs:
        lines.append(f"\U0001f4e4 *Referred {len(refs)} user\\(s\\):*")
        for r in refs:
            name = escape_md(str(r["referred_name"])[:25])
            rid = r["referred_id"]
            status = r["status"]
            commission = float(r["commission"] or 0)
            status_esc = escape_md(status)
            comm_esc = escape_md(f"\u20b9{commission:.1f}")
            lines.append(f"  \u2022 `{rid}` *{name}* \u2014 {status_esc}, comm\\={comm_esc}")
            buttons.append([InlineKeyboardButton(
                text=f"\U0001f5d1\ufe0f Remove {str(r['referred_name'])[:20]} ({rid})",
                callback_data=f"admin_del_ref:{user_id}:{rid}"
            )])
        buttons.append([InlineKeyboardButton(
            text="\U0001f5d1\ufe0f Remove ALL outgoing referrals (reset)",
            callback_data=f"admin_del_ref_all:{user_id}"
        )])
    else:
        lines.append("\U0001f4e4 *Referred:* _No one_")

    # Nothing at all
    if not referrer_of and not refs:
        await message.answer(
            f"\u2139\ufe0f User *{escape_md(user_name)}* `{user_id}` has no referral relationships\\.\n\n"
            f"\U0001f4e5 Not referred by anyone\n"
            f"\U0001f4e4 Has not referred anyone",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [back_button("admin_referral_settings")]
            ])
        )
        return

    text_body = (
        f"\U0001f464 *Referrals for* `{user_id}` \\({escape_md(user_name)}\\)\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        + "\n".join(lines)
        + f"\n\n_Removing a referral reverses wallet credit and lets the user re\\-refer\\._"
    )

    buttons.append([back_button("admin_referral_settings")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(text_body, parse_mode="MarkdownV2", reply_markup=kb)



@router.callback_query(F.data.startswith("admin_del_ref:"))
@admin_only
@error_handler
async def cb_admin_del_ref(callback: types.CallbackQuery):
    """Delete one specific referral and reverse its wallet credit."""
    _, referrer_id, referred_id = callback.data.split(":")
    referrer_id = int(referrer_id)
    referred_id = int(referred_id)

    result = await db.delete_referral(referrer_id, referred_id)
    if result["deleted"]:
        rev = result["reversed_amount"]
        msg = f"✅ Referral deleted\\. Reversed ₹{escape_md(str(round(rev, 2)))} from referrer's wallet\\."
        if rev == 0:
            msg = "✅ Referral deleted \\(no wallet credit to reverse\\)\\."
        logger.info(f"Admin {callback.from_user.id} deleted referral {referrer_id}->{referred_id}")
    else:
        msg = "❌ Referral record not found\\."

    await callback.answer()
    # Refresh the referral list for the same referrer
    refs = await db.get_referrals_for_user(referrer_id)
    if not refs:
        await _safe_edit_or_send(
            callback.message,
            msg + f"\n\nNo more referrals for `{referrer_id}`\\.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [back_button("admin_referral_settings")]
            ])
        )
        return

    lines   = []
    buttons = []
    for r in refs:
        name = escape_md(str(r["referred_name"])[:25])
        rid  = r["referred_id"]
        commission = float(r["commission"] or 0)
        status_esc = escape_md(r['status'])
        comm_esc = escape_md(f"₹{commission:.1f}")
        lines.append(f"• `{rid}` *{name}* — {status_esc}, comm\\={comm_esc}")
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ Remove {str(r['referred_name'])[:20]} ({rid})",
            callback_data=f"admin_del_ref:{referrer_id}:{rid}"
        )])
    buttons.append([InlineKeyboardButton(
        text="🗑️ Remove ALL referrals (reset)",
        callback_data=f"admin_del_ref_all:{referrer_id}"
    )])
    buttons.append([back_button("admin_referral_settings")])

    body = (
        msg + "\n\n"
        f"*Remaining referrals for* `{referrer_id}`:\n"
        + "\n".join(lines)
    )
    await _safe_edit_or_send(callback.message, body,
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("admin_del_ref_all:"))
@admin_only
@error_handler
async def cb_admin_del_ref_all(callback: types.CallbackQuery):
    """Delete ALL referrals for a referrer — full reset for testing."""
    referrer_id = int(callback.data.split(":")[1])
    refs = await db.get_referrals_for_user(referrer_id)
    if not refs:
        await callback.answer("No referrals found.", show_alert=True)
        return

    total_reversed = 0.0
    count = 0
    for r in refs:
        result = await db.delete_referral(referrer_id, r["referred_id"])
        if result["deleted"]:
            total_reversed += result["reversed_amount"]
            count += 1

    logger.info(
        f"Admin {callback.from_user.id} reset ALL {count} referrals for user {referrer_id}, "
        f"reversed ₹{total_reversed:.2f}"
    )
    await callback.answer(
        f"✅ Removed {count} referral(s). Reversed ₹{total_reversed:.2f} from wallet.",
        show_alert=True
    )
    await _safe_edit_or_send(
        callback.message,
        f"✅ *All {count} referral\\(s\\) deleted* for `{referrer_id}`\\."
        f"\n💰 Total reversed: ₹{escape_md(str(round(total_reversed, 2)))}\\."
        f"\n\nThe user can now be re\\-referred for fresh testing\\.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_referral_settings")]
        ])
    )


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


# ── Earning Cap Settings (Wallet Reward Mode) ────────────

@router.callback_query(F.data == "admin_ref_edit_cap")
@admin_only
@error_handler
async def cb_ref_edit_cap(callback: types.CallbackQuery, state: FSMContext):
    """Edit earning cap (max amount + duration in days)."""
    settings = await db.get_referral_settings()
    max_amt = settings.get("wallet_reward_max_amount") or 0
    dur_days = settings.get("wallet_reward_duration_days") or 0

    text = (
        f"🔒 *Edit Earning Cap*\n\n"
        f"Current: ₹{escape_md(str(float(max_amt)))} "
        f"per {escape_md(str(int(dur_days)))} days\n\n"
        f"Send new cap in format:\n"
        f"`amount duration_days`\n\n"
        f"Example: `250 30`\n"
        f"\\(Max ₹250 in 30 days\\)\n\n"
        f"Send `0` to disable cap \\(unlimited\\)\\."
    )
    await callback.message.edit_text(
        text, parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [back_button("admin_referral_settings"), admin_cancel_button()]
        ]),
    )
    await state.set_state(AdminStates.ref_earning_cap_input)
    await callback.answer()


@router.message(AdminStates.ref_earning_cap_input)
@error_handler
async def msg_ref_earning_cap_input(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_referral_settings")]])

    if text == "0":
        await db.update_referral_settings(
            wallet_reward_max_amount=0,
            wallet_reward_duration_days=0
        )
        await message.answer("✅ Earning cap disabled \\(unlimited\\)\\.", parse_mode="MarkdownV2", reply_markup=kb)
        logger.info(f"Admin {message.from_user.id} disabled referral earning cap")
        return

    parts = text.split()
    if len(parts) != 2:
        await message.answer(
            "⚠️ Please send in format: `amount days`\n"
            "Example: `250 30` or `0` to disable",
            parse_mode="MarkdownV2"
        )
        return

    try:
        max_amt = float(parts[0])
        dur_days = int(parts[1])
        if max_amt <= 0 or dur_days <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "⚠️ Invalid values. Amount must be > 0, days must be > 0.\n"
            "Example: `250 30`",
            parse_mode="MarkdownV2"
        )
        return

    await db.update_referral_settings(
        wallet_reward_max_amount=max_amt,
        wallet_reward_duration_days=dur_days
    )
    await message.answer(
        f"✅ Earning cap set: ₹{max_amt} per {dur_days} days",
        reply_markup=kb
    )
    logger.info(f"Admin {message.from_user.id} set earning cap: ₹{max_amt} / {dur_days} days")


# ── Reward Coupon Management (Code Reward Mode) ──────────

@router.callback_query(F.data == "admin_ref_add_reward")
@admin_only
@error_handler
async def cb_ref_add_reward(callback: types.CallbackQuery):
    """Show confirmation if a reward already exists, then coupon selection."""
    existing_rewards = await db.get_referral_rewards()
    active_rewards = [r for r in existing_rewards if r["is_active"]]

    if active_rewards:
        # Show confirmation before replacing
        current = active_rewards[0]
        title_esc = escape_md(current["title"])
        await callback.message.edit_text(
            f"⚠️ *Replace Existing Reward?*\n\n"
            f"Current reward: 🎁 *{title_esc}* \\({current['referrals_needed']} refs\\)\n\n"
            f"Adding a new reward will *remove the current one*\\.\n"
            f"Do you want to continue?",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Yes, Replace", callback_data="admin_ref_replace_confirm"),
                 InlineKeyboardButton(text="❌ Cancel", callback_data="admin_referral_settings")],
            ]),
        )
        await callback.answer()
        return

    # No existing rewards — go straight to coupon selection
    await _show_reward_coupon_picker(callback)


@router.callback_query(F.data == "admin_ref_replace_confirm")
@admin_only
@error_handler
async def cb_ref_replace_confirm(callback: types.CallbackQuery):
    """Admin confirmed replacing the existing reward. Show coupon picker."""
    await _show_reward_coupon_picker(callback)


async def _show_reward_coupon_picker(callback: types.CallbackQuery):
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

        # ── Single-reward policy: DELETE all existing rewards ──
        existing = await db.get_referral_rewards()
        for r in existing:
            await db.remove_referral_reward(r["id"])
            logger.info(f"Auto-deleted reward {r['id']} ({r['title']}) for single-reward policy")

        await db.add_referral_reward(coupon_id, val)
        coupon = await get_coupon_detail(coupon_id)
        title = coupon["title"] if coupon else "Unknown"
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("admin_referral_settings")]])

        replaced_msg = ""
        if existing:
            replaced_msg = "\n⚠️ Previous reward was replaced\\."

        await message.answer(
            f"✅ Reward set\\!\n\n"
            f"🏷️ {escape_md(title)} — needs {val} referrals to claim"
            f"{replaced_msg}",
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
    
    timeout_val   = dyn["payment_timeout_seconds"]
    res_timeout   = dyn.get("reservation_timeout_seconds", 900)
    min_recharge  = dyn["bharatpe_min_recharge"]
    poll_val      = dyn["payment_poll_interval"]
    reservation_on = dyn.get("reservation_enabled", True)
    waitlist_on    = dyn.get("waitlist_enabled", True)
    
    res_icon = "🟢 ON" if reservation_on else "🔴 OFF"
    wl_icon  = "🟢 ON" if waitlist_on  else "🔴 OFF"
    
    text = (
        f"⚙️ *Bot Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏷️ *Bot Name:* `{escape_md(bot_name)}`\n\n"
        f"━━━ *Dynamic Config* ━━━\n"
        f"⏱️ Payment Timeout: *{timeout_val}s* \\({timeout_val // 60} min\\)\n"
        f"🔒 Reservation Hold: *{res_timeout}s* \\({res_timeout // 60} min\\)\n"
        f"   _How long stock stays locked per pending order_\n"
        f"💰 Min Recharge \\(BharatPe\\): *₹{min_recharge:.0f}*\n"
        f"🔄 Expiry Poll Interval: *{poll_val}s*\n\n"
        f"━━━ *System Controls* ━━━\n"
        f"🔒 Reservation System: *{res_icon}*\n"
        f"   _When ON: stock is locked per order \\(prevents overselling\\)_\n"
        f"   _When OFF: all current reservations are released instantly_\n\n"
        f"📋 Waitlist System: *{wl_icon}*\n"
        f"   _When ON: out\\-of\\-stock users join a queue \\& get notified_\n"
        f"   _When OFF: users see simple out\\-of\\-stock message_\n"
    )
    
    res_toggle_text = "🔴 Disable Reservation" if reservation_on else "🟢 Enable Reservation"
    wl_toggle_text  = "🔴 Disable Waitlist"    if waitlist_on   else "🟢 Enable Waitlist"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✏️ Bot Name: {bot_name}", callback_data="admin_change_bot_name")],
        [InlineKeyboardButton(text="⏱️ Payment Timeout",   callback_data="admin_dynconf:payment_timeout_seconds"),
         InlineKeyboardButton(text="💰 Min Recharge",       callback_data="admin_dynconf:bharatpe_min_recharge")],
        [InlineKeyboardButton(text="🔒 Reservation Hold Time", callback_data="admin_dynconf:reservation_timeout_seconds"),
         InlineKeyboardButton(text="🔄 Poll Interval",     callback_data="admin_dynconf:payment_poll_interval")],
        [InlineKeyboardButton(text=res_toggle_text, callback_data="admin_toggle_reservation")],
        [InlineKeyboardButton(text=wl_toggle_text,  callback_data="admin_toggle_waitlist")],
        [InlineKeyboardButton(text="👮 Manage Admins", callback_data="admin_manage_admins")],
        [back_button("admin_panel")],
    ])

    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


# ── Reservation System Toggle ─────────────────────────────

@router.callback_query(F.data == "admin_toggle_reservation")
@admin_only
@error_handler
async def cb_admin_toggle_reservation(callback: types.CallbackQuery):
    """Toggle the stock reservation system on/off.

    When turning OFF:
      - ALL pending orders are instantly expired in the DB.
      - Stock is restored to the available pool immediately.
      - Every user whose order was cancelled receives a push message
        automatically — no /start or any action needed on their side.
    """
    dyn = await db.get_dynamic_config()
    current = dyn.get("reservation_enabled", True)
    new_val = not current
    try:
        await db.update_bot_settings(reservation_enabled=new_val)
    except Exception as e:
        if "does not exist" in str(e) or "UndefinedColumn" in type(e).__name__:
            await callback.answer(
                "⚠️ Database migration not applied!\n"
                "Run 'python run_migration.py' to update the database schema.",
                show_alert=True
            )
            return
        raise

    released_count = 0
    notified = 0

    if not new_val:
        # ── Reservation turned OFF ─────────────────────────────────────
        # 1. Release stock + expire pending orders, get list of affected users
        try:
            released_count, affected_orders = await db.release_all_reservations()
            logger.info(
                f"Admin {callback.from_user.id} disabled reservation: "
                f"{released_count} pending order(s) expired, stock restored."
            )
        except Exception as e:
            logger.error(f"release_all_reservations failed: {e}")
            affected_orders = []

        # 2. Push a cancellation message to every affected user automatically
        for order in affected_orders:
            try:
                title_esc = escape_md(order.get("coupon_title") or "your coupon")
                oid_esc   = escape_md(order["order_id"])
                await callback.bot.send_message(
                    order["user_id"],
                    f"⚠️ *Order Cancelled*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"Your order `{oid_esc}` for *{title_esc}* has been "
                    f"cancelled because the admin switched the store to "
                    f"*first\\-come, first\\-served* mode\\.\n\n"
                    f"🛒 You can place a new order anytime — no reservation "
                    f"needed now\\!\n"
                    f"💡 _First to pay gets the coupon\\._",
                    parse_mode="MarkdownV2",
                )
                notified += 1
            except Exception as notify_err:
                logger.warning(
                    f"Could not notify user {order['user_id']} "
                    f"(order {order['order_id']}): {notify_err}"
                )
        # ──────────────────────────────────────────────────────────────

    status = "🟢 Enabled" if new_val else "🔴 Disabled"
    await db.add_admin_log(
        callback.from_user.id, "toggle_reservation", "bot_settings", "reservation_enabled",
        f"Reservation {'enabled' if new_val else 'disabled'}"
        + (f", {released_count} orders released, {notified} users notified" if released_count else "")
    )
    logger.info(f"Admin {callback.from_user.id} toggled reservation system: {status}")

    alert_msg = f"Reservation System: {status}"
    if not new_val:
        if released_count > 0:
            alert_msg += f"\n✅ {released_count} order(s) cancelled & stock restored!"
        if notified > 0:
            alert_msg += f"\n📨 {notified} user(s) notified automatically."
    await callback.answer(alert_msg, show_alert=True)
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
    try:
        await db.update_bot_settings(waitlist_enabled=new_val)
    except Exception as e:
        if "does not exist" in str(e) or "UndefinedColumn" in type(e).__name__:
            await callback.answer(
                "⚠️ Database migration not applied!\n"
                "Run 'python run_migration.py' to update the database schema.",
                show_alert=True
            )
            return
        raise
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
    "payment_timeout_seconds": (
        "⏱️ Payment Timeout",
        "seconds",
        "How long a payment session stays open before expiring. Example: 600 = 10 min."
    ),
    "reservation_timeout_seconds": (
        "🔒 Reservation Hold Time",
        "seconds",
        "How long stock is locked for a pending order when reservation is ON. "
        "Example: 900 = 15 min. Stock is released automatically after this time."
    ),
    "bharatpe_min_recharge": (
        "💰 Min Recharge",
        "INR",
        "Minimum BharatPe payment amount in INR. Example: 10"
    ),
    "payment_poll_interval": (
        "🔄 Poll Interval",
        "seconds",
        "How often the bot checks for expired orders in the background. Example: 30"
    ),
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

    # Show total deduplicated count
    all_ids = set(seed_ids) | {adm["telegram_id"] for adm in db_admins}
    lines.append(f"📊 *Total Active Admins: {len(all_ids)}*")
    lines.append("")

    lines.append("*Seed Admins* \\(from \\.env — cannot remove\\):")
    for sid in seed_ids:
        lines.append(f"  🔒 `{sid}`")

    lines.append("")
    if db_admins:
        lines.append("*Dynamic Admins* \\(added via panel\\):")
        for adm in db_admins:
            tid = adm["telegram_id"]
            added_by = adm["added_by"]
            overlap = " \\(also seed\\)" if tid in seed_ids else ""
            lines.append(f"  👤 `{tid}` — added by `{added_by}`{overlap}")
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

    # Gateway display names (admin-customizable)
    paytm_name = escape_md(ps.get("gateway_paytm_name", "Paytm"))
    bp_name = escape_md(ps.get("gateway_bharatpe_name", "BharatPe"))
    rp_name = escape_md(ps.get("gateway_razorpay_name", "Razorpay"))

    text = (
        f"💳 *Payment Settings*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Gateway Status:*\n"
        f"  ✅ {paytm_name}: *{paytm_status}*\n"
        f"  🏦 {bp_name}: *{bp_status}*\n"
        f"  💳 {rp_name}: *{rp_status}*\n\n"
        f"*Display Names \\(shown to users\\):*\n"
        f"  ✅ Paytm → `{paytm_name}`\n"
        f"  🏦 BharatPe → `{bp_name}`\n"
        f"  💳 Razorpay → `{rp_name}`\n\n"
        f"━━━ *{paytm_name}* ━━━\n"
        f"🏢 MID: `{paytm_mid}`\n"
        f"📱 UPI ID: `{paytm_upi}`\n\n"
        f"━━━ *{bp_name}* ━━━\n"
        f"🏢 Merchant ID: `{bp_mid}`\n"
        f"🔑 Token: `{bp_token}`\n"
        f"📱 UPI ID: `{bp_upi}`\n"
        f"📷 QR Image: {bp_qr}\n\n"
        f"━━━ *{rp_name}* ━━━\n"
        f"🔑 Key ID: `{rp_key}`\n"
        f"🔐 Secret: `{rp_secret}`\n\n"
        f"━━━ *General* ━━━\n"
        f"👤 Payee Name: `{payee}`\n"
    )

    # Use raw names for toggle labels
    paytm_raw = ps.get("gateway_paytm_name", "Paytm")
    bp_raw = ps.get("gateway_bharatpe_name", "BharatPe")
    rp_raw = ps.get("gateway_razorpay_name", "Razorpay")

    # Toggle buttons
    paytm_toggle = f"🔴 Disable {paytm_raw}" if paytm_on else f"🟢 Enable {paytm_raw}"
    bp_toggle = f"🔴 Disable {bp_raw}" if bp_on else f"🟢 Enable {bp_raw}"
    rp_toggle = f"🔴 Disable {rp_raw}" if rp_on else f"🟢 Enable {rp_raw}"

    buttons = [
        # Gateway toggles
        [InlineKeyboardButton(text=paytm_toggle, callback_data="admin_gw_toggle:gateway_paytm_enabled"),
         InlineKeyboardButton(text=bp_toggle, callback_data="admin_gw_toggle:gateway_bharatpe_enabled")],
        [InlineKeyboardButton(text=rp_toggle, callback_data="admin_gw_toggle:gateway_razorpay_enabled")],
        # Gateway name customization
        [InlineKeyboardButton(text=f"✏️ Rename {paytm_raw}", callback_data="admin_pay_edit:gateway_paytm_name"),
         InlineKeyboardButton(text=f"✏️ Rename {bp_raw}", callback_data="admin_pay_edit:gateway_bharatpe_name")],
        [InlineKeyboardButton(text=f"✏️ Rename {rp_raw}", callback_data="admin_pay_edit:gateway_razorpay_name")],
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

    await _safe_edit_or_send(callback.message, text,
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
    # Gateway display names
    "gateway_paytm_name": "Paytm Display Name",
    "gateway_bharatpe_name": "BharatPe Display Name",
    "gateway_razorpay_name": "Razorpay Display Name",
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
    await _safe_edit_or_send(callback.message, text,
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

    await _safe_edit_or_send(callback.message, text,
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
        f"📊 Total: *{total}* \\( ✅ Paid: *{paid_count}* \\) 💰 {escape_md(format_currency(total_spent))}",
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

# ══════════════════════════════════════════════════════════════
# 📊 ANALYTICS DASHBOARD — Multi-page Telegram Interactive
# ══════════════════════════════════════════════════════════════

async def _analytics_safe_edit(callback, text: str, reply_markup, page_name: str):
    """Edit analytics message with MarkdownV2, falling back to plain text on parse error."""
    import re
    try:
        await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=reply_markup)
    except Exception as e:
        error_msg = str(e).lower()
        if "not modified" in error_msg:
            return  # Same content — not a real error
        logger.warning(f"Analytics {page_name} MarkdownV2 failed: {str(e)[:150]}")
        # Strip MarkdownV2 formatting and retry as plain text
        try:
            plain = re.sub(r'\\(.)', r'\1', text)
            plain = re.sub(r'[*_`~]', '', plain)
            await callback.message.edit_text(plain, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Analytics {page_name} plain text also failed: {e2}")
            # Last resort: send a new message
            try:
                await callback.message.answer(
                    f"⚠️ Analytics page failed to render. Please try again.",
                    reply_markup=reply_markup,
                )
            except Exception:
                pass

def _analytics_nav_kb(current_page: str) -> InlineKeyboardMarkup:
    """Navigation keyboard for analytics pages."""
    pages = [
        ("📊 Overview", "admin_analytics"),
        ("👑 Admins", "analytics_admins"),
        ("📦 Products", "analytics_products:1"),
        ("🧾 Sales", "analytics_sales:1"),
        ("📈 Trends", "analytics_trends"),
        ("🔻 Losses", "analytics_promo_losses"),
        ("🤝 Referrals", "analytics_referrals:1"),
        ("📆 Daily P&L", "analytics_daily_pnl"),
        ("🏷️ Category", "analytics_category_profit"),
    ]
    rows = []
    current_row = []
    for i, (label, data) in enumerate(pages):
        base = data.split(":")[0]
        if base == current_page or data == current_page:
            label = f"• {label} •"
        btn = InlineKeyboardButton(text=label, callback_data=data)
        current_row.append(btn)
        if len(current_row) == 3:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([InlineKeyboardButton(text="🔄 Refresh", callback_data=current_page)])
    rows.append([back_button("admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



# ── Page 1: Overview Dashboard ────────────────────────────

@router.callback_query(F.data == "admin_analytics")
@admin_only
@error_handler
async def cb_admin_analytics(callback: types.CallbackQuery):
    """Main analytics overview — key metrics at a glance."""
    stats = await db.get_sales_stats()
    user_count = await db.get_user_count()
    total_stock = await db.get_total_stock()

    revenue = float(stats["total_revenue"])
    revenue_str = escape_md(format_currency(revenue))

    # Wallet / referral reward stats
    wallet_used = await db.get_total_wallet_used_in_purchases()
    rewards_given = await db.get_total_referral_rewards_given()
    gateway_revenue = revenue - wallet_used  # actual money received

    # Promotional losses
    total_promo_loss = 0
    try:
        promo_losses = await db.get_total_promotional_losses()
        total_promo_loss = promo_losses.get("_grand_total", 0)
    except Exception:
        pass

    # Expenses & COGS
    total_expenses = 0
    stock_cogs = 0
    try:
        total_expenses = await db.get_total_expenses()
        stock_cogs = await db.get_total_stock_cost()
    except Exception:
        pass

    # Calculate TRUE NET PROFIT (Revenue - Losses - Expenses - COGS)
    total_loss = wallet_used + total_promo_loss
    total_costs = total_loss + total_expenses + stock_cogs
    net_profit = gateway_revenue - total_promo_loss - total_expenses - stock_cogs

    # Profit/Loss indicator
    if net_profit > 0:
        profit_icon = "📈"
        profit_label = "NET PROFIT"
    elif net_profit < 0:
        profit_icon = "📉"
        profit_label = "NET LOSS"
    else:
        profit_icon = "➖"
        profit_label = "BREAK EVEN"

    # Admin count
    admin_count = await db.get_admin_count()

    # Payment method breakdown
    pay_methods = await db.get_payment_method_stats()
    method_lines = []
    method_icons = {"wallet": "💰", "paytm": "📱", "bharatpe": "🏦", "razorpay": "💳",
                    "combo_paytm": "🔀", "combo_bharatpe": "🔀", "combo_razorpay": "🔀", "gateway": "💳"}
    for pm in pay_methods:
        m = pm["method"]
        icon = method_icons.get(m, "💳")
        amt = escape_md(format_currency(float(pm["total_amount"])))
        method_lines.append(f"   {icon} {escape_md(m)}: *{pm['order_count']}* orders \\| *{amt}*")

    methods_text = "\n".join(method_lines) if method_lines else "   _No paid orders yet_"

    text = (
        f"📊 *ANALYTICS DASHBOARD*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{profit_icon} *{profit_label}: {escape_md(format_currency(abs(net_profit)))}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 *REVENUE \\(Paisa Aaya\\)*\n"
        f"  🏦 Gateway se mila: *{escape_md(format_currency(gateway_revenue))}*\n"
        f"  💰 Wallet se pay hua: *{escape_md(format_currency(wallet_used))}*\n"
        f"  📊 Total Revenue: *{revenue_str}*\n\n"
        f"💸 *LOSSES \\(Paisa Gaya\\)*\n"
        f"  🎁 Referral Rewards: *{escape_md(format_currency(rewards_given))}*\n"
        f"  🔻 Promotions/Giveaways: *{escape_md(format_currency(total_promo_loss))}*\n"
        f"  💸 Loss Total: *{escape_md(format_currency(total_loss))}*\n\n"
        f"📦 *EXPENSES \\(Kharcha\\)*\n"
        f"  📦 Stock COGS: *{escape_md(format_currency(stock_cogs))}*\n"
        f"  💼 Operational: *{escape_md(format_currency(total_expenses))}*\n"
        f"  📋 Expense Total: *{escape_md(format_currency(total_expenses + stock_cogs))}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏪 *STORE*\n"
        f"  👥 Users: *{user_count}* \\| 👑 Admins: *{admin_count}*\n"
        f"  📦 Stock: *{total_stock}* coupons\n\n"
        f"📋 *ORDERS*\n"
        f"  📊 Total: *{escape_md(str(stats['total_orders']))}*\n"
        f"  ✅ Paid: *{escape_md(str(stats['total_paid']))}* \\| 🟡 Pending: *{escape_md(str(stats['total_pending']))}* \\| ⏰ Expired: *{escape_md(str(stats['total_expired']))}*\n\n"
        f"💳 *PAYMENT METHODS*\n"
        f"{methods_text}\n\n"
        f"_Navigate below for details_ ⬇️"
    )

    await _analytics_safe_edit(
        callback, text, _analytics_nav_kb("admin_analytics"), "overview"
    )
    await callback.answer()


# ── Page 2: Admin-wise Sales & Net Revenue ────────────────

@router.callback_query(F.data == "analytics_admins")
@admin_only
@error_handler
async def cb_analytics_admins(callback: types.CallbackQuery):
    """Per-admin sales breakdown with proper net revenue calculation.
    
    Net Revenue = Gross Revenue - Referral Loss Share - Promotional Losses
    """
    admin_sales = await db.get_admin_sales_analytics()

    # Get ALL admin IDs (seed + DB, deduplicated) for accurate counting
    all_admin_ids = await db.get_all_admin_ids()
    admin_count = len(all_admin_ids)

    # Collect admin IDs for name lookup — include ALL admins
    admin_ids_for_names = all_admin_ids | {a["admin_id"] for a in admin_sales if a["admin_id"]}
    admin_names = await db.get_admin_names_map(admin_ids_for_names)

    # ── Loss Calculations ──
    # 1. Referral wallet loss (equally split among all admins)
    wallet_used = await db.get_total_wallet_used_in_purchases()
    referral_loss_per_admin = wallet_used / admin_count if admin_count > 0 else 0

    # 2. Promotional losses per admin (giveaways, extractions, rewards — direct + shared)
    admin_loss_shares = await db.get_admin_loss_share()
    loss_share_map = {ls["admin_id"]: ls for ls in admin_loss_shares}

    text = (
        f"👑 *ADMIN SALES REPORT*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # Global loss summary
    total_promo_loss = sum(ls["total_loss"] for ls in admin_loss_shares) if admin_loss_shares else 0
    total_loss = wallet_used + total_promo_loss
    if total_loss > 0:
        text += (
            f"⚠️ *Platform Loss Summary*\n"
            f"┌──────────────────\n"
            f"│ 🎁 Referral Rewards: *{escape_md(format_currency(wallet_used))}*\n"
            f"│ 🔻 Promotional Losses: *{escape_md(format_currency(total_promo_loss))}*\n"
            f"│ 💸 Total Loss: *{escape_md(format_currency(total_loss))}*\n"
            f"│ 👥 Split Among: *{admin_count}* admins\n"
            f"└──────────────────\n\n"
        )

    # Build admin_id -> sales data map
    sales_map = {a["admin_id"]: a for a in admin_sales}

    # Show all admins — those with sales first, then those without
    sorted_admins = []
    for a in admin_sales:
        sorted_admins.append(a["admin_id"])
    for aid in all_admin_ids:
        if aid not in sorted_admins:
            sorted_admins.append(aid)

    if not sorted_admins:
        text += "_No admins registered yet\\._"
    else:
        rank_emojis = ["🥇", "🥈", "🥉"]
        for i, aid in enumerate(sorted_admins):
            name = admin_names.get(aid, str(aid))
            rank = rank_emojis[i] if i < 3 else f"\\#{i+1}"
            a = sales_map.get(aid)

            # Get this admin's loss breakdown
            ls = loss_share_map.get(aid, {"direct_loss": 0, "shared_loss": 0, "total_loss": 0})
            promo_loss = ls["total_loss"]
            total_admin_loss = referral_loss_per_admin + promo_loss

            if a:
                gross_rev = float(a["total_revenue"])
                net_rev = max(0, gross_rev - total_admin_loss)
                rev_str = escape_md(format_currency(gross_rev))
                net_str = escape_md(format_currency(net_rev))
                pending_str = escape_md(format_currency(float(a["pending_revenue"])))

                text += (
                    f"{rank} *{escape_md(name)}*\n"
                    f"┌──────────────────\n"
                    f"│ 📦 Products: *{a['products_added']}* added • *{a['active_products']}* active\n"
                    f"│ 🛒 Total Sold: *{a['total_sold']}*\n"
                    f"│ 💰 Gross Revenue: *{rev_str}*\n"
                )
                if total_admin_loss > 0:
                    if referral_loss_per_admin > 0:
                        text += f"│ 🎁 Referral Loss: *\\-{escape_md(format_currency(referral_loss_per_admin))}*\n"
                    if promo_loss > 0:
                        text += f"│ 🔻 Promo Loss: *\\-{escape_md(format_currency(promo_loss))}*\n"
                text += f"│ 💵 *Net Revenue: {net_str}*\n"
                if a["pending_orders"] > 0:
                    text += f"│ 🟡 Pending: *{a['pending_orders']}* orders \\({pending_str}\\)\n"
                text += f"└──────────────────\n\n"
            else:
                # Admin exists but has no products — still show net calculation
                net_rev = max(0, 0 - total_admin_loss)
                text += (
                    f"{rank} *{escape_md(name)}*\n"
                    f"┌──────────────────\n"
                    f"│ 📦 Products: *0*\n"
                    f"│ 🛒 Total Sold: *0*\n"
                    f"│ 💰 Gross Revenue: *{escape_md(format_currency(0))}*\n"
                )
                if total_admin_loss > 0:
                    if referral_loss_per_admin > 0:
                        text += f"│ 🎁 Referral Loss: *\\-{escape_md(format_currency(referral_loss_per_admin))}*\n"
                    if promo_loss > 0:
                        text += f"│ 🔻 Promo Loss: *\\-{escape_md(format_currency(promo_loss))}*\n"
                text += f"│ 💵 *Net Revenue: {escape_md(format_currency(net_rev))}*\n"
                text += f"└──────────────────\n\n"

    await _analytics_safe_edit(
        callback, text, _analytics_nav_kb("analytics_admins"), "admins"
    )
    await callback.answer()


# ── Page 3: Product Analytics (Paginated) ─────────────────

@router.callback_query(F.data.regexp(r"^analytics_products(:\d+)?$"))
@admin_only
@error_handler
async def cb_analytics_products(callback: types.CallbackQuery):
    """Product-level analytics with pagination."""
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1
    PER_PAGE = 6

    product_stats = await db.get_product_analytics()

    # Collect admin names
    admin_ids = {p["admin_id"] for p in product_stats if p["admin_id"]}
    admin_names = await db.get_admin_names_map(admin_ids)

    total = len(product_stats)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PER_PAGE
    end = min(start + PER_PAGE, total)
    page_items = product_stats[start:end]

    text = (
        f"📦 *PRODUCT ANALYTICS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Page *{page}* / *{total_pages}* \\| Total: *{total}* products\n\n"
    )

    if not page_items:
        text += "_No products found\\._"
    else:
        for p in page_items:
            status = "🟢" if p["is_active"] else "🔴"
            title = escape_md(str(p["title"])[:30])
            price = escape_md(format_currency(float(p["price"])))
            rev = escape_md(format_currency(float(p["revenue"])))
            admin_name = admin_names.get(p["admin_id"], "Unknown") if p["admin_id"] else "Unknown"

            text += (
                f"{status} *{title}*\n"
                f"┌──────────────────\n"
                f"│ 💰 Price: *{price}* \\| Revenue: *{rev}*\n"
                f"│ 🛒 Sold: *{p['sold_count']}* \\| 📦 Stock: *{p['codes_available']}*\n"
                f"│ 🔑 Codes: *{p['codes_sold']}* sold / *{p['codes_sold'] + p['codes_available']}* total\n"
                f"│ 👤 By: _{escape_md(admin_name)}_\n"
                f"└──────────────────\n\n"
            )

    # Build navigation with product pagination
    pages_nav = [
        ("📊 Overview", "admin_analytics"),
        ("👑 Admins", "analytics_admins"),
        ("• 📦 Products •", f"analytics_products:{page}"),
        ("🧾 Sales", "analytics_sales:1"),
        ("📈 Trends", "analytics_trends"),
        ("🔻 Losses", "analytics_promo_losses"),
        ("🤝 Referrals", "analytics_referrals:1"),
    ]
    row1 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[:3]]
    row2 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[3:5]]
    row3 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[5:]]

    # Pagination row
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"analytics_products:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"analytics_products:{page+1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        row1, row2, row3, nav_row,
        [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"analytics_products:{page}")],
        [back_button("admin_panel")],
    ])

    await _analytics_safe_edit(callback, text, kb, "products")
    await callback.answer()


# ── Page 4: Recent Sales (Paginated) ──────────────────────

@router.callback_query(F.data.regexp(r"^analytics_sales(:\d+)?$"))
@admin_only
@error_handler
async def cb_analytics_sales(callback: types.CallbackQuery):
    """Recent sales with buyer details and payment method."""
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1
    PER_PAGE = 8

    recent = await db.get_recent_sales_detailed(100)

    # Admin names
    admin_ids = {r["admin_id"] for r in recent if r["admin_id"]}
    admin_names = await db.get_admin_names_map(admin_ids)

    total = len(recent)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PER_PAGE
    end = min(start + PER_PAGE, total)
    page_items = recent[start:end]

    text = (
        f"🧾 *RECENT SALES*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Page *{page}* / *{total_pages}* \\| Total: *{total}* sales\n\n"
    )

    if not page_items:
        text += "_No sales yet\\._"
    else:
        method_icons = {"wallet": "💰", "paytm": "📱", "bharatpe": "🏦", "razorpay": "💳",
                        "combo_paytm": "🔀", "combo_bharatpe": "🔀", "combo_razorpay": "🔀", "gateway": "💳"}
        for i, r in enumerate(page_items, start + 1):
            buyer = escape_md((r["buyer_name"] or "Unknown")[:20])
            title = escape_md((r["coupon_title"] or "N/A")[:20])
            amt = escape_md(format_currency(float(r["amount"])))
            method = r["payment_method"]
            m_icon = method_icons.get(method, "💳")
            admin_name = admin_names.get(r["admin_id"], "—") if r["admin_id"] else "—"
            uid = r["user_id"]

            # Format date
            paid_str = ""
            if r["paid_at"]:
                paid_str = r["paid_at"].strftime("%d/%m %H:%M")

            text += (
                f"*{i}\\.* 🛍️ *{title}*\n"
                f"   👤 {buyer} \\(`{uid}`\\)\n"
                f"   💸 *{amt}* × {r['quantity']} \\| {m_icon} {escape_md(method)}\n"
                f"   👑 _{escape_md(admin_name)}_ \\| 🕐 {escape_md(paid_str)}\n\n"
            )

    # Navigation
    pages_nav = [
        ("📊 Overview", "admin_analytics"),
        ("👑 Admins", "analytics_admins"),
        ("📦 Products", "analytics_products:1"),
        ("• 🧾 Sales •", f"analytics_sales:{page}"),
        ("📈 Trends", "analytics_trends"),
        ("🔻 Losses", "analytics_promo_losses"),
        ("🤝 Referrals", "analytics_referrals:1"),
    ]
    row1 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[:3]]
    row2 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[3:5]]
    row3 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[5:]]

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"analytics_sales:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"analytics_sales:{page+1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        row1, row2, row3, nav_row,
        [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"analytics_sales:{page}")],
        [back_button("admin_panel")],
    ])

    await _analytics_safe_edit(callback, text, kb, "sales")
    await callback.answer()


# ── Page 5: Revenue Trends ────────────────────────────────

@router.callback_query(F.data == "analytics_trends")
@admin_only
@error_handler
async def cb_analytics_trends(callback: types.CallbackQuery):
    """Text-based revenue trends — last 14 days."""
    daily = await db.get_daily_revenue(14)

    text = (
        f"📈 *REVENUE TRENDS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Last 14 days_\n\n"
    )

    if not daily:
        text += "_No revenue data yet\\._"
    else:
        # Find max revenue for bar chart scaling
        max_rev = max(float(d["revenue"]) for d in daily) if daily else 1
        max_rev = max(max_rev, 1)  # prevent division by zero

        total_period_rev = sum(float(d["revenue"]) for d in daily)
        total_period_orders = sum(d["order_count"] for d in daily)

        text += (
            f"💰 Period Total: *{escape_md(format_currency(total_period_rev))}*\n"
            f"🛒 Total Orders: *{total_period_orders}*\n\n"
        )

        # Text bar chart
        for d in daily:
            day_str = d["day"].strftime("%d/%m")
            rev = float(d["revenue"])
            orders = d["order_count"]
            bar_len = int((rev / max_rev) * 12) if max_rev > 0 else 0
            bar = "█" * bar_len + "░" * (12 - bar_len)
            rev_str = escape_md(format_currency(rev))

            text += f"`{day_str}` {bar} *{rev_str}* \\({orders}\\)\n"

        text += (
            f"\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Daily Average:*\n"
        )
        avg_rev = total_period_rev / len(daily) if daily else 0
        avg_orders = total_period_orders / len(daily) if daily else 0
        text += (
            f"   💰 Revenue: *{escape_md(format_currency(avg_rev))}*\n"
            f"   🛒 Orders: *{escape_md(f'{avg_orders:.1f}')}*"
        )

    await _analytics_safe_edit(
        callback, text, _analytics_nav_kb("analytics_trends"), "trends"
    )
    await callback.answer()


# ── Page 6: Promotional Loss Analytics ────────────────────

@router.callback_query(F.data == "analytics_promo_losses")
@admin_only
@error_handler
async def cb_analytics_promo_losses(callback: types.CallbackQuery):
    """Promotional loss dashboard — tracks all platform losses."""
    promo_losses = await db.get_total_promotional_losses()
    admin_losses = await db.get_admin_promotional_losses()

    # Get ALL admin IDs (seed + DB) for complete name resolution
    all_admin_ids = await db.get_all_admin_ids()
    admin_count = len(all_admin_ids)
    admin_ids_for_names = all_admin_ids | {a["admin_id"] for a in admin_losses if a["admin_id"]}
    admin_names = await db.get_admin_names_map(admin_ids_for_names)

    grand_total = promo_losses.get("_grand_total", 0)

    text = (
        f"🔻 *PROMOTIONAL LOSS REPORT*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💸 *Total Platform Losses:* *{escape_md(format_currency(grand_total))}*\n"
        f"👥 *Active Admins:* *{admin_count}*\n\n"
    )

    # Loss by type
    loss_icons = {
        "wallet_reward": "💰", "referral_reward": "🤝",
        "coupon_reward": "🎟️", "giveaway": "🎁",
        "extraction": "📤", "manual_distribution": "📋",
        "free_coupon": "🆓", "promotional_discount": "🏷️"
    }
    type_lines = []
    for loss_type, data in promo_losses.items():
        if loss_type.startswith("_"):
            continue
        icon = loss_icons.get(loss_type, "📉")
        type_name = escape_md(loss_type.replace("_", " ").title())
        count = data["count"]
        amount = escape_md(format_currency(data["amount"]))
        type_lines.append(f"   {icon} {type_name}: *{amount}* \\({count} events\\)")

    if type_lines:
        text += "📊 *Loss Breakdown by Type*\n┌──────────────────\n"
        text += "\n".join(type_lines)
        text += "\n└──────────────────\n\n"
    else:
        text += "_No promotional losses recorded yet\\._\n\n"

    # Per-admin losses
    if admin_losses:
        text += "👑 *Loss Attribution by Admin*\n┌──────────────────\n"
        for a in admin_losses[:10]:
            name = escape_md(admin_names.get(a["admin_id"], str(a["admin_id"])))
            total = escape_md(format_currency(float(a["total_loss"])))
            giveaway = escape_md(format_currency(float(a["giveaway_loss"])))
            extraction = escape_md(format_currency(float(a["extraction_loss"])))
            text += (
                f"│ 👤 *{name}*\n"
                f"│    Total: *{total}* \\({a['event_count']} events\\)\n"
                f"│    🎁 Giveaway: *{giveaway}* \\({a['giveaway_count']}\\)\n"
                f"│    📤 Extraction: *{extraction}* \\({a['extraction_count']}\\)\n"
            )
        text += "└──────────────────\n\n"

    # Giveaway stats
    giveaway_stats = await db.get_admin_giveaway_stats()
    if giveaway_stats:
        text += "🎁 *Giveaway Distribution Stats*\n┌──────────────────\n"
        for g in giveaway_stats[:5]:
            name = escape_md(admin_names.get(g["admin_id"], str(g["admin_id"])))
            total_val = escape_md(format_currency(float(g["total_value_given"])))
            self_val = escape_md(format_currency(float(g["self_stock_value"])))
            other_val = escape_md(format_currency(float(g["other_stock_value"])))
            text += (
                f"│ 👤 *{name}*\n"
                f"│    📦 {g['total_codes_given']} codes given \\(*{total_val}*\\)\n"
                f"│    ✅ Self stock: *{self_val}* \\({g['self_stock_count']}\\)\n"
                f"│    ⚠️ Others' stock: *{other_val}* \\({g['other_stock_count']}\\)\n"
            )
        text += "└──────────────────\n\n"

    text += "_Updated in real\\-time_ 🔄"

    await _analytics_safe_edit(
        callback, text, _analytics_nav_kb("analytics_promo_losses"), "promo_losses"
    )
    await callback.answer()

# ── Page 7: Referral Leaderboard ──────────────────────────

@router.callback_query(F.data.regexp(r"^analytics_referrals(:\d+)?$"))
@admin_only
@error_handler
async def cb_analytics_referrals(callback: types.CallbackQuery):
    """Referral leaderboard — top referrers with earnings breakdown."""
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1
    PER_PAGE = 8

    # Get platform-wide referral summary
    ref_stats = await db.get_referral_summary_stats()

    # Get paginated leaderboard
    total_referrers = await db.get_referral_leaderboard_count()
    total_pages = max(1, (total_referrers + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PER_PAGE
    leaderboard = await db.get_referral_leaderboard(limit=PER_PAGE, offset=offset)

    text = (
        f"🤝 *REFERRAL LEADERBOARD*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # Platform summary
    text += (
        f"📊 *Platform Referral Stats*\n"
        f"┌──────────────────\n"
        f"│ 👥 Total Referrals: *{ref_stats['total_referrals']}*\n"
        f"│ 🧑 Active Referrers: *{ref_stats['total_referrers']}*\n"
        f"│ 🆕 Users Referred: *{ref_stats['total_referred']}*\n"
        f"│ 💰 Commissions Paid: *{escape_md(format_currency(ref_stats['total_commission_paid']))}*\n"
        f"│ 🎁 Total Rewards: *{escape_md(format_currency(ref_stats['total_rewards_distributed']))}*\n"
        f"└──────────────────\n\n"
    )

    if not leaderboard:
        text += "_No referrals recorded yet\\._"
    else:
        text += f"🏆 *Top Referrers* — Page *{page}*/*{total_pages}*\n\n"

        rank_emojis = ["🥇", "🥈", "🥉"]
        for idx, r in enumerate(leaderboard):
            global_rank = offset + idx
            rank = rank_emojis[global_rank] if global_rank < 3 else f"\\#{global_rank + 1}"

            name = r["full_name"] or "Unknown"
            uname = f"@{r['username']}" if r["username"] else ""
            uid = r["telegram_id"]
            ref_count = r["referral_count"]
            commission = float(r["total_commission"])
            wallet_rew = float(r["wallet_rewards_earned"])
            comm_rew = float(r["commission_rewards_earned"])
            total_earned = wallet_rew + comm_rew

            # Format join date
            join_date = ""
            if r["join_date"]:
                try:
                    join_date = r["join_date"].strftime("%d %b %Y")
                except Exception:
                    join_date = str(r["join_date"])[:10]

            text += (
                f"{rank} *{escape_md(name)}*"
            )
            if uname:
                text += f" _{escape_md(uname)}_"
            text += (
                f"\n"
                f"┌──────────────────\n"
                f"│ 🆔 ID: `{uid}`\n"
                f"│ 👥 Referrals: *{ref_count}*\n"
                f"│ 💰 Total Earned: *{escape_md(format_currency(total_earned))}*\n"
            )
            if wallet_rew > 0:
                text += f"│    🎁 Wallet Rewards: *{escape_md(format_currency(wallet_rew))}*\n"
            if comm_rew > 0:
                text += f"│    🤝 Commissions: *{escape_md(format_currency(comm_rew))}*\n"
            if join_date:
                text += f"│ 📅 Joined: _{escape_md(join_date)}_\n"
            text += f"└──────────────────\n\n"

    # Build navigation with pagination
    pages_nav = [
        ("📊 Overview", "admin_analytics"),
        ("👑 Admins", "analytics_admins"),
        ("📦 Products", "analytics_products:1"),
        ("🧾 Sales", "analytics_sales:1"),
        ("📈 Trends", "analytics_trends"),
        ("🔻 Losses", "analytics_promo_losses"),
        (f"• 🤝 Referrals •", f"analytics_referrals:{page}"),
    ]
    nav_row1 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[:3]]
    nav_row2 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[3:5]]
    nav_row3 = [InlineKeyboardButton(text=l, callback_data=d) for l, d in pages_nav[5:]]

    # Pagination row
    pg_row = []
    if page > 1:
        pg_row.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"analytics_referrals:{page-1}"))
    pg_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        pg_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"analytics_referrals:{page+1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav_row1, nav_row2, nav_row3, pg_row,
        [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"analytics_referrals:{page}")],
        [back_button("admin_panel")],
    ])

    await _analytics_safe_edit(callback, text, kb, "referrals")
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


# ══════════════════════════════════════════════════════════════
# 🔔 STOCK ALERT SETTINGS
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_stock_alerts")
@admin_only
@error_handler
async def cb_admin_stock_alerts(callback: types.CallbackQuery):
    """Stock alert settings page."""
    settings = await db.get_stock_alert_settings()
    threshold = settings.get("global_threshold", 5)
    enabled = settings.get("is_enabled", True)
    status_icon = "🟢" if enabled else "🔴"
    status_text = "Enabled" if enabled else "Disabled"

    # Count low stock coupons
    low_stock = await db.get_low_stock_coupons(threshold)
    low_count = len(low_stock)
    out_of_stock = sum(1 for c in low_stock if c["stock"] == 0)
    warning_count = low_count - out_of_stock

    text = (
        f"🔔 *STOCK ALERT SETTINGS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{status_icon} Status: *{status_text}*\n"
        f"📊 Threshold: *{threshold}* units\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 *Current Status*\n"
        f"  🟡 Low Stock: *{warning_count}* products\n"
        f"  🔴 Out of Stock: *{out_of_stock}* products\n\n"
        f"_When stock drops below the threshold,_\n"
        f"_all admins will be notified automatically\\._"
    )

    toggle_text = "🔴 Disable Alerts" if enabled else "🟢 Enable Alerts"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="admin_toggle_stock_alerts")],
        [InlineKeyboardButton(text="📊 Set Threshold", callback_data="admin_set_alert_threshold")],
        [InlineKeyboardButton(text="📋 View Low Stock", callback_data="admin_view_low_stock")],
        [back_button("admin_panel")],
    ])

    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_toggle_stock_alerts")
@admin_only
@error_handler
async def cb_toggle_stock_alerts(callback: types.CallbackQuery):
    settings = await db.get_stock_alert_settings()
    new_status = not settings.get("is_enabled", True)
    await db.update_stock_alert_settings(is_enabled=new_status)
    status_text = "enabled" if new_status else "disabled"
    await callback.answer(f"Stock alerts {status_text}!", show_alert=True)
    # Re-render settings page
    await cb_admin_stock_alerts(callback)


@router.callback_query(F.data == "admin_set_alert_threshold")
@admin_only
@error_handler
async def cb_set_alert_threshold(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.stock_alert_threshold_input)
    await _safe_edit_or_send(
        callback.message,
        f"📊 *Set Stock Alert Threshold*\n\n"
        f"Enter the stock level at which you want to\n"
        f"receive low\\-stock alerts\\."
        f"\n\n_Current: {escape_md(str((await db.get_stock_alert_settings()).get('global_threshold', 5)))}_"
        f"\n\nSend a number \\(e\\.g\\. 5, 10, 20\\):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [admin_cancel_button()],
        ]),
    )
    await callback.answer()


@router.message(AdminStates.stock_alert_threshold_input)
@admin_only
async def msg_stock_alert_threshold(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("⚠️ Please enter a valid positive number (e.g. 5, 10, 20).")
        return
    threshold = int(text)
    await db.update_stock_alert_settings(threshold=threshold)
    await state.clear()
    await message.answer(f"✅ Stock alert threshold set to {threshold} units.")
    logger.info(f"Admin {message.from_user.id} set stock alert threshold to {threshold}")


@router.callback_query(F.data == "admin_view_low_stock")
@admin_only
@error_handler
async def cb_view_low_stock(callback: types.CallbackQuery):
    """View all products currently below stock threshold."""
    settings = await db.get_stock_alert_settings()
    threshold = settings.get("global_threshold", 5)
    low_stock = await db.get_low_stock_coupons(threshold)

    if not low_stock:
        text = (
            f"📋 *LOW STOCK REPORT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ All products have sufficient stock\\!\n"
            f"_\\(threshold: {threshold} units\\)_"
        )
    else:
        lines = []
        for c in low_stock[:20]:  # Max 20 items
            stock = c["stock"]
            if stock == 0:
                icon = "🔴"
            elif stock <= 2:
                icon = "🟠"
            else:
                icon = "🟡"
            cat = f" [{escape_md(c.get('category', ''))}]" if c.get('category') else ""
            lines.append(f"{icon} {escape_md(c['title'])}{cat}: *{stock}* left")

        text = (
            f"📋 *LOW STOCK REPORT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Threshold: {threshold} units_\n\n"
            + "\n".join(lines)
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_view_low_stock")],
        [back_button("admin_stock_alerts")],
    ])
    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


# ══════════════════════════════════════════════════════════════
# 💰 EXPENSE TRACKING
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_expenses")
@admin_only
@error_handler
async def cb_admin_expenses(callback: types.CallbackQuery):
    """Expense overview page."""
    summary = await db.get_expenses_summary()
    total = summary.get("_grand_total", 0)
    stock_cost = await db.get_total_stock_cost()

    type_icons = {
        "stock_purchase": "📦", "operational": "⚙️", "payout": "💸",
        "refund": "↩️", "gateway_fee": "💳", "other": "📝"
    }

    lines = []
    for etype, data in summary.items():
        if etype.startswith("_"):
            continue
        icon = type_icons.get(etype, "📝")
        lines.append(f"  {icon} {escape_md(etype)}: *{escape_md(format_currency(data['total']))}* \\({data['count']} entries\\)")

    exp_text = "\n".join(lines) if lines else "   _No expenses recorded yet_"

    text = (
        f"💰 *EXPENSE TRACKER*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Summary*\n"
        f"  💸 Total Expenses: *{escape_md(format_currency(total))}*\n"
        f"  📦 Stock COGS: *{escape_md(format_currency(stock_cost))}*\n"
        f"  📋 Combined: *{escape_md(format_currency(total + stock_cost))}*\n\n"
        f"📂 *By Type*\n"
        f"{exp_text}\n\n"
        f"_Add expenses to track operational costs_"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Expense", callback_data="admin_add_expense")],
        [InlineKeyboardButton(text="📋 Recent Expenses", callback_data="admin_recent_expenses")],
        [InlineKeyboardButton(text="👑 By Admin", callback_data="admin_expenses_by_admin")],
        [back_button("admin_panel")],
    ])

    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_add_expense")
@admin_only
@error_handler
async def cb_add_expense(callback: types.CallbackQuery, state: FSMContext):
    """Start add expense flow."""
    await state.set_state(AdminStates.expense_type_input)
    types_text = (
        "📦 stock\\_purchase — Stock/inventory cost\n"
        "⚙️ operational — Server, hosting, tools\n"
        "💸 payout — Payouts to partners\n"
        "↩️ refund — Customer refunds\n"
        "💳 gateway\\_fee — Payment gateway fees\n"
        "📝 other — Miscellaneous"
    )
    await _safe_edit_or_send(
        callback.message,
        f"➕ *ADD EXPENSE*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Select expense type:\n\n"
        f"{types_text}\n\n"
        f"_Type one of: stock\\_purchase, operational, payout, refund, gateway\\_fee, other_",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [admin_cancel_button()],
        ]),
    )
    await callback.answer()


@router.message(AdminStates.expense_type_input)
@admin_only
async def msg_expense_type(message: types.Message, state: FSMContext):
    valid_types = ["stock_purchase", "operational", "payout", "refund", "gateway_fee", "other"]
    etype = message.text.strip().lower()
    if etype not in valid_types:
        await message.answer(f"⚠️ Invalid type. Choose: {', '.join(valid_types)}")
        return
    await state.update_data(expense_type=etype)
    await state.set_state(AdminStates.expense_amount_input)
    await message.answer(f"✅ Type: {etype}\n\n💰 Now enter the amount (e.g. 500, 1000.50):")


@router.message(AdminStates.expense_amount_input)
@admin_only
async def msg_expense_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Enter a valid positive amount (e.g. 500, 1000.50).")
        return
    await state.update_data(expense_amount=amount)
    await state.set_state(AdminStates.expense_desc_input)
    await message.answer(f"✅ Amount: ₹{amount:.2f}\n\n📝 Enter a description (or send 'skip'):")


@router.message(AdminStates.expense_desc_input)
@admin_only
async def msg_expense_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    desc = message.text.strip()
    if desc.lower() == "skip":
        desc = None

    admin_id = message.from_user.id
    expense_id = await db.add_expense(
        admin_id=admin_id,
        expense_type=data["expense_type"],
        amount=data["expense_amount"],
        description=desc,
    )
    await state.clear()
    await message.answer(
        f"✅ Expense recorded!\n\n"
        f"📋 ID: #{expense_id}\n"
        f"📂 Type: {data['expense_type']}\n"
        f"💰 Amount: ₹{data['expense_amount']:.2f}\n"
        f"📝 Note: {desc or 'N/A'}\n\n"
        f"This will now appear in analytics."
    )
    logger.info(f"Admin {admin_id} added expense #{expense_id}: {data['expense_type']} ₹{data['expense_amount']:.2f}")


@router.callback_query(F.data == "admin_recent_expenses")
@admin_only
@error_handler
async def cb_recent_expenses(callback: types.CallbackQuery):
    expenses = await db.get_admin_expenses_list(limit=15)
    if not expenses:
        text = "📋 *RECENT EXPENSES*\n━━━━━━━━━━━━━━━━━━━━\n\n_No expenses recorded yet\\._"
    else:
        admin_ids = {e["admin_id"] for e in expenses}
        names = await db.get_admin_names_map(admin_ids)

        lines = []
        for e in expenses:
            admin_name = escape_md(names.get(e["admin_id"], str(e["admin_id"])))
            amt = escape_md(format_currency(float(e["amount"])))
            desc = escape_md(e.get("description", "") or "")
            if len(desc) > 30:
                desc = desc[:27] + "\\.\\.\\."
            date_str = escape_md(format_datetime(e["created_at"]))
            lines.append(f"• {escape_md(e['expense_type'])} \\| *{amt}* \\| {admin_name}\n  _{desc}_ \\| {date_str}")

        text = (
            f"📋 *RECENT EXPENSES*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n\n".join(lines)
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_recent_expenses")],
        [back_button("admin_expenses")],
    ])
    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_expenses_by_admin")
@admin_only
@error_handler
async def cb_expenses_by_admin(callback: types.CallbackQuery):
    admin_totals = await db.get_admin_expense_totals()
    if not admin_totals:
        text = "👑 *EXPENSES BY ADMIN*\n━━━━━━━━━━━━━━━━━━━━\n\n_No expenses recorded yet\\._"
    else:
        admin_ids = {a["admin_id"] for a in admin_totals}
        names = await db.get_admin_names_map(admin_ids)

        lines = []
        for i, a in enumerate(admin_totals, 1):
            name = escape_md(names.get(a["admin_id"], str(a["admin_id"])))
            total = escape_md(format_currency(float(a["total_spent"])))
            lines.append(f"{i}\\. {name}: *{total}* \\({a['expense_count']} entries\\)")

        text = (
            f"👑 *EXPENSES BY ADMIN*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(lines)
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [back_button("admin_expenses")],
    ])
    await _safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


# ══════════════════════════════════════════════════════════════
# 📈 ENHANCED ANALYTICS — Daily P&L, Category Profit, Time-based
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "analytics_daily_pnl")
@admin_only
@error_handler
async def cb_analytics_daily_pnl(callback: types.CallbackQuery):
    """Daily profit & loss for the last 7 days."""
    daily = await db.get_daily_profit(7)

    lines = []
    for d in daily:
        day_str = d["day"].strftime("%d %b")
        rev = float(d["revenue"])
        profit = float(d["net_profit"])
        orders = int(d["orders"])
        
        if profit > 0:
            icon = "📈"
        elif profit < 0:
            icon = "📉"
        else:
            icon = "➖"

        lines.append(
            f"{icon} *{escape_md(day_str)}*: "
            f"Rev *{escape_md(format_currency(rev))}* \\| "
            f"P/L *{escape_md(format_currency(profit))}* \\| "
            f"{orders} orders"
        )

    text = (
        f"📆 *DAILY PROFIT \\& LOSS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Last 7 days_\n\n"
        + ("\n".join(lines) if lines else "_No data yet_")
    )

    kb = _analytics_nav_kb("analytics_daily_pnl")
    await _analytics_safe_edit(callback, text, kb, "daily_pnl")
    await callback.answer()


@router.callback_query(F.data == "analytics_category_profit")
@admin_only
@error_handler
async def cb_analytics_category_profit(callback: types.CallbackQuery):
    """Category-wise profitability."""
    categories = await db.get_category_profitability()

    lines = []
    for c in categories:
        cat_name = escape_md(c["category"])
        rev = float(c["revenue"])
        cost = float(c["total_cost"])
        profit = float(c["profit"])
        sold = int(c["units_sold"])
        stock = int(c["current_stock"])

        if profit > 0:
            icon = "🟢"
        elif profit < 0:
            icon = "🔴"
        else:
            icon = "⚪"

        lines.append(
            f"{icon} *{cat_name}*\n"
            f"   Rev: *{escape_md(format_currency(rev))}* \\| Cost: *{escape_md(format_currency(cost))}*\n"
            f"   Profit: *{escape_md(format_currency(profit))}* \\| Sold: *{sold}* \\| Stock: *{stock}*"
        )

    text = (
        f"🏷️ *CATEGORY PROFITABILITY*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        + ("\n\n".join(lines) if lines else "_No data yet_")
    )

    kb = _analytics_nav_kb("analytics_category_profit")
    await _analytics_safe_edit(callback, text, kb, "category_profit")
    await callback.answer()


# ── No-op handler for pagination page indicators ──────────

@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    """No-op — handles page indicator buttons that shouldn't do anything."""
    await callback.answer()
