"""
DreamX Coupon Bot — /start Command Handler
Registers user and shows welcome screen.
"""

from aiogram import Router, types
from aiogram.filters import CommandStart

from bot.services.user_service import register_user
from bot.keyboards.main_menu import main_menu_kb
from bot.utils.decorators import error_handler
from bot.utils.logger import logger

router = Router()


@router.message(CommandStart())
@error_handler
async def cmd_start(message: types.Message):
    user = message.from_user
    await register_user(user.id, user.username, user.full_name)
    logger.info(f"/start from {user.id} (@{user.username})")

    welcome = (
        f"🌟 *Welcome to DreamX Store\\!*\n\n"
        f"Hey *{user.first_name or 'there'}*\\! 👋\n\n"
        f"🛍️ Browse exclusive coupons & deals\n"
        f"💰 Manage your wallet balance\n"
        f"⚡ Instant UPI payments\n"
        f"🔒 Secure & verified transactions\n\n"
        f"Choose an option below to get started\\:"
    )

    await message.answer(
        welcome,
        parse_mode="MarkdownV2",
        reply_markup=main_menu_kb(user.id),
    )
