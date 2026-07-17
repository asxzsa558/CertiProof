"""Persisted direct-Finding verification worker."""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.secret_box import decrypt_json
from app.models.document_knowledge import DocumentAnalysisRun
from app.models.finding import Finding
from app.models.verification import VerificationItem, VerificationOutcome, VerificationRun, VerificationRunStatus
from app.services.task_executor import TaskExecutor
from app.services.verification_service import (
    add_finding_event,
    apply_verification_outcome,
    finish_verification_run,
    make_finding_fingerprint,
)


WORKER_ID = f"verification-worker-{os.getenv('HOSTNAME', 'local')}-{os.getpid()}"
CAPABILITY_TASK_TYPES = {
    "scan_ports": "high_risk_port_scan",
    "masscan_scan": "asset_discovery",
    "fping_scan": "asset_discovery",
    "scan_vulnerabilities": "basic_vulnerability_scan",
    "baseline_check": "basic_baseline_check",
    "scan_weak_passwords": "basic_weak_password_scan",
    "scan_ssl": "basic_ssl_tls_scan",
    "nikto_scan": "web_vulnerability_assessment",
    "sqlmap_scan": "sql_injection_assessment",
    "web_discovery_scan": "directory_discovery_assessment",
    "ffuf_scan": "web_fuzz_assessment",
    "database_security_scan": "database_security_assessment",
    "network_device_scan": "network_device_assessment",
    "windows_security_scan": "windows_ad_smb_assessment",
}


async def _renew_verification_lease(db: AsyncSession, run_id: int) -> bool:
    now = datetime.utcnow()
    renewed = await db.execute(update(VerificationRun).where(
        VerificationRun.id == run_id,
        VerificationRun.status == VerificationRunStatus.RUNNING,
        VerificationRun.lease_owner == WORKER_ID,
        VerificationRun.cancel_requested_at.is_(None),
    ).values(
        heartbeat_at=now,
        lease_expires_at=now + timedelta(minutes=settings.TASK_LEASE_MINUTES),
    ))
    await db.commit()
    return renewed.rowcount == 1


async def _monitor_verification_lease(run_id: int) -> None:
    while True:
        await asyncio.sleep(max(1, settings.TASK_HEARTBEAT_SECONDS))
        async with AsyncSessionLocal() as db:
            if not await _renew_verification_lease(db, run_id):
                return


def _document_clause_statuses(run: DocumentAnalysisRun) -> tuple[dict[str, str], bool]:
    analysis = run.result_summary or {}
    if analysis.get("status") == "unable":
        return {}, False
    statuses = {}
    for control in analysis.get("controls", []):
        for point in control.get("points", []):
            statuses[f"DOC-TASK-{run.task_id}-{control.get('id')}-{point.get('id')}"] = point.get("status") or "unable"
    return statuses, bool(statuses)


async def _process_document_items(db: AsyncSession, items: list[VerificationItem]) -> None:
    for item in items:
        run = await db.get(DocumentAnalysisRun, item.current_document_run_id) if item.current_document_run_id else None
        if not run or run.status in {"queued", "running"}:
            continue
        if item.outcome not in {VerificationOutcome.QUEUED, VerificationOutcome.RUNNING}:
            continue
        if run.status in {"failed", "cancelled"}:
            outcome = VerificationOutcome.CANCELLED if run.status == "cancelled" else VerificationOutcome.UNABLE
            await apply_verification_outcome(db, item, outcome, error=run.error_message or f"文档复测{run.status}")
            continue
        statuses, reliable = _document_clause_statuses(run)
        finding = await db.get(Finding, item.finding_id)
        if not reliable or not finding:
            await apply_verification_outcome(db, item, VerificationOutcome.UNABLE, error="文档复测结果不完整，不能关闭原问题")
        elif finding.clause_id.endswith("-ANALYSIS-UNABLE"):
            await apply_verification_outcome(
                db, item, VerificationOutcome.FIXED,
                observation={"analysis_status": "completed", "run_id": run.id},
                comparison={"before": "unable", "after": "completed"},
            )
        elif statuses.get(finding.clause_id) in {"fail", "partial"}:
            await apply_verification_outcome(
                db, item, VerificationOutcome.STILL_PRESENT,
                observation={"clause_id": finding.clause_id, "present": True, "run_id": run.id},
                comparison={"before": "fail", "after": statuses[finding.clause_id]},
            )
        elif statuses.get(finding.clause_id) == "pass":
            await apply_verification_outcome(
                db, item, VerificationOutcome.FIXED,
                observation={"clause_id": finding.clause_id, "present": False, "run_id": run.id},
                comparison={"before": "fail", "after": "pass"},
            )
        else:
            await apply_verification_outcome(
                db, item, VerificationOutcome.UNABLE,
                error="本次文档分析没有覆盖原检查点，不能判定为已修复",
                observation={"clause_id": finding.clause_id, "status": statuses.get(finding.clause_id, "missing"), "run_id": run.id},
            )


