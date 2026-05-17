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
from bot.services.payment_service import expire_orders_loop
from bot.payments.verifier import close_http_session
from bot.utils.logger import logger

# Import routers
from bot.handlers.start import router as start_router
from bot.handlers.menu import router as menu_router
from bot.handlers.coupons import router as coupons_router
from bot.handlers.purchase import router as purchase_router
from bot.handlers.admin import router as admin_router
from bot.handlers.referral import router as referral_router
from bot.handlers.wallet import router as wallet_router
from bot.middlewares.force_join import ForceJoinMiddleware
from bot.middlewares.fsm_clear import FSMClearMiddleware


async def on_startup(bot: Bot):
    """Runs on bot startup."""
    # Drop any existing webhook to ensure polling works
    await bot.delete_webhook(drop_pending_updates=True)

    await init_db()

    # Load DB admin IDs into cache for is_admin() checks
    try:
        from bot.database import queries as db
        from bot.config import refresh_admin_cache
        db_admins = await db.get_db_admin_ids()
        refresh_admin_cache(db_admins)
        logger.info(f"Loaded {len(db_admins)} DB admins into cache.")
    except Exception as e:
        logger.warning(f"Could not load DB admins: {e}")

    # Sync all coupon stocks with actual code counts (fixes stale stock data)
    try:
        from bot.database import queries as db
        await db.sync_all_coupon_stocks()
        logger.info("Startup stock sync completed.")
    except Exception as e:
        logger.warning(f"Startup stock sync failed (non-critical): {e}")

    # Start lightweight order expiry task (NO payment API polling)
    asyncio.create_task(expire_orders_loop(bot))

    # Start analytics web server (Telegram Mini App)
    try:
        from bot.webapp.server import start_webapp
        webapp_port = 8443
        try:
            from bot.database import queries as db
            settings = await db.get_bot_settings()
            webapp_port = int(settings.get("webapp_port") or 8443)
        except Exception:
            pass
        await start_webapp(webapp_port)
    except Exception as e:
        logger.warning(f"Analytics webapp failed to start (non-critical): {e}")

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

    # Register Middlewares
    # FSMClearMiddleware MUST be first — clears stale FSM state when menu buttons are pressed
    dp.message.outer_middleware(FSMClearMiddleware())
    dp.message.outer_middleware(ForceJoinMiddleware())
    dp.callback_query.outer_middleware(ForceJoinMiddleware())


    # Register startup/shutdown hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Register all routers
    dp.include_router(start_router)
    dp.include_router(menu_router)
    dp.include_router(coupons_router)
    dp.include_router(purchase_router)
    dp.include_router(admin_router)
    dp.include_router(referral_router)
    dp.include_router(wallet_router)

    logger.info("Starting DreamX Coupon Bot...")

    # Global error handler — catches ANY unhandled exception from any handler
    # This ensures the bot NEVER crashes from handler errors
    from aiogram.types import ErrorEvent

    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        logger.error(f"UNHANDLED ERROR: {event.exception}", exc_info=event.exception)
        # Try to notify the user
        try:
            update = event.update
            if update.callback_query:
                await update.callback_query.answer(
                    "❌ Something went wrong. Please try again.",
                    show_alert=True,
                )
            elif update.message:
                await update.message.answer(
                    "❌ An error occurred. Please try again later."
                )
        except Exception:
            pass  # Can't even notify — just swallow
        return True  # Prevent exception from propagating

    # Start polling — handle_signals=False is critical for AlwaysData hosting
    # where the process manager sends SIGTERM to stop the bot
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        handle_signals=False,
    )


if __name__ == "__main__":
    asyncio.run(main())
