from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.models.scan_task import ScanTask
from app.models.finding import Finding
from app.models.remediation import RemediationTicket
from app.models.questionnaire import QuestionnaireRecord
from app.models.evidence import Evidence
from app.models.context import (
    ConversationHistory, ActionHistory, ResultCache,
    ProjectMemory, ConversationArchive, ConversationThread,
)
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListResponse
from app.services.report_service import generate_report, generate_json_report

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(
        user_id=current_user.id,
        name=project_data.name,
        description=project_data.description,
        compliance_level=project_data.compliance_level,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/", response_model=List[ProjectListResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).where(Project.user_id == current_user.id).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project_data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Update fields
    if project_data.name is not None:
        project.name = project_data.name
    if project_data.description is not None:
        project.description = project_data.description
    if project_data.status is not None:
        project.status = project_data.status
    
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    await db.execute(delete(RemediationTicket).where(RemediationTicket.project_id == project_id))
    await db.execute(delete(Evidence).where(Evidence.project_id == project_id))
    await db.execute(
        delete(Evidence).where(
            Evidence.finding_id.in_(
                select(Finding.id).where(Finding.project_id == project_id)
            )
        )
    )
    await db.execute(
        delete(Evidence).where(
            Evidence.questionnaire_record_id.in_(
                select(QuestionnaireRecord.id).where(QuestionnaireRecord.project_id == project_id)
            )
        )
    )
    await db.execute(delete(QuestionnaireRecord).where(QuestionnaireRecord.project_id == project_id))
    await db.execute(delete(Finding).where(Finding.project_id == project_id))
    await db.execute(delete(ScanTask).where(ScanTask.project_id == project_id))
    await db.execute(delete(Asset).where(Asset.project_id == project_id))

    await db.execute(delete(ProjectMemory).where(ProjectMemory.project_id == project_id))
    await db.execute(delete(ActionHistory).where(ActionHistory.project_id == project_id))
    await db.execute(delete(ResultCache).where(ResultCache.project_id == project_id))

    await db.execute(
        delete(ConversationHistory).where(ConversationHistory.project_id == project_id)
    )
    await db.execute(
        delete(ConversationArchive).where(ConversationArchive.project_id == project_id)
    )
    await db.execute(
        delete(ConversationThread).where(ConversationThread.project_id == project_id)
    )

    await db.delete(project)
    await db.commit()
    return None


@router.get("/{project_id}/report")
async def download_report(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate and download PDF compliance report."""
    # Verify project access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    try:
        pdf_buffer = await generate_report(db, project_id)
        pdf_data = pdf_buffer.getvalue()
        
        from fastapi.responses import Response
        return Response(
            content=pdf_data,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=verisure_report_{project_id}.pdf"
            }
        )
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Report generation error: {error_detail}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )


@router.get("/{project_id}/report/json")
async def download_json_report(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate and download JSON compliance report."""
    # Verify project access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    try:
        report_data = await generate_json_report(db, project_id)
        
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=report_data,
            headers={
                "Content-Disposition": f"attachment; filename=verisure_report_{project_id}.json"
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )
