from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, case
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project, ProjectStatus, ComplianceLevel
from app.models.asset import Asset, AssetType, VerificationStatus
from app.models.finding import Finding, Severity, Judgment, FindingStatus
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType
from app.models.questionnaire import QuestionnaireRecord
from app.models.remediation import RemediationTicket, RemediationStatus
from pydantic import BaseModel

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class ProjectOverview(BaseModel):
    total: int
    active: int
    archived: int
    level2_count: int
    level3_count: int
    avg_score: Optional[float]
    recent_7d: int


class CompliancePosture(BaseModel):
    total_clauses: int
    tested: int
    passed: int
    failed: int
    partial: int
    paper_compliant: int
    not_tested: int
    pass_rate: float
    score: float
    by_pillar: List[Dict[str, Any]]


class RiskMap(BaseModel):
    critical: int
    high: int
    medium: int
    low: int
    info: int
    open: int
    in_progress: int
    resolved: int
    top_clauses: List[Dict[str, Any]]


class AssessmentProgress(BaseModel):
    active_tasks: int
    pending: int
    running: int
    completed_7d: int
    failed_7d: int
    questionnaires_total: int
    questionnaires_completed: int
    remediation_total: int
    remediation_completed: int


class AssetPosture(BaseModel):
    total: int
    by_type: Dict[str, int]
    verified: int
    pending: int
    failed: int
    new_7d: int


class UserWorkload(BaseModel):
    total_users: int
    active_users_7d: int
    by_role: Dict[str, int]
    assigned_findings: int
    assigned_remediations: int


class DashboardData(BaseModel):
    overview: ProjectOverview
    compliance: CompliancePosture
    risk: RiskMap
    progress: AssessmentProgress
    assets: AssetPosture
    users: UserWorkload
    generated_at: datetime


