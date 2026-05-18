"""
DreamX Coupon Bot — /start Command Handler
Registers user, tracks referrals, and shows welcome screen.
"""

from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from bot.services.user_service import register_user
from bot.keyboards.main_menu import get_fresh_main_menu_kb
from bot.database import queries as db
from bot.utils.helpers import escape_md
from bot.utils.decorators import error_handler
from bot.utils.logger import logger

router = Router()


@router.message(CommandStart())
@error_handler
async def cmd_start(message: types.Message, state: FSMContext):
    # Clear any stale FSM state (e.g., abandoned BharatPe UTR entry)
    await state.clear()

    user = message.from_user
    await register_user(user.id, user.username, user.full_name)
    logger.info(f"/start from {user.id} (@{user.username})")

    referral_msg = ""

    # Handle referral: /start REF_CODE
    try:
        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            ref_code = args[1].strip()
            # Skip non-referral deep links (e.g. "restart")
            if ref_code and not ref_code.startswith("/"):
                referrer = await db.get_user_by_referral_code(ref_code)
                if referrer and referrer["telegram_id"] != user.id:
                    success = await db.record_referral(referrer["telegram_id"], user.id)
                    if success:
                        referrer_id = referrer["telegram_id"]
                        referrer_name = referrer.get("full_name") or str(referrer_id)
                        logger.info(f"[REFERRAL] Recorded: {referrer_id} -> {user.id}")

                        # Show referred user a message
                        referral_msg = (
                            f"\n\n🔗 You were referred by *{escape_md(referrer_name)}*\\!\n"
                            f"🎁 Your friend will receive a reward\\!"
                        )

                        # ── Credit based on CURRENT REFERRAL MODE ──
                        ref_settings = await db.get_referral_settings()
                        if ref_settings and ref_settings["is_active"]:
                            mode = ref_settings.get("mode", "wallet_reward") or "wallet_reward"

                            if mode == "wallet_reward":
                                # ── INSTANT WALLET REWARD ──
                                reward_amt = float(ref_settings.get("reward_amount", 10.0) or 10.0)

                                # Enforce earning cap (max per duration)
                                can_earn = await db.check_referral_earning_cap(
                                    referrer_id, ref_settings
                                )
                                if not can_earn:
                                    logger.info(
                                        f"[REFERRAL] {referrer_id} hit earning cap — no reward"
                                    )
                                else:
                                    try:
                                        await db.add_referral_earnings(referrer_id, reward_amt)
                                        logger.info(f"[REFERRAL] ₹{reward_amt} credited to {referrer_id}")

                                        # Log wallet transaction
                                        try:
                                            bal = await db.get_wallet_balance(referrer_id)
                                            await db.add_wallet_transaction(
                                                referrer_id, reward_amt, "topup",
                                                bal_before=bal - reward_amt,
                                                bal_after=bal,
                                                reference=f"referral_from_{user.id}",
                                            )
                                        except Exception as wt_err:
                                            logger.warning(f"[REFERRAL] wallet txn log failed: {wt_err}")

                                        # Notify referrer
                                        try:
                                            ref_name = escape_md(user.first_name or "Someone")
                                            bal = await db.get_wallet_balance(referrer_id)
                                            notify_text = (
                                                f"🎉 *New Referral\\!*\n\n"
                                                f"👤 {ref_name} joined using your link\\!\n"
                                                f"💵 *₹{escape_md(str(reward_amt))}* added to your wallet\\!\n"
                                                f"💰 Balance: *₹{escape_md(str(round(float(bal), 2)))}*\n\n"
                                                f"🚀 _Keep sharing to earn more\\!_"
                                            )
                                            await message.bot.send_message(
                                                referrer_id, notify_text, parse_mode="MarkdownV2"
                                            )
                                        except Exception as n_err:
                                            logger.warning(f"[REFERRAL] notification failed: {n_err}")

                                    except Exception as credit_err:
                                        logger.error(f"[REFERRAL] CREDIT FAILED: {credit_err}")

                            elif mode == "code_reward":
                                # ── COUPON REWARD MODE ──
                                # No cash on join. User claims reward coupons from Refer & Earn page.
                                logger.info(f"[REFERRAL] code_reward mode — no cash for {referrer_id}")
                                try:
                                    ref_name = escape_md(user.first_name or "Someone")
                                    ref_count = await db.get_referral_count(referrer_id)
                                    notify_text = (
                                        f"🎉 *New Referral\\!*\n\n"
                                        f"👤 {ref_name} joined using your link\\!\n"
                                        f"👥 Total referrals: *{ref_count}*\n\n"
                                        f"🎁 _Check Refer \\& Earn to claim rewards\\!_"
                                    )
                                    await message.bot.send_message(
                                        referrer_id, notify_text, parse_mode="MarkdownV2"
                                    )
                                except Exception as n_err:
                                    logger.warning(f"[REFERRAL] notification failed: {n_err}")

                            elif mode == "commission":
                                # ── COMMISSION MODE ──
                                # No cash on join. Commission is credited on referred user's purchase.
                                logger.info(f"[REFERRAL] commission mode — no cash for {referrer_id}")
                                try:
                                    ref_name = escape_md(user.first_name or "Someone")
                                    pct = ref_settings.get("commission_percent", 10)
                                    notify_text = (
                                        f"🎉 *New Referral\\!*\n\n"
                                        f"👤 {ref_name} joined using your link\\!\n"
                                        f"💰 You'll earn *{escape_md(str(pct))}%* commission\n"
                                        f"on their purchases\\!\n\n"
                                        f"🚀 _Keep sharing to earn more\\!_"
                                    )
                                    await message.bot.send_message(
                                        referrer_id, notify_text, parse_mode="MarkdownV2"
                                    )
                                except Exception as n_err:
                                    logger.warning(f"[REFERRAL] notification failed: {n_err}")
                        else:
                            logger.info("[REFERRAL] System inactive — no reward credited.")
                    else:
                        logger.info(f"[REFERRAL] record_referral returned False for {user.id}")
    except Exception as e:
        logger.error(f"[REFERRAL] Start referral error: {e}")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    first = escape_md(user.first_name or "there")

    # Get dynamic data
    try:
        total_stock = await db.get_total_stock()
    except Exception:
        total_stock = 0

    # Get support info from DB (admin-managed)
    try:
        settings = await db.get_bot_settings()
        support_text = settings.get("disclaimer_text") or ""
        ch_inline = settings.get("channels_inline_enabled")
        if ch_inline is None: ch_inline = True
    except Exception:
        support_text = ""
        ch_inline = True

    support_line = ""
    if support_text:
        # Show first line of support text as summary
        first_line = support_text.split("\n")[0][:60]
        support_line = f"🆘 Support: _{escape_md(first_line)}_\n"

    # Get wallet/reward balance
    try:
        wallet_bal = await db.get_wallet_balance(user.id)
    except Exception:
        wallet_bal = 0.0

    wallet_line = f"💰 Reward Balance: *₹{escape_md(f'{wallet_bal:.2f}')}*\n"

    welcome = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 *WELCOME, {first}\\!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚀 *Instant Delivery System*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ Verified Vouchers\n"
        f"⚡ Auto Payment Verification\n"
        f"📦 Available Stock: *{total_stock}* coupons\n"
        f"{wallet_line}"
        f"{support_line}"
        f"━━━━━━━━━━━━━━━━━━"
        f"{referral_msg}"
    )

    # Inline buttons — original layout with unique callback_data
    inline_rows = [
        [
            InlineKeyboardButton(text="🛍️ Stock Status", callback_data="stock_status"),
            InlineKeyboardButton(text="🛒 Buy Now", callback_data="browse_coupons"),
        ],
        [
            InlineKeyboardButton(text="📁 My Orders", callback_data="my_orders"),
            InlineKeyboardButton(text="🆘 Support", callback_data="show_support"),
        ],
    ]
    bottom_row = [InlineKeyboardButton(text="🤝 Refer & Earn", callback_data="referral_menu")]
    if ch_inline:
        bottom_row.append(InlineKeyboardButton(text="📢 Join Channels", callback_data="show_channels"))
    inline_rows.append(bottom_row)

    inline_kb = InlineKeyboardMarkup(inline_keyboard=inline_rows)

    # Send welcome with inline buttons
    await message.answer(
        welcome,
        parse_mode="MarkdownV2",
        reply_markup=inline_kb,
    )

    # Send persistent reply keyboard (auto-fetches latest settings)
    await message.answer(
        "📋 *Quick Menu:*",
        parse_mode="MarkdownV2",
        reply_markup=await get_fresh_main_menu_kb(user.id),
    )
