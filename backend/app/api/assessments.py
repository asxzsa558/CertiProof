"""
等保测评流程管理 API

提供流程模板、测评实例、阶段、任务的 CRUD 和操作接口
"""

import os
import re
import uuid
import logging
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings

logger = logging.getLogger(__name__)
from app.models.user import User
from app.models.assessment import FlowTemplate, Assessment, PhaseInstance, TaskInstance, FlowEvent
from app.models.project import Project
from app.services.flow_engine import FlowEngine, get_flow_engine
from app.services.assessment_templates import LEVEL_2_TEMPLATE, LEVEL_3_TEMPLATE

router = APIRouter(prefix="/assessments", tags=["Assessments"])


async def require_project_permission(db: AsyncSession, project_id: int, user: User, permission: str):
    from app.api.projects import get_project_for_user
    return await get_project_for_user(db, project_id, user.id, permission)


async def require_assessment_permission(db: AsyncSession, assessment_id: int, user: User, permission: str):
    engine = get_flow_engine(db)
    assessment = await engine.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    await require_project_permission(db, assessment.project_id, user, permission)
    return assessment


async def require_phase_permission(db: AsyncSession, phase_id: int, user: User, permission: str):
    engine = get_flow_engine(db)
    phase = await engine.get_phase(phase_id)
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")
    assessment = await require_assessment_permission(db, phase.assessment_id, user, permission)
    return phase, assessment


async def require_task_permission(db: AsyncSession, task_id: int, user: User, permission: str):
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    phase, assessment = await require_phase_permission(db, task.phase_id, user, permission)
    return task, phase, assessment


# ========== Request/Response Models ==========

class CreateAssessmentRequest(BaseModel):
    template_id: int
    name: Optional[str] = None
    target_system: Optional[str] = None


class AssessmentResponse(BaseModel):
    id: int
    project_id: int
    template_id: int
    name: str
    target_system: Optional[str]
    assessment_level: int
    status: str
    total_phases: int
    completed_phases: int
    progress: float
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    
    class Config:
        from_attributes = True


class PhaseResponse(BaseModel):
    id: int
    assessment_id: int
    phase_id: str
    name: str
    description: Optional[str]
    order: int
    status: str
    total_tasks: int
    completed_tasks: int
    progress: float
    started_at: Optional[str]
    completed_at: Optional[str]
    depends_on: Optional[list]
    
    class Config:
        from_attributes = True


class TaskResponse(BaseModel):
    id: int
    phase_id: int
    task_type: str
    name: str
    description: Optional[str]
    status: str
    assignee_id: Optional[int]
    priority: int
    result: Optional[dict]
    started_at: Optional[str]
    completed_at: Optional[str]
    
    class Config:
        from_attributes = True


class TemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    compliance_level: int
    version: str
    phases_count: int
    is_active: bool
    
    class Config:
        from_attributes = True


class CompletePhaseRequest(BaseModel):
    outputs: Optional[dict] = None


class CompleteTaskRequest(BaseModel):
    result: Optional[dict] = None


class ExecuteTaskRequest(BaseModel):
    target: Optional[str] = None
    targets: Optional[List[str]] = None
    params: Optional[dict] = None
    credentials: Optional[Dict[str, dict]] = None


class SkipPhaseRequest(BaseModel):
    reason: str = ""


class CreateTaskRequest(BaseModel):
    task_type: str
    name: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None


# ========== Template APIs ==========

