"""
等保测评流程管理 API

提供流程模板、测评实例、阶段、任务的 CRUD 和操作接口
"""

import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import Dict, List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings

logger = logging.getLogger(__name__)
MAX_TASK_UPLOAD_SIZE = 100 * 1024 * 1024
from app.models.user import User
from app.models.assessment import FlowTemplate, Assessment, PhaseInstance, TaskInstance, FlowEvent
from app.models.project import Project
from app.models.finding import Finding, Severity, Judgment, JudgmentEngine, FindingStatus
from app.models.remediation import RemediationTicket, RemediationStatus
from app.models.document_knowledge import DocumentAnalysisRun, DocumentFile, DocumentRunFile
from app.services.flow_engine import FlowEngine, get_flow_engine
from app.services.config_service import get_config_service
from app.services.document_pipeline import (
    DocumentExtractionError,
    ARCHIVE_SUFFIXES,
    SUPPORTED_SUFFIXES,
    MAX_BATCH_FILES,
    MAX_BATCH_UNCOMPRESSED,
    create_document_batch_run,
    create_document_run,
    expand_document_upload,
    normalize_analysis_mode,
    safe_document_name,
)
from app.services.file_storage import file_storage
from app.services.upload_validation import read_limited_upload

router = APIRouter(prefix="/assessments", tags=["Assessments"])


async def _read_document_upload(file: UploadFile, max_bytes: int, allowed_suffixes: set[str] | None = None) -> bytes:
    try:
        return await read_limited_upload(file, max_bytes, allowed_suffixes or SUPPORTED_SUFFIXES)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=413 if "超过" in detail else 400, detail=detail) from exc


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


class ExecuteGapTechnicalRequest(BaseModel):
    asset_ids: Optional[List[int]] = None
    credentials: Optional[Dict[str, dict]] = None


BASIC_TECHNICAL_TASK_TYPES = {
    "high_risk_port_scan",
    "basic_vulnerability_scan",
    "basic_baseline_check",
    "basic_weak_password_scan",
    "basic_ssl_tls_scan",
}


def _public_task_result(result: dict | None) -> dict | None:
    if not result or not isinstance(result.get("execution"), dict):
        return result
    execution = {key: value for key, value in result["execution"].items() if key != "credential_envelope"}
    return {**result, "execution": execution}


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
    templates = await engine.upsert_default_templates()
    return {"message": "Default templates upserted", "count": len(templates)}


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
    phase, assessment = await require_phase_permission(db, phase_id, current_user, "assessment:read")
    engine = get_flow_engine(db)
    tasks = await engine.get_tasks(phase_id, official_only=True)
    
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
            result=_public_task_result(t.result),
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
        )
        for t in tasks
    ]


