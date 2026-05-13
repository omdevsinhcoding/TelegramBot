"""
DreamX Coupon Bot — Main Application
Initializes bot, registers routers, and starts polling.
"""

import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import Config
from bot.database.connection import init_db, close_db
from bot.services.payment_service import poll_payment_status
from bot.payments.verifier import close_http_session
from bot.utils.logger import logger

# Import routers
from bot.handlers.start import router as start_router
from bot.handlers.menu import router as menu_router
from bot.handlers.coupons import router as coupons_router
from bot.handlers.purchase import router as purchase_router
from bot.handlers.admin import router as admin_router


async def on_startup(bot: Bot):
    """Runs on bot startup."""
    # Drop any existing webhook to ensure polling works
    await bot.delete_webhook(drop_pending_updates=True)

    await init_db()

    # Start payment polling as background task
    asyncio.create_task(poll_payment_status(bot))

    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username} (ID: {me.id})")


async def on_shutdown(bot: Bot):
    """Runs on bot shutdown."""
    await close_http_session()
    await close_db()
    logger.info("Bot shutdown complete.")


async def main():
    # Validate config
    errors = Config.validate()
    if errors:
        for e in errors:
            logger.error(f"Config error: {e}")
        raise SystemExit("Fix configuration errors before starting.")

    # Initialize bot and dispatcher
    bot = Bot(
        token=Config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register startup/shutdown hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Register all routers
    dp.include_router(start_router)
    dp.include_router(menu_router)
    dp.include_router(coupons_router)
    dp.include_router(purchase_router)
    dp.include_router(admin_router)

    logger.info("Starting DreamX Coupon Bot...")

    # Start polling — handle_signals=False is critical for AlwaysData hosting
    # where the process manager sends SIGTERM to stop the bot
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        handle_signals=False,
    )


if __name__ == "__main__":
    asyncio.run(main())