@router.get("/templates", response_model=List[TemplateResponse])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出流程模板"""
    engine = get_flow_engine(db)
    templates = await engine.list_templates()
    
    result = []
    for t in templates:
        result.append(TemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            compliance_level=t.compliance_level,
            version=t.version,
            phases_count=len(t.phases_config) if t.phases_config else 0,
            is_active=t.is_active,
        ))
    return result


@router.post("/templates/init")
async def init_default_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """初始化默认流程模板"""
    engine = get_flow_engine(db)
    
    # 检查是否已存在
    existing = await engine.list_templates(active_only=False)
    if existing:
        return {"message": "Templates already exist", "count": len(existing)}
    
    # 创建二级模板
    await engine.create_template(
        name=LEVEL_2_TEMPLATE["name"],
        compliance_level=LEVEL_2_TEMPLATE["compliance_level"],
        phases_config=LEVEL_2_TEMPLATE["phases_config"],
    )
    
    # 创建三级模板
    await engine.create_template(
        name=LEVEL_3_TEMPLATE["name"],
        compliance_level=LEVEL_3_TEMPLATE["compliance_level"],
        phases_config=LEVEL_3_TEMPLATE["phases_config"],
    )
    
    return {"message": "Default templates created"}


# ========== Assessment APIs ==========

@router.post("/projects/{project_id}", response_model=AssessmentResponse)
async def create_assessment(
    project_id: int,
    req: CreateAssessmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建测评实例"""
    await require_project_permission(db, project_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    assessment = await engine.create_assessment(
        project_id=project_id,
        template_id=req.template_id,
        name=req.name,
        owner_id=current_user.id,
    )
    
    return AssessmentResponse(
        id=assessment.id,
        project_id=assessment.project_id,
        template_id=assessment.template_id,
        name=assessment.name,
        target_system=assessment.target_system,
        assessment_level=assessment.assessment_level,
        status=assessment.status,
        total_phases=assessment.total_phases,
        completed_phases=assessment.completed_phases,
        progress=assessment.progress,
        started_at=assessment.started_at.isoformat() if assessment.started_at else None,
        completed_at=assessment.completed_at.isoformat() if assessment.completed_at else None,
        created_at=assessment.created_at.isoformat(),
    )


@router.get("/projects/{project_id}", response_model=List[AssessmentResponse])
async def list_assessments(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出项目的测评实例"""
    await require_project_permission(db, project_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    assessments = await engine.list_assessments(project_id)
    
    return [
        AssessmentResponse(
            id=a.id,
            project_id=a.project_id,
            template_id=a.template_id,
            name=a.name,
            target_system=a.target_system,
            assessment_level=a.assessment_level,
            status=a.status,
            total_phases=a.total_phases,
            completed_phases=a.completed_phases,
            progress=a.progress,
            started_at=a.started_at.isoformat() if a.started_at else None,
            completed_at=a.completed_at.isoformat() if a.completed_at else None,
            created_at=a.created_at.isoformat(),
        )
        for a in assessments
    ]


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取测评实例详情"""
    await require_assessment_permission(db, assessment_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    assessment = await engine.get_assessment(assessment_id)
    
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    return AssessmentResponse(
        id=assessment.id,
        project_id=assessment.project_id,
        template_id=assessment.template_id,
        name=assessment.name,
        target_system=assessment.target_system,
        assessment_level=assessment.assessment_level,
        status=assessment.status,
        total_phases=assessment.total_phases,
        completed_phases=assessment.completed_phases,
        progress=assessment.progress,
        started_at=assessment.started_at.isoformat() if assessment.started_at else None,
        completed_at=assessment.completed_at.isoformat() if assessment.completed_at else None,
        created_at=assessment.created_at.isoformat(),
    )


@router.post("/{assessment_id}/start", response_model=AssessmentResponse)
async def start_assessment(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """启动测评"""
    await require_assessment_permission(db, assessment_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        assessment = await engine.start_assessment(assessment_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return AssessmentResponse(
        id=assessment.id,
        project_id=assessment.project_id,
        template_id=assessment.template_id,
        name=assessment.name,
        target_system=assessment.target_system,
        assessment_level=assessment.assessment_level,
        status=assessment.status,
        total_phases=assessment.total_phases,
        completed_phases=assessment.completed_phases,
        progress=assessment.progress,
        started_at=assessment.started_at.isoformat() if assessment.started_at else None,
        completed_at=assessment.completed_at.isoformat() if assessment.completed_at else None,
        created_at=assessment.created_at.isoformat(),
    )


@router.post("/{assessment_id}/pause")
async def pause_assessment(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """暂停测评"""
    await require_assessment_permission(db, assessment_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        await engine.pause_assessment(assessment_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Assessment paused"}


@router.post("/{assessment_id}/resume")
async def resume_assessment(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复测评"""
    await require_assessment_permission(db, assessment_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        await engine.resume_assessment(assessment_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Assessment resumed"}


# ========== Phase APIs ==========

@router.get("/{assessment_id}/phases", response_model=List[PhaseResponse])
async def list_phases(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出测评的所有阶段"""
    await require_assessment_permission(db, assessment_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    phases = await engine.get_phases(assessment_id)
    
    return [
        PhaseResponse(
            id=p.id,
            assessment_id=p.assessment_id,
            phase_id=p.phase_id,
            name=p.name,
            description=p.description,
            order=p.order,
            status=p.status,
            total_tasks=p.total_tasks,
            completed_tasks=p.completed_tasks,
            progress=p.progress,
            started_at=p.started_at.isoformat() if p.started_at else None,
            completed_at=p.completed_at.isoformat() if p.completed_at else None,
            depends_on=p.depends_on,
        )
        for p in phases
    ]


@router.get("/phases/{phase_id}", response_model=PhaseResponse)
async def get_phase(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取阶段详情"""
    await require_phase_permission(db, phase_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    phase = await engine.get_phase(phase_id)
    
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")
    
    return PhaseResponse(
        id=phase.id,
        assessment_id=phase.assessment_id,
        phase_id=phase.phase_id,
        name=phase.name,
        description=phase.description,
        order=phase.order,
        status=phase.status,
        total_tasks=phase.total_tasks,
        completed_tasks=phase.completed_tasks,
        progress=phase.progress,
        started_at=phase.started_at.isoformat() if phase.started_at else None,
        completed_at=phase.completed_at.isoformat() if phase.completed_at else None,
        depends_on=phase.depends_on,
    )


@router.post("/phases/{phase_id}/start")
async def start_phase(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """激活阶段"""
    await require_phase_permission(db, phase_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        await engine.activate_phase(phase_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Phase started"}


@router.post("/phases/{phase_id}/complete")
async def complete_phase(
    phase_id: int,
    req: CompletePhaseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成阶段"""
    await require_phase_permission(db, phase_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        await engine.complete_phase(phase_id, req.outputs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Phase completed"}


@router.post("/phases/{phase_id}/skip")
async def skip_phase(
    phase_id: int,
    req: SkipPhaseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """跳过阶段"""
    await require_phase_permission(db, phase_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        await engine.skip_phase(phase_id, req.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Phase skipped"}


@router.post("/phases/{phase_id}/jump-to")
async def jump_to_phase(
    phase_id: int,
    req: SkipPhaseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    跳到指定阶段：
    - 跳过当前 active 阶段
    - 跳过所有中间阶段（order < target 且 pending/active）
    - 激活目标阶段
    """
    engine = get_flow_engine(db)
    await require_phase_permission(db, phase_id, current_user, "assessment:manage")
    
    try:
        phase = await engine.jump_to_phase(phase_id, req.reason)
        return {
            "status": "jumped",
            "phase_id": phase_id,
            "phase_name": phase.name,
            "message": f"已跳到阶段: {phase.name}",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========== Task APIs ==========

@router.get("/phases/{phase_id}/tasks", response_model=List[TaskResponse])
async def list_tasks(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出阶段的所有任务"""
    await require_phase_permission(db, phase_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    tasks = await engine.get_tasks(phase_id)
    
    return [
        TaskResponse(
            id=t.id,
            phase_id=t.phase_id,
            task_type=t.task_type,
            name=t.name,
            description=t.description,
            status=t.status,
            assignee_id=t.assignee_id,
            priority=t.priority,
            result=t.result,
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
        )
        for t in tasks
    ]


@router.post("/phases/{phase_id}/tasks", response_model=TaskResponse)
async def create_task(
    phase_id: int,
    req: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建任务"""
    await require_phase_permission(db, phase_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    task = await engine.create_task(
        phase_id=phase_id,
        task_type=req.task_type,
        name=req.name,
        description=req.description,
        assignee_id=req.assignee_id,
    )
    
    return TaskResponse(
        id=task.id,
        phase_id=task.phase_id,
        task_type=task.task_type,
        name=task.name,
        description=task.description,
        status=task.status,
        assignee_id=task.assignee_id,
        priority=task.priority,
        result=task.result,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


@router.get("/tasks/{task_id}/status")
async def get_task_status(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取任务状态（用于轮询）"""
    await require_task_permission(db, task_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {
        "id": task.id,
        "status": task.status,
        "result": task.result,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.post("/tasks/{task_id}/start")
async def start_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开始任务并自动执行（如果是可自动执行的任务）"""
    from app.services.task_executor import get_task_executor
    from app.models.asset import Asset
    from sqlalchemy import select
    import asyncio
    
    await require_task_permission(db, task_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        task = await engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        # pentest 任务已废弃：等保要求中渗透测试是文档审查（8.1.4.27）
        if task.task_type == "pentest":
            raise HTTPException(
                status_code=400,
                detail="渗透测试任务已废弃，请使用文档审查模式上传渗透测试报告"
            )
        
        task = await engine.start_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # 获取任务所属的阶段和评估
    phase = await engine.get_phase(task.phase_id)
    assessment = await engine.get_assessment(phase.assessment_id)
    
    # 检查任务是否可以自动执行
    executor = get_task_executor(db)
    if executor.is_automated_task(task.task_type):
        # 获取项目的所有资产作为目标
        result = await db.execute(
            select(Asset).where(Asset.project_id == assessment.project_id)
        )
        assets = result.scalars().all()
        
        if assets:
            targets = [asset.value for asset in assets]
            # 异步执行任务（支持多目标）
            asyncio.create_task(_execute_task_async_multi(
                task_id=task_id,
                task_type=task.task_type,
                targets=targets,
                project_id=assessment.project_id,
                user_id=current_user.id,
                db=db
            ))
        else:
            # 没有资产，标记为需要手动执行
            pass
    
    return {"message": "Task started", "task_id": task_id, "status": task.status}


async def _execute_task_async(
    task_id: int,
    task_type: str,
    target: str,
    project_id: int,
    user_id: int,
    db: AsyncSession
):
    """异步执行任务"""
    from app.services.task_executor import get_task_executor
    from app.services.flow_engine import get_flow_engine
    
    engine = get_flow_engine(db)
    
    try:
        # 确保任务状态为 in_progress（防止状态机错误）
        task = await engine.get_task(task_id)
        if task.status == "todo":
            await engine.start_task(task_id)
        
        executor = get_task_executor(db)
        result = await executor.execute_task(
            task_type=task_type,
            target=target,
            project_id=project_id,
            user_id=user_id,
        )
        
        # 更新任务状态
        if result["status"] in ["completed", "partial"]:
            await engine.complete_task(task_id, result)
        elif result["status"] == "failed":
            task = await engine.get_task(task_id)
            task.status = "failed"
            task.result = result
            await db.commit()
    except Exception as e:
        logger.error(f"Task {task_id} execution failed: {e}")
        try:
            task = await engine.get_task(task_id)
            task.status = "failed"
            task.result = {"error": str(e)}
            await db.commit()
        except Exception as e2:
            logger.error(f"Failed to update task status: {e2}")


async def _execute_task_async_multi(
    task_id: int,
    task_type: str,
    targets: list,
    project_id: int,
    user_id: int,
    db: AsyncSession
):
    """异步执行任务（支持多目标）"""
    from app.services.task_executor import get_task_executor
    from app.services.flow_engine import get_flow_engine
    import asyncio
    
    engine = get_flow_engine(db)
    
    try:
        # 确保任务状态为 in_progress
        task = await engine.get_task(task_id)
        if task.status == "todo":
            await engine.start_task(task_id)
        
        executor = get_task_executor(db)
        
        # 并发执行所有目标
        tasks_list = []
        for target in targets:
            tasks_list.append(
                executor.execute_task(
                    task_type=task_type,
                    target=target,
                    project_id=project_id,
                    user_id=user_id,
                )
            )
        results = await asyncio.gather(*tasks_list, return_exceptions=True)
        
        # 汇总结果
        asset_results = {}
        all_failed = []
        all_completed = []
        
        for i, result in enumerate(results):
            target = targets[i]
            if isinstance(result, Exception):
                asset_results[target] = {
                    "status": "failed",
                    "error": str(result),
                }
                all_failed.append({"target": target, "error": str(result)})
            else:
                asset_results[target] = result
                if result["status"] == "failed":
                    all_failed.append({"target": target, **result})
                else:
                    all_completed.append({"target": target, **result})
        
        final_result = {
            "status": "completed" if not all_failed else ("partial" if all_completed else "failed"),
            "task_type": task_type,
            "asset_results": asset_results,
            "completed": all_completed,
            "failed": all_failed,
        }
        
        # 更新任务状态
        if final_result["status"] in ["completed", "partial"]:
            await engine.complete_task(task_id, final_result)
        elif final_result["status"] == "failed":
            task = await engine.get_task(task_id)
            task.status = "failed"
            task.result = final_result
            await db.commit()
    except Exception as e:
        logger.error(f"Task {task_id} execution failed: {e}")
        try:
            task = await engine.get_task(task_id)
            task.status = "failed"
            task.result = {"error": str(e)}
            await db.commit()
        except Exception as e2:
            logger.error(f"Failed to update task status: {e2}")


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: int,
    req: CompleteTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成任务"""
    await require_task_permission(db, task_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        await engine.complete_task(task_id, req.result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Task completed"}


@router.post("/tasks/{task_id}/execute")
async def execute_task(
    task_id: int,
    req: ExecuteTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行流程任务（调用安全工具）"""
    from app.services.task_executor import get_task_executor
    
    await require_task_permission(db, task_id, current_user, "scan:execute")
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 检查任务是否可以自动执行
    executor = get_task_executor(db)
    if not executor.is_automated_task(task.task_type):
        raise HTTPException(
            status_code=400, 
            detail=f"任务类型 {task.task_type} 不支持自动执行"
        )
    
    # 确定目标列表
    targets = []
    if req.targets:
        targets = req.targets
    elif req.target:
        targets = [req.target]
    else:
        raise HTTPException(status_code=400, detail="请指定目标地址")
    
    phase = await engine.get_phase(task.phase_id)
    assessment = await engine.get_assessment(phase.assessment_id)
    
    try:
        # 开始任务
        await engine.start_task(task_id)
        
        # 单目标执行
        if len(targets) == 1:
            target_params = dict(req.params or {})
            if req.credentials and targets[0] in req.credentials:
                target_params.update(req.credentials[targets[0]])
            result = await executor.execute_task(
                task_type=task.task_type,
                target=targets[0],
                project_id=assessment.project_id,
                user_id=current_user.id,
                params=target_params,
            )
        else:
            # 多目标并发执行
            import asyncio
            tasks_list = []
            for target in targets:
                target_params = dict(req.params or {})
                if req.credentials and target in req.credentials:
                    target_params.update(req.credentials[target])
                tasks_list.append(
                    executor.execute_task(
                        task_type=task.task_type,
                        target=target,
                        project_id=assessment.project_id,
                        user_id=current_user.id,
                        params=target_params,
                    )
                )
            results = await asyncio.gather(*tasks_list, return_exceptions=True)
            
            # 汇总结果
            asset_results = {}
            all_failed = []
            all_completed = []
            
            for i, result in enumerate(results):
                target = targets[i]
                if isinstance(result, Exception):
                    asset_results[target] = {
                        "status": "failed",
                        "error": str(result),
                    }
                    all_failed.append({"target": target, "error": str(result)})
                else:
                    asset_results[target] = result
                    if result["status"] == "failed":
                        all_failed.append({"target": target, **result})
                    else:
                        all_completed.append({"target": target, **result})
            
            result = {
                "status": "completed" if not all_failed else ("partial" if all_completed else "failed"),
                "task_type": task.task_type,
                "asset_results": asset_results,
                "completed": all_completed,
                "failed": all_failed,
            }
        
        # 更新任务状态
        if result["status"] in ["completed", "partial"]:
            await engine.complete_task(task_id, result)
            return {
                "message": "任务执行完成",
                "status": "completed",
                "result": result
            }
        elif result["status"] == "failed":
            task = await engine.get_task(task_id)
            task.status = "failed"
            task.result = result
            await db.commit()
            
            error_msg = result.get("failed", [{}])[0].get("error", "任务执行失败")
            return {
                "message": f"任务执行失败: {error_msg}",
                "status": "failed",
                "result": result
            }
        else:
            return {
                "message": "任务已跳过",
                "status": "skipped",
                "result": result
            }
    except Exception as e:
        logger.error(f"Task {task_id} execution failed: {e}")
        try:
            task = await engine.get_task(task_id)
            task.status = "failed"
            task.result = {"error": str(e)}
            await db.commit()
        except Exception as e2:
            logger.error(f"Failed to update task status: {e2}")
        
        raise HTTPException(
            status_code=500, 
            detail=f"任务执行异常: {str(e)}"
        )


# ========== Event APIs ==========

@router.get("/{assessment_id}/events")
async def list_events(
    assessment_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取流程事件"""
    await require_assessment_permission(db, assessment_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    events = await engine.get_events(assessment_id, limit)
    
    return [
        {
            "id": e.id,
            "assessment_id": e.assessment_id,
            "phase_id": e.phase_id,
            "task_id": e.task_id,
            "event_type": e.event_type,
            "event_data": e.event_data,
            "user_id": e.user_id,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


# ========== 文档上传与跳过 API ==========

UPLOAD_DIR = Path(settings.UPLOAD_DIR) / "assessments"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _extract_text_from_file(file_path: Path) -> str:
    """从文件中提取文本内容（支持 txt、md、pdf、docx）"""
    suffix = file_path.suffix.lower()

    if suffix in (".txt", ".md", ".csv", ".log"):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    if suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(file_path))
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        except ImportError:
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(str(file_path))
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                return text
            except ImportError:
                return ""
        except Exception:
            return ""

    if suffix == ".docx":
        try:
            import docx
            doc = docx.Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return ""
        except Exception:
            return ""

    return ""


@router.post("/tasks/{task_id}/upload")
async def upload_task_document(
    task_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    上传任务文档（如定级报告）

    - 定级报告任务会严格验证文档中的定级信息与项目等级是否一致
    - 不一致时任务标记为 failed
    - 一致时任务标记为 completed
    """
    await require_task_permission(db, task_id, current_user, "evidence:manage")
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 保存文件
    file_ext = Path(file.filename).suffix if file.filename else ""
    unique_name = f"{uuid.uuid4().hex}{file_ext}"
    task_upload_dir = UPLOAD_DIR / str(task.phase_id)
    task_upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = task_upload_dir / unique_name

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # 获取任务所在阶段和测评信息
    phase = await engine.get_phase(task.phase_id)
    if not phase:
        raise HTTPException(status_code=404, detail="阶段不存在")

    assessment = await engine.get_assessment(phase.assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="测评不存在")

    # 提取文档文本内容
    document_content = _extract_text_from_file(file_path)

    # 验证定级信息（如果是定级任务）
    validation_result = None
    if task.task_type == "doc_review" and "定级" in task.name:
        validation_result = await engine.validate_classification_document(
            project_id=assessment.project_id,
            document_content=document_content,
        )

    # 上传文档并完成任务
    result = await engine.upload_task_document(
        task_id=task_id,
        file_path=str(file_path),
        file_name=file.filename or unique_name,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        project_id=assessment.project_id,
        validation_result=validation_result,
    )

    return result


class SkipTaskRequest(BaseModel):
    reason: str = ""


@router.post("/tasks/{task_id}/skip")
async def skip_task(
    task_id: int,
    req: SkipTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    跳过任务

    - 原因字段选填
    - 任务标记为 cancelled
    """
    await require_task_permission(db, task_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status not in ("todo", "in_progress"):
        raise HTTPException(
            status_code=400,
            detail=f"任务状态为 {task.status}，不能跳过",
        )

    try:
        skipped_task = await engine.skip_task(task_id, req.reason)
        return {
            "status": "skipped",
            "task_id": task_id,
            "message": "任务已跳过",
            "reason": req.reason,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class StopTaskRequest(BaseModel):
    reason: str = ""


@router.post("/tasks/{task_id}/stop")
async def stop_task(
    task_id: int,
    req: StopTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    停止任务

    - 原因字段选填
    - 任务标记为 failed
    """
    await require_task_permission(db, task_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != "in_progress":
        raise HTTPException(
            status_code=400,
            detail=f"任务状态为 {task.status}，不能停止",
        )

    try:
        stopped_task = await engine.stop_task(task_id, req.reason)
        return {
            "status": "stopped",
            "task_id": task_id,
            "message": "任务已停止",
            "reason": req.reason,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tasks/{task_id}/reset")
async def reset_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    重置任务（将 failed/cancelled 状态的任务重置为 todo）
    """
    await require_task_permission(db, task_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status not in ("failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"任务状态为 {task.status}，不能重置",
        )

    try:
        reset_task = await engine.reset_task(task_id)
        return {
            "status": "reset",
            "task_id": task_id,
            "message": "任务已重置",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{assessment_id}/restart")
async def restart_assessment(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    重新开始测评（将 completed 状态重置为 not_started）
    同时重置所有阶段和任务
    """
    await require_assessment_permission(db, assessment_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        assessment = await engine.restart_assessment(assessment_id)
        return {
            "status": "restarted",
            "assessment_id": assessment_id,
            "message": "测评已重新开始",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/phases/{phase_id}/restart")
async def restart_phase(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    重新开始阶段（将 completed/skipped 状态重置为 pending）
    同时重置该阶段下所有任务
    """
    await require_phase_permission(db, phase_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        phase = await engine.restart_phase(phase_id)
        return {
            "status": "restarted",
            "phase_id": phase_id,
            "message": "阶段已重新开始",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tasks/{task_id}/project-level")
async def get_task_project_level(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取任务所属项目的等级（用于定级报告上传前提示用户）
    """
    await require_task_permission(db, task_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    phase = await engine.get_phase(task.phase_id)
    if not phase:
        raise HTTPException(status_code=404, detail="阶段不存在")

    assessment = await engine.get_assessment(phase.assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="测评不存在")

    result = await db.execute(
        select(Project).where(Project.id == assessment.project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    return {
        "task_id": task_id,
        "task_name": task.name,
        "task_type": task.task_type,
        "project_id": project.id,
        "project_name": project.name,
        "project_level": project.compliance_level,
        "requires_level_check": task.task_type == "doc_review" and "定级" in task.name,
    }


# ========== 测评完成报告 API ==========

@router.get("/{assessment_id}/summary")
async def get_assessment_summary(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取测评完成摘要（用于完成页面展示）"""
    await require_assessment_permission(db, assessment_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    assessment = await engine.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="测评不存在")
    
    phases = await engine.get_phases(assessment_id)
    
    result = await db.execute(
        select(Project).where(Project.id == assessment.project_id)
    )
    project = result.scalar_one_or_none()
    
    # 统计任务结果
    total_tasks = 0
    completed_tasks = 0
    failed_tasks = 0
    todo_tasks = 0
    task_details = []
    
    for phase in phases:
        tasks = await engine.get_tasks(phase.id)
        for task in tasks:
            total_tasks += 1
            if task.status == "completed":
                completed_tasks += 1
            elif task.status == "failed":
                failed_tasks += 1
            elif task.status == "todo":
                todo_tasks += 1
            task_details.append({
                "phase": phase.name,
                "name": task.name,
                "type": task.task_type,
                "status": task.status,
            })
    
    # 计算分数
    score = await engine._calculate_compliance_score(assessment) if hasattr(engine, '_calculate_compliance_score') else 0
    
    # 确定合规等级
    if score >= 90:
        grade = "优秀"
    elif score >= 75:
        grade = "良好"
    elif score >= 60:
        grade = "一般"
    else:
        grade = "危险"
    
    return {
        "assessment_id": assessment_id,
        "project": {
            "id": project.id if project else None,
            "name": project.name if project else "",
            "level": project.compliance_level.value if project and project.compliance_level else "",
            "score": score,
            "grade": grade,
        },
        "status": assessment.status,
        "progress": assessment.progress,
        "started_at": assessment.started_at.isoformat() if assessment.started_at else None,
        "completed_at": assessment.completed_at.isoformat() if assessment.completed_at else None,
        "phases": [
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "order": p.order,
                "total_tasks": p.total_tasks,
                "completed_tasks": p.completed_tasks,
                "completed_at": p.completed_at.isoformat() if p.completed_at else None,
                "score": await _calculate_phase_score(engine, p),
                "tasks": [
                    {
                        "name": t.name,
                        "type": t.task_type,
                        "status": t.status,
                        "result": t.result,
                    }
                    for t in await engine.get_tasks(p.id)
                ],
            }
            for p in phases
        ],
        "stats": {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "todo_tasks": todo_tasks,
            "completion_rate": round(completed_tasks / total_tasks * 100, 1) if total_tasks > 0 else 0,
        },
    }


async def _calculate_phase_score(engine, phase) -> float:
    """计算阶段分数"""
    tasks = await engine.get_tasks(phase.id)
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == "completed")
    return round((completed / total * 100) if total > 0 else 0, 1)


@router.get("/{assessment_id}/report")
async def get_assessment_report(
    assessment_id: int,
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取测评报告（支持 json 和 pdf 格式）"""
    await require_assessment_permission(db, assessment_id, current_user, "report:export")
    engine = get_flow_engine(db)
    assessment = await engine.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="测评不存在")
    
    if format == "pdf":
        from app.services.report_service import generate_report
        pdf_bytes = await generate_report(
            db=db,
            project_id=assessment.project_id
        )
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=assessment_report.pdf"},
        )
    else:
        from app.services.report_service import generate_json_report
        json_report = await generate_json_report(
            db=db,
            project_id=assessment.project_id
        )
        return json_report
