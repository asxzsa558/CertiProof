"""
Chat API - 对话接口
使用 Orchestrator 处理用户输入
"""

import asyncio
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.models.scan_task import ScanTask, ScanTaskType, ScanTaskStatus, TriggeredBy
from app.models.finding import Finding, Severity, Judgment, JudgmentEngine, FindingStatus
from app.models.evidence import Evidence, EvidenceType
from app.models.remediation import RemediationTicket, RemediationStatus
from app.orchestrator import orchestrator

router = APIRouter(prefix="/chat", tags=["AI Chat"])


# --- Models ---

class ChatMessage(BaseModel):
    message: str
    project_id: Optional[int] = None
    asset: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    task_ids: List[str] = []
    agents: List[Dict[str, Any]] = []
    context: Optional[Dict[str, Any]] = None


class TaskStatusResponse(BaseModel):
    running: List[Dict[str, Any]] = []
    completed: List[Dict[str, Any]] = []


# --- Chat Endpoint ---

@router.post("/", response_model=ChatResponse)
async def chat(
    msg: ChatMessage,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    处理用户输入 - 使用 Orchestrator
    
    1. 识别意图
    2. 加载 Skill
    3. 创建 Agent（可能多个）
    4. 后台启动 Agent
    5. 立即返回任务 ID
    """
    message = msg.message.strip()
    project_id = msg.project_id
    asset = msg.asset
    
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # 获取项目
    project = None
    if project_id:
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
    
    # 如果没有提供 asset，从项目获取第一个资产
    if not asset and project:
        result = await db.execute(
            select(Asset).where(Asset.project_id == project.id).limit(1)
        )
        asset_obj = result.scalar_one_or_none()
        if asset_obj:
            asset = asset_obj.value
    
    if not asset:
        raise HTTPException(status_code=400, detail="No asset specified")
    
    # 使用 Orchestrator 处理
    result = await orchestrator.handle_user_input(
        user_input=message,
        project_id=project_id or 0,
        user_id=current_user.id,
        asset=asset,
    )
    
    return ChatResponse(
        response=result["message"],
        task_ids=result["task_ids"],
        agents=result["agents"],
        context={"asset": asset},
    )


@router.get("/status", response_model=TaskStatusResponse)
async def get_task_status(
    current_user: User = Depends(get_current_user),
):
    """
    获取当前所有 Agent 的状态
    """
    status = orchestrator.get_status()
    return TaskStatusResponse(
        running=status["running"],
        completed=status["completed"],
    )


@router.get("/status/{task_id}")
async def get_agent_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    获取特定 Agent 的状态
    """
    # 检查是否在运行中
    if task_id in orchestrator.active_agents:
        agent = orchestrator.active_agents[task_id]
        return agent.to_dict()
    
    # 检查是否已完成
    for task in orchestrator.completed_tasks:
        if task["task_id"] == task_id:
            return task
    
    raise HTTPException(status_code=404, detail="Task not found")


# --- Legacy Endpoints (for backward compatibility) ---

@router.get("/scanner-info")
async def scanner_info(current_user: User = Depends(get_current_user)):
    """获取扫描器信息"""
    return {
        "orchestrator": "active",
        "active_agents": len(orchestrator.active_agents),
        "completed_tasks": len(orchestrator.completed_tasks),
    }
