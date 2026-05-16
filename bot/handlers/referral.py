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
    """Show the Refer & Earn page with rewards info."""
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

    mode = settings["mode"]
    if mode == "code_reward":
        rewards = await db.get_referral_rewards()
        active_rewards = [r for r in rewards if r["is_active"]]
        if active_rewards:
            how_it_works = (
                f"✨ *How it works:*\n"
                f"1️⃣ Share your link\n"
                f"2️⃣ Friends join the bot\n"
                f"3️⃣ Reach milestones to claim free coupons\\!\n\n"
                f"🎁 *Available Rewards:*\n"
            )
            for r in active_rewards:
                title_esc = escape_md(r["title"])
                needed = r["referrals_needed"]
                if ref_count >= needed:
                    how_it_works += f"✅ {title_esc} — {needed} refs \\(unlocked\\!\\)\n"
                else:
                    how_it_works += f"🔒 {title_esc} — {needed} refs\n"
        else:
            how_it_works = (
                f"✨ *How it works:*\n"
                f"1️⃣ Share your link\n"
                f"2️⃣ Friends join the bot\n"
                f"3️⃣ Earn free coupons\\!\n"
            )
    elif mode == "wallet_reward":
        reward_amt = float(settings.get("reward_amount", 10.0) or 10.0)
        how_it_works = (
            f"✨ *How it works:*\n"
            f"1️⃣ Share your link\n"
            f"2️⃣ Friends join the bot\n"
            f"3️⃣ Get 💵 *₹{escape_md(str(reward_amt))}* per referral\\!\n\n"
            f"💰 Reward goes straight to your wallet\\!\n"
        )
    else:  # commission
        pct = settings["commission_percent"]
        how_it_works = (
            f"✨ *How it works:*\n"
            f"1️⃣ Share your link\n"
            f"2️⃣ Friends join \\& buy\n"
            f"3️⃣ Earn 💰 *{escape_md(str(pct))}%* commission\n"
        )

    link_esc = escape_md(link)
    ref_code_esc = escape_md(ref_code)
    earnings_esc = escape_md(format_currency(earnings))
    wallet_esc = escape_md(format_currency(wallet))

    text = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 *REFER \\& EARN*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{how_it_works}\n"
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

    # 🎁 Claim Rewards — FIRST PRIORITY (top)
    if mode == "code_reward":
        claimable = await db.get_claimable_rewards(user_id, ref_count)
        if claimable:
            buttons.append([InlineKeyboardButton(text="🎁 Claim Rewards", callback_data="ref_claim_rewards")])

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
    """Called after a successful purchase to credit referral commission.
    
    Works for ALL payment methods (Paytm, BharatPe, Razorpay, Wallet).
    Converts order_amount to float to safely handle Decimal from DB.
    """
    from bot.utils.logger import logger

    settings = await db.get_referral_settings()
    if not settings or not settings["is_active"]:
        return

    # Get who referred this user
    pool = await db.get_pool()
    user = await pool.fetchrow("SELECT referred_by FROM users WHERE telegram_id = $1", user_id)
    if not user or not user["referred_by"]:
        return

    referrer_id = user["referred_by"]
    mode = settings["mode"]

    if mode == "commission":
        # Commission mode: give % of purchase to referrer's wallet
        pct = float(settings["commission_percent"])
        amount_float = float(order_amount)  # CRITICAL: Decimal → float to avoid TypeError
        commission = round(amount_float * pct / 100, 2)
        if commission <= 0:
            return

        # Credit referrer's wallet + referral_earnings
        await db.add_referral_earnings(referrer_id, commission)

        # Log wallet transaction for referrer
        try:
            referrer_wallet = await db.get_wallet_balance(referrer_id)
            await db.add_wallet_transaction(
                referrer_id, commission, "topup",
                bal_before=referrer_wallet - commission,
                bal_after=referrer_wallet,
                reference=f"referral_commission_from_{user_id}",
            )
        except Exception as e:
            logger.warning(f"Referral wallet transaction log failed (non-critical): {e}")

        # Update referral record
        await pool.execute(
            "UPDATE referrals SET status = 'purchased', commission = commission + $3 "
            "WHERE referrer_id = $1 AND referred_id = $2",
            referrer_id, user_id, commission
        )

        # Notify referrer about earned commission
        try:
            buyer = await pool.fetchrow(
                "SELECT full_name, username FROM users WHERE telegram_id = $1", user_id
            )
            buyer_name = ""
            if buyer:
                buyer_name = buyer["full_name"] or buyer["username"] or str(user_id)
            else:
                buyer_name = str(user_id)

            notify_text = (
                f"🎉 *Referral Commission Earned\\!*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Your referral *{escape_md(buyer_name)}* made a purchase\\!\n"
                f"💰 Commission: *₹{escape_md(str(commission))}* \\({escape_md(str(pct))}%\\)\n"
                f"💵 Wallet Balance: *₹{escape_md(str(round(float(referrer_wallet), 2)))}*\n\n"
                f"🚀 _Keep referring to earn more\\!_"
            )
            if bot:
                await bot.send_message(referrer_id, notify_text, parse_mode="MarkdownV2")
            else:
                logger.debug(f"No bot instance for referrer notification (user={referrer_id})")
        except Exception as e:
            logger.warning(f"Referrer notification failed (non-critical): {e}")

        logger.info(
            f"Referral commission credited: referrer={referrer_id}, "
            f"buyer={user_id}, commission=₹{commission}, pct={pct}%"
        )


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
    if referrer_id == message.from_user.id:
        await message.answer("❌ You cannot use your own referral code.")
        return

    # Ensure current user is registered (prevents FK violation on referrals table)
    await db.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )

    await db.set_user_referrer(message.from_user.id, referrer_id)
    await state.clear()
    
    await message.answer("✅ Referral code applied successfully!")
    await text_refer_earn(message)