@router.post("/phases/{phase_id}/technical/execute", status_code=status.HTTP_202_ACCEPTED)
async def execute_gap_technical_tasks(
    phase_id: int,
    req: ExecuteGapTechnicalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue all five basic technical checks for the selected project assets."""
    from app.services.asset_scope import list_scannable_assets
    from app.services.assessment_task_queue import queue_assessment_task

    phase, assessment = await require_phase_permission(db, phase_id, current_user, "scan:execute")
    if phase.phase_id != "gap_analysis":
        raise HTTPException(status_code=400, detail="自动基础技术检测仅适用于差距分析阶段")
    assets = await list_scannable_assets(db, assessment.project_id)
    requested_ids = set(req.asset_ids or [])
    if requested_ids:
        assets = [asset for asset in assets if asset.id in requested_ids]
        if {asset.id for asset in assets} != requested_ids:
            raise HTTPException(status_code=400, detail="选择的资产包含非当前项目或已停用资产")
    if not assets:
        raise HTTPException(status_code=400, detail="当前项目没有可执行检测的启用资产")

    engine = get_flow_engine(db)
    tasks = [
        task for task in await engine.get_tasks(phase_id, official_only=True)
        if task.task_type in BASIC_TECHNICAL_TASK_TYPES
    ]
    queued, running = [], []
    credentials = {
        asset.value: {
            key: value for key, value in (req.credentials or {}).get(asset.value, {}).items()
            if key in {"username", "password", "key_file"} and value
        }
        for asset in assets
    }
    credentials = {target: value for target, value in credentials.items() if value}
    for task in tasks:
        if task.status == "in_progress":
            running.append(task.id)
            continue
        if task.status != "todo":
            await engine.reset_task(task.id)
        task = await engine.start_task(task.id)
        await queue_assessment_task(
            task,
            [asset.id for asset in assets],
            current_user.id,
            db,
            credentials if task.task_type == "basic_baseline_check" else None,
        )
        queued.append(task.id)
    return {
        "status": "queued",
        "queued_task_ids": queued,
        "already_running_task_ids": running,
        "asset_count": len(assets),
        "credential_asset_count": len(credentials),
        "message": f"已为 {len(assets)} 个资产提交 {len(queued)} 项基础技术检测",
    }


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
        "result": _public_task_result(task.result),
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
    from app.services.asset_scope import list_scannable_assets
    from app.services.assessment_task_queue import queue_assessment_task
    
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
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # 获取任务所属的阶段和评估
    phase = await engine.get_phase(task.phase_id)
    assessment = await engine.get_assessment(phase.assessment_id)
    
    # 检查任务是否可以自动执行
    executor = get_task_executor(db)
    assets = []
    if executor.is_automated_task(task.task_type):
        assets = await list_scannable_assets(db, assessment.project_id)
        if not assets:
            raise HTTPException(status_code=400, detail="当前项目没有启用资产，无法执行技术检测")

    try:
        task = await engine.start_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if assets:
        await queue_assessment_task(task, [asset.id for asset in assets], current_user.id, db)
        return {"message": "技术检测已加入持久化队列", "task_id": task_id, "status": "queued"}
    return {"message": "Task started", "task_id": task_id, "status": task.status}


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
        targets = list(dict.fromkeys(req.targets))
    elif req.target:
        targets = [req.target]
    else:
        raise HTTPException(status_code=400, detail="请指定目标地址")
    
    phase = await engine.get_phase(task.phase_id)
    assessment = await engine.get_assessment(phase.assessment_id)
    from app.services.asset_scope import require_scannable_target
    try:
        for target in targets:
            await require_scannable_target(db, assessment.project_id, target)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    try:
        if task.status != "todo":
            await engine.reset_task(task_id)
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
            from app.core.database import AsyncSessionLocal

            async def execute_target(target):
                target_params = dict(req.params or {})
                if req.credentials and target in req.credentials:
                    target_params.update(req.credentials[target])
                async with AsyncSessionLocal() as target_db:
                    return await get_task_executor(target_db).execute_task(
                        task_type=task.task_type,
                        target=target,
                        project_id=assessment.project_id,
                        user_id=current_user.id,
                        params=target_params,
                    )

            semaphore = asyncio.Semaphore(max(1, min(settings.ASSESSMENT_MAX_CONCURRENT, 10)))
            tasks_list = []

            for target in targets:
                async def limited_execute(value=target):
                    async with semaphore:
                        return await execute_target(value)
                tasks_list.append(limited_execute())
            results = await asyncio.gather(*tasks_list, return_exceptions=True)
            
            # 汇总结果
            asset_results = {}
            all_failed = []
            all_completed = []
            all_warnings = []
            
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
                    elif result["status"] == "partial":
                        all_completed.append({"target": target, **result})
                        all_warnings.append({"target": target, **result})
                    else:
                        all_completed.append({"target": target, **result})
            
            result = {
                "status": "completed" if not all_failed and not all_warnings else ("partial" if all_completed else "failed"),
                "task_type": task.task_type,
                "asset_results": asset_results,
                "completed": all_completed,
                "failed": all_failed,
                "warnings": all_warnings,
            }
        
        # 更新任务状态
        if result["status"] in ["completed", "partial"]:
            await engine.complete_task(task_id, result)
            return {
                "message": "任务部分完成，存在无法检测项" if result["status"] == "partial" else "任务执行完成",
                "status": result["status"],
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

async def _resolve_document_analysis_mode(db: AsyncSession, mode: str | None) -> str:
    if not mode or mode == "default":
        mode = await get_config_service(db).get("document.analysis_mode", settings.DOCUMENT_ANALYSIS_MODE)
    return normalize_analysis_mode(mode)


@router.post("/phases/{phase_id}/documents/batch", status_code=status.HTTP_202_ACCEPTED)
async def upload_phase_documents(
    phase_id: int,
    files: List[UploadFile] = File(...),
    analysis_mode: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload documents or a supported archive, classify them, then run matching checks."""
    phase, assessment = await require_phase_permission(db, phase_id, current_user, "evidence:manage")
    if phase.phase_id != "gap_analysis":
        raise HTTPException(status_code=400, detail="批量文档归类仅适用于差距分析阶段")
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件或压缩包")
    document_tasks = [
        task for task in await get_flow_engine(db).get_tasks(phase_id, official_only=True)
        if task.task_type == "doc_review"
    ]
    if not document_tasks:
        raise HTTPException(status_code=400, detail="当前阶段没有文档检查任务")
    if any(task.status == "in_progress" for task in document_tasks):
        raise HTTPException(status_code=409, detail="已有文档正在分析，请等待完成后再批量上传")

    configured_mode = await _resolve_document_analysis_mode(db, analysis_mode)
    expanded: list[tuple[str, bytes]] = []
    skipped_files: list[str] = []
    total_size = 0
    try:
        for file in files:
            file_name = safe_document_name(file.filename or "document")
            suffix = Path(file_name).suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES | ARCHIVE_SUFFIXES:
                skipped_files.append(file_name)
                continue
            content = await _read_document_upload(file, MAX_TASK_UPLOAD_SIZE, SUPPORTED_SUFFIXES | ARCHIVE_SUFFIXES)
            documents, skipped = expand_document_upload(file_name, content)
            expanded.extend(documents)
            skipped_files.extend(skipped)
            total_size += sum(len(item[1]) for item in documents)
            if len(expanded) > MAX_BATCH_FILES or total_size > MAX_BATCH_UNCOMPRESSED:
                raise DocumentExtractionError(f"单次最多处理 {MAX_BATCH_FILES} 个文档，解压后总计不超过 300MB。")
        if not expanded:
            raise DocumentExtractionError("上传内容中没有可分析的 DOCX、PDF、TXT、MD 或图片文档。")
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document_file_ids: list[int] = []
    saved_files: list[dict] = []
    duplicate_files: list[dict] = []
    for file_name, content in expanded:
        file_path, digest, file_size = await file_storage.save_file(assessment.project_id, file_name, content)
        duplicate = (await db.execute(
            select(DocumentFile).where(
                DocumentFile.assessment_id == assessment.id,
                DocumentFile.sha256 == digest,
                DocumentFile.is_active.is_(True),
            ).limit(1)
        )).scalar_one_or_none()
        if duplicate:
            await file_storage.delete_file(file_path)
            document_file_ids.append(duplicate.id)
            duplicate_files.append({"id": duplicate.id, "file_name": duplicate.original_name})
            continue
        document_file = DocumentFile(
            project_id=assessment.project_id,
            assessment_id=assessment.id,
            task_id=None,
            uploaded_in_run_id=None,
            original_name=file_name,
            storage_path=file_path,
            mime_type=mimetypes.guess_type(file_name)[0] or "application/octet-stream",
            size_bytes=file_size,
            sha256=digest,
            parse_status="queued",
        )
        db.add(document_file)
        await db.flush()
        document_file_ids.append(document_file.id)
        saved_files.append({"id": document_file.id, "file_name": file_name})
    await db.commit()
    run = await create_document_batch_run(
        db,
        phase.id,
        assessment.project_id,
        list(dict.fromkeys(document_file_ids)),
        current_user.id,
        configured_mode,
        skipped_files,
        duplicate_files,
    )
    return {
        "status": "queued",
        "run_id": run.id,
        "analysis_mode": configured_mode,
        "files": saved_files,
        "duplicates": duplicate_files,
        "skipped_files": skipped_files,
    }


@router.get("/phases/{phase_id}/documents/batch/latest")
async def get_latest_phase_document_batch(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    phase, assessment = await require_phase_permission(db, phase_id, current_user, "assessment:read")
    run = (await db.execute(
        select(DocumentAnalysisRun)
        .where(
            DocumentAnalysisRun.assessment_id == assessment.id,
            DocumentAnalysisRun.phase_id == phase.id,
            DocumentAnalysisRun.run_kind == "batch",
        )
        .order_by(DocumentAnalysisRun.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if not run:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "progress": run.progress,
        "error": run.error_message,
        "result": run.result_summary,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


@router.post("/tasks/{task_id}/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_task_documents(
    task_id: int,
    files: List[UploadFile] = File(...),
    analysis_mode: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存一个或多个文档证据，并排队执行聚合合规分析。"""
    task, _, assessment = await require_task_permission(db, task_id, current_user, "evidence:manage")
    if task.status == "in_progress":
        raise HTTPException(status_code=409, detail="文档正在分析，请等待完成后再上传")
    if task.task_type != "doc_review" or "文档检查：" not in task.name:
        raise HTTPException(status_code=400, detail="该任务不是文档合规检查任务")
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")

    configured_mode = await _resolve_document_analysis_mode(db, analysis_mode)

    saved = []
    for file in files:
        file_name = safe_document_name(file.filename or "document")
        suffix = Path(file_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            detail = "暂不支持旧版 DOC，请转换为 DOCX 或 PDF" if suffix == ".doc" else f"不支持的文件格式：{suffix or '未知'}"
            raise HTTPException(status_code=415, detail=detail)
        content = await _read_document_upload(file, MAX_TASK_UPLOAD_SIZE)

        file_path, digest, file_size = await file_storage.save_file(assessment.project_id, file_name, content)
        duplicate = (await db.execute(
            select(DocumentFile).where(
                DocumentFile.assessment_id == assessment.id,
                DocumentFile.task_id == task.id,
                DocumentFile.sha256 == digest,
                DocumentFile.is_active.is_(True),
            )
        )).scalar_one_or_none()
        if duplicate:
            await file_storage.delete_file(file_path)
            saved.append({"id": duplicate.id, "file_name": duplicate.original_name, "duplicate": True})
            continue

        document_file = DocumentFile(
            project_id=assessment.project_id,
            assessment_id=assessment.id,
            task_id=task.id,
            uploaded_in_run_id=None,
            original_name=file_name,
            storage_path=file_path,
            mime_type=file.content_type or "application/octet-stream",
            size_bytes=file_size,
            sha256=digest,
            parse_status="queued",
        )
        db.add(document_file)
        await db.flush()
        saved.append({"id": document_file.id, "file_name": file_name, "duplicate": False})

    await db.commit()
    run = await create_document_run(db, task, assessment.project_id, current_user.id, configured_mode)
    return {"status": "queued", "task_id": task.id, "run_id": run.id, "analysis_mode": configured_mode, "files": saved}


@router.get("/tasks/{task_id}/documents")
async def list_task_documents(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task, _, assessment = await require_task_permission(db, task_id, current_user, "assessment:read")
    documents = (await db.execute(
        select(DocumentFile)
        .where(
            DocumentFile.assessment_id == assessment.id,
            DocumentFile.task_id == task.id,
            DocumentFile.is_active.is_(True),
        )
        .order_by(DocumentFile.created_at)
    )).scalars().all()
    return [{
        "id": document.id,
        "file_name": document.original_name,
        "file_size": document.size_bytes,
        "mime_type": document.mime_type,
        "hash_sha256": document.sha256,
        "parse_status": document.parse_status,
        "classification": document.classification,
        "created_at": document.created_at,
        "extraction": document.extraction_summary,
    } for document in documents]


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = await db.get(DocumentFile, document_id)
    if not document or not document.is_active:
        raise HTTPException(status_code=404, detail="文档不存在")
    await require_project_permission(db, document.project_id, current_user, "assessment:read")
    content = await file_storage.read_file(document.storage_path)
    if content is None:
        raise HTTPException(status_code=404, detail="原始文档文件已丢失")
    return Response(
        content=content,
        media_type=document.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(Path(document.original_name).name)}"},
    )


@router.delete("/tasks/{task_id}/documents/{evidence_id}")
async def delete_task_document(
    task_id: int,
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task, _, assessment = await require_task_permission(db, task_id, current_user, "evidence:manage")
    if task.status == "in_progress":
        raise HTTPException(status_code=409, detail="文档正在分析，请等待完成后再删除")
    document = (await db.execute(
        select(DocumentFile).where(
            DocumentFile.id == evidence_id,
            DocumentFile.assessment_id == assessment.id,
            DocumentFile.task_id == task.id,
            DocumentFile.is_active.is_(True),
        )
    )).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    active_run = (await db.execute(
        select(DocumentAnalysisRun.id)
        .join(DocumentRunFile, DocumentRunFile.analysis_run_id == DocumentAnalysisRun.id)
        .where(
            DocumentRunFile.document_file_id == document.id,
            DocumentAnalysisRun.status.in_(["queued", "running"]),
        ).limit(1)
    )).scalar_one_or_none()
    if active_run:
        raise HTTPException(status_code=409, detail="文档仍在分析中，请等待任务结束后删除")
    await file_storage.delete_file(document.storage_path)
    from app.services.knowledge_graph import knowledge_graph
    await knowledge_graph.purge_file(db, document.id)
    await db.delete(document)
    await db.commit()

    remaining = (await db.execute(
        select(DocumentFile.id).where(
            DocumentFile.assessment_id == assessment.id,
            DocumentFile.task_id == task.id,
            DocumentFile.is_active.is_(True),
        )
    )).scalars().all()
    if remaining:
        previous_mode = (task.result or {}).get("analysis_mode")
        configured_mode = await _resolve_document_analysis_mode(db, previous_mode)
        run = await create_document_run(db, task, assessment.project_id, current_user.id, configured_mode)
        return {"status": "queued", "run_id": run.id, "analysis_mode": configured_mode}

    await get_flow_engine(db).reset_task(task.id)
    return {"status": "empty"}


@router.post("/tasks/{task_id}/documents/analyze", status_code=status.HTTP_202_ACCEPTED)
async def reanalyze_task_documents(
    task_id: int,
    analysis_mode: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task, _, assessment = await require_task_permission(db, task_id, current_user, "evidence:manage")
    has_files = (await db.execute(
        select(DocumentFile.id).where(
            DocumentFile.assessment_id == assessment.id,
            DocumentFile.task_id == task.id,
            DocumentFile.is_active.is_(True),
        ).limit(1)
    )).scalar_one_or_none()
    if not has_files:
        raise HTTPException(status_code=400, detail="该任务尚未上传文档")
    configured_mode = await _resolve_document_analysis_mode(db, analysis_mode)
    run = await create_document_run(db, task, assessment.project_id, current_user.id, configured_mode)
    return {"status": "queued", "run_id": run.id, "analysis_mode": configured_mode}


@router.get("/document-runs/{run_id}")
async def get_document_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await db.get(DocumentAnalysisRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="文档分析任务不存在")
    await require_project_permission(db, run.project_id, current_user, "assessment:read")
    return {
        "id": run.id,
        "status": run.status,
        "progress": run.progress,
        "error": run.error_message,
        "result": run.result_summary,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


async def _sync_document_gap_findings(
    db: AsyncSession,
    project_id: int,
    task: TaskInstance,
    analysis: dict,
    user_id: int,
) -> dict:
    if (
        not analysis
        or analysis.get("type") != "document_control_analysis"
    ):
        return {"created_or_updated": 0, "scan_task_id": None}

    from app.models.document_knowledge import DocumentAnalysisRun

    document_run = await db.get(DocumentAnalysisRun, analysis.get("run_id")) if analysis.get("run_id") else None
    if not document_run:
        raise ValueError("文档差距结果缺少有效的分析运行记录")
    if analysis.get("status") == "unable":
        return {
            "created_or_updated": 0,
            "fixed": 0,
            "document_run_id": document_run.id,
            "skipped": True,
            "reason": "分析结果为无法判断，未变更问题和整改状态",
        }

    failed_clause_ids = set()
    passed_clause_ids = set()
    changed = 0
    for control in analysis.get("controls", []):
        for point in control.get("points", []):
            clause_id = f"DOC-TASK-{task.id}-{control.get('id')}-{point.get('id')}"
            if point.get("status") == "pass":
                passed_clause_ids.add(clause_id)
                continue
            if point.get("status") not in {"fail", "partial"}:
                continue

            failed_clause_ids.add(clause_id)
            result = await db.execute(
                select(Finding).where(Finding.project_id == project_id, Finding.clause_id == clause_id)
            )
            finding = result.scalar_one_or_none()
            is_partial = point.get("status") == "partial"
            reason = point.get("llm_reason") or point.get("missing_judgement") or point.get("text") or "证据不足"
            description = (
                f"{analysis.get('document_name') or task.name}："
                f"{'证据不完整，' if is_partial else ''}{reason}"
            )
            suggestion = point.get("remediation") or f"补充“{point.get('text')}”相关制度描述，并在文档中保留可审计证据。"
            evidence_ids = sorted({
                item.get("block_id") for item in point.get("evidence", []) if item.get("block_id")
            })

            if finding:
                finding.scan_task_id = None
                finding.document_run_id = document_run.id
                finding.description = description
                finding.remediation_suggestion = suggestion
                finding.confidence = analysis.get("confidence")
                finding.judgment = Judgment.PARTIAL if is_partial else Judgment.FAIL
                finding.judgment_engine = JudgmentEngine.HYBRID if analysis.get("evidence_engine") == "hybrid" else JudgmentEngine.RULE
                finding.severity = Severity(point.get("severity", "medium"))
                finding.evidence_ids = evidence_ids
                if finding.status == FindingStatus.RESOLVED:
                    finding.status = FindingStatus.OPEN
                    finding.resolved_at = None
            else:
                finding = Finding(
                    project_id=project_id,
                    scan_task_id=None,
                    document_run_id=document_run.id,
                    clause_id=clause_id,
                    clause_name=control.get("title") or analysis.get("document_name"),
                    severity=Severity(point.get("severity", "medium")),
                    judgment=Judgment.PARTIAL if is_partial else Judgment.FAIL,
                    judgment_engine=JudgmentEngine.HYBRID if analysis.get("evidence_engine") == "hybrid" else JudgmentEngine.RULE,
                    confidence=analysis.get("confidence"),
                    description=description,
                    remediation_suggestion=suggestion,
                    status=FindingStatus.OPEN,
                    evidence_ids=evidence_ids,
                )
                db.add(finding)
                await db.flush()

            result = await db.execute(
                select(RemediationTicket).where(RemediationTicket.finding_id == finding.id)
            )
            ticket = result.scalar_one_or_none()
            if ticket:
                ticket.title = description[:500]
                ticket.description = description
                ticket.remediation_plan = suggestion
                if ticket.status in (
                    RemediationStatus.RESOLVED,
                    RemediationStatus.VERIFIED,
                    RemediationStatus.CLOSED,
                ):
                    ticket.status = RemediationStatus.OPEN
                    ticket.resolved_at = None
                    ticket.verified_at = None
                    ticket.resolution_notes = "复测再次发现该缺失项，已重新打开。"
            else:
                db.add(RemediationTicket(
                    finding_id=finding.id,
                    project_id=project_id,
                    title=description[:500],
                    description=description,
                    remediation_plan=suggestion,
                    priority="medium",
                    assigned_by=user_id,
                    status=RemediationStatus.OPEN,
                ))
            changed += 1

    fixed = 0
    existing_result = await db.execute(
        select(Finding).where(
            Finding.project_id == project_id,
            Finding.clause_id.like(f"DOC-TASK-{task.id}-%"),
        )
    )
    for finding in existing_result.scalars().all():
        if finding.clause_id not in passed_clause_ids:
            continue
        if finding.status != FindingStatus.RESOLVED:
            finding.status = FindingStatus.RESOLVED
            finding.resolved_at = datetime.utcnow()

        ticket_result = await db.execute(
            select(RemediationTicket).where(RemediationTicket.finding_id == finding.id)
        )
        ticket = ticket_result.scalar_one_or_none()
        if ticket and ticket.status not in (RemediationStatus.CLOSED, RemediationStatus.SKIPPED):
            ticket.status = RemediationStatus.RESOLVED
            ticket.resolved_at = ticket.resolved_at or datetime.utcnow()
            ticket.resolution_notes = ticket.resolution_notes or "文档复测未再发现该缺失项。"
        fixed += 1

    summary = dict(document_run.result_summary or {})
    summary["findings_count"] = len(failed_clause_ids)
    document_run.result_summary = summary
    await db.commit()
    return {
        "created_or_updated": changed,
        "fixed": fixed,
        "document_run_id": document_run.id,
    }


class SkipTaskRequest(BaseModel):
    reason: str = ""


class RestartRequest(BaseModel):
    mode: str = "reset"


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
    重置任务（清空结果并回到 todo；正在执行中的任务需先停止）
    """
    await require_task_permission(db, task_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status == "in_progress":
        raise HTTPException(
            status_code=400,
            detail="任务正在执行中，请先停止后再重置",
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
    req: Optional[RestartRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    继续或重置测评。mode=continue 保留流程结果，mode=reset 重置阶段、任务和测评产物。
    """
    await require_assessment_permission(db, assessment_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        mode = (req.mode if req else "reset")
        assessment = await engine.restart_assessment(assessment_id, mode=mode)
        reset = mode != "continue"
        return {
            "status": "reset" if reset else "reopened",
            "assessment_id": assessment_id,
            "message": "测评进度、问题、证据和整改队列已完全重置" if reset else "测评已重新打开，历史结果和证据已保留",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/phases/{phase_id}/restart")
async def restart_phase(
    phase_id: int,
    req: Optional[RestartRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    继续或重置阶段。mode=continue 保留任务结果，mode=reset 重置本阶段任务进度。
    """
    await require_phase_permission(db, phase_id, current_user, "assessment:manage")
    engine = get_flow_engine(db)
    
    try:
        mode = (req.mode if req else "reset")
        phase = await engine.restart_phase(phase_id, mode=mode)
        reset = mode != "continue"
        return {
            "status": "reset" if reset else "reopened",
            "phase_id": phase_id,
            "message": "阶段进度已重置" if reset else "阶段已重新打开，历史结果和证据已保留",
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
        tasks = await engine.get_tasks(phase.id, official_only=True)
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
                    for t in await engine.get_tasks(p.id, official_only=True)
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
    tasks = await engine.get_tasks(phase.id, official_only=True)
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == "completed")
    return round((completed / total * 100) if total > 0 else 0, 1)


@router.get("/{assessment_id}/report")
async def get_assessment_report(
    assessment_id: int,
    format: str = "html",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取测评报告（HTML 为主，兼容 json）"""
    await require_assessment_permission(db, assessment_id, current_user, "report:export")
    engine = get_flow_engine(db)
    assessment = await engine.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="测评不存在")
    
    if format == "json":
        from app.services.report_service import generate_json_report
        return await generate_json_report(db=db, project_id=assessment.project_id)

    from app.services.report_service import generate_html_report
    return Response(
        content=await generate_html_report(db=db, project_id=assessment.project_id),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=assessment_report.html"},
    )
