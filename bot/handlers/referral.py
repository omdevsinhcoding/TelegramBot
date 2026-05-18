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
from bot.utils.logger import logger
from bot.keyboards.common import back_button
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

class ReferralStates(StatesGroup):
    enter_referral_code = State()

router = Router()


@router.message(F.text == "🎁 Refer & Earn")
@error_handler
async def text_refer_earn(message: types.Message):
    """Show the Refer & Earn page — respects admin mode setting."""
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

    # ── Build mode-specific "how it works" section ──
    mode = settings.get("mode", "wallet_reward") or "wallet_reward"

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
    elif mode == "commission":
        pct = settings.get("commission_percent", 10)
        how_it_works = (
            f"✨ *How it works:*\n"
            f"1️⃣ Share your link\n"
            f"2️⃣ Friends join \\& buy\n"
            f"3️⃣ Earn 💰 *{escape_md(str(pct))}%* commission\n"
        )
    else:  # wallet_reward (default)
        reward_amt = float(settings.get("reward_amount", 10.0) or 10.0)
        amt_esc = escape_md(str(reward_amt))
        how_it_works = (
            f"✨ *How it works:*\n"
            f"1️⃣ Share your link\n"
            f"2️⃣ Friends join the bot\n"
            f"3️⃣ Get 💵 *₹{amt_esc}* per referral\\!\n\n"
            f"💰 Reward goes straight to your wallet\\!\n"
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

    # 🎁 Claim Rewards — show in code_reward mode when rewards are available
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

    # Track promotional loss for coupon reward
    try:
        coupon_detail = await db.get_coupon(reward["coupon_id"])
        estimated_value = float(coupon_detail["discounted_price"]) if coupon_detail else 0
        coupon_owner = coupon_detail.get("created_by") if coupon_detail else None
        await db.record_promotional_loss(
            loss_type="coupon_reward",
            amount=estimated_value,
            coupon_owner_admin_id=coupon_owner,
            user_id=user_id,
            coupon_id=reward["coupon_id"],
            order_id=order_id,
            reference=f"referral_coupon_reward_{reward_id}",
            details={
                "reward_title": reward["title"],
                "referrals_needed": reward["referrals_needed"],
                "code": code,
            }
        )
    except Exception:
        pass

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
    """Credit referrer with purchase commission when referred user buys.

    Only active in 'commission' mode. Calculates commission_percent of
    the order amount and adds it to the referrer's wallet.
    """
    try:
        ref_settings = await db.get_referral_settings()
        if not ref_settings or not ref_settings["is_active"]:
            return
        if ref_settings.get("mode") != "commission":
            return  # Only applies in commission mode

        # Get this user's referrer
        referrer = await db.get_referrer_of(user_id)
        if not referrer:
            return

        referrer_id = referrer["telegram_id"]
        commission_pct = float(ref_settings.get("commission_percent", 10) or 10)
        commission_amt = round(float(order_amount) * commission_pct / 100, 2)

        if commission_amt <= 0:
            return

        # Credit commission to referrer's wallet
        await db.add_referral_earnings(referrer_id, commission_amt)

        # Update the referral row's commission total
        pool = await db.get_pool()
        await pool.execute(
            "UPDATE referrals SET commission = commission + $3, status = 'purchased' "
            "WHERE referrer_id = $1 AND referred_id = $2",
            referrer_id, user_id, commission_amt
        )

        # Log wallet transaction
        try:
            bal = await db.get_wallet_balance(referrer_id)
            await db.add_wallet_transaction(
                referrer_id, commission_amt, "referral_commission",
                bal_before=bal - commission_amt,
                bal_after=bal,
                reference=f"commission_from_{user_id}",
                description=f"{commission_pct}% commission on ₹{order_amount} purchase",
            )
        except Exception as wt_err:
            logger.warning(f"[REFERRAL] commission wallet txn log failed: {wt_err}")

        logger.info(
            f"[REFERRAL] Commission ₹{commission_amt} ({commission_pct}% of ₹{order_amount}) "
            f"credited to {referrer_id} from {user_id}'s purchase"
        )

        # Track promotional loss
        try:
            await db.record_promotional_loss(
                loss_type="referral_reward",
                amount=commission_amt,
                user_id=referrer_id,
                reference=f"commission_{commission_pct}pct_from_{user_id}",
                details={
                    "buyer_user_id": user_id,
                    "order_amount": float(order_amount),
                    "commission_pct": commission_pct,
                    "mode": "commission"
                }
            )
        except Exception:
            pass

        # Notify referrer
        if bot:
            try:
                from bot.utils.helpers import escape_md
                buyer = await db.get_user(user_id)
                buyer_name = escape_md((buyer["full_name"] if buyer else "Someone") or "Someone")
                notify_text = (
                    f"💰 *Commission Earned\\!*\n\n"
                    f"👤 {buyer_name} made a purchase\\!\n"
                    f"💵 *₹{escape_md(str(commission_amt))}* "
                    f"\\({escape_md(str(commission_pct))}%\\) added to your wallet\\!\n"
                    f"💰 Balance: *₹{escape_md(str(round(float(bal), 2)))}*\n\n"
                    f"🚀 _Keep sharing to earn more\\!_"
                )
                await bot.send_message(referrer_id, notify_text, parse_mode="MarkdownV2")
            except Exception as n_err:
                logger.warning(f"[REFERRAL] commission notification failed: {n_err}")

    except Exception as e:
        logger.error(f"[REFERRAL] process_referral_on_purchase error: {e}")


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
    # Guard: menu button or command pressed during input
    text = (message.text or "").strip()
    if text.startswith("/") or any(ord(c) > 127 for c in text):
        await state.clear()
        return

    code = text
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

    # Credit the referrer based on current mode
    ref_settings = await db.get_referral_settings()
    if ref_settings and ref_settings["is_active"]:
        mode = ref_settings.get("mode", "wallet_reward") or "wallet_reward"

        if mode == "wallet_reward":
            reward_amt = float(ref_settings.get("reward_amount", 10.0) or 10.0)

            # Enforce earning cap
            can_earn = await db.check_referral_earning_cap(referrer_id, ref_settings)
            if not can_earn:
                logger.info(f"[REFERRAL] {referrer_id} hit earning cap — no reward (manual)")
            else:
                try:
                    await db.add_referral_earnings(referrer_id, reward_amt)
                    logger.info(f"[REFERRAL] ₹{reward_amt} credited to {referrer_id} (manual code entry)")

                    # Log wallet transaction
                    try:
                        bal = await db.get_wallet_balance(referrer_id)
                        await db.add_wallet_transaction(
                            referrer_id, reward_amt, "referral_reward",
                            bal_before=bal - reward_amt,
                            bal_after=bal,
                            reference=f"referral_from_{user_id}",
                            description=f"Referral reward for inviting user {user_id}",
                        )
                    except Exception as wt_err:
                        logger.warning(f"[REFERRAL] wallet txn log failed: {wt_err}")

                    # Track promotional loss
                    try:
                        await db.record_promotional_loss(
                            loss_type="wallet_reward",
                            amount=reward_amt,
                            user_id=referrer_id,
                            reference=f"referral_reward_from_{user_id}_manual",
                            details={"referred_user": user_id, "mode": "wallet_reward", "entry": "manual"}
                        )
                    except Exception:
                        pass

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

        elif mode == "code_reward":
            logger.info(f"[REFERRAL] code_reward mode — no cash for {referrer_id} (manual)")

        elif mode == "commission":
            logger.info(f"[REFERRAL] commission mode — no cash for {referrer_id} (manual)")

    referrer_name = referrer.get("full_name") or str(referrer_id)
    await message.answer(
        f"✅ Referral code applied\\! You were referred by *{escape_md(referrer_name)}*\\.\n"
        f"🎁 Your friend has been notified\\!",
        parse_mode="MarkdownV2"
    )
    await text_refer_earn(message)

