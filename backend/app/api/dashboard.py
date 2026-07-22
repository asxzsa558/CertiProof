from typing import Optional, List
from datetime import datetime
import json
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, case, func, select
from app.core.database import get_db
from app.core.rbac import resolve_member_permissions
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.report import ReportArtifact
from app.models.asset import Asset
from app.models.assessment_type import ProjectAssessment, AssessmentType
from app.models.organization import OrganizationMember, OrganizationRole, OrganizationRoleAudit
from app.models.scan_task import ScanTask
from app.models.evidence import Evidence
from app.models.finding import Finding, FindingStatus
from app.services.display_names import CAPABILITY_DISPLAY_NAMES
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


async def organization_rbac_snapshot(
    db: AsyncSession,
    org_id: int,
    permissions: set[str],
) -> dict:
    if "role:read" not in permissions:
        return {"roles": [], "members": [], "audits": []}

    role_result = await db.execute(
        select(OrganizationRole)
        .where(OrganizationRole.organization_id == org_id)
        .order_by(OrganizationRole.is_system.desc(), OrganizationRole.created_at.asc())
    )
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
        "roles": [
            {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "permission_count": len(json.loads(role.permissions or "[]")),
                "is_system": role.is_system,
            }
            for role in role_result.scalars().all()
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
    }


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


TOPOLOGY_RISK_SEVERITIES = ("critical", "high", "medium")


def _is_incomplete_technical_finding(finding) -> bool:
    return (
        finding.clause_name == "自动化技术检测"
        and "检测未完成（不代表通过）" in (finding.description or "")
    )


def _actionable_risk_summary(findings) -> dict:
    counts = {"critical": 0, "high": 0, "medium": 0}
    for finding in findings:
        severity = _enum_value(finding.severity)
        if (
            _enum_value(finding.status) == FindingStatus.OPEN.value
            and severity in counts
            and not _is_incomplete_technical_finding(finding)
        ):
            counts[severity] += 1
    return {
        "risk_count": sum(counts.values()),
        "critical_count": counts["critical"],
        "high_count": counts["high"],
        "medium_count": counts["medium"],
    }


def _risk_level(stats: dict) -> str:
    if stats.get("critical_count", 0):
        return "critical"
    if stats.get("high_count", 0):
        return "high"
    if stats.get("risk_count", 0):
        return "warning"
    return "normal"


def _asset_topology_status(stats: dict, verification, has_observation: bool) -> str:
    risk_level = _risk_level(stats)
    if risk_level != "normal":
        return risk_level
    if _enum_value(verification) != "verified" or not has_observation:
        return "unverified"
    return "normal"


def _topology_services(summary):
    """Extract only observed open services from normalized scan summaries."""
    services = []
    seen = set()

    def visit(value, depth=0):
        if depth > 5 or not value:
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        for port in value.get("open_ports") or []:
            if not isinstance(port, dict) or port.get("state") not in (None, "open"):
                continue
            number = port.get("port")
            if number in (None, ""):
                continue
            protocol = str(port.get("protocol") or "tcp").lower()
            service = str(port.get("service") or port.get("name") or "").strip()
            key = f"{number}/{protocol}"
            if key not in seen:
                seen.add(key)
                services.append({
                    "id": key,
                    "label": key,
                    "port": number,
                    "protocol": protocol,
                    "service": service or None,
                })
        for key in ("data", "result", "results", "scan_results"):
            visit(value.get(key), depth + 1)

    visit(summary)
    return services[:6]


def _matrix_progress(assessment, _phases, _task_completion_rate):
    """Read the Flow Engine percentage shown by the project assessment page."""
    return round(float(assessment.progress or 0), 1)


TOOL_GROUPS = (
    ("端口扫描", {"scan_ports", "nmap_scan", "port_scan", "masscan_scan"}),
    ("漏洞扫描", {"scan_vulnerabilities", "nuclei_scan", "vuln_scan"}),
    ("弱口令检测", {"scan_weak_passwords", "hydra_bruteforce"}),
    ("SSL/TLS", {"scan_ssl", "testssl_scan"}),
    ("Web 检测", {"nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan", "web_discovery_scan"}),
    ("数据库", {"database_security_scan", "redis_check", "mysql_check", "mongodb_check", "memcached_check", "oracle_check"}),
    ("网络设备", {"network_device_scan", "snmp_walk", "snmp_scan"}),
    ("Windows/AD", {"windows_security_scan", "smb_enum"}),
    ("SSH 基线", {"baseline_check", "ssh_config_check"}),
    ("文档 OCR", {"document_page_parse", "document_control_analysis"}),
)


