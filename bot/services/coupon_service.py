"""
DreamX Coupon Bot — Coupon Service
Business logic for coupon CRUD operations.
"""

from bot.database import queries as db
from bot.utils.logger import logger


async def list_active_coupons() -> list:
    rows = await db.get_active_coupons()
    return [dict(r) for r in rows]


async def list_all_coupons() -> list:
    rows = await db.get_all_coupons()
    return [dict(r) for r in rows]


async def get_coupon_detail(coupon_id: int) -> dict | None:
    row = await db.get_coupon(coupon_id)
    return dict(row) if row else None


async def add_coupon(title: str, description: str, original_price: float,
                      discounted_price: float, stock: int, category: str = None) -> int:
    cid = await db.create_coupon(title, description, original_price,
                                   discounted_price, stock, category)
    logger.info(f"Coupon created: id={cid}, title={title}")
    return cid


async def edit_coupon(coupon_id: int, **fields):
    await db.update_coupon(coupon_id, **fields)
    logger.info(f"Coupon updated: id={coupon_id}, fields={list(fields.keys())}")


async def remove_coupon(coupon_id: int):
    await db.delete_coupon(coupon_id)
    logger.info(f"Coupon deleted: id={coupon_id}")


async def toggle_coupon(coupon_id: int) -> bool:
    """Toggle coupon active status. Returns new status."""
    coupon = await db.get_coupon(coupon_id)
    if not coupon:
        return False
    new_status = not coupon["is_active"]
    await db.update_coupon(coupon_id, is_active=new_status)
    logger.info(f"Coupon toggled: id={coupon_id}, active={new_status}")
    return new_status
