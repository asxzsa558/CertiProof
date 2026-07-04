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


# ========== ARGUS Dashboard API ==========

from app.models.assessment import Assessment, PhaseInstance, TaskInstance
from app.models.finding import Finding


@router.get("/argus/overview")
async def get_argus_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ARGUS 风格概览数据"""
    # 项目统计 - 获取用户所属组织的所有项目
    from app.models.organization import OrganizationMember
    org_ids_result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == current_user.id)
    )
    org_ids = [row[0] for row in org_ids_result.all()]
    
    if org_ids:
        projects_result = await db.execute(
            select(Project).where(Project.organization_id.in_(org_ids))
        )
    else:
        projects_result = await db.execute(
            select(Project).where(Project.user_id == current_user.id)
        )
    projects = projects_result.scalars().all()
    
    total_projects = len(projects)
    
    # 活跃测评数
    assessments_result = await db.execute(
        select(Assessment).where(
            Assessment.project_id.in_([p.id for p in projects]),
            Assessment.status == 'in_progress'
        )
    )
    active_assessments = len(assessments_result.scalars().all())
    
    # 关键发现数
    findings_result = await db.execute(
        select(func.count(Finding.id)).where(
            Finding.project_id.in_([p.id for p in projects]),
            Finding.severity.in_(['critical', 'high'])
        )
    )
    critical_findings = findings_result.scalar() or 0
    
    # 等级分布
    level_distribution = {}
    for project in projects:
        level = project.compliance_level or '未知'
        level_distribution[level] = level_distribution.get(level, 0) + 1
    
    # 最近项目
    recent_projects = sorted(projects, key=lambda p: p.updated_at or p.created_at, reverse=True)[:5]
    
    return {
        "total_projects": total_projects,
        "active_assessments": active_assessments,
        "critical_findings": critical_findings,
        "level_distribution": level_distribution,
        "recent_projects": [
            {
                "id": p.id,
                "name": p.name,
                "compliance_level": p.compliance_level,
                "compliance_score": p.compliance_score,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in recent_projects
        ]
    }


@router.get("/argus/score-trend")
async def get_score_trend(
    days: int = Query(default=30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """合规分数趋势（基于项目当前分数，简化版）"""
    # 获取用户所有项目 - 包括组织项目
    from app.models.organization import OrganizationMember
    org_ids_result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == current_user.id)
    )
    org_ids = [row[0] for row in org_ids_result.all()]
    
    if org_ids:
        projects_result = await db.execute(
            select(Project).where(Project.organization_id.in_(org_ids))
        )
    else:
        projects_result = await db.execute(
            select(Project).where(Project.user_id == current_user.id)
        )
    projects = projects_result.scalars().all()
    
    # 简化：返回当前分数作为趋势（实际应该从历史记录表读取）
    scores = []
    for project in projects:
        if project.compliance_score is not None:
            scores.append({
                "project_id": project.id,
                "project_name": project.name,
                "score": project.compliance_score,
            })
    
    return {
        "scores": scores,
        "days": days,
    }


@router.get("/argus/risk-heatmap")
async def get_risk_heatmap(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """风险发现热力图"""
    # 获取用户项目 - 包括组织项目
    from app.models.organization import OrganizationMember
    org_ids_result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == current_user.id)
    )
    org_ids = [row[0] for row in org_ids_result.all()]
    
    if org_ids:
        projects_result = await db.execute(
            select(Project).where(Project.organization_id.in_(org_ids))
        )
    else:
        projects_result = await db.execute(
            select(Project).where(Project.user_id == current_user.id)
        )
    projects = projects_result.scalars().all()
    project_ids = [p.id for p in projects]
    
    if not project_ids:
        return {"assets": []}
    
    # 按项目和严重性统计发现（简化版，不按资产）
    findings_result = await db.execute(
        select(
            Finding.project_id,
            Finding.severity,
            func.count(Finding.id).label('count')
        ).where(
            Finding.project_id.in_(project_ids)
        ).group_by(Finding.project_id, Finding.severity)
    )
    
    findings = findings_result.all()
    
    # 组织数据
    project_risks = {}
    for project_id, severity, count in findings:
        if project_id not in project_risks:
            project_risks[project_id] = {
                "project_id": project_id,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "info": 0,
            }
        if severity in project_risks[project_id]:
            project_risks[project_id][severity] = count
    
    return {
        "projects": list(project_risks.values())
    }