def _scan_capabilities(parameters):
    """Read capabilities recorded by direct scans, plans, and assessment tasks."""
    if not isinstance(parameters, dict):
        return set()

    capabilities = set()
    for value in (parameters.get("capability"), parameters.get("tool_name")):
        if isinstance(value, str):
            capabilities.add(value)
    for value in parameters.get("capabilities") or []:
        if isinstance(value, str):
            capabilities.add(value)
    for step in parameters.get("plan") or []:
        if isinstance(step, dict) and isinstance(step.get("capability"), str):
            capabilities.add(step["capability"])
    return capabilities


def _format_scan_latency(scan):
    if not scan.started_at or not scan.completed_at:
        return "未记录"
    elapsed = max(0, round((scan.completed_at - scan.started_at).total_seconds()))
    if elapsed < 60:
        return f"{elapsed}s"
    return f"{elapsed // 60}m {elapsed % 60}s"


def _tool_health(scans):
    """Build telemetry from persisted scans only; never invent health or latency."""
    grouped = {name: [] for name, _ in TOOL_GROUPS}
    for scan in scans:
        capabilities = _scan_capabilities(scan.parameters)
        for name, aliases in TOOL_GROUPS:
            if capabilities.intersection(aliases):
                grouped[name].append(scan)

    records = []
    for name, _ in TOOL_GROUPS:
        tool_scans = grouped[name]
        latest = tool_scans[0] if tool_scans else None
        latest_status = _enum_value(latest.status) if latest else "idle"
        if latest_status == "completed":
            health = "healthy"
        elif latest_status in ("pending", "running"):
            health = "running"
        elif latest:
            health = "warning"
        else:
            health = "idle"
        records.append({
            "name": name,
            "status": health,
            "latency": _format_scan_latency(latest) if latest else "暂无记录",
            "last_run": latest.created_at.isoformat() if latest and latest.created_at else None,
            "failure_count": sum(1 for scan in tool_scans if _enum_value(scan.status) == "failed"),
        })
    return records


