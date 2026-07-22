"""Persist reliable findings produced outside a formal assessment."""

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.scan_task import ScanTask
from app.services.asset_scope import target_identity
from app.services.display_names import CAPABILITY_DISPLAY_NAMES
from app.services.verification_service import add_finding_event, make_finding_fingerprint


SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.INFO,
}


def _reliable_execution(execution: dict) -> bool:
    data = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    return (
        execution.get("status") == "success"
        and data.get("scan_completed") is not False
        and data.get("reachable") is not False
        and not data.get("tool_error")
        and not data.get("connection_error")
    )


def _execution_units(execution: dict):
    capability = str(execution.get("capability") or "").strip()
    if capability:
        yield capability, execution
    data = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    for sub in data.get("sub_results") or []:
        if not isinstance(sub, dict):
            continue
        child = {
            "capability": sub.get("capability") or capability,
            "target": sub.get("target") or execution.get("target"),
            "status": sub.get("status"),
            "error": sub.get("error"),
            "result": sub.get("data") if isinstance(sub.get("data"), dict) else {},
        }
        yield from _execution_units(child)


async def sync_independent_findings(
    db: AsyncSession,
    scan_task: ScanTask,
    executions: list[dict],
    *,
    actor_id: int | None = None,
) -> dict:
    """Upsert real risks and close them only after a reliable clean rerun."""
    if scan_task.assessment_id is not None:
        return {"tracked": 0, "resolved": 0, "finding_ids": []}

    from app.services.task_executor import TaskExecutor

    assets = list((await db.execute(select(Asset).where(
        Asset.project_id == scan_task.project_id,
        Asset.is_active.is_(True),
    ))).scalars().all())
    assets_by_identity = {target_identity(asset.value): asset for asset in assets}
    source = (scan_task.parameters or {}).get("source") or "interactive"
    source_channel = "scheduled" if source == "scheduled_monitoring" else "interactive"
    now = datetime.utcnow()
    touched_ids: list[int] = []
    resolved = 0
    severities: list[Severity] = []

    for execution in executions:
        capability = str(execution.get("capability") or "").strip()
        target = str(execution.get("target") or "").strip()
        if not capability or not target:
            continue
        asset = assets_by_identity.get(target_identity(target))
        if not asset:
            continue
        scope_key = asset.value
        items = [
            item for item in TaskExecutor._risk_items(capability, execution, scope_key)
            if item.get("judgment") != "not_tested"
        ]
        current_fingerprints: dict[str, set[str]] = defaultdict(set)

        for item in items:
            item_capability = str(item.get("capability") or capability)
            fingerprint = make_finding_fingerprint(
                "technical", scope_key, item_capability, str(item.get("risk_key") or item["description"]),
            )
            current_fingerprints[item_capability].add(fingerprint)
            severity = SEVERITY_MAP.get(str(item.get("severity") or "medium").lower(), Severity.MEDIUM)
            finding = (await db.execute(select(Finding).where(
                Finding.project_id == scan_task.project_id,
                Finding.assessment_id.is_(None),
                Finding.fingerprint == fingerprint,
            ))).scalar_one_or_none()
            if finding:
                finding.asset_id = asset.id
                finding.scan_task_id = scan_task.id
                finding.source_channel = source_channel
                finding.description = item["description"]
                finding.severity = severity
                finding.judgment = Judgment.FAIL
                finding.last_seen_at = now
                finding.occurrence_count = (finding.occurrence_count or 0) + 1
                if finding.status == FindingStatus.FIXED:
                    finding.status = FindingStatus.OPEN
                    finding.resolved_at = None
                    event_type = "finding_reopened"
                else:
                    event_type = "finding_detected"
            else:
                finding = Finding(
                    project_id=scan_task.project_id,
                    assessment_id=None,
                    asset_id=asset.id,
                    scan_task_id=scan_task.id,
                    fingerprint=fingerprint,
                    source_type="technical",
                    source_channel=source_channel,
                    source_key=item_capability,
                    scope_key=scope_key,
                    clause_id=f"TECH-{item_capability.upper()[:40]}",
                    clause_name=CAPABILITY_DISPLAY_NAMES.get(item_capability, item_capability),
                    severity=severity,
                    judgment=Judgment.FAIL,
                    judgment_engine=JudgmentEngine.RULE,
                    description=item["description"],
                    remediation_suggestion=item.get("remediation") or "确认风险是否为业务必要；按最小暴露原则修复后重新执行同一检测。",
                    status=FindingStatus.OPEN,
                    last_seen_at=now,
                    occurrence_count=1,
                )
                db.add(finding)
                await db.flush()
                event_type = "finding_created"
            await add_finding_event(
                db,
                finding,
                event_type,
                actor_id=actor_id,
                data={"scan_task_id": scan_task.id, "source_channel": source_channel},
            )
            touched_ids.append(finding.id)
            severities.append(severity)

        reliable_capabilities = {
            unit_capability
            for unit_capability, unit in _execution_units(execution)
            if _reliable_execution(unit)
        }
        for reliable_capability in reliable_capabilities:
            previous = list((await db.execute(select(Finding).where(
                Finding.project_id == scan_task.project_id,
                Finding.assessment_id.is_(None),
                Finding.source_type == "technical",
                Finding.source_key == reliable_capability,
                Finding.scope_key == scope_key,
                Finding.status == FindingStatus.OPEN,
            ))).scalars().all())
            for finding in previous:
                if finding.fingerprint in current_fingerprints[reliable_capability]:
                    continue
                finding.status = FindingStatus.FIXED
                finding.resolved_at = now
                finding.scan_task_id = scan_task.id
                await add_finding_event(
                    db,
                    finding,
                    "verification_fixed",
                    actor_id=actor_id,
                    data={"scan_task_id": scan_task.id, "automatic": True},
                )
                resolved += 1

    scan_task.findings_count = len(set(touched_ids))
    scan_task.high_severity_count = sum(value in {Severity.CRITICAL, Severity.HIGH} for value in severities)
    scan_task.medium_severity_count = sum(value == Severity.MEDIUM for value in severities)
    scan_task.low_severity_count = sum(value in {Severity.LOW, Severity.INFO} for value in severities)
    return {"tracked": scan_task.findings_count, "resolved": resolved, "finding_ids": sorted(set(touched_ids))}
