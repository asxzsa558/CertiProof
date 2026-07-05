"""Lightweight persisted task worker.

Run with:
    python -m app.worker
"""

import asyncio
import logging
import sys

from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.core.initialization import initialize_default_models
from app.orchestrator import orchestrator


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings.validate_runtime_security()
    await init_db()

    async with AsyncSessionLocal() as db:
        await initialize_default_models(db)

    logger.info("Task worker started; polling every %s seconds", settings.TASK_WORKER_POLL_SECONDS)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await orchestrator.recover_incomplete_scan_tasks(db)
                from app.api.monitoring import run_due_scheduled_scans
                ran = await run_due_scheduled_scans(db, limit=settings.MONITORING_WORKER_BATCH_SIZE)
                if ran:
                    logger.info("Executed %d scheduled monitoring scan(s)", ran)
        except Exception:
            logger.exception("Task worker poll failed")
        await asyncio.sleep(max(1, settings.TASK_WORKER_POLL_SECONDS))


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Task worker stopped")


if __name__ == "__main__":
    main()
