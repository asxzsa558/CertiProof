"""
问卷管理 API
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.questionnaire import QuestionnaireRecord
from app.services.questionnaire_engine import QuestionnaireEngine

router = APIRouter(prefix="/questionnaires", tags=["Questionnaires"])


# ========== Request/Response Models ==========

class CreateQuestionnaireRequest(BaseModel):
    project_id: int
    clause_id: str
    level: int = 3


class QuestionnaireResponse(BaseModel):
    id: int
    project_id: int
    clause_id: str
    clause_name: str
    questions: list
    answers: Optional[list] = None
    evaluation: Optional[dict] = None
    status: str
    created_at: str
    completed_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class SubmitAnswersRequest(BaseModel):
    answers: List[dict]


class QuestionnaireSummaryResponse(BaseModel):
    total: int
    pending: int
    completed: int
    evaluated: int
    passed: int
    failed: int
    average_score: float


# ========== API Endpoints ==========

@router.post("/", response_model=QuestionnaireResponse)
async def create_questionnaire(
    req: CreateQuestionnaireRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建问卷"""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, req.project_id, current_user.id, "assessment:manage")

    engine = QuestionnaireEngine(db)
    
    record = await engine.create_questionnaire_record(
        project_id=req.project_id,
        clause_id=req.clause_id,
        level=req.level,
        user_id=current_user.id,
    )
    
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clause {req.clause_id} not found or not a questionnaire type"
        )
    
    return QuestionnaireResponse(
        id=record.id,
        project_id=record.project_id,
        clause_id=record.clause_id,
        clause_name=record.clause_name,
        questions=record.questions,
        answers=record.answers,
        evaluation=record.evaluation,
        status=record.status,
        created_at=record.created_at.isoformat(),
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
    )


@router.get("/{record_id}", response_model=QuestionnaireResponse)
async def get_questionnaire(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取问卷详情"""
    engine = QuestionnaireEngine(db)
    record = await engine.get_questionnaire_record(record_id)
    
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Questionnaire not found"
        )
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, record.project_id, current_user.id, "assessment:read")
    
    return QuestionnaireResponse(
        id=record.id,
        project_id=record.project_id,
        clause_id=record.clause_id,
        clause_name=record.clause_name,
        questions=record.questions,
        answers=record.answers,
        evaluation=record.evaluation,
        status=record.status,
        created_at=record.created_at.isoformat(),
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
    )


@router.post("/{record_id}/submit", response_model=QuestionnaireResponse)
async def submit_answers(
    record_id: int,
    req: SubmitAnswersRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交问卷答案"""
    engine = QuestionnaireEngine(db)
    record = await engine.get_questionnaire_record(record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Questionnaire not found"
        )
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, record.project_id, current_user.id, "assessment:manage")

    record = await engine.submit_answers(record_id, req.answers)
    
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Questionnaire not found"
        )
    
    return QuestionnaireResponse(
        id=record.id,
        project_id=record.project_id,
        clause_id=record.clause_id,
        clause_name=record.clause_name,
        questions=record.questions,
        answers=record.answers,
        evaluation=record.evaluation,
        status=record.status,
        created_at=record.created_at.isoformat(),
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
    )


@router.post("/{record_id}/evaluate", response_model=dict)
async def evaluate_questionnaire(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """评估问卷答案"""
    engine = QuestionnaireEngine(db)
    record = await engine.get_questionnaire_record(record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Questionnaire not found"
        )
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, record.project_id, current_user.id, "assessment:manage")
    
    evaluation = await engine.evaluate_answers(record_id)
    
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Questionnaire not found or no answers submitted"
        )
    
    return evaluation


@router.get("/project/{project_id}/list", response_model=List[QuestionnaireResponse])
async def list_project_questionnaires(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出项目的所有问卷"""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:read")

    engine = QuestionnaireEngine(db)
    records = await engine.list_questionnaire_records(project_id)
    
    return [
        QuestionnaireResponse(
            id=record.id,
            project_id=record.project_id,
            clause_id=record.clause_id,
            clause_name=record.clause_name,
            questions=record.questions,
            answers=record.answers,
            evaluation=record.evaluation,
            status=record.status,
            created_at=record.created_at.isoformat(),
            completed_at=record.completed_at.isoformat() if record.completed_at else None,
        )
        for record in records
    ]


@router.get("/project/{project_id}/summary", response_model=QuestionnaireSummaryResponse)
async def get_project_summary(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目问卷汇总"""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:read")

    engine = QuestionnaireEngine(db)
    summary = await engine.get_project_questionnaire_summary(project_id)
    
    return QuestionnaireSummaryResponse(**summary)