async def _process_technical_group(
    db: AsyncSession,
    run: VerificationRun,
    items: list[VerificationItem],
    credentials: dict,
) -> None:
    target = items[0].target or ""
    capability = items[0].capability or ""
    task_type = CAPABILITY_TASK_TYPES.get(capability)
    if not target or not task_type:
        for item in items:
            await apply_verification_outcome(db, item, VerificationOutcome.UNABLE, error=f"缺少可复测的目标或工具能力：{capability or '未知'}")
        return
    for item in items:
        item.outcome = VerificationOutcome.RUNNING
        item.started_at = item.started_at or datetime.utcnow()
    await db.commit()

    try:
        result = await TaskExecutor(db).execute_task(
            task_type=task_type,
            target=target,
            project_id=run.project_id,
            user_id=run.requested_by,
            params=credentials.get(target) or {},
        )
    except Exception as exc:
        for item in items:
            await apply_verification_outcome(db, item, VerificationOutcome.UNABLE, error=str(exc))
        return

    scan_task_id = result.get("scan_task_id")
    execution = next((entry for entry in result.get("results", []) if entry.get("capability") == capability), None)
    complete = result.get("status") == "completed" and execution and execution.get("status") == "completed"
    if not complete:
        errors = [entry.get("error") for entry in result.get("failed", []) if entry.get("error")]
        errors.extend(
            entry.get("error") or entry.get("warning")
            for entry in result.get("warnings", [])
            if entry.get("error") or entry.get("warning")
        )
        error = "；".join(errors) or "技术复测未完整执行，原问题保持未关闭"
        for item in items:
            item.current_scan_task_id = scan_task_id
            await apply_verification_outcome(
                db, item, VerificationOutcome.UNABLE, error=error,
                observation={"execution_status": result.get("status")},
            )
        return

    current = TaskExecutor._risk_items(capability, execution, target)
    current_fingerprints = {
        make_finding_fingerprint("technical", target, capability, risk.get("risk_key") or risk["description"]): risk
        for risk in current
    }
    for item in items:
        item.current_scan_task_id = scan_task_id
        risk = current_fingerprints.get(item.fingerprint)
        if risk:
            await apply_verification_outcome(
                db, item, VerificationOutcome.STILL_PRESENT,
                observation={"present": True, "scan_task_id": scan_task_id, "risk": risk},
                comparison={"before": "present", "after": "present"},
            )
        else:
            await apply_verification_outcome(
                db, item, VerificationOutcome.FIXED,
                observation={"present": False, "scan_task_id": scan_task_id},
                comparison={"before": "present", "after": "absent"},
            )

    baseline_ids = {item.finding_id for item in items}
    new_findings = (await db.execute(select(Finding).where(
        Finding.scan_task_id == scan_task_id,
        Finding.id.not_in(baseline_ids),
    ))).scalars().all()
    for finding in new_findings:
        new_item = VerificationItem(
            run_id=run.id,
            project_id=run.project_id,
            finding_id=finding.id,
            source_type="technical",
            target=finding.scope_key,
            capability=finding.source_key,
            fingerprint=finding.fingerprint or "",
            outcome=VerificationOutcome.NEW,
            current_scan_task_id=scan_task_id,
            current_observation={"present": True, "description": finding.description},
            comparison={"before": "absent", "after": "present"},
            completed_at=datetime.utcnow(),
        )
        db.add(new_item)
        await db.flush()
        await add_finding_event(db, finding, "verification_new", verification_item=new_item, data={"scan_task_id": scan_task_id})


