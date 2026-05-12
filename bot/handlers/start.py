"""
DreamX Coupon Bot — /start Command Handler
Registers user and shows welcome screen with persistent reply keyboard.
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
