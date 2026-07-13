"""Bootstrap legacy installations, then apply versioned Alembic migrations."""

import asyncio
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine, init_db


async def _has_alembic_version() -> bool:
    async with engine.connect() as conn:
        if "postgresql" in settings.DATABASE_URL:
            result = await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
            return result.scalar() is not None
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"))
        return result.scalar() is not None


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


async def main() -> bool:
    settings.validate_runtime_security()
    await init_db()
    async with AsyncSessionLocal() as db:
        from app.services.flow_engine import get_flow_engine
        await get_flow_engine(db).reconcile_all_assessment_progress()
    return await _has_alembic_version()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    if action not in {"upgrade", "downgrade"}:
        raise SystemExit("Usage: python -m app.migrate [upgrade|downgrade]")
    has_alembic_version = asyncio.run(main())
    config = _alembic_config()
    if action == "downgrade":
        command.downgrade(config, "003")
    else:
        # Older releases used create_all + compatibility ALTERs.  They become
        # the 003 baseline once bootstrapped, then receive explicit revisions.
        if not has_alembic_version:
            command.stamp(config, "003")
        command.upgrade(config, "head")
