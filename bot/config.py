"""
DreamX Coupon Bot — Configuration Module
Loads core settings from environment variables.
Payment credentials are managed via Admin Panel (stored in DB).
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env file
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Config:
    """Central configuration loaded from environment variables.
    
    NOTE: Payment gateway credentials (Paytm, BharatPe) are NOT stored here.
    They are managed dynamically from the Admin Panel and stored in the database.
    See: bot.database.queries.get_payment_settings()
    """

    # ── Telegram ──────────────────────────────────────────
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]

    # ── Database ──────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # ── Payment (non-credential config) ───────────────────
    PAYMENT_TIMEOUT: int = int(os.getenv("PAYMENT_TIMEOUT_SECONDS", "600"))
    BHARATPE_MIN_RECHARGE: float = float(os.getenv("BHARATPE_MIN_RECHARGE", "10"))

    # ── Logging ───────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")

    @classmethod
    def is_admin(cls, telegram_id: int) -> bool:
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
