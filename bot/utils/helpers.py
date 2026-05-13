"""
DreamX Coupon Bot — Helper Utilities
Common helper functions used across the bot.
"""

import uuid
import hashlib
import time
from datetime import datetime, timezone


def generate_order_id() -> str:
    """Generate a unique human-readable order ID."""
    ts = int(time.time() * 1000) % 100000000
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"DX-{ts}-{short_uuid}"


def generate_txn_ref() -> str:
    """Generate a unique transaction reference."""
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8].upper()
    return f"TXN{ts}{uid}"


def format_currency(amount: float) -> str:
    """Format amount as Indian Rupees."""
    return f"₹{amount:,.2f}"


def format_datetime(dt: datetime | None) -> str:
    """Format datetime for display."""
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d %b %Y, %I:%M %p")


def truncate_text(text: str, max_len: int = 100) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def compute_checksum(data: str, key: str) -> str:
    """Compute HMAC-SHA256 checksum for payment verification."""
    return hashlib.sha256(f"{data}{key}".encode()).hexdigest()


def mask_string(s: str, visible: int = 4) -> str:
    """Mask sensitive strings for logging."""
    if len(s) <= visible:
        return "*" * len(s)
    return "*" * (len(s) - visible) + s[-visible:]


def escape_md(text: str) -> str:
    """Escape ALL MarkdownV2 special characters.

    Per Telegram API docs, these characters must be escaped:
    _ * [ ] ( ) ~ ` > # + - = | { } . !
    
    Also handles the double-escape case: if text already has \\., 
    we don't want to produce \\\\.
    """
    if not isinstance(text, str):
        text = str(text)
    special = r"_*[]()~`>#+-=|{}.!"
    # Remove existing escapes first to prevent double-escaping
    for ch in special:
        text = text.replace(f"\\{ch}", ch)
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


async def safe_send_message(target, text: str, parse_mode: str = "MarkdownV2", **kwargs):
    """Send a message with MarkdownV2, falling back to plain text on parse error.
    
    Works with both Message and Bot objects:
    - Message.answer(...)
    - Bot.send_message(chat_id, ...)
    
    Args:
        target: A Message object (uses .answer) or a tuple of (Bot, chat_id)
        text: Message text
        parse_mode: Parse mode to try first
        **kwargs: Additional kwargs passed to the send method
    """
    from aiogram import types, Bot
    import re
    
    try:
        if isinstance(target, types.Message):
            return await target.answer(text, parse_mode=parse_mode, **kwargs)
        elif isinstance(target, tuple) and len(target) == 2:
            bot, chat_id = target
            return await bot.send_message(chat_id, text, parse_mode=parse_mode, **kwargs)
    except Exception as e:
        error_str = str(e).lower()
        if "parse" in error_str or "can't" in error_str or "markdown" in error_str:
            # Strip all markdown formatting and retry as plain text
            plain = re.sub(r'\\(.)', r'\1', text)      # remove escapes
            plain = re.sub(r'[*_`~]', '', plain)        # remove formatting chars
            try:
                if isinstance(target, types.Message):
                    return await target.answer(plain, parse_mode=None, **kwargs)
                elif isinstance(target, tuple) and len(target) == 2:
                    bot, chat_id = target
                    return await bot.send_message(chat_id, plain, parse_mode=None, **kwargs)
            except Exception:
                pass  # Even plain text failed — nothing we can do
        raise  # Re-raise non-parse errors

