"""
Chat API - 对话接口
使用 Orchestrator 处理用户输入
支持异步任务执行 + 结果轮询
"""

import asyncio
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.scan_task import ScanTask
from app.orchestrator import orchestrator
from app.services.audit import record_audit_event
from app.services.display_names import scan_display_name

router = APIRouter(prefix="/chat", tags=["AI Chat"])

async def _can_read_task_payload(task: Dict[str, Any], db: AsyncSession, current_user: User) -> bool:
    if task.get("user_id") == current_user.id:
        return True
    project_id = task.get("project_id")
    if not project_id:
        return False
    from app.api.projects import get_project_for_user
    try:
        await get_project_for_user(db, int(project_id), current_user.id, "scan:read")
        return True
    except HTTPException:
        return False


# --- Models ---

class ChatMessage(BaseModel):
    message: str
    project_id: Optional[int] = None
    asset: Optional[str] = None
    model_id: Optional[int] = None
    thread_id: Optional[int] = None


class ChatResponse(BaseModel):
    response: str
    task_ids: List[str] = []
    agents: List[Dict[str, Any]] = []
    context: Optional[Dict[str, Any]] = None
    task_id: Optional[str] = None
    scan_task_id: Optional[int] = None
    next_thread_id: Optional[int] = None


class TaskStatusResponse(BaseModel):
    running: List[Dict[str, Any]] = []
    completed: List[Dict[str, Any]] = []


class TaskResultResponse(BaseModel):
    task_id: str
    status: str  # 'running', 'completed', 'failed'
    result_description: Optional[str] = None
    scan_results: Optional[Dict[str, Any]] = None
    completed_at: Optional[str] = None
    current_step: Optional[str] = None
    step_progress: Optional[Dict[str, Any]] = None
    next_thread_id: Optional[int] = None


# --- Chat Endpoint ---