@router.get("/overview", response_model=DashboardData)
async def get_dashboard_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    proj_total = await db.execute(select(func.count(Project.id)))
    proj_active = await db.execute(
        select(func.count(Project.id)).where(Project.status == ProjectStatus.ACTIVE)
    )
    proj_archived = await db.execute(
        select(func.count(Project.id)).where(Project.status == ProjectStatus.ARCHIVED)
    )
    proj_l2 = await db.execute(
        select(func.count(Project.id)).where(Project.compliance_level == ComplianceLevel.LEVEL_2)
    )
    proj_l3 = await db.execute(
        select(func.count(Project.id)).where(Project.compliance_level == ComplianceLevel.LEVEL_3)
    )
    proj_recent = await db.execute(
        select(func.count(Project.id)).where(Project.created_at >= seven_days_ago)
    )
    avg_score_row = await db.execute(select(func.avg(Project.compliance_score)))

    overview = ProjectOverview(
        total=proj_total.scalar() or 0,
        active=proj_active.scalar() or 0,
        archived=proj_archived.scalar() or 0,
        level2_count=proj_l2.scalar() or 0,
        level3_count=proj_l3.scalar() or 0,
        avg_score=float(avg_score_row.scalar() or 0),
        recent_7d=proj_recent.scalar() or 0,
    )

    total_findings = await db.execute(select(func.count(Finding.id)))
    passed = await db.execute(select(func.count(Finding.id)).where(Finding.judgment == Judgment.PASS))
    failed = await db.execute(select(func.count(Finding.id)).where(Finding.judgment == Judgment.FAIL))
    partial = await db.execute(select(func.count(Finding.id)).where(Finding.judgment == Judgment.PARTIAL))
    paper = await db.execute(
        select(func.count(Finding.id)).where(Finding.judgment == Judgment.PAPER_COMPLIANT)
    )
    not_tested = await db.execute(
        select(func.count(Finding.id)).where(Finding.judgment == Judgment.NOT_TESTED)
    )

    total = total_findings.scalar() or 0
    p = passed.scalar() or 0
    f = failed.scalar() or 0
    pa = partial.scalar() or 0
    pc = paper.scalar() or 0
    nt = not_tested.scalar() or 0

    if total > 0:
        pass_rate = round(p / total * 100, 1)
        score = round((p + pa * 0.5 + pc * 0.7) / total * 100, 1)
    else:
        pass_rate = 0.0
        score = 0.0

    pillar_rows = await db.execute(
        select(Finding.clause_id, Finding.judgment, func.count(Finding.id))
        .group_by(Finding.clause_id, Finding.judgment)
    )
    pillar_stats: Dict[str, Dict[str, int]] = {}
    for cid, jdg, cnt in pillar_rows.all():
        section = ".".join(cid.split(".")[:3]) if "." in cid else cid
        if section not in pillar_stats:
            pillar_stats[section] = {"total": 0, "pass": 0, "fail": 0}
        pillar_stats[section]["total"] += cnt
        if jdg == Judgment.PASS:
            pillar_stats[section]["pass"] += cnt
        elif jdg == Judgment.FAIL:
            pillar_stats[section]["fail"] += cnt

    by_pillar = []
    for s, stats in sorted(pillar_stats.items()):
        t = stats["total"]
        by_pillar.append({
            "section": s,
            "total": t,
            "passed": stats["pass"],
            "failed": stats["fail"],
            "pass_rate": round(stats["pass"] / t * 100, 1) if t > 0 else 0.0,
        })

    compliance = CompliancePosture(
        total_clauses=total,
        tested=total - nt,
        passed=p,
        failed=f,
        partial=pa,
        paper_compliant=pc,
        not_tested=nt,
        pass_rate=pass_rate,
        score=score,
        by_pillar=by_pillar,
    )

    crit = await db.execute(select(func.count(Finding.id)).where(Finding.severity == Severity.CRITICAL))
    high = await db.execute(select(func.count(Finding.id)).where(Finding.severity == Severity.HIGH))
    med = await db.execute(select(func.count(Finding.id)).where(Finding.severity == Severity.MEDIUM))
    low = await db.execute(select(func.count(Finding.id)).where(Finding.severity == Severity.LOW))
    info = await db.execute(select(func.count(Finding.id)).where(Finding.severity == Severity.INFO))

    open_n = await db.execute(select(func.count(Finding.id)).where(Finding.status == FindingStatus.OPEN))
    in_prog = await db.execute(
        select(func.count(Finding.id)).where(Finding.status == FindingStatus.IN_PROGRESS)
    )
    resolved = await db.execute(
        select(func.count(Finding.id)).where(Finding.status == FindingStatus.RESOLVED)
    )

    top_rows = await db.execute(
        select(
            Finding.clause_id,
            Finding.clause_name,
            func.count(Finding.id).label("cnt"),
        )
        .where(Finding.judgment == Judgment.FAIL)
        .group_by(Finding.clause_id, Finding.clause_name)
        .order_by(func.count(Finding.id).desc())
        .limit(10)
    )
    top_clauses = [
        {"clause_id": cid, "name": cname or cid, "count": cnt}
        for cid, cname, cnt in top_rows.all()
    ]

    risk = RiskMap(
        critical=crit.scalar() or 0,
        high=high.scalar() or 0,
        medium=med.scalar() or 0,
        low=low.scalar() or 0,
        info=info.scalar() or 0,
        open=open_n.scalar() or 0,
        in_progress=in_prog.scalar() or 0,
        resolved=resolved.scalar() or 0,
        top_clauses=top_clauses,
    )

    active_tasks = await db.execute(
        select(func.count(ScanTask.id)).where(
            ScanTask.status.in_([ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING])
        )
    )
    pending = await db.execute(
        select(func.count(ScanTask.id)).where(ScanTask.status == ScanTaskStatus.PENDING)
    )
    running = await db.execute(
        select(func.count(ScanTask.id)).where(ScanTask.status == ScanTaskStatus.RUNNING)
    )
    completed_7d = await db.execute(
        select(func.count(ScanTask.id)).where(
            and_(ScanTask.status == ScanTaskStatus.COMPLETED, ScanTask.created_at >= seven_days_ago)
        )
    )
    failed_7d = await db.execute(
        select(func.count(ScanTask.id)).where(
            and_(ScanTask.status == ScanTaskStatus.FAILED, ScanTask.created_at >= seven_days_ago)
        )
    )

    q_total = await db.execute(select(func.count(QuestionnaireRecord.id)))
    q_completed = await db.execute(
        select(func.count(QuestionnaireRecord.id)).where(
            QuestionnaireRecord.status == "completed"
        )
    )
    r_total = await db.execute(select(func.count(RemediationTicket.id)))
    r_completed = await db.execute(
        select(func.count(RemediationTicket.id)).where(
            RemediationTicket.status == RemediationStatus.RESOLVED
        )
    )

    progress = AssessmentProgress(
        active_tasks=active_tasks.scalar() or 0,
        pending=pending.scalar() or 0,
        running=running.scalar() or 0,
        completed_7d=completed_7d.scalar() or 0,
        failed_7d=failed_7d.scalar() or 0,
        questionnaires_total=q_total.scalar() or 0,
        questionnaires_completed=q_completed.scalar() or 0,
        remediation_total=r_total.scalar() or 0,
        remediation_completed=r_completed.scalar() or 0,
    )

    asset_total = await db.execute(select(func.count(Asset.id)))
    by_type_rows = await db.execute(
        select(Asset.asset_type, func.count(Asset.id)).group_by(Asset.asset_type)
    )
    by_type = {t.value: cnt for t, cnt in by_type_rows.all()}
    verified = await db.execute(
        select(func.count(Asset.id)).where(Asset.verification_status == VerificationStatus.VERIFIED)
    )
    pending_v = await db.execute(
        select(func.count(Asset.id)).where(Asset.verification_status == VerificationStatus.PENDING)
    )
    failed_v = await db.execute(
        select(func.count(Asset.id)).where(Asset.verification_status == VerificationStatus.FAILED)
    )
    new_7d = await db.execute(
        select(func.count(Asset.id)).where(Asset.created_at >= seven_days_ago)
    )

    assets = AssetPosture(
        total=asset_total.scalar() or 0,
        by_type=by_type,
        verified=verified.scalar() or 0,
        pending=pending_v.scalar() or 0,
        failed=failed_v.scalar() or 0,
        new_7d=new_7d.scalar() or 0,
    )

    user_total = await db.execute(select(func.count(User.id)))
    user_active = await db.execute(
        select(func.count(User.id)).where(
            and_(User.is_active == True, User.last_login_at >= seven_days_ago)  # noqa: E712
        )
    )
    role_rows = await db.execute(select(User.role, func.count(User.id)).group_by(User.role))
    by_role = {r.value: cnt for r, cnt in role_rows.all()}
    assigned_f = await db.execute(
        select(func.count(Finding.id)).where(Finding.assigned_to.isnot(None))
    )

    users = UserWorkload(
        total_users=user_total.scalar() or 0,
        active_users_7d=user_active.scalar() or 0,
        by_role=by_role,
        assigned_findings=assigned_f.scalar() or 0,
        assigned_remediations=0,
    )

    return DashboardData(
        overview=overview,
        compliance=compliance,
        risk=risk,
        progress=progress,
        assets=assets,
        users=users,
        generated_at=now,
    )


