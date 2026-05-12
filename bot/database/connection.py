"""
DreamX Coupon Bot — Database Connection Pool
Async PostgreSQL connection management using asyncpg.
"""

import asyncpg
from pathlib import Path
from bot.config import Config
from bot.utils.logger import logger

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("Database pool not initialized.")
    return _pool


async def init_db() -> asyncpg.Pool:
    global _pool
    dsn = Config.DATABASE_URL
    if not dsn:
        raise RuntimeError("DATABASE_URL is required in .env")

    logger.info("Connecting to PostgreSQL...")
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10, command_timeout=60)

    schema_path = Path(__file__).resolve().parent.parent.parent / "sql" / "schema.sql"
    if schema_path.exists():
        async with _pool.acquire() as conn:
            try:
                await conn.execute(schema_path.read_text(encoding="utf-8"))
                logger.info("Database schema applied.")
            except Exception as e:
                logger.warning(f"Schema note: {e}")

    logger.info("Database pool ready.")
    return _pool


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")
