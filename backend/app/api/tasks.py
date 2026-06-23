"""
Tasks API - 任务控制接口
支持暂停、恢复、停止正在执行的任务
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.orchestrator import orchestrator

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("/{task_id}/status")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取任务状态"""
    status = orchestrator.get_task_status(task_id)
    progress = orchestrator.task_progress.get(task_id, {})
    
    return {
        "task_id": task_id,
        "status": status or "unknown",
        "progress": progress,
    }


@router.post("/{task_id}/pause")
async def pause_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """暂停任务"""
    success = await orchestrator.pause_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="任务无法暂停（可能已完成或已停止）")
    
    return {
        "task_id": task_id,
        "status": "paused",
        "message": "任务已暂停",
    }


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """恢复任务"""
    success = await orchestrator.resume_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="任务无法恢复（可能未暂停）")
    
    return {
        "task_id": task_id,
        "status": "running",
        "message": "任务已恢复",
    }


@router.post("/{task_id}/stop")
async def stop_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """停止任务"""
    success = await orchestrator.stop_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="任务无法停止（可能已完成）")
    
    return {
        "task_id": task_id,
        "status": "stopped",
        "message": "任务已停止",
    }


@router.get("/running")
async def list_running_tasks(
    current_user: User = Depends(get_current_user),
):
    """列出所有正在运行的任务"""
    running_tasks = []
    
    for task_id, status in orchestrator.task_status.items():
        if status in ("running", "paused"):
            progress = orchestrator.task_progress.get(task_id, {})
            running_tasks.append({
                "task_id": task_id,
                "status": status,
                "progress": progress,
            })
    
    return {
        "tasks": running_tasks,
        "count": len(running_tasks),
    }
