"""
Chat API - 对话接口
使用 Orchestrator 处理用户输入
支持异步任务执行 + 结果轮询
"""

import asyncio
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.orchestrator import orchestrator

router = APIRouter(prefix="/chat", tags=["AI Chat"])


# --- Models ---

class ChatMessage(BaseModel):
    message: str
    project_id: Optional[int] = None
    asset: Optional[str] = None
    model_id: Optional[int] = None


class ChatResponse(BaseModel):
    response: str
    task_ids: List[str] = []
    agents: List[Dict[str, Any]] = []
    context: Optional[Dict[str, Any]] = None
    task_id: Optional[str] = None
    scan_task_id: Optional[int] = None


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
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
    
    # 如果是多资产扫描，直接构建执行计划，跳过 AI 决策
    if is_multi_asset_scan and multi_asset_data:
        capability = multi_asset_data.get("capability", "scan_ports")
        assets = multi_asset_data.get("assets", [])
        
        # 构建执行计划
        plan = []
        for asset_item in assets:
            plan.append({
                "capability": capability,
                "parameters": {"target": asset_item.get("value")}
            })
        
        # 生成人类可读的响应
        asset_names = [a.get("value") for a in assets]
        response = f"好的，我将对项目中的 {len(assets)} 个资产执行{capability}：{', '.join(asset_names)}"
        
        # 生成 task_id
        task_id = str(uuid.uuid4())
        
        # 异步执行计划
        asyncio.create_task(orchestrator._execute_plan_async(
            task_id=task_id,
            plan=plan,
            user_id=current_user.id,
            project_id=project_id or 0,
            db=db,
            context_manager=None,
            ai_response=response,
        ))
        
        return ChatResponse(
            response=response,
            task_ids=[task_id],
            agents=[],
            context={"asset": asset},
            task_id=task_id,
        )
    
    # 如果没有提供 asset，从项目获取第一个资产
    if not asset and project:
        result = await db.execute(
            select(Asset).where(Asset.project_id == project.id).limit(1)
        )
        asset_obj = result.scalar_one_or_none()
        if asset_obj:
            asset = asset_obj.value
    
    # 使用 Orchestrator 处理
    result = await orchestrator.handle_user_input(
        user_input=message,
        project_id=project_id or 0,
        user_id=current_user.id,
        asset=asset,
        db=db,
    )
    
    return ChatResponse(
        response=result["message"],
        task_ids=result["task_ids"],
        agents=result["agents"],
        context={"asset": asset},
        task_id=result.get("task_id"),
        scan_task_id=result.get("scan_task_id"),
    )


@router.get("/status", response_model=TaskStatusResponse)
async def get_task_status(
    current_user: User = Depends(get_current_user),
):
    """获取当前所有任务的状态"""
    status = orchestrator.get_status()
    return TaskStatusResponse(
        running=status["running"],
        completed=status["completed"],
    )


@router.get("/result/{task_id}", response_model=TaskResultResponse)
async def get_task_result(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    获取任务执行结果
    
    前端轮询此接口，直到 status 变为 completed 或 failed
    """
    # 检查是否已完成
    for task in orchestrator.completed_tasks:
        if task["task_id"] == task_id:
            return TaskResultResponse(
                task_id=task_id,
                status="completed",
                result_description=task.get("result_description", ""),
                scan_results=task.get("scan_results", {}),
                completed_at=task.get("completed_at"),
            )
    
    # 检查是否有进度信息
    progress = orchestrator.task_progress.get(task_id)
    if progress:
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
    
    # 未找到任务，可能还在异步执行中
    return TaskResultResponse(
        task_id=task_id,
        status="running",
        current_step="正在准备执行...",
    )


@router.get("/status/{task_id}")
async def get_agent_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取特定任务的状态（兼容旧接口）"""
    # 检查 completed_tasks
    for task in orchestrator.completed_tasks:
        if task["task_id"] == task_id:
            return task
    
    # 未找到，可能还在运行中
    return {"task_id": task_id, "status": "running"}


@router.get("/history")
async def get_chat_history(
    project_id: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取对话历史"""
    from app.models.context import ConversationHistory
    
    query = select(ConversationHistory).where(
        ConversationHistory.user_id == current_user.id
    )
    
    if project_id:
        query = query.where(ConversationHistory.project_id == project_id)
    
    query = query.order_by(ConversationHistory.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    histories = result.scalars().all()
    
    return [
        {
            "id": h.id,
            "role": h.role,
            "content": h.content,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in reversed(histories)
    ]


@router.post("/clear")
async def clear_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清理当前用户所有对话历史 + 操作历史"""
    from app.models.context import ConversationHistory, ActionHistory
    
    await db.execute(
        delete(ConversationHistory).where(ConversationHistory.user_id == current_user.id)
    )
    await db.execute(
        delete(ActionHistory).where(ActionHistory.user_id == current_user.id)
    )
    await db.commit()
    
    return {"message": "已清理所有对话和操作历史"}


@router.post("/clear/{project_id}")
async def clear_project_history(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清理指定项目的对话/操作/缓存"""
    from app.models.context import ConversationHistory, ActionHistory, ResultCache
    
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")
    
    await db.execute(
        delete(ConversationHistory).where(
            ConversationHistory.user_id == current_user.id,
            ConversationHistory.project_id == project_id,
        )
    )
    await db.execute(
        delete(ActionHistory).where(
            ActionHistory.user_id == current_user.id,
            ActionHistory.project_id == project_id,
        )
    )
    await db.execute(
        delete(ResultCache).where(
            ResultCache.user_id == current_user.id,
            ResultCache.project_id == project_id,
        )
    )
    await db.commit()
    
    return {"message": f"已清理项目 {project_id} 的所有历史数据"}


# --- Legacy Endpoints ---

@router.get("/scanner-info")
async def scanner_info(current_user: User = Depends(get_current_user)):
    """获取扫描器信息"""
    return {
        "orchestrator": "active",
        "active_agents": len(orchestrator.active_agents),
        "completed_tasks": len(orchestrator.completed_tasks),
    }
