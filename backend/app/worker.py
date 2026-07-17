"""Role-based persisted task worker.

Run with:
    WORKER_ROLE=interactive python -m app.worker
"""

import asyncio
import logging
import sys

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.orchestrator import orchestrator


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def _run_role_once(role: str) -> int:
    async with AsyncSessionLocal() as db:
        if role == "interactive":
            active = sum(not task.done() for task in orchestrator.active_tasks.values())
            available = max(0, settings.INTERACTIVE_SCAN_MAX_CONCURRENT - active)
            return await orchestrator.recover_incomplete_scan_tasks(db, limit=available) if available else 0
        if role == "document":
            from app.services.document_pipeline import process_pending_document_runs
            return await process_pending_document_runs(db)
        if role == "assessment":
            from app.services.assessment_task_queue import process_pending_assessment_tasks
            return await process_pending_assessment_tasks(db)
        if role == "verification":
            from app.services.verification_queue import process_pending_verification_runs
            return await process_pending_verification_runs(db)

        from app.api.monitoring import run_due_scheduled_scans
        from app.services.archive_queue import process_pending_archive_jobs, process_pending_conversation_summaries

        scheduled = await run_due_scheduled_scans(db, limit=settings.MONITORING_WORKER_BATCH_SIZE)
        archives = await process_pending_archive_jobs(db)
        summaries = await process_pending_conversation_summaries(db)
        return scheduled + archives + summaries


async def run_worker() -> None:
    settings.validate_runtime_security()
    role = settings.WORKER_ROLE
    if role == "document":
        from app.services.document_pipeline import recover_incomplete_document_runs
        async with AsyncSessionLocal() as db:
            recovered = await recover_incomplete_document_runs(db)
            if recovered:
                logger.info("Recovered %d interrupted document analysis run(s)", recovered)

    logger.info("%s worker started; polling every %s seconds", role, settings.TASK_WORKER_POLL_SECONDS)
    while True:
        try:
            processed = await _run_role_once(role)
            if processed:
                logger.info("%s worker accepted/processed %d item(s)", role, processed)
        except Exception:
            logger.exception("%s worker poll failed", role)
        await asyncio.sleep(max(1, settings.TASK_WORKER_POLL_SECONDS))


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Task worker stopped")


if __name__ == "__main__":
    main()
