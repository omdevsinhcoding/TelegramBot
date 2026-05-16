"""
DreamX Coupon Bot — /start Command Handler
Registers user, tracks referrals, and shows welcome screen.
"""

from aiogram import Router, types
from aiogram.filters import CommandStart, Command

from bot.services.user_service import register_user
from bot.keyboards.main_menu import get_fresh_main_menu_kb
from bot.database import queries as db
from bot.utils.helpers import escape_md
from bot.utils.decorators import error_handler
from bot.utils.logger import logger

router = Router()


@router.message(CommandStart())
@error_handler
async def cmd_start(message: types.Message):
    user = message.from_user
    await register_user(user.id, user.username, user.full_name)
    logger.info(f"/start from {user.id} (@{user.username})")

    referral_msg = ""

    # Handle referral: /start REF_CODE
    try:
        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            ref_code = args[1].strip()
            if ref_code.startswith("ERROROO"):
                referrer = await db.get_user_by_referral_code(ref_code)
                if referrer and referrer["telegram_id"] != user.id:
                    success = await db.record_referral(referrer["telegram_id"], user.id)
                    if success:
                        referrer_id = referrer["telegram_id"]
                        referrer_name = referrer.get("full_name") or str(referrer_id)
                        logger.info(f"Referral recorded: {referrer_id} -> {user.id}")

                        # Notify the REFERRED user
                        referral_msg = (
                            f"\n\n🔗 You were referred by *{escape_md(referrer_name)}*\\!\n"
                            f"Start shopping to unlock referral rewards 🎁"
                        )

                        # Get referral mode
                        ref_settings = await db.get_referral_settings()
                        mode = ref_settings["mode"] if ref_settings else "commission"

                        # Grant wallet_reward IMMEDIATELY on join — no channel gate
                        # (force_channel controls bot access, not referral rewards)
                        reward_msg = ""
                        if mode == "wallet_reward" and ref_settings:
                            reward_amt = float(ref_settings.get("reward_amount", 10.0) or 10.0)
                            try:
                                await db.add_referral_earnings(referrer_id, reward_amt)
                                reward_msg = f"\n💵 ₹{reward_amt} added to your wallet\\!"
                                logger.info(
                                    f"[REFERRAL] wallet_reward ₹{reward_amt} credited: "
                                    f"referrer={referrer_id}, new_user={user.id}"
                                )
                                # Log wallet transaction
                                try:
                                    bal = await db.get_wallet_balance(referrer_id)
                                    await db.add_wallet_transaction(
                                        referrer_id, reward_amt, "topup",
                                        bal_before=bal - reward_amt,
                                        bal_after=bal,
                                        reference=f"ref_join_reward_from_{user.id}",
                                    )
                                except Exception as wt_err:
                                    logger.warning(f"[REFERRAL] wallet_txn log failed: {wt_err}")
                            except Exception as credit_err:
                                logger.error(
                                    f"[REFERRAL] wallet_reward credit FAILED: "
                                    f"referrer={referrer_id}, amount={reward_amt}, err={credit_err}"
                                )

                        # Notify the REFERRER
                        try:
                            ref_name = escape_md(user.first_name or "Someone")
                            notify_text = (
                                f"🎉 *New Referral\\!*\n\n"
                                f"👤 {ref_name} joined using your link\\!"
                            )
                            if mode == "wallet_reward" and ref_settings:
                                reward_amt = float(ref_settings.get("reward_amount", 10.0) or 10.0)
                                bal = await db.get_wallet_balance(referrer_id)
                                notify_text += (
                                    f"\n💵 *₹{escape_md(str(reward_amt))}* added to your wallet\\!"
                                    f"\n💰 Balance: *₹{escape_md(str(round(float(bal), 2)))}*"
                                )
                            elif mode == "commission":
                                pct = ref_settings.get("commission_percent", 10)
                                notify_text += f"\n💰 You'll earn {escape_md(str(pct))}% on their purchases\\!"
                            elif mode == "code_reward":
                                notify_text += f"\n🎁 Keep referring to unlock free coupons\\!"

                            notify_text += f"\nKeep sharing to earn more rewards 💰"

                            await message.bot.send_message(
                                referrer_id, notify_text, parse_mode="MarkdownV2",
                            )
                        except Exception as notify_err:
                            logger.warning(f"[REFERRAL] referrer notification failed: {notify_err}")
    except Exception as e:
        logger.warning(f"Referral processing error (non-critical): {e}")

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

    welcome = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 *WELCOME, {first}\\!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚀 *Instant Delivery System*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ Verified Vouchers\n"
        f"⚡ Auto Payment Verification\n"
        f"📦 Available Stock: *{total_stock}* coupons\n"
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


@router.message(Command("id"))
async def cmd_id(message: types.Message):
    """Show Telegram IDs — works in private, groups, and channels."""
    user = message.from_user
    chat = message.chat

    user_id = user.id if user else "Unknown"
    user_name = escape_md(user.first_name or "Unknown") if user else "Unknown"

    if chat.type == "private":
        # Private chat — just user ID
        text = (
            f"🆔 *Your Telegram ID*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: *{user_name}*\n"
            f"🔑 ID: `{user_id}`"
        )
    elif chat.type in ("group", "supergroup"):
        # Group — show both group ID and user ID
        group_name = escape_md(chat.title or "Unknown")
        text = (
            f"🆔 *Telegram IDs*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Group: *{group_name}*\n"
            f"🔑 Group ID: `{chat.id}`\n\n"
            f"👤 Your Name: *{user_name}*\n"
            f"🔑 Your ID: `{user_id}`"
        )
    elif chat.type == "channel":
        # Channel — show channel ID and user ID
        ch_name = escape_md(chat.title or "Unknown")
        text = (
            f"🆔 *Telegram IDs*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📢 Channel: *{ch_name}*\n"
            f"🔑 Channel ID: `{chat.id}`\n\n"
            f"👤 Your Name: *{user_name}*\n"
            f"🔑 Your ID: `{user_id}`"
        )
    else:
        text = f"🔑 Chat ID: `{chat.id}`\n👤 Your ID: `{user_id}`"

    await message.answer(text, parse_mode="MarkdownV2")
