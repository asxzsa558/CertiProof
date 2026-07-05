from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.core.database import get_db
from app.core.rbac import require_org_permission_for_user_id
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.models.scan_task import ScanTask
from app.models.finding import Finding
from app.models.remediation import RemediationTicket
from app.models.questionnaire import QuestionnaireRecord
from app.models.evidence import Evidence
from app.models.assessment import Assessment, PhaseInstance, TaskInstance, FlowEvent
from app.models.assessment_type import AssessmentType, ProjectAssessment
from app.models.monitoring import ScheduledScan, ScanHistory
from app.models.organization import OrganizationMember
from app.models.context import (
    ConversationHistory, ActionHistory, ResultCache,
    ProjectMemory, ConversationArchive, ConversationThread,
)
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListResponse
from app.services.report_service import generate_report, generate_json_report

router = APIRouter(prefix="/projects", tags=["Projects"])


async def check_org_member(db: AsyncSession, org_id: int, user_id: int, permission: str = "project:read") -> None:
    """检查用户是否属于该组织"""
    await require_org_permission_for_user_id(db, org_id, user_id, permission)


async def get_project_for_user(
    db: AsyncSession,
    project_id: int,
    user_id: int,
    permission: str = "project:read",
) -> Project:
    """获取项目并验证用户有权限访问（通过组织成员关系）"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.organization_id:
        await check_org_member(db, project.organization_id, user_id, permission)
    else:
        # Fallback: old projects without org
        if project.user_id != user_id:
            raise HTTPException(status_code=403, detail="No access to this project")

    return project


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify user is member of organization
    await check_org_member(db, project_data.organization_id, current_user.id, "project:create")

    project = Project(
        user_id=current_user.id,
        organization_id=project_data.organization_id,
        owner_id=current_user.id,
        name=project_data.name,
        system_name=project_data.system_name,
        description=project_data.description,
        compliance_level=project_data.compliance_level,
    )
    db.add(project)
    await db.flush()

    # Create ProjectAssessment records for each assessment type
    if project_data.assessment_type_ids:
        result = await db.execute(
            select(AssessmentType).where(
                AssessmentType.id.in_(project_data.assessment_type_ids),
                AssessmentType.is_active == True,
            )
        )
        assessment_types = result.scalars().all()
        for atype in assessment_types:
            level = None
            if atype.code == "dengbao" and project_data.compliance_level:
                level = project_data.compliance_level.value
            pa = ProjectAssessment(
                project_id=project.id,
                assessment_type_id=atype.id,
                level=level,
                status="not_started",
                progress=0.0,
            )
            db.add(pa)

    await db.commit()
    result = await db.execute(
        select(Project)
        .where(Project.id == project.id)
        .options(selectinload(Project.assessments).selectinload(ProjectAssessment.assessment_type))
    )
    project = result.scalar_one()
    return project


@router.get("/", response_model=List[ProjectListResponse])
async def list_projects(
    organization_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if organization_id:
        # Verify user is member of organization
        await check_org_member(db, organization_id, current_user.id, "project:read")
        result = await db.execute(
            select(Project)
            .where(Project.organization_id == organization_id)
            .order_by(Project.created_at.desc())
        )
    else:
        # Return all projects from all organizations the user belongs to
        org_ids_result = await db.execute(
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == current_user.id)
        )
        org_ids = [row[0] for row in org_ids_result.all()]
        if not org_ids:
            return []
        result = await db.execute(
            select(Project)
            .where(Project.organization_id.in_(org_ids))
            .order_by(Project.created_at.desc())
        )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_project_for_user(db, project_id, current_user.id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project_data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_project_for_user(db, project_id, current_user.id, "project:update")

    # Update fields
    if project_data.name is not None:
        project.name = project_data.name
    if project_data.description is not None:
        project.description = project_data.description
    if project_data.system_name is not None:
        project.system_name = project_data.system_name
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
    project = await get_project_for_user(db, project_id, current_user.id, "project:delete")

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
    await db.execute(delete(ProjectAssessment).where(ProjectAssessment.project_id == project_id))

    # 删除测评流程相关记录
    assessment_ids = await db.execute(
        select(Assessment.id).where(Assessment.project_id == project_id)
    )
    assessment_id_list = [row[0] for row in assessment_ids.all()]

    if assessment_id_list:
        await db.execute(
            delete(FlowEvent).where(FlowEvent.assessment_id.in_(assessment_id_list))
        )
        phase_ids = await db.execute(
            select(PhaseInstance.id).where(PhaseInstance.assessment_id.in_(assessment_id_list))
        )
        phase_id_list = [row[0] for row in phase_ids.all()]
        if phase_id_list:
            await db.execute(
                delete(TaskInstance).where(TaskInstance.phase_id.in_(phase_id_list))
            )
            await db.execute(
                delete(PhaseInstance).where(PhaseInstance.assessment_id.in_(assessment_id_list))
            )
        await db.execute(delete(Assessment).where(Assessment.project_id == project_id))

    # 删除监控相关记录
    scheduled_scan_ids = await db.execute(
        select(ScheduledScan.id).where(ScheduledScan.project_id == project_id)
    )
    scheduled_scan_id_list = [row[0] for row in scheduled_scan_ids.all()]

    if scheduled_scan_id_list:
        await db.execute(
            delete(ScanHistory).where(ScanHistory.scheduled_scan_id.in_(scheduled_scan_id_list))
        )
        await db.execute(delete(ScheduledScan).where(ScheduledScan.project_id == project_id))

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
    await get_project_for_user(db, project_id, current_user.id, "report:export")

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
    await get_project_for_user(db, project_id, current_user.id, "report:export")

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