@router.get("/recent-activities")
async def get_recent_activities(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    activities = []

    proj_rows = await db.execute(
        select(Project).order_by(Project.created_at.desc()).limit(limit)
    )
    for p in proj_rows.scalars().all():
        activities.append({
            "type": "project_created",
            "timestamp": p.created_at.isoformat() if p.created_at else None,
            "title": f"项目创建：{p.name}",
            "description": f"等级：{p.compliance_level.value}",
            "level": "info",
        })

    finding_rows = await db.execute(
        select(Finding).order_by(Finding.created_at.desc()).limit(limit)
    )
    for f in finding_rows.scalars().all():
        sev = f.severity.value if f.severity else "unknown"
        level = "critical" if sev == "critical" else "warning" if sev in ("high", "medium") else "info"
        activities.append({
            "type": "finding_created",
            "timestamp": f.created_at.isoformat() if f.created_at else None,
            "title": f"发现漏洞：{f.clause_name or f.clause_id}",
            "description": f"等级：{sev} | 判断：{f.judgment.value if f.judgment else 'unknown'}",
            "level": level,
        })

    activities.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return {"activities": activities[:limit]}


@router.get("/compliance-trend")
async def get_compliance_trend(
    days: int = Query(30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.utcnow()
    trend = []
    for i in range(days):
        day = now - timedelta(days=days - i - 1)
        trend.append({
            "date": day.strftime("%Y-%m-%d"),
            "score": 0.0,
            "passed": 0,
            "failed": 0,
        })
    return {"trend": trend, "note": "需要历史快照表，目前返回空骨架"}