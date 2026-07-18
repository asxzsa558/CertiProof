"""Direct Finding remediation and verification lifecycle."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_box import encrypt_json
from app.models.assessment import Assessment, PhaseInstance, TaskInstance
from app.models.finding import Finding, FindingStatus
from app.models.verification import (
    FindingEvent,
    VerificationItem,
    VerificationOutcome,
    VerificationRun,
    VerificationRunStatus,
)


SENSITIVE_PARAMETER_KEYS = {
    "password", "passphrase", "private_key", "key_file", "token", "secret", "credential_envelope",
}


def scrub_sensitive_parameters(value):
    if isinstance(value, dict):
        return {
            key: scrub_sensitive_parameters(item)
            for key, item in value.items()
            if key.lower() not in SENSITIVE_PARAMETER_KEYS and not key.startswith("_")
        }
    if isinstance(value, list):
        return [scrub_sensitive_parameters(item) for item in value]
    return value


def make_finding_fingerprint(source_type: str, scope_key: str, source_key: str, risk_key: str) -> str:
    canonical = json.dumps(
        [source_type.strip().lower(), scope_key.strip().lower(), source_key.strip().lower(), risk_key.strip().lower()],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def add_finding_event(
    db: AsyncSession,
    finding: Finding,
    event_type: str,
    *,
    verification_item: VerificationItem | None = None,
    actor_id: int | None = None,
    data: dict | None = None,
) -> FindingEvent:
    event = FindingEvent(
        project_id=finding.project_id,
        finding_id=finding.id,
        verification_item_id=verification_item.id if verification_item else None,
        event_type=event_type,
        event_data=data or {},
        actor_id=actor_id,
    )
    db.add(event)
    return event


async def delete_verification_data(
    db: AsyncSession,
    project_id: int,
    finding_ids: Iterable[int] | None = None,
) -> None:
    scoped_ids = list(dict.fromkeys(int(value) for value in finding_ids or []))
    if finding_ids is not None and not scoped_ids:
        return
    if finding_ids is None:
        await db.execute(delete(FindingEvent).where(FindingEvent.project_id == project_id))
        await db.execute(delete(VerificationItem).where(VerificationItem.project_id == project_id))
        await db.execute(delete(VerificationRun).where(VerificationRun.project_id == project_id))
        return

    run_ids = list((await db.execute(
        select(VerificationItem.run_id).where(VerificationItem.finding_id.in_(scoped_ids)).distinct()
    )).scalars().all())
    await db.execute(delete(FindingEvent).where(FindingEvent.finding_id.in_(scoped_ids)))
    await db.execute(delete(VerificationItem).where(VerificationItem.finding_id.in_(scoped_ids)))
    for run_id in run_ids:
        remaining = (await db.execute(
            select(VerificationItem.id).where(VerificationItem.run_id == run_id).limit(1)
        )).scalar_one_or_none()
        if remaining is None:
            await db.execute(delete(VerificationRun).where(VerificationRun.id == run_id))


async def reset_verification_data(db: AsyncSession, project_id: int) -> None:
    await delete_verification_data(db, project_id)
    findings = (await db.execute(select(Finding).where(
        Finding.project_id == project_id,
        Finding.status.not_in([FindingStatus.FALSE_POSITIVE]),
    ))).scalars().all()
    for finding in findings:
        finding.status = FindingStatus.OPEN
        finding.resolved_at = None


async def latest_assessment_and_phase(db: AsyncSession, project_id: int) -> tuple[Assessment, PhaseInstance]:
    assessment = (await db.execute(
        select(Assessment).where(Assessment.project_id == project_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1)
    )).scalar_one_or_none()
    if not assessment:
        raise ValueError("当前项目尚未创建等保测评")
    phase = (await db.execute(select(PhaseInstance).where(
        PhaseInstance.assessment_id == assessment.id,
        PhaseInstance.phase_id == "remediation_verification",
    ))).scalar_one_or_none()
    if not phase:
        raise ValueError("当前测评缺少整改与复测阶段")
    return assessment, phase


async def create_verification_run(
    db: AsyncSession,
    *,
    project_id: int,
    findings: Iterable[Finding],
    source_type: str,
    actor_id: int,
    notes: str = "",
    credentials: dict | None = None,
    document_file_ids: list[int] | None = None,
) -> VerificationRun:
    findings = list(findings)
    if not findings:
        raise ValueError("没有可复测的问题")
    if any(finding.project_id != project_id for finding in findings):
        raise ValueError("复测问题不属于当前项目")
    if any((finding.source_type or "") != source_type for finding in findings):
        raise ValueError("一次复测只能处理同一种问题来源")
    active = (await db.execute(select(VerificationItem.finding_id).join(VerificationRun).where(
        VerificationItem.finding_id.in_([finding.id for finding in findings]),
        VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
    ))).scalars().all()
    if active:
        raise ValueError(f"所选问题已有复测在执行：{sorted(set(active))}")

    assessment, phase = await latest_assessment_and_phase(db, project_id)
    from app.services.report_service import invalidate_report_artifacts
    await invalidate_report_artifacts(db, project_id, "已发起新的整改复测")
    run = VerificationRun(
        project_id=project_id,
        assessment_id=assessment.id,
        phase_id=phase.id,
        source_type=source_type,
        requested_by=actor_id,
        notes=notes.strip() or None,
        document_file_ids=document_file_ids or [],
        credential_envelope=encrypt_json(credentials) if credentials else None,
        summary={"total": len(findings), "completed": 0},
    )
    db.add(run)
    await db.flush()
    for finding in findings:
        item = VerificationItem(
            run_id=run.id,
            project_id=project_id,
            finding_id=finding.id,
            source_type=source_type,
            target=finding.scope_key,
            capability=finding.source_key,
            fingerprint=finding.fingerprint or make_finding_fingerprint(
                source_type, finding.scope_key or "", finding.source_key or finding.clause_id, finding.clause_id,
            ),
            baseline_scan_task_id=finding.scan_task_id,
            baseline_document_run_id=finding.document_run_id,
            baseline_observation={
                "description": finding.description,
                "judgment": getattr(finding.judgment, "value", finding.judgment),
                "severity": getattr(finding.severity, "value", finding.severity),
            },
        )
        db.add(item)
        await db.flush()
        await add_finding_event(db, finding, "verification_queued", verification_item=item, actor_id=actor_id)
    await reconcile_verification_phase(db, project_id)
    return run


async def queue_document_task_verification(
    db: AsyncSession,
    *,
    project_id: int,
    task: TaskInstance,
    actor_id: int,
    analysis_mode: str,
    notes: str = "",
) -> tuple[VerificationRun, object, list[int], int]:
    """Queue one full document-category recheck against its open findings."""
    phase = await db.get(PhaseInstance, task.phase_id)
    assessment = await db.get(Assessment, phase.assessment_id) if phase else None
    if not assessment or assessment.project_id != project_id:
        raise ValueError("原文档检查任务不属于当前项目")
    findings = list((await db.execute(select(Finding).where(
        Finding.project_id == project_id,
        Finding.source_type == "document",
        Finding.scope_key == f"task:{task.id}",
        Finding.status == FindingStatus.OPEN,
    ))).scalars().all())
    if not findings:
        raise ValueError("该类文档当前没有待复测问题")

    from app.models.document_knowledge import DocumentFile
    active_ids = list((await db.execute(select(DocumentFile.id).where(
        DocumentFile.assessment_id == assessment.id,
        DocumentFile.task_id == task.id,
        DocumentFile.is_active.is_(True),
    ))).scalars().all())
    if not active_ids:
        raise ValueError("该类文档没有可重新分析的有效材料")

    verification = await create_verification_run(
        db,
        project_id=project_id,
        findings=findings,
        source_type="document",
        actor_id=actor_id,
        notes=notes,
        document_file_ids=active_ids,
    )
    from app.services.document_pipeline import create_document_run
    document_run = await create_document_run(
        db,
        task,
        project_id,
        actor_id,
        analysis_mode,
        run_parameters={"verification_run_id": verification.id},
    )
    items = (await db.execute(select(VerificationItem).where(
        VerificationItem.run_id == verification.id
    ))).scalars().all()
    for item in items:
        item.current_document_run_id = document_run.id
    await db.commit()
    return verification, document_run, active_ids, len(findings)


async def apply_verification_outcome(
    db: AsyncSession,
    item: VerificationItem,
    outcome: VerificationOutcome,
    *,
    observation: dict | None = None,
    comparison: dict | None = None,
    error: str | None = None,
) -> None:
    finding = await db.get(Finding, item.finding_id)
    if not finding:
        raise ValueError("复测项关联的问题不存在")
    item.outcome = outcome
    item.current_observation = observation or {}
    item.comparison = comparison or {}
    item.error_message = error
    item.completed_at = datetime.utcnow()
    if outcome == VerificationOutcome.FIXED:
        finding.status = FindingStatus.FIXED
        finding.resolved_at = datetime.utcnow()
        event_type = "verification_fixed"
    elif outcome in {VerificationOutcome.STILL_PRESENT, VerificationOutcome.UNABLE, VerificationOutcome.CANCELLED}:
        finding.status = FindingStatus.OPEN
        finding.resolved_at = None
        event_type = f"verification_{outcome.value}"
    else:
        event_type = "verification_new"
    await add_finding_event(
        db, finding, event_type, verification_item=item,
        data={"error": error, "comparison": comparison or {}},
    )


async def finish_verification_run(db: AsyncSession, run: VerificationRun) -> None:
    items = (await db.execute(select(VerificationItem).where(VerificationItem.run_id == run.id))).scalars().all()
    counts = {outcome.value: 0 for outcome in VerificationOutcome}
    for item in items:
        key = getattr(item.outcome, "value", item.outcome)
        counts[key] = counts.get(key, 0) + 1
    terminal = {
        VerificationOutcome.FIXED, VerificationOutcome.STILL_PRESENT, VerificationOutcome.NEW,
        VerificationOutcome.UNABLE, VerificationOutcome.CANCELLED,
    }
    if items and all(item.outcome in terminal for item in items):
        run.status = (
            VerificationRunStatus.COMPLETED
            if not counts["unable"] and not counts["cancelled"]
            else VerificationRunStatus.PARTIAL
        )
        run.completed_at = datetime.utcnow()
        run.lease_owner = None
        run.lease_expires_at = None
        run.credential_envelope = None
    run.summary = {"total": len(items), "completed": sum(counts[item.value] for item in terminal), **counts}
    await reconcile_verification_phase(db, run.project_id)


async def reopen_finding(db: AsyncSession, finding: Finding, actor_id: int) -> None:
    finding.status = FindingStatus.OPEN
    finding.resolved_at = None
    await add_finding_event(db, finding, "finding_reopened", actor_id=actor_id)
    await reconcile_verification_phase(db, finding.project_id)


async def reconcile_verification_phase(db: AsyncSession, project_id: int) -> None:
    assessment = (await db.execute(
        select(Assessment).where(Assessment.project_id == project_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1)
    )).scalar_one_or_none()
    if not assessment:
        return
    phases = (await db.execute(
        select(PhaseInstance).where(PhaseInstance.assessment_id == assessment.id).order_by(PhaseInstance.order)
    )).scalars().all()
    by_key = {phase.phase_id: phase for phase in phases}
    gap = by_key.get("gap_analysis")
    field = by_key.get("field_assessment")
    verification = by_key.get("remediation_verification")
    report = by_key.get("report")
    if not field or not verification:
        return

    findings = (await db.execute(select(Finding).where(
        Finding.project_id == project_id,
        Finding.status != FindingStatus.FALSE_POSITIVE,
    ))).scalars().all()
    reviewed_ids = set((await db.execute(select(VerificationItem.finding_id).where(
        VerificationItem.project_id == project_id,
        VerificationItem.outcome.in_([
            VerificationOutcome.FIXED,
            VerificationOutcome.STILL_PRESENT,
            VerificationOutcome.UNABLE,
            VerificationOutcome.NEW,
        ]),
    ))).scalars().all())
    reviewed = sum(finding.status == FindingStatus.FIXED or finding.id in reviewed_ids for finding in findings)
    active_runs = int((await db.execute(select(VerificationRun.id).where(
        VerificationRun.project_id == project_id,
        VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
    ))).scalars().first() is not None)
    explicitly_finalized = bool((verification.outputs or {}).get("continued_to_report"))
    if active_runs and explicitly_finalized:
        verification.outputs = None
        explicitly_finalized = False
    upstream_done = bool(gap and gap.status == "completed" and field.status == "completed")
    failed_tasks = (await db.execute(
        select(TaskInstance).join(PhaseInstance, PhaseInstance.id == TaskInstance.phase_id).where(
            PhaseInstance.assessment_id == assessment.id,
            PhaseInstance.phase_id.in_(["gap_analysis", "field_assessment"]),
            TaskInstance.status == "failed",
        )
    )).scalars().all()
    from app.services.task_executor import TASK_CAPABILITY_MAP
    execution_blockers = []
    for task in failed_tasks:
        capabilities = set((TASK_CAPABILITY_MAP.get(task.task_type) or {}).get("capabilities") or [])
        represented = any(
            (finding.source_type == "document" and finding.scope_key == f"task:{task.id}")
            or (finding.source_type == "technical" and finding.source_key in capabilities)
            for finding in findings
        )
        if not represented:
            execution_blockers.append(task.id)
    total_work = len(findings) + len(execution_blockers)
    review_progress = (reviewed / total_work * 100) if total_work else (100 if upstream_done else 0)
    verification.total_tasks = total_work
    verification.completed_tasks = reviewed
    verification.progress = 100 if explicitly_finalized and not active_runs else review_progress
    if explicitly_finalized:
        verification.outputs = {
            **(verification.outputs or {}),
            "review_progress": round(review_progress, 1),
            "finding_summary": {
                "total": len(findings),
                "open": sum(finding.status == FindingStatus.OPEN for finding in findings),
                "fixed": sum(finding.status == FindingStatus.FIXED for finding in findings),
            },
        }
    report_must_wait = False
    if not upstream_done:
        verification.progress = review_progress
        if explicitly_finalized:
            verification.outputs = None
        verification.status = "pending"
        verification.started_at = None
        verification.completed_at = None
        report_must_wait = True
    elif explicitly_finalized and not active_runs:
        verification.status = "completed"
        verification.started_at = verification.started_at or datetime.utcnow()
        verification.completed_at = verification.completed_at or datetime.utcnow()
        if report and report.status == "pending":
            report.status = "active"
            report.started_at = report.started_at or datetime.utcnow()
    elif reviewed == len(findings) and not execution_blockers and not active_runs:
        verification.status = "completed"
        verification.started_at = verification.started_at or datetime.utcnow()
        verification.completed_at = verification.completed_at or datetime.utcnow()
        if report and report.status == "pending":
            report.status = "active"
            report.started_at = report.started_at or datetime.utcnow()
    else:
        verification.status = "active"
        verification.started_at = verification.started_at or datetime.utcnow()
        verification.completed_at = None
        report_must_wait = True

    if report and report_must_wait:
        from app.services.report_service import invalidate_report_artifacts
        await invalidate_report_artifacts(db, project_id, "测评或复测状态已变化")
        report.status = "pending"
        report.progress = 0
        report.completed_tasks = 0
        report.started_at = None
        report.completed_at = None
        report.outputs = None
        report_tasks = (await db.execute(
            select(TaskInstance).where(TaskInstance.phase_id == report.id)
        )).scalars().all()
        for task in report_tasks:
            task.status = "todo"
            task.result = None
            task.evidence_ids = None
            task.started_at = None
            task.completed_at = None
            task.lease_owner = None
            task.lease_expires_at = None
            task.heartbeat_at = None
            task.cancel_requested_at = None

    from app.services.flow_engine import workflow_progress

    assessment.completed_phases = sum(phase.status == "completed" for phase in phases)
    assessment.total_phases = len(phases)
    assessment.progress = workflow_progress(phases)
    if assessment.completed_phases < assessment.total_phases:
        assessment.status = "in_progress" if any(phase.status != "pending" for phase in phases) else "not_started"
        assessment.completed_at = None
