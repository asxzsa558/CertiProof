"""Role-based persisted task worker.

Run with:
    WORKER_ROLE=interactive python -m app.worker
"""

import asyncio
import logging
import sys
import time
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.config import SystemConfig
from app.orchestrator import orchestrator
from sqlalchemy import select


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
_last_pressure_log = 0.0


async def _write_heartbeat(role: str, *, processed: int = 0, error: str | None = None) -> None:
    key = f"worker.heartbeat.{role}"
    async with AsyncSessionLocal() as db:
        heartbeat = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )).scalar_one_or_none()
        value = {
            "at": datetime.now(timezone.utc).isoformat(),
            "state": "error" if error else "ready",
            "processed": processed,
            "error": error,
        }
        if heartbeat:
            heartbeat.value = value
        else:
            db.add(SystemConfig(
                key=key,
                value=value,
                description=f"{role} worker heartbeat",
                category="operations",
            ))
        await db.commit()


async def _run_role_once(role: str) -> int:
    global _last_pressure_log
    async with AsyncSessionLocal() as db:
        from app.services.runtime_resources import runtime_status

        resources = await runtime_status(db)
        if resources["pressure"]["paused"]:
            now = time.monotonic()
            if now - _last_pressure_log >= 60:
                logger.warning("%s worker backpressure: %s", role, "、".join(resources["pressure"]["reasons"]))
                _last_pressure_log = now
            return 0
        limits = resources["limits"]
        if role == "interactive":
            active = sum(not task.done() for task in orchestrator.active_tasks.values())
            available = max(0, limits["interactive"] - active)
            return await orchestrator.recover_incomplete_scan_tasks(db, limit=available) if available else 0
        if role == "document":
            from app.services.document_pipeline import process_pending_document_runs
            return await process_pending_document_runs(db, limit=limits["document"])
        if role == "assessment":
            from app.services.assessment_task_queue import process_pending_assessment_tasks
            return await process_pending_assessment_tasks(db, limit=limits["assessment"])
        if role == "verification":
            from app.services.verification_queue import process_pending_verification_runs
            return await process_pending_verification_runs(db, limit=limits["verification"])

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
            await _write_heartbeat(role, processed=processed)
            if processed:
                logger.info("%s worker accepted/processed %d item(s)", role, processed)
        except Exception as exc:
            logger.exception("%s worker poll failed", role)
            try:
                await _write_heartbeat(role, error=f"{type(exc).__name__}: {exc}")
            except Exception:
                logger.exception("%s worker heartbeat failed", role)
        await asyncio.sleep(max(1, settings.TASK_WORKER_POLL_SECONDS))


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Task worker stopped")


if __name__ == "__main__":
    main()
