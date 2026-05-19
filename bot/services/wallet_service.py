"""
DreamX Coupon Bot — Wallet Service
Business logic for wallet operations.
"""

from bot.database import queries as db
from bot.utils.logger import logger


async def get_balance(telegram_id: int) -> float:
    return await db.get_wallet_balance(telegram_id)


async def credit_wallet(telegram_id: int, amount: float, reference: str = None,
                          description: str = "Wallet top-up") -> float:
    """Credit amount to user wallet. Returns new balance. Atomic (race-safe)."""
    result = await db.credit_wallet_atomic(telegram_id, amount)
    bal_before = result["balance_before"]
    bal_after = result["balance_after"]
    await db.add_wallet_transaction(
        telegram_id, amount, "topup", bal_before, bal_after, reference, description
    )
    logger.info(f"Wallet credited: user={telegram_id}, amount={amount}, new_balance={bal_after}")
    return bal_after


async def debit_wallet(telegram_id: int, amount: float, reference: str = None,
                        description: str = "Purchase") -> float | None:
    """Debit amount from wallet. Returns new balance or None if insufficient. Atomic (race-safe)."""
    result = await db.debit_wallet_atomic(telegram_id, amount)
    if result is None:
        return None  # Insufficient funds
    bal_before = result["balance_before"]
    bal_after = result["balance_after"]
    await db.add_wallet_transaction(
        telegram_id, amount, "purchase", bal_before, bal_after, reference, description
    )
    logger.info(f"Wallet debited: user={telegram_id}, amount={amount}, new_balance={bal_after}")
    return bal_after


async def get_history(telegram_id: int, limit: int = 10) -> list:
    rows = await db.get_wallet_history(telegram_id, limit)
    return [dict(r) for r in rows]
