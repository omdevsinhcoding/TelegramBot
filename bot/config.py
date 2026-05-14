"""
DreamX Coupon Bot — Configuration Module
Loads MINIMAL core settings from environment variables.

Everything else is managed dynamically via Admin Panel (stored in DB):
- Payment credentials (Paytm, BharatPe, Razorpay)
- Payment timeout, min recharge, poll interval
- Support/Disclaimer text
- Gateway toggles
- Additional admins
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env file
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


# Cached set of DB admin IDs (refreshed on add/remove)
_db_admin_ids: set[int] = set()


class Config:
    """Central configuration — only truly static values from .env.
    
    Dynamic settings (payment timeout, min recharge, etc.) are fetched
    from the database via bot.database.queries.get_dynamic_config().
    """

    # ── Telegram ──────────────────────────────────────────
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]

    # ── Database ──────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # ── Logging ───────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")

    @classmethod
    def is_admin(cls, telegram_id: int) -> bool:
        """Check if user is admin — checks .env seed admins AND DB admins."""
        return telegram_id in cls.ADMIN_IDS or telegram_id in _db_admin_ids

    @classmethod
    def is_seed_admin(cls, telegram_id: int) -> bool:
        """Check if user is a seed admin (from .env). These cannot be removed."""
        return telegram_id in cls.ADMIN_IDS

    @classmethod
    def validate(cls) -> list[str]:
        """Return list of missing critical config keys."""
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN is required")
        if not cls.ADMIN_IDS:
            errors.append("ADMIN_IDS is required (comma-separated Telegram IDs)")
        if not cls.DATABASE_URL:
            errors.append("DATABASE_URL is required")
        return errors


def refresh_admin_cache(admin_ids: set[int]):
    """Update the cached DB admin IDs. Called after add/remove admin."""
    global _db_admin_ids
    _db_admin_ids = admin_ids
