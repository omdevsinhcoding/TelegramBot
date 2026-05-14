"""
DreamX Coupon Bot — /start Command Handler
Registers user, tracks referrals, and shows welcome screen.
"""

from aiogram import Router, types
from aiogram.filters import CommandStart, Command

from bot.services.user_service import register_user
from bot.keyboards.main_menu import main_menu_kb
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
                from bot.database import queries as db
                referrer = await db.get_user_by_referral_code(ref_code)
                if referrer and referrer["telegram_id"] != user.id:
                    success = await db.record_referral(referrer["telegram_id"], user.id)
                    if success:
                        referrer_name = referrer.get("full_name") or str(referrer["telegram_id"])
                        logger.info(f"Referral recorded: {referrer['telegram_id']} -> {user.id}")

                        # Notify the REFERRED user
                        referral_msg = (
                            f"\n\n🔗 You were referred by *{escape_md(referrer_name)}*\\!\n"
                            f"Start shopping to unlock referral rewards 🎁"
                        )

                        # Notify the REFERRER
                        try:
                            ref_name = escape_md(user.first_name or "Someone")
                            await message.bot.send_message(
                                referrer["telegram_id"],
                                f"🎉 *New Referral\\!*\n\n"
                                f"👤 {ref_name} joined using your link\\!\n"
                                f"Keep sharing to earn more rewards 💰",
                                parse_mode="MarkdownV2",
                            )
                        except Exception:
                            pass
    except Exception as e:
        logger.warning(f"Referral processing error (non-critical): {e}")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from bot.database import queries as db

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
        disclaimer_mode = settings.get("disclaimer_mode") or "button"
        channels_enabled = settings.get("channels_button_enabled")
        if channels_enabled is None:
            channels_enabled = True
    except Exception:
        support_text = ""
        disclaimer_mode = "button"
        channels_enabled = True

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

    # Inline buttons that fly in
    inline_rows = [
        [
            InlineKeyboardButton(text="🛍️ Stock Status", callback_data="browse_coupons"),
            InlineKeyboardButton(text="🛒 Buy Now", callback_data="browse_coupons"),
        ],
        [
            InlineKeyboardButton(text="📁 My Orders", callback_data="my_orders"),
            InlineKeyboardButton(text="🆘 Support", callback_data="show_support"),
        ],
    ]
    bottom_row = [InlineKeyboardButton(text="🤝 Refer & Earn", callback_data="referral_menu")]
    if channels_enabled:
        bottom_row.append(InlineKeyboardButton(text="📢 Join Channels", callback_data="show_channels"))
    inline_rows.append(bottom_row)

    inline_kb = InlineKeyboardMarkup(inline_keyboard=inline_rows)

    # Send welcome with inline buttons
    await message.answer(
        welcome,
        parse_mode="MarkdownV2",
        reply_markup=inline_kb,
    )

    # Send persistent reply keyboard
    await message.answer(
        "📋 *Quick Menu:*",
        parse_mode="MarkdownV2",
        reply_markup=main_menu_kb(user.id, disclaimer_mode, channels_enabled),
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
