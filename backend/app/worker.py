"""Lightweight persisted task worker.

Run with:
    python -m app.worker
"""

import asyncio
import logging
import sys

from app.core.config import settings
from app.core.database import AsyncSessionLocal
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
    async with AsyncSessionLocal() as db:
        await initialize_default_models(db)
        from app.services.document_pipeline import recover_incomplete_document_runs
        recovered_documents = await recover_incomplete_document_runs(db)
        if recovered_documents:
            logger.info("Recovered %d interrupted document analysis run(s)", recovered_documents)

    logger.info("Task worker started; polling every %s seconds", settings.TASK_WORKER_POLL_SECONDS)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await orchestrator.recover_incomplete_scan_tasks(db)
                from app.api.monitoring import run_due_scheduled_scans
                ran = await run_due_scheduled_scans(db, limit=settings.MONITORING_WORKER_BATCH_SIZE)
                if ran:
                    logger.info("Executed %d scheduled monitoring scan(s)", ran)
                from app.services.document_pipeline import process_pending_document_runs
                documents_ran = await process_pending_document_runs(db)
                if documents_ran:
                    logger.info("Executed %d document analysis run(s)", documents_ran)
                from app.services.archive_queue import process_pending_archive_jobs, process_pending_conversation_summaries
                archives_ran = await process_pending_archive_jobs(db)
                summaries_ran = await process_pending_conversation_summaries(db)
                if archives_ran or summaries_ran:
                    logger.info("Processed %d archive(s) and %d conversation summary segment(s)", archives_ran, summaries_ran)
                from app.services.assessment_task_queue import process_pending_assessment_tasks
                assessment_tasks_ran = await process_pending_assessment_tasks(db)
                if assessment_tasks_ran:
                    logger.info("Executed %d queued assessment task(s)", assessment_tasks_ran)
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
