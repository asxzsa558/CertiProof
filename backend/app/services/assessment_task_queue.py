"""Persisted execution queue for automated assessment tasks."""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.secret_box import decrypt_json, encrypt_json
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
        if result.get("status") == "failed" or result.get("blocking"):
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


async def queue_assessment_task(
    task: TaskInstance,
    asset_ids: list[int],
    user_id: int,
    db: AsyncSession,
    credentials: dict[str, dict] | None = None,
) -> None:
    execution = {
        "mode": "automated",
        "state": "queued",
        "asset_ids": asset_ids,
        "asset_results": {},
        "attempt_count": 0,
        "user_id": user_id,
        "queued_at": datetime.utcnow().isoformat(),
    }
    if credentials:
        execution["credential_envelope"] = encrypt_json(credentials)
    task.result = {
        "execution": execution
    }
    task.lease_owner = None
    task.lease_expires_at = None
    task.heartbeat_at = None
    task.cancel_requested_at = None
    await db.commit()


async def _monitor_task(task_id: int) -> str:
    while True:
        await asyncio.sleep(max(1, settings.TASK_HEARTBEAT_SECONDS))
        async with AsyncSessionLocal() as monitor_db:
            task = await monitor_db.get(TaskInstance, task_id)
            if not task:
                return "missing"
            execution = (task.result or {}).get("execution") or {}
            if task.cancel_requested_at or execution.get("state") == "cancelled" or task.status != "in_progress":
                return "cancelled"
            if task.lease_owner != WORKER_ID:
                return "lease_lost"
            now = datetime.utcnow()
            task.heartbeat_at = now
            task.lease_expires_at = now + timedelta(minutes=settings.TASK_LEASE_MINUTES)
            await monitor_db.commit()


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
            await engine.reconcile_phase_progress(task.phase_id)
            return

        try:
            credentials = decrypt_json(execution["credential_envelope"]) if execution.get("credential_envelope") else {}
        except ValueError as exc:
            task.status = "failed"
            task.completed_at = datetime.utcnow()
            task.result = {"status": "failed", "error": str(exc), "execution": {"mode": "automated", "state": "failed"}}
            task.lease_owner = None
            task.lease_expires_at = None
            await db.commit()
            await engine.reconcile_phase_progress(task.phase_id)
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
                        params=credentials.get(target) or {},
                    )

        checkpoints = dict(execution.get("asset_results") or {})
        pending = {
            asyncio.create_task(execute_target(target)): target
            for target in targets
            if target not in checkpoints
        }
        monitor = asyncio.create_task(_monitor_task(task.id))
        try:
            while pending:
                done, _ = await asyncio.wait(
                    {*pending, monitor},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if monitor in done:
                    for future in pending:
                        future.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    return
                for future in done:
                    if future is monitor:
                        continue
                    target = pending.pop(future)
                    try:
                        value = future.result()
                    except asyncio.CancelledError:
                        return
                    except Exception as exc:
                        value = {"status": "failed", "error": str(exc)}
                    checkpoints[target] = value
                    execution = {
                        **execution,
                        "state": "running",
                        "asset_results": checkpoints,
                        "completed_assets": len(checkpoints),
                        "total_assets": len(targets),
                    }
                    checkpoint_result = {
                        "status": "running",
                        "task_type": task.task_type,
                        "execution": execution,
                    }
                    saved = await db.execute(
                        update(TaskInstance)
                        .where(
                            TaskInstance.id == task.id,
                            TaskInstance.status == "in_progress",
                            TaskInstance.cancel_requested_at.is_(None),
                            TaskInstance.lease_owner == WORKER_ID,
                        )
                        .values(result=checkpoint_result, heartbeat_at=datetime.utcnow())
                    )
                    await db.commit()
                    if saved.rowcount != 1:
                        for remaining in pending:
                            remaining.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        return
        finally:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor

        await db.refresh(task)
        current_execution = (task.result or {}).get("execution") or {}
        if task.status != "in_progress" or task.cancel_requested_at or current_execution.get("state") == "cancelled":
            return
        results = [checkpoints.get(target, {"status": "failed", "error": "资产检测未返回结果"}) for target in targets]
        final_result = _aggregate(task.task_type, targets, results)
        public_execution = {key: value for key, value in execution.items() if key != "credential_envelope"}
        final_result["execution"] = {**public_execution, "state": "finished", "finished_at": datetime.utcnow().isoformat()}
        task.lease_owner = None
        task.lease_expires_at = None
        task.heartbeat_at = datetime.utcnow()
        if final_result["status"] in {"completed", "partial"} and not final_result["failed"]:
            await engine.complete_task(task.id, final_result)
            return
        await db.execute(
            update(TaskInstance)
            .where(
                TaskInstance.id == task.id,
                TaskInstance.status == "in_progress",
                TaskInstance.cancel_requested_at.is_(None),
            )
            .values(
                status="failed",
                completed_at=datetime.utcnow(),
                result=final_result,
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        await db.commit()
        await engine.reconcile_phase_progress(task.phase_id)


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
        if task.cancel_requested_at:
            continue
        attempts = int(execution.get("attempt_count") or 0)
        if attempts >= settings.TASK_MAX_RECOVERY_ATTEMPTS:
            task.status = "failed"
            task.completed_at = now
            task.result = {
                **(task.result or {}),
                "status": "failed",
                "error": "自动检测连续中断，已达到恢复次数上限",
                "execution": {**execution, "state": "failed"},
            }
            task.lease_owner = None
            task.lease_expires_at = None
            continue
        next_execution = {
            **execution,
            "state": "running",
            "attempt_count": attempts + 1,
            "recovered_at": now.isoformat() if attempts else None,
        }
        claim = await db.execute(
            update(TaskInstance)
            .where(
                TaskInstance.id == task.id,
                TaskInstance.status == "in_progress",
                TaskInstance.cancel_requested_at.is_(None),
                or_(TaskInstance.lease_expires_at.is_(None), TaskInstance.lease_expires_at < now),
            )
            .values(
                result={**(task.result or {}), "execution": next_execution},
                lease_owner=WORKER_ID,
                lease_expires_at=now + timedelta(minutes=settings.TASK_LEASE_MINUTES),
                heartbeat_at=now,
            )
        )
        if claim.rowcount == 1:
            claimed.append(task.id)
    await db.commit()
    semaphore = asyncio.Semaphore(max(1, min(limit, 10)))

    async def run_task(task_id: int) -> None:
        async with semaphore:
            await _run_claimed_task(task_id)

    await asyncio.gather(*(run_task(task_id) for task_id in claimed))
    return len(claimed)
