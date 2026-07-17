"""
Tasks API - 任务控制接口
支持暂停、恢复、停止正在执行的任务
"""

from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.rbac import get_project_for_user
from app.core.security import get_current_user
from app.models.scan_task import ScanTask, ScanTaskStatus
from app.models.user import User
from app.orchestrator import orchestrator
from app.services.audit import record_audit_event

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _task_exists(task_id: str) -> bool:
    return bool(
        task_id in orchestrator.task_status
        or task_id in orchestrator.task_progress
        or orchestrator.get_task_metadata(task_id)
    )


async def _require_task_access(
    task_id: str,
    db: AsyncSession,
    current_user: User,
    permission: str = "scan:read",
) -> dict:
    metadata = orchestrator.get_task_metadata(task_id)
    if not metadata and not _task_exists(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")

    owner_id = metadata.get("user_id")
    if owner_id is not None and str(owner_id) == str(current_user.id):
        return metadata

    project_id = metadata.get("project_id")
    if project_id:
        await get_project_for_user(db, int(project_id), current_user, permission)
        return metadata

    raise HTTPException(status_code=403, detail="无权访问该任务")


async def _get_persisted_task(
    task_id: str,
    db: AsyncSession,
    current_user: User,
    permission: str = "scan:read",
) -> Optional[ScanTask]:
    result = await db.execute(select(ScanTask).where(ScanTask.orchestrator_task_id == task_id))
    scan_task = result.scalar_one_or_none()
    if not scan_task:
        return None
    await get_project_for_user(db, scan_task.project_id, current_user, permission)
    return scan_task


async def _can_access_task(task_id: str, db: AsyncSession, current_user: User) -> bool:
    try:
        await _require_task_access(task_id, db, current_user)
        return True
    except HTTPException:
        return False


async def _require_task_control_access(task_id: str, db: AsyncSession, current_user: User) -> None:
    try:
        await _require_task_access(task_id, db, current_user, "scan:cancel")
        return
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    persisted_task = await _get_persisted_task(task_id, db, current_user, "scan:cancel")
    if not persisted_task:
        raise HTTPException(status_code=404, detail="任务不存在")


async def _persist_control_state(
    task_id: str,
    db: AsyncSession,
    current_user: User,
    *,
    status_text: str,
    scan_status: Optional[ScanTaskStatus] = None,
) -> None:
    scan_task = await _get_persisted_task(task_id, db, current_user, "scan:cancel")
    if not scan_task:
        return
    progress = dict(scan_task.progress or {})
    progress.update({
        "task_id": task_id,
        "status": status_text,
        "current_step": {
            "paused": "任务已暂停",
            "running": "任务已恢复，继续执行中...",
            "stopped": "任务已停止",
        }.get(status_text, progress.get("current_step", "")),
    })
    scan_task.progress = progress
    scan_task.control_state = {
        "paused": "paused",
        "running": "running",
        "stopped": "cancelled",
    }.get(status_text, status_text)
    if scan_status:
        scan_task.status = scan_status
    if scan_status in (ScanTaskStatus.CANCELLED, ScanTaskStatus.FAILED, ScanTaskStatus.COMPLETED):
        scan_task.completed_at = datetime.utcnow()
        scan_task.lease_owner = None
        scan_task.lease_expires_at = None
    elif status_text == "paused":
        scan_task.paused_at = datetime.utcnow()
        scan_task.lease_owner = "paused"
        scan_task.lease_expires_at = datetime.utcnow() + timedelta(days=3650)
    elif status_text == "running":
        scan_task.paused_at = None
        scan_task.lease_owner = "resumed"
        scan_task.lease_expires_at = None
    elif status_text == "stopped":
        scan_task.cancel_requested_at = datetime.utcnow()
    await record_audit_event(
        db,
        event_type=f"scan.{status_text}",
        resource_type="scan_task",
        resource_id=scan_task.id,
        actor_user_id=current_user.id,
        project_id=scan_task.project_id,
        details={"orchestrator_task_id": task_id},
    )
    await db.commit()


@router.get("/{task_id}/status")
async def get_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取任务状态"""
    persisted_task = None
    if _task_exists(task_id):
        await _require_task_access(task_id, db, current_user)
    else:
        persisted_task = await _get_persisted_task(task_id, db, current_user)
    status = orchestrator.get_task_status(task_id)
    progress = orchestrator.task_progress.get(task_id, {})
    if persisted_task:
        status = persisted_task.effective_control_state
        progress = persisted_task.progress or {}
    
    return {
        "task_id": task_id,
        "status": status or "unknown",
        "progress": progress,
    }


@router.post("/{task_id}/pause")
async def pause_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """暂停任务"""
    await _require_task_control_access(task_id, db, current_user)
    success = await orchestrator.pause_task(task_id)
    if not success:
        persisted_task = await _get_persisted_task(task_id, db, current_user, "scan:cancel")
        if not persisted_task or persisted_task.status not in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING):
            raise HTTPException(status_code=400, detail="任务无法暂停（可能已完成或已停止）")
    await _persist_control_state(task_id, db, current_user, status_text="paused")
    
    return {
        "task_id": task_id,
        "status": "paused",
        "message": "任务已暂停",
    }


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复任务"""
    await _require_task_control_access(task_id, db, current_user)
    success = await orchestrator.resume_task(task_id)
    if not success:
        persisted_task = await _get_persisted_task(task_id, db, current_user, "scan:cancel")
        if not persisted_task or (persisted_task.progress or {}).get("status") != "paused":
            raise HTTPException(status_code=400, detail="任务无法恢复（可能未暂停）")
        if persisted_task.status == ScanTaskStatus.PENDING:
            await _persist_control_state(task_id, db, current_user, status_text="running")
        else:
            await _persist_control_state(task_id, db, current_user, status_text="running", scan_status=ScanTaskStatus.RUNNING)
    else:
        await _persist_control_state(task_id, db, current_user, status_text="running", scan_status=ScanTaskStatus.RUNNING)
    
    return {
        "task_id": task_id,
        "status": "running",
        "message": "任务已恢复",
    }


@router.post("/{task_id}/stop")
async def stop_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止任务"""
    await _require_task_control_access(task_id, db, current_user)
    success = await orchestrator.stop_task(task_id)
    if not success:
        persisted_task = await _get_persisted_task(task_id, db, current_user, "scan:cancel")
        if persisted_task and persisted_task.status in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING):
            await _persist_control_state(
                task_id,
                db,
                current_user,
                status_text="stopped",
                scan_status=ScanTaskStatus.CANCELLED,
            )
            return {
                "task_id": task_id,
                "status": "stopped",
                "message": "任务已标记停止（当前进程未持有可取消的执行句柄）",
            }
        raise HTTPException(status_code=400, detail="任务无法停止（可能已完成）")
    await _persist_control_state(task_id, db, current_user, status_text="stopped", scan_status=ScanTaskStatus.CANCELLED)
    
    return {
        "task_id": task_id,
        "status": "stopped",
        "message": "任务已停止",
    }


@router.get("/running")
async def list_running_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有正在运行的任务"""
    running_tasks = []
    
    for task_id, status in orchestrator.task_status.items():
        if status in ("running", "paused"):
            if not await _can_access_task(task_id, db, current_user):
                continue
            progress = orchestrator.task_progress.get(task_id, {})
            running_tasks.append({
                "task_id": task_id,
                "status": status,
                "progress": progress,
            })

    result = await db.execute(
        select(ScanTask)
        .where(ScanTask.status.in_([ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING]))
        .order_by(ScanTask.created_at.desc())
        .limit(50)
    )
    seen = {task["task_id"] for task in running_tasks}
    for scan_task in result.scalars().all():
        task_id = scan_task.orchestrator_task_id
        if not task_id or task_id in seen:
            continue
        try:
            await get_project_for_user(db, scan_task.project_id, current_user, "scan:read")
        except HTTPException:
            continue
        running_tasks.append({
            "task_id": task_id,
            "status": scan_task.effective_control_state,
            "progress": scan_task.progress or {},
            "scan_task_id": scan_task.id,
        })
    
    return {
        "tasks": running_tasks,
        "count": len(running_tasks),
    }
