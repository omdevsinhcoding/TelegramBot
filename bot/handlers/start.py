"""
DreamX Coupon Bot — /start Command Handler
Registers user, tracks referrals, and shows welcome screen.
"""

from aiogram import Router, types
from aiogram.filters import CommandStart

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

    # Handle referral: /start REF_CODE
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        ref_code = args[1].strip()
        if ref_code.startswith("ERROROO"):
            from bot.database import queries as db
            referrer = await db.get_user_by_referral_code(ref_code)
            if referrer and referrer["telegram_id"] != user.id:
                success = await db.record_referral(referrer["telegram_id"], user.id)
                if success:
                    logger.info(f"Referral recorded: {referrer['telegram_id']} -> {user.id}")
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

    first = escape_md(user.first_name or "there")

    welcome = (
        f"🌟 *Welcome to DreamX Store\\!*\n\n"
        f"Hey *{first}*\\! 👋\n\n"
        f"🛍️ Browse exclusive coupons & deals\n"
        f"💰 Direct UPI payments\n"
        f"⚡ Instant payment verification\n"
        f"🔒 Secure & verified transactions\n\n"
        f"Use the buttons below to get started 👇"
    )

    await message.answer(
        welcome,
        parse_mode="MarkdownV2",
        reply_markup=main_menu_kb(user.id),
    )
