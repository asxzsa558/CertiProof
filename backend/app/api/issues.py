from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.assessment import Assessment
from app.models.asset import Asset
from app.models.finding import Finding, FindingStatus
from app.models.user import User
from app.services.display_names import CAPABILITY_DISPLAY_NAMES
from app.services.report_service import invalidate_report_artifacts
from app.services.verification_service import add_finding_event, controlled_remediation_plan, reconcile_verification_phase


router = APIRouter(prefix="/projects/{project_id}/issues", tags=["Issues"])


class PromoteIssueRequest(BaseModel):
    assessment_code: Literal["dengbao", "miping"]


def _value(value):
    return getattr(value, "value", value)


async def _require_project(db: AsyncSession, project_id: int, current_user: User, permission: str):
    from app.api.projects import get_project_for_user
    return await get_project_for_user(db, project_id, current_user.id, permission)


@router.get("/independent")
async def independent_issues(
    project_id: int,
    finding_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "scan:read")
    query = (
        select(Finding, Asset)
        .outerjoin(Asset, Asset.id == Finding.asset_id)
        .where(Finding.project_id == project_id, Finding.assessment_id.is_(None))
        .order_by(Finding.last_seen_at.desc().nullslast(), Finding.updated_at.desc())
    )
    if finding_id is not None:
        query = query.where(Finding.id == finding_id)
    rows = (await db.execute(query)).all()
    items = [{
        "id": finding.id,
        "project_id": project_id,
        "asset": {
            "id": asset.id if asset else finding.asset_id,
            "name": asset.name if asset else None,
            "value": asset.value if asset else finding.scope_key,
            "type": _value(asset.asset_type) if asset else None,
        },
        "title": finding.clause_name or CAPABILITY_DISPLAY_NAMES.get(finding.source_key, finding.source_key) or "安全问题",
        "description": finding.description,
        "severity": _value(finding.severity),
        "status": _value(finding.status),
        "judgment": _value(finding.judgment),
        "source_channel": finding.source_channel,
        "source_key": finding.source_key,
        "source_label": "定时检测" if finding.source_channel == "scheduled" else "独立检测",
        "tool_label": CAPABILITY_DISPLAY_NAMES.get(finding.source_key, finding.source_key),
        "scan_task_id": finding.scan_task_id,
        "occurrence_count": finding.occurrence_count or 1,
        "first_seen_at": finding.created_at,
        "last_seen_at": finding.last_seen_at or finding.updated_at,
        "resolved_at": finding.resolved_at,
        "remediation_suggestion": finding.remediation_suggestion,
        "remediation_plan": controlled_remediation_plan(finding),
    } for finding, asset in rows]
    return {
        "summary": {
            "total": len(items),
            "open": sum(item["status"] == "open" for item in items),
            "fixed": sum(item["status"] == "fixed" for item in items),
            "critical_high": sum(item["status"] == "open" and item["severity"] in {"critical", "high"} for item in items),
        },
        "items": items,
    }


@router.post("/{finding_id}/promote")
async def promote_independent_issue(
    project_id: int,
    finding_id: int,
    request: PromoteIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "assessment:manage")
    source = (await db.execute(select(Finding).where(
        Finding.id == finding_id,
        Finding.project_id == project_id,
        Finding.assessment_id.is_(None),
    ))).scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="独立检测问题不存在")
    assessment = (await db.execute(select(Assessment).where(
        Assessment.project_id == project_id,
        Assessment.assessment_type_code == request.assessment_code,
    ).order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1))).scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=400, detail="当前项目尚未启用该测评类型")
    existing = (await db.execute(select(Finding).where(
        Finding.assessment_id == assessment.id,
        Finding.origin_finding_id == source.id,
    ))).scalar_one_or_none()
    if existing:
        return {"status": "exists", "finding_id": existing.id, "assessment_id": assessment.id}
    imported = Finding(
        project_id=project_id,
        assessment_id=assessment.id,
        asset_id=source.asset_id,
        scan_task_id=source.scan_task_id,
        fingerprint=source.fingerprint,
        source_type=source.source_type,
        source_channel="assessment",
        source_key=source.source_key,
        scope_key=source.scope_key,
        origin_finding_id=source.id,
        clause_id=source.clause_id,
        clause_name=source.clause_name,
        severity=source.severity,
        judgment=source.judgment,
        judgment_engine=source.judgment_engine,
        confidence=source.confidence,
        description=source.description,
        remediation_suggestion=source.remediation_suggestion,
        status=FindingStatus.OPEN,
        evidence_ids=source.evidence_ids,
        last_seen_at=source.last_seen_at or datetime.utcnow(),
        occurrence_count=source.occurrence_count or 1,
    )
    db.add(imported)
    await db.flush()
    await add_finding_event(db, source, "finding_promoted", actor_id=current_user.id, data={
        "assessment_id": assessment.id, "assessment_code": request.assessment_code, "finding_id": imported.id,
    })
    await add_finding_event(db, imported, "finding_imported", actor_id=current_user.id, data={
        "origin_finding_id": source.id,
    })
    await invalidate_report_artifacts(db, project_id, "已纳入新的独立检测问题", assessment_id=assessment.id)
    await reconcile_verification_phase(db, project_id, assessment.id)
    await db.commit()
    return {"status": "promoted", "finding_id": imported.id, "assessment_id": assessment.id}
