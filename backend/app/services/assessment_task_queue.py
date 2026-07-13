"""Persisted execution queue for automated assessment tasks."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.assessment import TaskInstance
from app.models.asset import Asset
from app.services.flow_engine import get_flow_engine
from app.services.task_executor import get_task_executor


WORKER_ID = f"assessment-worker-{os.getenv('HOSTNAME', 'local')}-{os.getpid()}"


def _aggregate(task_type: str, targets: list[str], results: list[object]) -> dict:
    asset_results, completed, failed, warnings = {}, [], [], []
    for target, result in zip(targets, results):
        if isinstance(result, Exception):
            entry = {"status": "failed", "error": str(result)}
            asset_results[target] = entry
            failed.append({"target": target, **entry})
            continue
        asset_results[target] = result
        entry = {"target": target, **result}
        if result.get("status") == "failed":
            failed.append(entry)
        else:
            completed.append(entry)
            if result.get("status") == "partial":
                warnings.append(entry)
    return {
        "status": "completed" if not failed and not warnings else ("partial" if completed else "failed"),
        "task_type": task_type,
        "asset_results": asset_results,
        "completed": completed,
        "failed": failed,
        "warnings": warnings,
    }


async def queue_assessment_task(task: TaskInstance, asset_ids: list[int], user_id: int, db: AsyncSession) -> None:
    task.result = {
        "execution": {
            "mode": "automated",
            "state": "queued",
            "asset_ids": asset_ids,
            "user_id": user_id,
            "queued_at": datetime.utcnow().isoformat(),
        }
    }
    task.lease_owner = None
    task.lease_expires_at = None
    await db.commit()


async def _run_claimed_task(task_id: int) -> None:
    async with AsyncSessionLocal() as db:
        engine = get_flow_engine(db)
        task = await engine.get_task(task_id)
        if not task or task.status != "in_progress":
            return
        execution = (task.result or {}).get("execution") or {}
        asset_ids = execution.get("asset_ids") or []
        user_id = execution.get("user_id")
        phase = await engine.get_phase(task.phase_id)
        assessment = await engine.get_assessment(phase.assessment_id) if phase else None
        assets_result = await db.execute(select(Asset).where(Asset.id.in_(asset_ids), Asset.is_active.is_(True)))
        assets = list(assets_result.scalars().all())
        targets = [asset.value for asset in assets]
        if not targets or not user_id or not assessment:
            task.status = "failed"
            task.completed_at = datetime.utcnow()
            task.result = {"status": "failed", "error": "任务缺少可执行的授权资产或执行人", "execution": {**execution, "state": "failed"}}
            task.lease_owner = None
            task.lease_expires_at = None
            await db.commit()
            return

        semaphore = asyncio.Semaphore(max(1, min(settings.ASSESSMENT_MAX_CONCURRENT, 10)))

        async def execute_target(target: str):
            async with semaphore:
                async with AsyncSessionLocal() as target_db:
                    return await get_task_executor(target_db).execute_task(
                        task_type=task.task_type,
                        target=target,
                        project_id=assessment.project_id,
                        user_id=int(user_id),
                    )

        results = await asyncio.gather(*(execute_target(target) for target in targets), return_exceptions=True)
        final_result = _aggregate(task.task_type, targets, results)
        final_result["execution"] = {**execution, "state": "finished", "finished_at": datetime.utcnow().isoformat()}
        task.lease_owner = None
        task.lease_expires_at = None
        if final_result["status"] in {"completed", "partial"}:
            await engine.complete_task(task.id, final_result)
            return
        task.status = "failed"
        task.completed_at = datetime.utcnow()
        task.result = final_result
        await db.commit()


async def process_pending_assessment_tasks(db: AsyncSession, limit: int = 10) -> int:
    """Claim and execute queued assessment tasks; expired leases are safe to retry."""
    now = datetime.utcnow()
    result = await db.execute(
        select(TaskInstance)
        .where(
            TaskInstance.status == "in_progress",
            or_(TaskInstance.lease_expires_at.is_(None), TaskInstance.lease_expires_at < now),
        )
        .order_by(TaskInstance.started_at.asc())
        .limit(limit)
    )
    claimed = []
    for task in result.scalars().all():
        execution = (task.result or {}).get("execution") or {}
        if execution.get("mode") != "automated" or execution.get("state") not in {"queued", "running"}:
            continue
        claim = await db.execute(
            update(TaskInstance)
            .where(
                TaskInstance.id == task.id,
                TaskInstance.status == "in_progress",
                or_(TaskInstance.lease_expires_at.is_(None), TaskInstance.lease_expires_at < now),
            )
            .values(
                lease_owner=WORKER_ID,
                lease_expires_at=now + timedelta(minutes=settings.TASK_LEASE_MINUTES),
            )
        )
        if claim.rowcount == 1:
            claimed.append(task.id)
    await db.commit()
    for task_id in claimed:
        await _run_claimed_task(task_id)
    return len(claimed)
