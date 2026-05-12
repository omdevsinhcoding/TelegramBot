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
    """Escape Markdown V2 special characters."""
    special = r"_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text
