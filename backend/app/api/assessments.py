"""
等保测评流程管理 API

提供流程模板、测评实例、阶段、任务的 CRUD 和操作接口
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.assessment import FlowTemplate, Assessment, PhaseInstance, TaskInstance, FlowEvent
from app.services.flow_engine import FlowEngine, get_flow_engine
from app.services.assessment_templates import LEVEL_2_TEMPLATE, LEVEL_3_TEMPLATE

router = APIRouter(prefix="/assessments", tags=["Assessments"])


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
    engine = get_flow_engine(db)
    
    try:
        await engine.skip_phase(phase_id, req.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Phase skipped"}


# ========== Task APIs ==========

@router.get("/phases/{phase_id}/tasks", response_model=List[TaskResponse])
async def list_tasks(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出阶段的所有任务"""
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


@router.post("/tasks/{task_id}/start")
async def start_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开始任务"""
    engine = get_flow_engine(db)
    
    try:
        await engine.start_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Task started"}


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: int,
    req: CompleteTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成任务"""
    engine = get_flow_engine(db)
    
    try:
        await engine.complete_task(task_id, req.result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Task completed"}


# ========== Event APIs ==========

@router.get("/{assessment_id}/events")
async def list_events(
    assessment_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取流程事件"""
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
