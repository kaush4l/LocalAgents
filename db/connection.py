"""
Database connection pool — async PostgreSQL via asyncpg.

Usage::

    from db import get_pool, close_pool

    pool = await get_pool()            # lazy init
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM habits")

    await close_pool()                 # on shutdown
"""

from __future__ import annotations

import os
import logging

import asyncpg  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return the global connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        dsn = os.getenv(
            "DATABASE_URL",
            "postgresql://localhost:5432/localagents",
        )
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        logger.info("Database pool created: %s", dsn.split("@")[-1] if "@" in dsn else dsn)
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool (call at shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


async def run_migrations() -> None:
    """Run SQL migration files from db/migrations/ in order."""
    from pathlib import Path

    pool = await get_pool()
    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        logger.warning("No migrations directory found at %s", migrations_dir)
        return

    sql_files = sorted(migrations_dir.glob("*.sql"))
    async with pool.acquire() as conn:
        for sql_file in sql_files:
            sql = sql_file.read_text(encoding="utf-8")
            try:
                await conn.execute(sql)
                logger.info("Migration applied: %s", sql_file.name)
            except Exception as e:
                logger.warning("Migration %s (may already exist): %s", sql_file.name, e)
