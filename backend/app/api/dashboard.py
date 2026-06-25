from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.models.assessment_type import ProjectAssessment, AssessmentType
from app.models.organization import OrganizationMember
from app.schemas.dashboard import (
    DashboardResponse,
    DashboardProject,
    DashboardAssessmentType,
    DashboardSummary,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def check_org_member(db: AsyncSession, org_id: int, user_id: int) -> None:
    """检查用户是否属于该组织"""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )


async def resolve_organization_id(
    db: AsyncSession, organization_id: Optional[int], user_id: int
) -> int:
    """解析 organization_id。如果未提供，则取该用户最早加入的组织。

    安全说明：
    - 严格限定在 current_user 的 memberships 中查找
    - 即使 logic 有 bug，check_org_member 也会兜底验证
    - 不会返回其他用户的数据
    """
    if organization_id is not None:
        return organization_id

    result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.user_id == user_id)
        .order_by(OrganizationMember.joined_at.asc())
        .limit(1)
    )
    first = result.scalar_one_or_none()
    if not first:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No organization found for this user. Please contact administrator.",
        )
    return first.organization_id


@router.get("/overview", response_model=DashboardResponse)
async def get_dashboard_overview(
    organization_id: Optional[int] = Query(
        None,
        description="组织ID（可选）。未提供时自动使用当前用户的默认组织。",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取组织的 Dashboard 总览数据

    安全：
    - organization_id 可选。未提供时自动取 current_user 最早的 membership
    - check_org_member 强制验证 current_user 属于该 org
    - current_user 来自 JWT，是可信身份标识
    """
    org_id = await resolve_organization_id(db, organization_id, current_user.id)
    await check_org_member(db, org_id, current_user.id)

    # Get all projects in this organization
    proj_result = await db.execute(
        select(Project)
        .where(Project.organization_id == org_id)
        .order_by(Project.updated_at.desc())
    )
    projects = proj_result.scalars().all()

    # Build project cards
    project_cards: List[DashboardProject] = []
    total_score_sum = 0.0
    score_count = 0
    in_progress_count = 0
    completed_count = 0
    not_started_count = 0

    for proj in projects:
        # Get assessment types for this project
        pa_result = await db.execute(
            select(ProjectAssessment, AssessmentType)
            .join(AssessmentType, AssessmentType.id == ProjectAssessment.assessment_type_id)
            .where(ProjectAssessment.project_id == proj.id)
        )
        assessment_data = []
        overall_score_sum = 0.0
        overall_score_count = 0
        for pa, atype in pa_result.all():
            assessment_data.append(DashboardAssessmentType(
                code=atype.code,
                name=atype.name,
                level=pa.level,
                status=pa.status,
                score=pa.score,
                progress=pa.progress,
            ))
            if pa.score is not None:
                overall_score_sum += pa.score
                overall_score_count += 1

        overall_score = overall_score_sum / overall_score_count if overall_score_count > 0 else None

        # Determine overall status
        statuses = [a.status for a in assessment_data]
        if not statuses or all(s == "not_started" for s in statuses):
            overall_status = "not_started"
            not_started_count += 1
        elif any(s == "in_progress" for s in statuses):
            overall_status = "in_progress"
            in_progress_count += 1
        elif all(s == "completed" for s in statuses):
            overall_status = "completed"
            completed_count += 1
        else:
            overall_status = "in_progress"
            in_progress_count += 1

        # Get asset count
        asset_count_result = await db.execute(
            select(func.count(Asset.id)).where(Asset.project_id == proj.id)
        )
        asset_count = asset_count_result.scalar() or 0

        if overall_score is not None:
            total_score_sum += overall_score
            score_count += 1

        project_cards.append(DashboardProject(
            id=proj.id,
            name=proj.name,
            system_name=proj.system_name,
            description=proj.description,
            assessment_types=assessment_data,
            asset_count=asset_count,
            overall_score=overall_score,
            overall_status=overall_status,
            updated_at=proj.updated_at,
        ))

    avg_score = total_score_sum / score_count if score_count > 0 else 0.0

    summary = DashboardSummary(
        total=len(projects),
        in_progress=in_progress_count,
        completed=completed_count,
        not_started=not_started_count,
        avg_score=round(avg_score, 1),
    )

    return DashboardResponse(
        summary=summary,
        projects=project_cards,
        generated_at=datetime.utcnow(),
    )


@router.get("/assessment-types")
async def get_available_assessment_types(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有可用的测评类型"""
    result = await db.execute(
        select(AssessmentType).where(AssessmentType.is_active == True).order_by(AssessmentType.sort_order)
    )
    types = result.scalars().all()
    return {
        "assessment_types": [
            {
                "id": t.id,
                "code": t.code,
                "name": t.name,
                "description": t.description,
                "icon": t.icon,
            }
            for t in types
        ]
    }