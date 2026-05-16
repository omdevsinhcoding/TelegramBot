"""
DreamX Coupon Bot — Referral System Handler
Handles Refer & Earn flow, referral tracking, commission distribution,
and coupon-based milestone rewards.
"""

from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.database import queries as db
from bot.config import Config
from bot.utils.helpers import escape_md, format_currency
from bot.utils.decorators import error_handler
from bot.keyboards.common import back_button
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

class ReferralStates(StatesGroup):
    enter_referral_code = State()

router = Router()


@router.message(F.text == "🎁 Refer & Earn")
@error_handler
async def text_refer_earn(message: types.Message):
    """Show the Refer & Earn page."""
    settings = await db.get_referral_settings()
    if not settings or not settings["is_active"]:
        await message.answer("🎁 Referral program is currently inactive.")
        return

    user_id = message.from_user.id
    ref_code = await db.get_or_create_referral_code(user_id)
    ref_count = await db.get_referral_count(user_id)
    earnings = await db.get_user_referral_earnings(user_id)
    wallet = await db.get_user_wallet(user_id)

    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={ref_code}"

    reward_amt = float(settings.get("reward_amount", 10.0) or 10.0)

    link_esc = escape_md(link)
    ref_code_esc = escape_md(ref_code)
    earnings_esc = escape_md(format_currency(earnings))
    wallet_esc = escape_md(format_currency(wallet))
    amt_esc = escape_md(str(reward_amt))

    text = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 *REFER \\& EARN*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✨ *How it works:*\n"
        f"1️⃣ Share your link\n"
        f"2️⃣ Friends join the bot\n"
        f"3️⃣ Get 💵 *₹{amt_esc}* per referral\\!\n\n"
        f"💰 Reward goes straight to your wallet\\!\n\n"
        f"🔗 *Your Link:*\n"
        f"`{link_esc}`\n\n"
        f"🔑 *Code:*\n"
        f"`{ref_code_esc}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Your Stats*\n\n"
        f"👥 Referrals: *{ref_count}*\n"
        f"💸 Earnings: *{earnings_esc}*\n"
        f"💰 Wallet: *{wallet_esc}*\n\n"
        f"💡 _Wallet balance can be used to purchase coupons\\!_ 💳\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    buttons = []

    # Allow manual entry if no referrer
    referrer = await db.get_referrer_of(user_id)
    if not referrer:
        buttons.append([InlineKeyboardButton(text="🔗 Enter Referral Code", callback_data="ref_enter_code")])

    buttons.append([InlineKeyboardButton(text="📋 My Referral History", callback_data="ref_history")])
    buttons.append([InlineKeyboardButton(text="◀️ Back", callback_data="back_home")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


@router.callback_query(F.data == "ref_claim_rewards")
@error_handler
async def cb_ref_claim_rewards(callback: types.CallbackQuery):
    """Show rewards user can claim based on their referral count."""
    user_id = callback.from_user.id
    ref_count = await db.get_referral_count(user_id)
    claimable = await db.get_claimable_rewards(user_id, ref_count)

    if not claimable:
        await callback.answer("No rewards to claim right now. Keep referring!", show_alert=True)
        return

    text = (
        "🎁 *Claim Your Referral Rewards*\n\n"
        f"👥 Your referrals: *{ref_count}*\n\n"
        "Select a reward to claim:"
    )

    buttons = []
    for r in claimable:
        title = r["title"][:30]
        buttons.append([InlineKeyboardButton(
            text=f"🎁 {title} ({r['referrals_needed']} refs)",
            callback_data=f"ref_claim:{r['id']}"
        )])
    buttons.append([back_button("back_home")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("ref_claim:"))
@error_handler
async def cb_ref_claim(callback: types.CallbackQuery):
    """User claims a specific referral reward."""
    reward_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Verify user has enough referrals
    ref_count = await db.get_referral_count(user_id)
    reward = await db.get_referral_reward(reward_id)
    if not reward:
        await callback.answer("Reward not found.", show_alert=True)
        return

    if ref_count < reward["referrals_needed"]:
        await callback.answer(
            f"You need {reward['referrals_needed']} referrals. You have {ref_count}.",
            show_alert=True
        )
        return

    # Try to claim
    code = await db.claim_referral_reward(user_id, reward_id)
    if not code:
        await callback.answer("Could not claim. Already claimed or out of stock.", show_alert=True)
        return

    # Create a reward order so it appears in Order History
    from bot.utils.helpers import generate_order_id
    order_id = generate_order_id()
    try:
        await db.create_reward_order(order_id, user_id, reward["coupon_id"], "referral_reward")
        # Link the coupon code to this order
        pool = await db.get_pool()
        await pool.execute(
            "UPDATE coupon_codes SET order_id = $1 WHERE coupon_id = $2 AND code = $3 AND sold_to = $4",
            order_id, reward["coupon_id"], code, user_id
        )
    except Exception as e:
        from bot.utils.logger import logger
        logger.warning(f"Failed to create reward order (non-critical): {e}")

    title_esc = escape_md(reward["title"])
    code_esc = escape_md(code)
    oid_esc = escape_md(order_id) if order_id else ""
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])

    await callback.message.edit_text(
        f"🎊✨ *CONGRATULATIONS\\!* ✨🎊\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 *REFERRAL REWARD CLAIMED\\!*\n\n"
        f"🎁 Reward: *{title_esc}*\n"
        f"🔑 Your Code:\n"
        f"`{code_esc}`\n\n"
        f"📦 Order ID: `{oid_esc}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 _This reward is saved in your_\n"
        f"_📦 Order History — view anytime\\!_\n\n"
        f"🤝 _Keep referring to unlock more rewards\\!_ 🚀",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer("🎉 Reward claimed!")


@router.callback_query(F.data == "ref_history")
@error_handler
async def cb_ref_history(callback: types.CallbackQuery):
    """Show referral history."""
    history = await db.get_referral_history(callback.from_user.id, 20)

    if not history:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
        await callback.message.edit_text(
            "📋 *Referral History*\n\nNo referrals yet\\. Share your link to start earning\\!",
            parse_mode="MarkdownV2", reply_markup=kb
        )
        await callback.answer()
        return

    lines = ["📋 *Referral History*\n"]
    for h in history:
        name = escape_md(h.get("full_name") or h.get("username") or "Unknown")
        # Guard against missing columns on older DB rows
        status = h.get("status", "joined") or "joined"
        comm_val = h.get("commission") or 0
        status_icon = "✅" if status == "purchased" else "👤"
        comm = escape_md(format_currency(float(comm_val)))
        lines.append(f"{status_icon} {name} — {comm}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
    await callback.message.edit_text(
        "\n".join(lines), parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer()


async def process_referral_on_purchase(user_id: int, order_amount, bot=None):
    """No-op — all referral rewards are credited at JOIN time (start.py).

    This function is kept as a stub so callers in order_service.py
    don't need to be modified.
    """
    pass


@router.callback_query(F.data == "ref_enter_code")
@error_handler
async def cb_ref_enter_code(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ReferralStates.enter_referral_code)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
    await callback.message.edit_text(
        "🔗 *Enter Referral Code*\n\nSend the code of the user who invited you:",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer()


@router.message(ReferralStates.enter_referral_code)
@error_handler
async def msg_ref_enter_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    referrer = await db.get_user_by_referral_code(code)
    
    if not referrer:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
        await message.answer("❌ Invalid referral code. Please try again or go back.", reply_markup=kb)
        return
    
    referrer_id = referrer["telegram_id"]
    user_id = message.from_user.id

    if referrer_id == user_id:
        await message.answer("❌ You cannot use your own referral code.")
        return

    # Check if already referred
    existing = await db.get_referrer_of(user_id)
    if existing:
        await message.answer("❌ You already have a referrer. Each user can only be referred once.")
        await state.clear()
        return

    # Ensure current user is registered (prevents FK violation)
    await db.upsert_user(user_id, message.from_user.username, message.from_user.full_name)

    # Record the referral
    success = await db.record_referral(referrer_id, user_id)
    if not success:
        await message.answer("❌ Could not apply referral code. You may already have a referrer.")
        await state.clear()
        return

    await state.clear()
    logger.info(f"[REFERRAL] Manual code entry: {referrer_id} -> {user_id}")

    # Credit the referrer
    ref_settings = await db.get_referral_settings()
    if ref_settings and ref_settings["is_active"]:
        reward_amt = float(ref_settings.get("reward_amount", 10.0) or 10.0)
        try:
            await db.add_referral_earnings(referrer_id, reward_amt)
            logger.info(f"[REFERRAL] ₹{reward_amt} credited to {referrer_id} (manual code entry)")

            # Log wallet transaction
            try:
                bal = await db.get_wallet_balance(referrer_id)
                await db.add_wallet_transaction(
                    referrer_id, reward_amt, "topup",
                    bal_before=bal - reward_amt,
                    bal_after=bal,
                    reference=f"referral_from_{user_id}",
                )
            except Exception as wt_err:
                logger.warning(f"[REFERRAL] wallet txn log failed: {wt_err}")

            # Notify referrer
            try:
                ref_name = escape_md(message.from_user.first_name or "Someone")
                bal = await db.get_wallet_balance(referrer_id)
                notify_text = (
                    f"🎉 *New Referral\\!*\n\n"
                    f"👤 {ref_name} joined using your code\\!\n"
                    f"💵 *₹{escape_md(str(reward_amt))}* added to your wallet\\!\n"
                    f"💰 Balance: *₹{escape_md(str(round(float(bal), 2)))}*\n\n"
                    f"🚀 _Keep sharing to earn more\\!_"
                )
                await message.bot.send_message(referrer_id, notify_text, parse_mode="MarkdownV2")
            except Exception as n_err:
                logger.warning(f"[REFERRAL] notification failed: {n_err}")

        except Exception as credit_err:
            logger.error(f"[REFERRAL] CREDIT FAILED (manual): {credit_err}")

    referrer_name = referrer.get("full_name") or str(referrer_id)
    await message.answer(
        f"✅ Referral code applied! You were referred by *{escape_md(referrer_name)}*\\.\n"
        f"🎁 Your friend has received their reward\\!",
        parse_mode="MarkdownV2"
    )
    await text_refer_earn(message)

