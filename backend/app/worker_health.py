"""Container health probe for role workers."""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.config import SystemConfig


async def check() -> None:
    key = f"worker.heartbeat.{settings.WORKER_ROLE}"
    async with AsyncSessionLocal() as db:
        heartbeat = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )).scalar_one_or_none()
    if not heartbeat or not isinstance(heartbeat.value, dict) or not heartbeat.value.get("at"):
        raise SystemExit(f"missing heartbeat for {settings.WORKER_ROLE}")
    recorded = datetime.fromisoformat(heartbeat.value["at"].replace("Z", "+00:00"))
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    max_age = max(30, settings.TASK_WORKER_POLL_SECONDS * 5)
    age = (datetime.now(timezone.utc) - recorded).total_seconds()
    if age > max_age:
        raise SystemExit(f"stale heartbeat for {settings.WORKER_ROLE}: {age:.0f}s")


if __name__ == "__main__":
    asyncio.run(check())