@router.get("/organization-command")
async def get_organization_command_dashboard(
    organization_id: Optional[int] = Query(None),
    assessment_code: Optional[str] = Query(None, pattern="^(dengbao|miping)$"),
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
    current_risk_statuses = [FindingStatus.OPEN]
    incomplete_technical_finding = and_(
        Finding.clause_name == "自动化技术检测",
        Finding.description.like("%检测未完成（不代表通过）%"),
    )

    if not project_ids:
        rbac = await organization_rbac_snapshot(db, org_id, current_permissions)
        return {
            "summary": {
                "project_count": 0,
                "active_project_count": 0,
                "completed_project_count": 0,
                "asset_count": 0,
                "asset_type_counts": {},
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
            "exposure_topology": {"nodes": [], "edges": [], "top_risky_assets": [], "risk_intelligence": []},
            "tool_health": [],
            "risk_queue": [],
            "rbac": rbac,
        }

    asset_count_result = await db.execute(select(func.count(Asset.id)).where(Asset.project_id.in_(project_ids)))
    asset_count = asset_count_result.scalar() or 0
    asset_type_rows = (await db.execute(select(Asset.asset_type, func.count(Asset.id)).where(
        Asset.project_id.in_(project_ids)
    ).group_by(Asset.asset_type))).all()
    asset_type_counts = {_enum_value(asset_type): count for asset_type, count in asset_type_rows}

    high_risk_result = await db.execute(
        select(func.count(Finding.id)).where(
            Finding.project_id.in_(project_ids),
            Finding.severity.in_(["critical", "high"]),
            Finding.status.in_(current_risk_statuses),
            ~incomplete_technical_finding,
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
    project_risk_stats = {}
    report_artifacts = (await db.execute(
        select(ReportArtifact)
        .where(ReportArtifact.project_id.in_(project_ids))
        .order_by(ReportArtifact.project_id, ReportArtifact.version.desc())
    )).scalars().all()
    latest_reports = {}
    for artifact in report_artifacts:
        latest_reports.setdefault(artifact.project_id, artifact)
    for project in projects:
        assessment_result = await db.execute(
            select(Assessment)
            .where(Assessment.project_id == project.id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        )
        project_assessments = list(assessment_result.scalars().all())
        assessment = next(
            (item for item in project_assessments if item.assessment_type_code == assessment_code),
            None,
        ) if assessment_code else next(
            (item for item in project_assessments if item.assessment_type_code == "dengbao"),
            project_assessments[0] if project_assessments else None,
        )
        current_phase = None
        phases = []
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

        finding_filters = [Finding.project_id == project.id]
        if assessment:
            finding_filters.append(Finding.assessment_id == assessment.id)
        else:
            finding_filters.append(Finding.assessment_id.is_(None))
        project_findings_result = await db.execute(select(Finding).where(*finding_filters))
        project_findings = project_findings_result.scalars().all()
        risk_stats = _actionable_risk_summary(project_findings)
        project_risk_stats[project.id] = risk_stats
        risk_count = risk_stats["risk_count"]

        if assessment_code and assessment:
            evidence_result = await db.execute(
                select(func.count(Evidence.id))
                .join(Finding, Finding.id == Evidence.finding_id)
                .where(Finding.assessment_id == assessment.id)
            )
        else:
            evidence_result = await db.execute(
                select(func.count(Evidence.id)).where(Evidence.project_id == project.id)
            )
        evidence_count = evidence_result.scalar() or 0
        task_completion_rate = round((task_done / task_total) * 100) if task_total else 0

        progress = _matrix_progress(assessment, phases, task_completion_rate) if assessment else round(float(project.compliance_score or 0))
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
            "evidence_count": evidence_count,
            "task_total": task_total,
            "task_done": task_done,
            "task_completion_rate": task_completion_rate,
            "owner": owner_name,
            "next_action": "查看整改" if risk_count else "推进测评",
            "report": (
                {
                    "available": True,
                    "version": latest_reports[project.id].version,
                    "status": latest_reports[project.id].status,
                    "stale": latest_reports[project.id].status == "stale",
                    "stale_reason": latest_reports[project.id].stale_reason,
                    "generated_at": latest_reports[project.id].created_at.isoformat() if latest_reports[project.id].created_at else None,
                }
                if project.id in latest_reports else {"available": False}
            ),
        })

    average_progress = round(sum(progress_values) / len(progress_values)) if progress_values else 0

    asset_result = await db.execute(
        select(Asset, Project)
        .join(Project, Project.id == Asset.project_id)
        .where(Asset.project_id.in_(project_ids))
        .order_by(Asset.updated_at.desc())
    )
    asset_rows = asset_result.all()
    risk_stats_result = await db.execute(
        select(
            ScanTask.asset_id,
            func.count(Finding.id).label("finding_count"),
            func.coalesce(func.sum(case((and_(
                Finding.status.in_(current_risk_statuses),
                Finding.severity.in_(["critical", "high", "medium"]),
                ~incomplete_technical_finding,
            ), 1), else_=0)), 0).label("risk_count"),
            func.coalesce(func.sum(case((and_(
                Finding.status.in_(current_risk_statuses),
                Finding.severity == "critical",
                ~incomplete_technical_finding,
            ), 1), else_=0)), 0).label("critical_count"),
            func.coalesce(func.sum(case((and_(
                Finding.status.in_(current_risk_statuses),
                Finding.severity == "high",
                ~incomplete_technical_finding,
            ), 1), else_=0)), 0).label("high_count"),
            func.coalesce(func.sum(case((and_(
                Finding.status.in_(current_risk_statuses),
                Finding.severity == "medium",
                ~incomplete_technical_finding,
            ), 1), else_=0)), 0).label("medium_count"),
        )
        .select_from(ScanTask)
        .outerjoin(Finding, Finding.scan_task_id == ScanTask.id)
        .where(ScanTask.project_id.in_(project_ids), ScanTask.asset_id.is_not(None))
        .group_by(ScanTask.asset_id)
    )
    asset_risk_stats = {
        row.asset_id: {
            "finding_count": int(row.finding_count or 0),
            "risk_count": int(row.risk_count or 0),
            "critical_count": int(row.critical_count or 0),
            "high_count": int(row.high_count or 0),
            "medium_count": int(row.medium_count or 0),
        }
        for row in risk_stats_result.all()
        if row.asset_id is not None
    }

    asset_summary_result = await db.execute(
        select(ScanTask.asset_id, ScanTask.result_summary, ScanTask.status, ScanTask.completed_at, ScanTask.created_at)
        .where(
            ScanTask.project_id.in_(project_ids),
            ScanTask.asset_id.is_not(None),
            ScanTask.result_summary.is_not(None),
        )
        .order_by(ScanTask.completed_at.desc().nullslast(), ScanTask.id.desc())
    )
    asset_services = {}
    asset_scan_meta = {}
    for asset_id, result_summary, scan_status, completed_at, created_at in asset_summary_result.all():
        observed_at = (completed_at or created_at).isoformat() if completed_at or created_at else None
        if asset_id not in asset_scan_meta:
            asset_scan_meta[asset_id] = {
                "status": _enum_value(scan_status),
                "observed_at": observed_at,
            }
        if asset_id not in asset_services:
            services = _topology_services(result_summary)
            if services:
                asset_services[asset_id] = [
                    {**service, "observed_at": observed_at}
                    for service in services
                ]

    assets_by_project = {}
    for asset, project in asset_rows:
        assets_by_project.setdefault(project.id, []).append((asset, project))

    project_matrix_by_id = {item["project_id"]: item for item in project_matrix}
    project_topology = {}
    for project in projects:
        project_assets = assets_by_project.get(project.id, [])
        total_stats = project_risk_stats.get(project.id, {"risk_count": 0})
        asset_risk_count = sum(
            asset_risk_stats.get(asset.id, {}).get("risk_count", 0)
            for asset, _ in project_assets
        )
        matrix = project_matrix_by_id.get(project.id, {})
        project_topology[project.id] = {
            **total_stats,
            "asset_risk_count": asset_risk_count,
            "unassigned_risk_count": max(total_stats.get("risk_count", 0) - asset_risk_count, 0),
            "verified_asset_count": sum(
                1 for asset, _ in project_assets
                if _enum_value(asset.verification_status) == "verified"
            ),
            "observed_service_count": sum(
                len(asset_services.get(asset.id, [])) for asset, _ in project_assets
            ),
            "progress": matrix.get("progress", 0),
            "stage": matrix.get("stage", "差距分析"),
            "evidence_count": matrix.get("evidence_count", 0),
            "report": matrix.get("report", {"available": False}),
        }

    organization_stats = {
        "risk_count": sum(item.get("risk_count", 0) for item in project_topology.values()),
        "asset_risk_count": sum(item.get("asset_risk_count", 0) for item in project_topology.values()),
        "unassigned_risk_count": sum(item.get("unassigned_risk_count", 0) for item in project_topology.values()),
        "critical_count": sum(item.get("critical_count", 0) for item in project_topology.values()),
        "high_count": sum(item.get("high_count", 0) for item in project_topology.values()),
        "medium_count": sum(item.get("medium_count", 0) for item in project_topology.values()),
    }
    nodes = [{
        "id": f"org-{org_id}",
        "label": "当前组织",
        "type": "organization",
        "status": _risk_level(organization_stats),
        "project_count": len(projects),
        "asset_count": int(asset_count),
        "verified_asset_count": sum(item.get("verified_asset_count", 0) for item in project_topology.values()),
        "observed_service_count": sum(item.get("observed_service_count", 0) for item in project_topology.values()),
        **organization_stats,
    }]
    edges = []
    for project in projects:
        project_assets = assets_by_project.get(project.id, [])
        stats = project_topology[project.id]
        project_node = f"project-{project.id}"
        nodes.append({
            "id": project_node,
            "project_id": project.id,
            "label": project.name,
            "type": "project",
            "status": _risk_level(stats),
            "asset_count": len(project_assets),
            **stats,
        })
        edges.append({"source": f"org-{org_id}", "target": project_node, "kind": "contains"})
    top_risky_assets = []
    for asset, project in asset_rows:
        stats = asset_risk_stats.get(asset.id, {})
        risk_count = stats.get("risk_count", 0)
        status_name = _asset_topology_status(
            stats,
            asset.verification_status,
            asset.id in asset_scan_meta,
        )
        asset_node = f"asset-{asset.id}"
        nodes.append({
            "id": asset_node,
            "asset_id": asset.id,
            "project_id": project.id,
            "project_name": project.name,
            "label": asset.value,
            "asset_name": asset.name,
            "value": asset.value,
            "type": _enum_value(asset.asset_type),
            "status": status_name,
            "verification": _enum_value(asset.verification_status),
            "verification_method": _enum_value(asset.verification_method),
            "verified_at": asset.verified_at.isoformat() if asset.verified_at else None,
            "is_active": bool(asset.is_active),
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
            "last_scan": asset_scan_meta.get(asset.id),
            "risk_count": risk_count,
            "finding_count": stats.get("finding_count", 0),
            "critical_count": stats.get("critical_count", 0),
            "high_count": stats.get("high_count", 0),
            "medium_count": stats.get("medium_count", 0),
            "services": asset_services.get(asset.id, []),
        })
        edges.append({"source": f"project-{project.id}", "target": asset_node, "kind": "contains"})
        if risk_count:
            top_risky_assets.append({
                "asset": asset.value,
                "project": project.name,
                "service": _enum_value(asset.asset_type),
                "risk_count": risk_count,
                "status": status_name,
            })
    top_risky_assets = sorted(top_risky_assets, key=lambda item: item["risk_count"], reverse=True)[:5]

    intelligence_result = await db.execute(
        select(Finding, ScanTask, Asset)
        .join(ScanTask, ScanTask.id == Finding.scan_task_id)
        .join(Asset, Asset.id == ScanTask.asset_id)
        .where(
            Finding.project_id.in_(project_ids),
            Finding.status.in_(current_risk_statuses),
            Finding.severity.in_(TOPOLOGY_RISK_SEVERITIES),
            ~incomplete_technical_finding,
        )
        .order_by(Finding.updated_at.desc())
    )
    risk_intelligence = [
        {
            "id": finding.id,
            "asset_id": f"asset-{asset.id}",
            "asset": asset.value,
            "project_id": asset.project_id,
            "severity": _enum_value(finding.severity),
            "status": _enum_value(finding.status),
            "title": finding.clause_name or finding.description or finding.clause_id,
            "description": finding.description,
            "observed_at": finding.updated_at.isoformat() if finding.updated_at else None,
        }
        for finding, _, asset in intelligence_result.all()
    ]

    scan_result = await db.execute(
        select(ScanTask)
        .where(ScanTask.project_id.in_(project_ids))
        .order_by(ScanTask.created_at.desc())
        .limit(80)
    )
    scans = scan_result.scalars().all()
    tool_health = _tool_health(scans)

    risk_result = await db.execute(
        select(Finding, Project, Asset, Assessment)
        .join(Project, Project.id == Finding.project_id)
        .outerjoin(Asset, Asset.id == Finding.asset_id)
        .outerjoin(Assessment, Assessment.id == Finding.assessment_id)
        .where(Finding.project_id.in_(project_ids), ~incomplete_technical_finding)
        .order_by(Finding.updated_at.desc())
        .limit(200)
    )
    risk_queue = []
    seen_risks = set()
    for finding, project, asset, assessment in risk_result.all():
        identity = (finding.assessment_id or 0, finding.fingerprint or finding.id)
        if identity in seen_risks:
            continue
        seen_risks.add(identity)
        assessment_code_value = assessment.assessment_type_code if assessment else None
        source_label = (
            "等保测评" if assessment_code_value == "dengbao"
            else "密评测评" if assessment_code_value == "miping"
            else "定时检测" if finding.source_channel == "scheduled"
            else "独立检测"
        )
        scope_label = asset.value if asset else "项目级问题"
        scope_name = (
            asset.name if asset else
            "文档合规检查" if finding.source_type == "document" else
            "未绑定具体资产"
        )
        risk_queue.append({
            "finding_id": finding.id,
            "project_id": project.id,
            "project": project.name,
            "asset_id": asset.id if asset else finding.asset_id,
            "asset": scope_label,
            "asset_name": scope_name,
            "risk": finding.description or finding.clause_name or finding.clause_id,
            "title": finding.clause_name or finding.clause_id,
            "control": finding.clause_id,
            "description": finding.description,
            "remediation_plan": finding.remediation_suggestion,
            "severity": _enum_value(finding.severity),
            "status": _enum_value(finding.status),
            "source": source_label,
            "source_channel": finding.source_channel,
            "assessment_code": assessment_code_value,
            "tool": CAPABILITY_DISPLAY_NAMES.get(finding.source_key, finding.source_key),
            "occurrence_count": finding.occurrence_count or 1,
            "last_seen_at": (finding.last_seen_at or finding.updated_at).isoformat() if (finding.last_seen_at or finding.updated_at) else None,
            "owner": "系统跟踪",
            "action": "查看" if _enum_value(finding.status) in ("fixed", "false_positive") else "整改与复测",
        })

    rbac = await organization_rbac_snapshot(db, org_id, current_permissions)

    return {
        "summary": {
            "project_count": len(projects),
            "active_project_count": sum(0 < item["progress"] < 100 for item in project_matrix),
            "completed_project_count": sum(item["progress"] >= 100 for item in project_matrix),
            "asset_count": asset_count,
            "asset_type_counts": asset_type_counts,
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
        "exposure_topology": {
            "nodes": nodes,
            "edges": edges,
            "top_risky_assets": top_risky_assets,
            "risk_intelligence": risk_intelligence,
        },
        "tool_health": tool_health,
        "risk_queue": risk_queue,
        "rbac": rbac,
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