@router.post("/", response_model=ChatResponse)
async def chat(
    msg: ChatMessage,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    处理用户输入 - AI 驱动
    
    流程：
    1. AI 理解用户需求，生成执行计划
    2. 立即返回 AI 回复 + task_id
    3. 后台异步执行计划
    4. 前端通过 /chat/result/{task_id} 获取结果
    """
    message = msg.message.strip()
    project_id = msg.project_id
    asset = msg.asset
    
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # 检测多资产扫描 JSON 格式
    import json
    is_multi_asset_scan = False
    multi_asset_data = None
    try:
        parsed = json.loads(message)
        if isinstance(parsed, dict) and parsed.get("type") == "multi_asset_scan":
            is_multi_asset_scan = True
            multi_asset_data = parsed
    except json.JSONDecodeError:
        pass
    
    # 获取项目
    project = None
    if project_id:
        from app.api.projects import get_project_for_user
        project = await get_project_for_user(db, project_id, current_user.id, "project:read")
    
    # 如果是多资产扫描，直接构建执行计划，跳过 AI 决策
    if is_multi_asset_scan and multi_asset_data:
        capability = multi_asset_data.get("capability", "scan_ports")
        raw_assets = multi_asset_data.get("assets", [])
        assets = []
        seen_asset_targets = set()
        for asset_item in raw_assets:
            if not isinstance(asset_item, dict):
                continue
            target = str(asset_item.get("value") or asset_item.get("target") or "").strip()
            target_key = target.lower()
            if not target or target_key in seen_asset_targets:
                continue
            seen_asset_targets.add(target_key)
            assets.append({**asset_item, "value": target})

        if not assets:
            raise HTTPException(status_code=400, detail="未选择有效资产")

        base_parameters = multi_asset_data.get("parameters") or {}
        ssh_credential = multi_asset_data.get("ssh_credential")  # 默认凭据（向后兼容）
        
        # 构建执行计划
        plan = []
        for asset_item in assets:
            parameters = {**base_parameters, "target": asset_item.get("value")}
            
            # 优先使用资产级凭据，否则使用默认凭据
            asset_ssh = asset_item.get("ssh_credential") or ssh_credential
            if asset_ssh:
                parameters["ssh_username"] = asset_ssh.get("username", "root")
                if asset_ssh.get("password"):
                    parameters["ssh_password"] = asset_ssh.get("password")
                if asset_ssh.get("key_file"):
                    parameters["ssh_key_file"] = asset_ssh.get("key_file")
                if asset_ssh.get("port"):
                    parameters["ssh_port"] = asset_ssh.get("port", 22)
            
            plan.append({
                "capability": capability,
                "parameters": parameters
            })
        
        # 生成人类可读的响应
        asset_names = [a.get("value") for a in assets]
        ssh_info = ""
        if ssh_credential:
            ssh_info = f"（SSH 用户: {ssh_credential.get('username', 'root')}）"
        capability_name = scan_display_name(capability)
        response = f"好的，我将对项目中的 {len(assets)} 个资产执行{capability_name}{ssh_info}：{', '.join(asset_names)}"
        
        try:
            task_info = await orchestrator.start_async_plan(
                plan=plan,
                user_id=current_user.id,
                project_id=project_id,
                db=db,
                context_manager=None,
                ai_response=response,
                user_input=message,
                ai_routing={
                    "intents": ["explicit_capability"],
                    "skills": [],
                    "scope": "explicit_assets",
                    "entities": {"asset_count": len(assets)},
                    "confidence": 1.0,
                    "needs_clarification": False,
                    "use_thread_context": False,
                },
                thread_id=msg.thread_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        task_id = task_info["task_id"]
        
        return ChatResponse(
            response=response,
            task_ids=[task_id],
            agents=[],
            context={"asset": asset},
            task_id=task_id,
            scan_task_id=task_info.get("scan_task_id"),
        )
    
    # 使用 Orchestrator 处理
    try:
        result = await orchestrator.handle_user_input(
            user_input=message,
            project_id=project_id,
            user_id=current_user.id,
            asset=asset,
            db=db,
            thread_id=msg.thread_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    return ChatResponse(
        response=result["message"],
        task_ids=result["task_ids"],
        agents=result["agents"],
        context={"asset": asset},
        task_id=result.get("task_id"),
        scan_task_id=result.get("scan_task_id"),
        next_thread_id=result.get("next_thread_id"),
    )


@router.get("/status", response_model=TaskStatusResponse)
async def get_task_status(
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的任务状态"""
    status = orchestrator.get_status(user_id=current_user.id)
    return TaskStatusResponse(
        running=status["running"],
        completed=status["completed"],
    )


@router.get("/result/{task_id}", response_model=TaskResultResponse)
async def get_task_result(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取任务执行结果
    
    前端轮询此接口，直到 status 变为 completed 或 failed
    """
    # 检查是否已完成
    for task in orchestrator.completed_tasks:
        if task["task_id"] == task_id and await _can_read_task_payload(task, db, current_user):
            return TaskResultResponse(
                task_id=task_id,
                status="completed",
                result_description=task.get("result_description", ""),
                scan_results=task.get("scan_results", {}),
                completed_at=task.get("completed_at"),
                next_thread_id=task.get("next_thread_id"),
            )
    
    # 检查是否有进度信息
    progress = orchestrator.task_progress.get(task_id)
    if progress and await _can_read_task_payload(progress, db, current_user):
        return TaskResultResponse(
            task_id=task_id,
            status="running",
            current_step=progress.get("current_step", ""),
            step_progress={
                "step_index": progress.get("step_index", 0),
                "total_steps": progress.get("total_steps", 0),
                "steps": progress.get("steps", []),
            },
        )

    # 进程内状态丢失或刷新后，从持久化 scan_tasks 恢复最终结果/基础状态
    result = await db.execute(select(ScanTask).where(ScanTask.orchestrator_task_id == task_id))
    scan_task = result.scalar_one_or_none()
    if scan_task:
        from app.api.projects import get_project_for_user
        await get_project_for_user(db, scan_task.project_id, current_user.id, "scan:read")
        if scan_task.status.value in ("completed", "failed", "cancelled"):
            summary = scan_task.result_summary or {}
            status_value = "failed" if scan_task.status.value in ("failed", "cancelled") else "completed"
            return TaskResultResponse(
                task_id=task_id,
                status=status_value,
                result_description=summary.get("result_description") or scan_task.error_message or "任务已结束",
                scan_results=summary.get("scan_results") or {},
                completed_at=scan_task.completed_at.isoformat() if scan_task.completed_at else None,
            )
        return TaskResultResponse(
            task_id=task_id,
            status=(scan_task.progress or {}).get("status") or scan_task.status.value,
            current_step=(scan_task.progress or {}).get("current_step", "任务执行中..."),
            step_progress={
                "step_index": (scan_task.progress or {}).get("step_index", 0),
                "total_steps": (scan_task.progress or {}).get("total_steps", 0),
                "steps": (scan_task.progress or {}).get("steps", []),
            },
        )
    
    # 未找到任务，可能还在异步执行中
    return TaskResultResponse(
        task_id=task_id,
        status="running",
        current_step="正在准备执行...",
    )


@router.get("/status/{task_id}")
async def get_agent_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取特定任务的状态（兼容旧接口）"""
    # 检查 completed_tasks
    for task in orchestrator.completed_tasks:
        if task["task_id"] == task_id and await _can_read_task_payload(task, db, current_user):
            return task

    result = await db.execute(select(ScanTask).where(ScanTask.orchestrator_task_id == task_id))
    scan_task = result.scalar_one_or_none()
    if scan_task:
        from app.api.projects import get_project_for_user
        await get_project_for_user(db, scan_task.project_id, current_user.id, "scan:read")
        return {
            "task_id": task_id,
            "status": scan_task.status.value,
            "progress": scan_task.progress or {},
            "result_summary": scan_task.result_summary or {},
        }
    
    # 未找到，可能还在运行中
    return {"task_id": task_id, "status": "running"}


@router.get("/history")
async def get_chat_history(
    project_id: Optional[int] = Query(None, description="项目ID"),
    thread_id: Optional[int] = Query(None, description="对话线程ID；省略时仅返回默认线程"),
    limit: int = Query(50, description="返回数量限制"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取对话历史"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("get_chat_history project_id=%s limit=%d user_id=%d", project_id, limit, current_user.id)
    
    from app.models.context import ConversationHistory
    
    query = select(ConversationHistory).where(
        ConversationHistory.user_id == current_user.id,
        ConversationHistory.archive_id.is_(None),
        ConversationHistory.thread_id.is_(None) if thread_id is None else ConversationHistory.thread_id == thread_id,
    )
    
    # 按项目过滤（仅当明确传入了 project_id 时）
    if project_id is not None:
        from app.api.projects import get_project_for_user
        await get_project_for_user(db, project_id, current_user.id, "project:read")
        query = query.where(ConversationHistory.project_id == project_id)
    else:
        query = query.where(ConversationHistory.project_id.is_(None))

    if thread_id is not None:
        from app.services.context_manager import ContextManager
        if not await ContextManager(db, current_user.id, project_id=project_id).get_thread(thread_id):
            raise HTTPException(status_code=404, detail="线程不存在")
    
    query = query.order_by(ConversationHistory.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    histories = result.scalars().all()
    
    return [
        {
            "id": h.id,
            "role": h.role,
            "content": h.content,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "context_snapshot": h.context_snapshot,
        }
        for h in reversed(histories)
    ]


@router.post("/clear")
async def clear_history(
    thread_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clear only active messages in the current default/thread context."""
    from app.models.context import ConversationHistory
    
    await db.execute(
        delete(ConversationHistory).where(
            ConversationHistory.user_id == current_user.id,
            ConversationHistory.project_id.is_(None),
            ConversationHistory.archive_id.is_(None),
            ConversationHistory.thread_id.is_(None) if thread_id is None else ConversationHistory.thread_id == thread_id,
        )
    )
    await db.commit()
    
    return {"message": "已清理当前未归档对话"}


@router.post("/clear/{project_id}")
async def clear_project_history(
    project_id: int,
    thread_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清理指定项目当前线程的未归档对话。"""
    from app.models.context import ConversationHistory
    from app.api.projects import get_project_for_user
    
    await get_project_for_user(db, project_id, current_user.id, "project:read")
    
    await db.execute(
        delete(ConversationHistory).where(
            ConversationHistory.user_id == current_user.id,
            ConversationHistory.project_id == project_id,
            ConversationHistory.archive_id.is_(None),
            ConversationHistory.thread_id.is_(None) if thread_id is None else ConversationHistory.thread_id == thread_id,
        )
    )
    await db.commit()
    
    return {"message": f"已清理项目 {project_id} 当前线程的未归档对话"}


# --- Legacy Endpoints ---

@router.get("/scanner-info")
async def scanner_info(current_user: User = Depends(get_current_user)):
    """获取扫描器信息"""
    return {
        "orchestrator": "active",
        "active_agents": len(orchestrator.active_agents),
        "completed_tasks": len(orchestrator.completed_tasks),
    }


# --- Archive Endpoints ---

class ArchiveRequest(BaseModel):
    title: Optional[str] = None
    project_id: Optional[int] = None
    thread_id: Optional[int] = None


class ArchiveResponse(BaseModel):
    archive_id: int
    message: str
    status: str = "completed"  # "pending" or "completed"


@router.post("/archives", response_model=ArchiveResponse)
async def create_archive(
    req: ArchiveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    创建对话归档（异步）
    
    1. 立即创建归档记录并保留原始对话
    2. 持久化 Worker 异步生成 LLM 摘要
    3. 前端轮询 /archives/{id} 获取完整结果
    """
    from app.services.context_manager import ContextManager
    
    project = None
    if req.project_id is not None:
        from app.api.projects import get_project_for_user
        project = await get_project_for_user(db, req.project_id, current_user.id, "project:read")

    context_manager = ContextManager(db, current_user.id, project_id=req.project_id, thread_id=req.thread_id)
    
    archive_id = await context_manager.create_archive_placeholder(title=req.title)
    
    if not archive_id:
        raise HTTPException(status_code=400, detail="没有可归档的对话")
    await record_audit_event(
        db,
        event_type="conversation.archive_created",
        resource_type="conversation_archive",
        resource_id=archive_id,
        actor_user_id=current_user.id,
        organization_id=project.organization_id if project else None,
        project_id=req.project_id,
        details={"thread_id": req.thread_id},
    )
    await db.commit()
    
    return ArchiveResponse(
        archive_id=archive_id,
        message="归档已创建，正在由后台任务生成摘要...",
        status="pending"
    )


@router.get("/archives")
async def list_archives(
    project_id: Optional[int] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出对话归档"""
    from app.services.context_manager import ContextManager
    if project_id:
        from app.api.projects import get_project_for_user
        await get_project_for_user(db, project_id, current_user.id, "project:read")
    
    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    archives = await context_manager.list_archives(limit=limit)
    
    return {"archives": archives, "count": len(archives)}


@router.get("/archives/search")
async def search_archive_messages(
    q: str = Query(..., min_length=2, max_length=200),
    project_id: Optional[int] = Query(None),
    limit: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if project_id is not None:
        from app.api.projects import get_project_for_user
        await get_project_for_user(db, project_id, current_user.id, "project:read")
    manager = ContextManager(db, current_user.id, project_id=project_id)
    matches = await manager.recall_archived_messages(q, limit=limit)
    return {"matches": matches, "count": len(matches)}


@router.get("/archives/{archive_id}")
async def get_archive(
    archive_id: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取归档详情"""
    from app.services.context_manager import ContextManager
    
    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    archive = await context_manager.get_archive(archive_id)
    
    if not archive:
        raise HTTPException(status_code=404, detail="归档不存在")
    
    return archive


@router.delete("/archives/{archive_id}")
async def delete_archive(
    archive_id: int,
    project_id: Optional[int] = None,
    permanent: bool = Query(False, description="明确确认永久删除归档和原文"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除对话归档"""
    from app.services.context_manager import ContextManager
    
    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    try:
        success = await context_manager.delete_archive(archive_id, permanent=permanent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    if not success:
        raise HTTPException(status_code=404, detail="归档不存在")
    await record_audit_event(
        db,
        event_type="conversation.archive_deleted",
        resource_type="conversation_archive",
        resource_id=archive_id,
        actor_user_id=current_user.id,
        project_id=project_id,
        details={"permanent": permanent},
    )
    await db.commit()
    
    return {"message": "归档已删除"}


@router.post("/archives/{archive_id}/retry")
async def retry_archive(
    archive_id: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.context_manager import ContextManager
    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    if not await context_manager.retry_archive(archive_id):
        raise HTTPException(status_code=400, detail="归档无法重试：可能为旧版摘要或不存在")
    await record_audit_event(
        db,
        event_type="conversation.archive_retried",
        resource_type="conversation_archive",
        resource_id=archive_id,
        actor_user_id=current_user.id,
        project_id=project_id,
    )
    await db.commit()
    return {"message": "归档摘要已重新加入队列", "status": "queued"}


@router.post("/archives/{archive_id}/continue")
async def continue_from_archive(
    archive_id: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.context_manager import ContextManager
    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    result = await context_manager.continue_from_archive(archive_id)
    if not result:
        raise HTTPException(status_code=400, detail="归档未完成、不可接续或不存在")
    await record_audit_event(
        db,
        event_type="conversation.archive_continued",
        resource_type="conversation_archive",
        resource_id=archive_id,
        actor_user_id=current_user.id,
        project_id=project_id,
        details={"thread_id": result["thread_id"]},
    )
    await db.commit()
    return {"thread_id": result["thread_id"], "message": "已创建接续线程"}


# --- Thread Endpoints ---

class ThreadRequest(BaseModel):
    title: Optional[str] = None
    parent_thread_id: Optional[int] = None
    project_id: Optional[int] = None


class ThreadResponse(BaseModel):
    thread_id: int
    message: str


@router.post("/threads", response_model=ThreadResponse)
async def create_thread(
    req: ThreadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新的对话线程"""
    from app.services.context_manager import ContextManager
    
    if req.project_id is not None:
        from app.api.projects import get_project_for_user
        await get_project_for_user(db, req.project_id, current_user.id, "project:read")

    context_manager = ContextManager(db, current_user.id, project_id=req.project_id)
    thread_id = await context_manager.create_thread(
        title=req.title,
        parent_thread_id=req.parent_thread_id
    )
    
    return ThreadResponse(
        thread_id=thread_id,
        message="线程创建成功"
    )


@router.get("/threads")
async def list_threads(
    project_id: Optional[int] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出对话线程"""
    from app.services.context_manager import ContextManager
    
    if project_id is not None:
        from app.api.projects import get_project_for_user
        await get_project_for_user(db, project_id, current_user.id, "project:read")

    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    threads = await context_manager.list_threads(limit=limit)
    
    return {"threads": threads, "count": len(threads)}


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取线程详情"""
    from app.services.context_manager import ContextManager
    
    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    thread = await context_manager.get_thread(thread_id)
    
    if not thread:
        raise HTTPException(status_code=404, detail="线程不存在")
    
    return thread


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除对话线程"""
    from app.services.context_manager import ContextManager
    
    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    success = await context_manager.delete_thread(thread_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="线程不存在")
    
    return {"message": "线程已删除"}


@router.post("/threads/{thread_id}/continue")
async def continue_from_thread(
    thread_id: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从指定线程接续上下文"""
    from app.services.context_manager import ContextManager
    
    context_manager = ContextManager(db, current_user.id, project_id=project_id)
    result = await context_manager.continue_from_thread(thread_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="线程不存在")
    
    return result
