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
    """Show the Refer & Earn page with milestone rewards."""
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
        # Show milestone-based rewards
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
    else:
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
    
    # Allow manual entry if no referrer
    referrer = await db.get_referrer_of(user_id)
    if not referrer:
        buttons.append([InlineKeyboardButton(text="🔗 Enter Referral Code", callback_data="ref_enter_code")])

    if mode == "code_reward":
        # Check if user has claimable rewards
        claimable = await db.get_claimable_rewards(user_id, ref_count)
        if claimable:
            buttons.append([InlineKeyboardButton(text="🎁 Claim Rewards", callback_data="ref_claim_rewards")])
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

    title_esc = escape_md(reward["title"])
    code_esc = escape_md(code)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])

    await callback.message.edit_text(
        f"🎉 *Congratulations\\!*\n\n"
        f"You claimed: *{title_esc}*\n\n"
        f"🔑 Your coupon code:\n"
        f"`{code_esc}`\n\n"
        f"_Save this code\\!_",
        parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer("Reward claimed! 🎉")


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
        status = "✅" if h["status"] == "purchased" else "👤"
        comm = escape_md(format_currency(float(h["commission"])))
        lines.append(f"{status} {name} — {comm}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[back_button("back_home")]])
    await callback.message.edit_text(
        "\n".join(lines), parse_mode="MarkdownV2", reply_markup=kb
    )
    await callback.answer()


async def process_referral_on_purchase(user_id: int, order_amount: float):
    """Called after a successful purchase to credit referral commission."""
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

    if mode == "balance":
        # Commission mode: give % of purchase to referrer
        pct = float(settings["commission_percent"])
        commission = round(order_amount * pct / 100, 2)
        if commission > 0:
            await db.add_referral_earnings(referrer_id, commission)
            # Update referral record
            await pool.execute(
                "UPDATE referrals SET status = 'purchased', commission = commission + $3 "
                "WHERE referrer_id = $1 AND referred_id = $2",
                referrer_id, user_id, commission
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
    
    await db.set_user_referrer(message.from_user.id, referrer_id)
    await state.clear()
    
    await message.answer("✅ Referral code applied successfully!")
    await text_refer_earn(message)
