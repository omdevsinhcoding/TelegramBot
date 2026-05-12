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
    """Credit amount to user wallet. Returns new balance."""
    current = await db.get_wallet_balance(telegram_id)
    new_balance = current + amount
    await db.update_wallet_balance(telegram_id, new_balance)
    await db.add_wallet_transaction(
        telegram_id, amount, "topup", current, new_balance, reference, description
    )
    logger.info(f"Wallet credited: user={telegram_id}, amount={amount}, new_balance={new_balance}")
    return new_balance


async def debit_wallet(telegram_id: int, amount: float, reference: str = None,
                        description: str = "Purchase") -> float | None:
    """Debit amount from wallet. Returns new balance or None if insufficient."""
    current = await db.get_wallet_balance(telegram_id)
    if current < amount:
        return None
    new_balance = current - amount
    await db.update_wallet_balance(telegram_id, new_balance)
    await db.add_wallet_transaction(
        telegram_id, amount, "purchase", current, new_balance, reference, description
    )
    logger.info(f"Wallet debited: user={telegram_id}, amount={amount}, new_balance={new_balance}")
    return new_balance


async def get_history(telegram_id: int, limit: int = 10) -> list:
    rows = await db.get_wallet_history(telegram_id, limit)
    return [dict(r) for r in rows]