async def _run_verification(run_id: int) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.get(VerificationRun, run_id)
        if not run or run.status not in {VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING}:
            return
        items = (await db.execute(
            select(VerificationItem).where(VerificationItem.run_id == run.id).order_by(VerificationItem.id)
        )).scalars().all()
        if run.cancel_requested_at:
            for item in items:
                if item.outcome in {VerificationOutcome.QUEUED, VerificationOutcome.RUNNING}:
                    await apply_verification_outcome(db, item, VerificationOutcome.CANCELLED, error="用户停止复测")
            run.status = VerificationRunStatus.CANCELLED
            run.completed_at = datetime.utcnow()
            run.credential_envelope = None
            await db.commit()
            return

        try:
            credentials = decrypt_json(run.credential_envelope) if run.credential_envelope else {}
        except ValueError as exc:
            credentials = {}
            for item in items:
                if item.source_type == "technical":
                    await apply_verification_outcome(db, item, VerificationOutcome.UNABLE, error=str(exc))

        run.status = VerificationRunStatus.RUNNING
        run.started_at = run.started_at or datetime.utcnow()
        run.heartbeat_at = datetime.utcnow()
        await _process_document_items(db, [item for item in items if item.source_type == "document"])

        groups: dict[tuple[str, str], list[VerificationItem]] = {}
        for item in items:
            if item.source_type == "technical" and item.outcome == VerificationOutcome.QUEUED:
                groups.setdefault((item.target or "", item.capability or ""), []).append(item)
        for group in groups.values():
            if run.cancel_requested_at:
                break
            await _process_technical_group(db, run, group, credentials)
            run.heartbeat_at = datetime.utcnow()
            run.lease_expires_at = datetime.utcnow() + timedelta(minutes=settings.TASK_LEASE_MINUTES)
            await db.commit()

        await finish_verification_run(db, run)
        if run.status not in {
            VerificationRunStatus.COMPLETED, VerificationRunStatus.PARTIAL,
            VerificationRunStatus.FAILED, VerificationRunStatus.CANCELLED,
        }:
            run.lease_owner = None
            run.lease_expires_at = None
        await db.commit()


async def process_pending_verification_runs(db: AsyncSession, limit: int = 5) -> int:
    now = datetime.utcnow()
    runs = (await db.execute(select(VerificationRun).where(
        VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
        or_(VerificationRun.lease_expires_at.is_(None), VerificationRun.lease_expires_at < now),
    ).order_by(VerificationRun.created_at).limit(limit))).scalars().all()
    claimed = []
    for run in runs:
        recovering = (
            run.status == VerificationRunStatus.RUNNING
            and run.lease_owner is not None
            and run.lease_expires_at is not None
            and run.lease_expires_at < now
        )
        next_attempt = run.attempt_count + (1 if run.status == VerificationRunStatus.QUEUED or recovering else 0)
        if next_attempt > settings.TASK_MAX_RECOVERY_ATTEMPTS:
            items = (await db.execute(select(VerificationItem).where(VerificationItem.run_id == run.id))).scalars().all()
            for item in items:
                if item.outcome in {VerificationOutcome.QUEUED, VerificationOutcome.RUNNING}:
                    await apply_verification_outcome(db, item, VerificationOutcome.UNABLE, error="复测连续中断，已达到自动恢复上限")
            run.status = VerificationRunStatus.FAILED
            run.completed_at = now
            run.credential_envelope = None
            continue
        claim = await db.execute(update(VerificationRun).where(
            VerificationRun.id == run.id,
            VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
            or_(VerificationRun.lease_expires_at.is_(None), VerificationRun.lease_expires_at < now),
        ).values(
            status=VerificationRunStatus.RUNNING,
            lease_owner=WORKER_ID,
            lease_expires_at=now + timedelta(minutes=settings.TASK_LEASE_MINUTES),
            heartbeat_at=now,
            attempt_count=next_attempt,
        ))
        if claim.rowcount == 1:
            claimed.append(run.id)
    await db.commit()
    for run_id in claimed:
        monitor = asyncio.create_task(_monitor_verification_lease(run_id))
        try:
            await _run_verification(run_id)
        finally:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
    return len(claimed)
