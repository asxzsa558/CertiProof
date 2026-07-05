from typing import Optional, List
from datetime import datetime
import json
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.rbac import resolve_member_permissions
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.models.assessment_type import ProjectAssessment, AssessmentType
from app.models.organization import OrganizationMember, OrganizationRole, OrganizationRoleAudit
from app.models.scan_task import ScanTask
from app.models.evidence import Evidence
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


def _enum_value(value):
    return getattr(value, "value", value)


@router.get("/organization-command")
async def get_organization_command_dashboard(
    organization_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """组织级安全合规态势总览。"""
    org_id = await resolve_organization_id(db, organization_id, current_user.id)
    await check_org_member(db, org_id, current_user.id)

    member_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == current_user.id,
        )
    )
    current_member = member_result.scalar_one_or_none()
    current_permissions = await resolve_member_permissions(db, current_member) if current_member else set()

    projects_result = await db.execute(
        select(Project)
        .where(Project.organization_id == org_id)
        .order_by(Project.updated_at.desc())
    )
    projects = projects_result.scalars().all()
    project_ids = [p.id for p in projects]

    if not project_ids:
        return {
            "summary": {
                "project_count": 0,
                "asset_count": 0,
                "high_risk_count": 0,
                "unknown_count": 0,
                "average_progress": 0,
                "todo_count": 0,
            },
            "current_role": {
                "base_role": current_member.role if current_member else "viewer",
                "custom_role_id": current_member.custom_role_id if current_member else None,
                "permissions": sorted(current_permissions),
                "permission_scope": "全局权限" if "system:config" in current_permissions and "role:manage" in current_permissions else "受限权限",
            },
            "project_matrix": [],
            "exposure_topology": {"nodes": [], "edges": [], "top_risky_assets": []},
            "tool_health": [],
            "risk_queue": [],
            "rbac": {"roles": [], "members": [], "audits": []},
        }

    asset_count_result = await db.execute(select(func.count(Asset.id)).where(Asset.project_id.in_(project_ids)))
    asset_count = asset_count_result.scalar() or 0

    high_risk_result = await db.execute(
        select(func.count(Finding.id)).where(
            Finding.project_id.in_(project_ids),
            Finding.severity.in_(["critical", "high"]),
        )
    )
    high_risk_count = high_risk_result.scalar() or 0

    unknown_result = await db.execute(
        select(func.count(Finding.id)).where(
            Finding.project_id.in_(project_ids),
            Finding.judgment.in_(["not_tested", "partial"]),
        )
    )
    unknown_count = unknown_result.scalar() or 0

    task_result = await db.execute(
        select(func.count(TaskInstance.id))
        .join(PhaseInstance, PhaseInstance.id == TaskInstance.phase_id)
        .join(Assessment, Assessment.id == PhaseInstance.assessment_id)
        .where(Assessment.project_id.in_(project_ids), TaskInstance.status.in_(["todo", "in_progress", "failed"]))
    )
    todo_count = task_result.scalar() or 0

    progress_values = []
    project_matrix = []
    for project in projects:
        assessment_result = await db.execute(
            select(Assessment)
            .where(Assessment.project_id == project.id)
            .order_by(Assessment.updated_at.desc())
            .limit(1)
        )
        assessment = assessment_result.scalar_one_or_none()
        current_phase = None
        evidence_count = 0
        task_total = 0
        task_done = 0
        if assessment:
            phase_result = await db.execute(
                select(PhaseInstance)
                .where(PhaseInstance.assessment_id == assessment.id)
                .order_by(PhaseInstance.order.asc())
            )
            phases = phase_result.scalars().all()
            current_phase = next((p for p in phases if p.status == "active"), None) or next((p for p in phases if p.status == "pending"), None)
            task_total = sum(p.total_tasks or 0 for p in phases)
            task_done = sum(p.completed_tasks or 0 for p in phases)

        project_findings_result = await db.execute(select(Finding).where(Finding.project_id == project.id))
        project_findings = project_findings_result.scalars().all()
        risk_count = len([f for f in project_findings if _enum_value(f.severity) in ("critical", "high", "medium")])

        evidence_result = await db.execute(select(func.count(Evidence.id)).where(Evidence.project_id == project.id))
        evidence_count = evidence_result.scalar() or 0
        evidence_rate = round((task_done / task_total) * 100) if task_total else min(100, evidence_count * 20)

        progress = round(float(assessment.progress if assessment else (project.compliance_score or 0)))
        progress_values.append(progress)

        owner_name = "未分配"
        if project.owner_id:
            owner_result = await db.execute(select(User).where(User.id == project.owner_id))
            owner = owner_result.scalar_one_or_none()
            owner_name = owner.full_name or owner.username if owner else "未分配"

        project_matrix.append({
            "project_id": project.id,
            "name": project.name,
            "level": _enum_value(project.compliance_level) or "未定级",
            "stage": current_phase.name if current_phase else ("报告输出" if progress >= 100 else "差距分析"),
            "progress": progress,
            "risk_count": risk_count,
            "evidence_rate": evidence_rate,
            "owner": owner_name,
            "next_action": "查看整改" if risk_count else "推进测评",
        })

    average_progress = round(sum(progress_values) / len(progress_values)) if progress_values else 0

    asset_result = await db.execute(
        select(Asset, Project)
        .join(Project, Project.id == Asset.project_id)
        .where(Asset.project_id.in_(project_ids))
        .order_by(Asset.updated_at.desc())
    )
    asset_rows = asset_result.all()
    nodes = [{"id": f"org-{org_id}", "label": "当前组织", "type": "organization", "status": "normal", "size": 22}]
    edges = []
    for project in projects[:6]:
        project_node = f"project-{project.id}"
        nodes.append({"id": project_node, "label": project.name, "type": "project", "status": "normal", "size": 16})
        edges.append({"source": f"org-{org_id}", "target": project_node})
    top_risky_assets = []
    for asset, project in asset_rows[:18]:
        findings_result = await db.execute(
            select(func.count(Finding.id)).where(
                Finding.project_id == project.id,
                Finding.severity.in_(["critical", "high", "medium"]),
            )
        )
        risk_count = findings_result.scalar() or 0
        status_name = "high" if risk_count >= 3 else "warning" if risk_count else "normal"
        asset_node = f"asset-{asset.id}"
        nodes.append({
            "id": asset_node,
            "label": asset.value,
            "type": _enum_value(asset.asset_type),
            "status": status_name,
            "size": min(22, 10 + risk_count * 3),
        })
        edges.append({"source": f"project-{project.id}", "target": asset_node})
        if risk_count:
            top_risky_assets.append({"asset": asset.value, "project": project.name, "service": _enum_value(asset.asset_type), "risk_count": risk_count})
    top_risky_assets = sorted(top_risky_assets, key=lambda item: item["risk_count"], reverse=True)[:5]

    scan_result = await db.execute(
        select(ScanTask)
        .where(ScanTask.project_id.in_(project_ids))
        .order_by(ScanTask.created_at.desc())
        .limit(80)
    )
    scans = scan_result.scalars().all()
    tool_names = ["端口扫描", "漏洞扫描", "弱口令", "Web 检测", "数据库", "网络设备", "Windows/AD", "SSH 基线", "OCR"]
    failed_scans = len([s for s in scans if _enum_value(s.status) == "failed"])
    tool_health = [
        {
            "name": name,
            "status": "warning" if failed_scans and index < 3 else "healthy",
            "latency": f"{180 + index * 35}ms",
            "last_run": scans[index % len(scans)].created_at.isoformat() if scans else None,
            "failure_count": failed_scans if index == 0 else 0,
        }
        for index, name in enumerate(tool_names)
    ]

    risk_result = await db.execute(
        select(Finding, Project)
        .join(Project, Project.id == Finding.project_id)
        .where(Finding.project_id.in_(project_ids))
        .order_by(Finding.updated_at.desc())
        .limit(8)
    )
    risk_queue = [
        {
            "asset": project.name,
            "risk": finding.clause_name or finding.description or finding.clause_id,
            "control": finding.clause_id,
            "severity": _enum_value(finding.severity),
            "status": _enum_value(finding.status),
            "owner": "待分配",
            "action": "创建整改" if _enum_value(finding.status) == "open" else "查看",
        }
        for finding, project in risk_result.all()
    ]

    role_result = await db.execute(
        select(OrganizationRole)
        .where(OrganizationRole.organization_id == org_id)
        .order_by(OrganizationRole.is_system.desc(), OrganizationRole.created_at.asc())
    )
    roles = role_result.scalars().all()
    member_result = await db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == org_id)
        .order_by(OrganizationMember.joined_at.asc())
    )
    audit_result = await db.execute(
        select(OrganizationRoleAudit)
        .where(OrganizationRoleAudit.organization_id == org_id)
        .order_by(OrganizationRoleAudit.created_at.desc())
        .limit(5)
    )

    return {
        "summary": {
            "project_count": len(projects),
            "asset_count": asset_count,
            "high_risk_count": high_risk_count,
            "unknown_count": unknown_count,
            "average_progress": average_progress,
            "todo_count": todo_count,
        },
        "current_role": {
            "base_role": current_member.role if current_member else "viewer",
            "custom_role_id": current_member.custom_role_id if current_member else None,
            "permissions": sorted(current_permissions),
            "permission_scope": "全局权限" if "system:config" in current_permissions and "role:manage" in current_permissions else "受限权限",
        },
        "project_matrix": project_matrix,
        "exposure_topology": {"nodes": nodes, "edges": edges, "top_risky_assets": top_risky_assets},
        "tool_health": tool_health,
        "risk_queue": risk_queue,
        "rbac": {
            "roles": [
                {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description,
                    "permission_count": len(json.loads(role.permissions or "[]")),
                    "is_system": role.is_system,
                }
                for role in roles
            ],
            "members": [
                {
                    "id": member.id,
                    "name": user.full_name or user.username,
                    "email": user.email,
                    "role": member.role,
                    "custom_role_id": member.custom_role_id,
                }
                for member, user in member_result.all()
            ],
            "audits": [
                {
                    "id": audit.id,
                    "action": audit.action,
                    "detail": audit.detail,
                    "created_at": audit.created_at.isoformat(),
                }
                for audit in audit_result.scalars().all()
            ],
        },
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
