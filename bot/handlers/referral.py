"""
DreamX Coupon Bot — Referral System Handler
Handles Refer & Earn flow, referral tracking, and commission distribution.
"""

from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.database import queries as db
from bot.config import Config
from bot.utils.helpers import escape_md, format_currency
from bot.utils.decorators import error_handler
from bot.keyboards.common import back_button

router = Router()


@router.message(F.text == "🎁 Refer & Earn")
@error_handler
async def text_refer_earn(message: types.Message):
    """Show the Refer & Earn page matching reference image."""
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
        needed = settings["referrals_needed"]
        how_it_works = (
            f"✨ *How it works:*\n"
            f"1️⃣ Share your link\n"
            f"2️⃣ Friends join the bot\n"
            f"3️⃣ After *{needed}* referrals, get a free coupon\\!\n"
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

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 My Referral History", callback_data="ref_history")],
        [InlineKeyboardButton(text="◀️ Back", callback_data="back_home")],
    ])

    await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb)


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

    elif mode == "code_reward":
        # Code reward: after N referrals, send reward code
        needed = settings["referrals_needed"]
        count = await db.get_referral_count(referrer_id)
        if count >= needed and settings.get("reward_code"):
            # Check if already rewarded (avoid duplicates)
            already = await pool.fetchrow(
                "SELECT id FROM referrals WHERE referrer_id = $1 AND status = 'rewarded' LIMIT 1",
                referrer_id
            )
            if not already:
                await pool.execute(
                    "UPDATE referrals SET status = 'rewarded' WHERE referrer_id = $1 AND referred_id = $2",
                    referrer_id, user_id
                )
                # The bot instance is not available here, so we store the reward
                # and it gets checked on the referrer's next interaction
                await pool.execute(
                    "UPDATE users SET wallet_balance = wallet_balance WHERE telegram_id = $1",
                    referrer_id  # no-op, reward code is sent via notification
                )
