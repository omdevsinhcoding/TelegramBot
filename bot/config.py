"""
DreamX Coupon Bot — Configuration Module
Loads all settings from environment variables.
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env file
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Config:
    """Central configuration loaded from environment variables."""

    # ── Telegram ──────────────────────────────────────────
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]

    # ── Database ──────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # ── Paytm (simple GET status check — no key needed) ──
    PAYTM_MID: str = os.getenv("PAYTM_MERCHANT_ID", "")
    PAYTM_UPI_ID: str = os.getenv("PAYTM_UPI_ID", "")
    PAYTM_QR_CODE: str = os.getenv("PAYTM_QR_CODE", "")

    # ── BharatPe (GET transactions with token header) ─────
    BHARATPE_MERCHANT_ID: str = os.getenv("BHARATPE_MERCHANT_ID", "")
    BHARATPE_TOKEN: str = os.getenv("BHARATPE_TOKEN", "")
    BHARATPE_UPI_ID: str = os.getenv("BHARATPE_UPI_ID", "")

    # ── Payment ───────────────────────────────────────────
    PAYMENT_TIMEOUT: int = int(os.getenv("PAYMENT_TIMEOUT_SECONDS", "600"))
    POLL_INTERVAL: int = int(os.getenv("PAYMENT_POLL_INTERVAL", "2"))
    UPI_PAYEE_NAME: str = os.getenv("UPI_PAYEE_NAME", "Paytm Merchant")

    # ── Bot Meta ──────────────────────────────────────────
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "CouponBot")
    SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "")

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
        if not cls.PAYTM_MID:
            errors.append("PAYTM_MERCHANT_ID is required")
        if not cls.PAYTM_UPI_ID:
            errors.append("PAYTM_UPI_ID is required")
        return errors
