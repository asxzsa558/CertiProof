from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from datetime import datetime, timedelta
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.models.monitoring import ScheduledScan, ScanHistory, ScheduleFrequency
from app.models.change_snapshot import ChangeSnapshot
from app.schemas.monitoring import (
    ScheduledScanCreate,
    ScheduledScanUpdate,
    ScheduledScanResponse,
    ScanHistoryResponse,
)

router = APIRouter(prefix="/projects/{project_id}/monitoring", tags=["Monitoring"])


@router.get("/changes")
async def list_detected_changes(
    project_id: int,
    limit: int = 50,
    reassessment_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:read")

    query = select(ChangeSnapshot).where(ChangeSnapshot.project_id == project_id)
    if reassessment_only:
        query = query.where(ChangeSnapshot.reassessment_required.is_(True))
    result = await db.execute(query.order_by(ChangeSnapshot.id.desc()).limit(min(limit, 100)))
    return [
        {
            "id": item.id,
            "type": item.snapshot_type,
            "subject": item.subject,
            "scope": item.scope,
            "changes": item.changes or {},
            "reliable": item.reliable,
            "reassessment_required": item.reassessment_required,
            "created_at": item.created_at,
        }
        for item in result.scalars().all()
    ]


@router.post("/changes/{change_id}/acknowledge")
async def acknowledge_detected_change(
    project_id: int,
    change_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:manage")
    result = await db.execute(
        select(ChangeSnapshot).where(ChangeSnapshot.id == change_id, ChangeSnapshot.project_id == project_id)
    )
    change = result.scalar_one_or_none()
    if not change:
        raise HTTPException(status_code=404, detail="Change snapshot not found")
    change.reassessment_required = False
    await db.commit()
    return {"id": change.id, "reassessment_required": False}


def calculate_next_run(frequency: ScheduleFrequency, from_time: datetime = None) -> datetime:
    """Calculate next run time based on frequency."""
    if from_time is None:
        from_time = datetime.utcnow()
    
    if frequency == ScheduleFrequency.DAILY:
        return from_time + timedelta(days=1)
    elif frequency == ScheduleFrequency.WEEKLY:
        return from_time + timedelta(weeks=1)
    elif frequency == ScheduleFrequency.MONTHLY:
        return from_time + timedelta(days=30)
    return from_time + timedelta(days=1)


def _result_payload(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    if isinstance(data, dict):
        return data
    payload = result.get("result")
    if isinstance(payload, dict):
        return payload
    return result


def _port_number(port: dict) -> Optional[int]:
    value = port.get("port") if isinstance(port, dict) else port
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_open_ports(scan_result: dict | None) -> list[dict]:
    payload = _result_payload(scan_result)
    ports = payload.get("open_ports") or []
    normalized = []
    for item in ports:
        if isinstance(item, dict):
            port = _port_number(item)
            if port is not None:
                normalized.append({
                    "port": port,
                    "service": item.get("service") or item.get("name") or "",
                    "protocol": item.get("protocol") or "tcp",
                })
        else:
            port = _port_number(item)
            if port is not None:
                normalized.append({"port": port, "service": "", "protocol": "tcp"})
    return sorted(normalized, key=lambda p: (p["protocol"], p["port"]))


def _detect_port_changes(current_ports: list[dict], previous_summary: dict | None) -> dict:
    previous_ports = previous_summary.get("open_ports", []) if isinstance(previous_summary, dict) else []
    previous_set = {(_port_number(p), p.get("protocol", "tcp")) for p in previous_ports if isinstance(p, dict)}
    current_set = {(p["port"], p.get("protocol", "tcp")) for p in current_ports}
    added = sorted(current_set - previous_set)
    removed = sorted(previous_set - current_set)
    return {
        "changes_detected": bool(added or removed),
        "added_ports": [{"port": port, "protocol": protocol} for port, protocol in added if port is not None],
        "removed_ports": [{"port": port, "protocol": protocol} for port, protocol in removed if port is not None],
    }


def _severity_for_port(port: int):
    from app.models.finding import Severity

    if port in {21, 23, 135, 139, 445, 1433, 1521, 3306, 3389, 5432, 5900, 6379, 9200, 11211, 27017}:
        return Severity.HIGH
    if port in {22, 25, 53, 110, 143, 389, 8080, 8443}:
        return Severity.MEDIUM
    return Severity.INFO


@router.post("/scheduled", response_model=ScheduledScanResponse, status_code=status.HTTP_201_CREATED)
async def create_scheduled_scan(
    project_id: int,
    scan_data: ScheduledScanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new scheduled scan."""
    # Verify project access
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "scan:execute")
    
    # Verify asset exists
    result = await db.execute(
        select(Asset).where(Asset.id == scan_data.asset_id, Asset.project_id == project_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Calculate next run time
    next_run = calculate_next_run(scan_data.frequency)
    
    scheduled_scan = ScheduledScan(
        project_id=project_id,
        asset_id=scan_data.asset_id,
        name=scan_data.name,
        frequency=scan_data.frequency,
        is_active=True,
        next_run_at=next_run,
        scan_parameters=scan_data.scan_parameters,
        notify_on_change=scan_data.notify_on_change,
        notify_emails=scan_data.notify_emails,
    )
    db.add(scheduled_scan)
    await db.commit()
    await db.refresh(scheduled_scan)
    
    return scheduled_scan


@router.get("/scheduled", response_model=List[ScheduledScanResponse])
async def list_scheduled_scans(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all scheduled scans for a project."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "scan:read")
    
    result = await db.execute(
        select(ScheduledScan)
        .where(ScheduledScan.project_id == project_id)
        .order_by(ScheduledScan.created_at.desc())
    )
    return result.scalars().all()


@router.put("/scheduled/{scan_id}", response_model=ScheduledScanResponse)
async def update_scheduled_scan(
    project_id: int,
    scan_id: int,
    scan_data: ScheduledScanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a scheduled scan."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "scan:execute")

    result = await db.execute(
        select(ScheduledScan).where(
            ScheduledScan.id == scan_id,
            ScheduledScan.project_id == project_id
        )
    )
    scheduled_scan = result.scalar_one_or_none()
    if not scheduled_scan:
        raise HTTPException(status_code=404, detail="Scheduled scan not found")
    
    if scan_data.name is not None:
        scheduled_scan.name = scan_data.name
    if scan_data.frequency is not None:
        scheduled_scan.frequency = scan_data.frequency
        scheduled_scan.next_run_at = calculate_next_run(scan_data.frequency)
    if scan_data.is_active is not None:
        scheduled_scan.is_active = scan_data.is_active
    if scan_data.notify_on_change is not None:
        scheduled_scan.notify_on_change = scan_data.notify_on_change
    if scan_data.notify_emails is not None:
        scheduled_scan.notify_emails = scan_data.notify_emails
    if scan_data.scan_parameters is not None:
        scheduled_scan.scan_parameters = scan_data.scan_parameters
    
    await db.commit()
    await db.refresh(scheduled_scan)
    
    return scheduled_scan


@router.delete("/scheduled/{scan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scheduled_scan(
    project_id: int,
    scan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a scheduled scan."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "scan:execute")

    result = await db.execute(
        select(ScheduledScan).where(
            ScheduledScan.id == scan_id,
            ScheduledScan.project_id == project_id
        )
    )
    scheduled_scan = result.scalar_one_or_none()
    if not scheduled_scan:
        raise HTTPException(status_code=404, detail="Scheduled scan not found")
    
    await db.delete(scheduled_scan)
    await db.commit()


@router.get("/history", response_model=List[ScanHistoryResponse])
async def get_scan_history(
    project_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get scan history with change detection."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "scan:read")
    
    result = await db.execute(
        select(ScanHistory)
        .join(ScheduledScan)
        .where(ScheduledScan.project_id == project_id)
        .order_by(ScanHistory.executed_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/scheduled/{scan_id}/run")
async def run_scheduled_scan_now(
    project_id: int,
    scan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger a scheduled scan."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "scan:execute")

    result = await db.execute(
        select(ScheduledScan).where(
            ScheduledScan.id == scan_id,
            ScheduledScan.project_id == project_id
        )
    )
    scheduled_scan = result.scalar_one_or_none()
    if not scheduled_scan:
        raise HTTPException(status_code=404, detail="Scheduled scan not found")

    return await execute_scheduled_scan(db, scheduled_scan)


async def execute_scheduled_scan(db: AsyncSession, scheduled_scan: ScheduledScan) -> dict:
    """Execute one scheduled scan and record findings/history."""
    # Import here to avoid circular imports
    from app.mcp.gateway_client import mcp_gateway_client
    from app.models.scan_task import ScanTask, ScanTaskType, ScanTaskStatus, TriggeredBy
    from app.models.finding import Finding, Judgment, JudgmentEngine, FindingStatus

    # Get asset
    result = await db.execute(
        select(Asset).where(Asset.id == scheduled_scan.asset_id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Create scan task
    scan_task = ScanTask(
        project_id=scheduled_scan.project_id,
        asset_id=scheduled_scan.asset_id,
        task_type=ScanTaskType.SCHEDULED,
        status=ScanTaskStatus.RUNNING,
        control_state="running",
        triggered_by=TriggeredBy.SCHEDULED,
        parameters={"source": "scheduled_monitoring", "scheduled_scan_id": scheduled_scan.id},
        started_at=datetime.utcnow(),
    )
    db.add(scan_task)
    await db.flush()
    
    try:
        scan_parameters = scheduled_scan.scan_parameters or {}
        port_range = scan_parameters.get("port_range", "high-risk")

        # Execute scan via MCP Gateway
        scan_result = await mcp_gateway_client.call(
            tool_name="nmap_scan",
            params={"target": asset.value, "port_range": port_range}
        )
        
        # Check SSL if HTTPS is open
        ssl_result = None
        open_ports = _normalize_open_ports(scan_result)
        if any(p["port"] == 443 for p in open_ports):
            ssl_result = await mcp_gateway_client.call(
                tool_name="testssl_scan",
                params={"target": asset.value, "port": 443}
            )
        
        created_findings = []
        for port in open_ports:
            if port["port"] in {22, 80, 443}:
                continue
            finding = Finding(
                project_id=scheduled_scan.project_id,
                scan_task_id=scan_task.id,
                clause_id="8.1.3.1",
                clause_name="边界访问控制",
                severity=_severity_for_port(port["port"]),
                judgment=Judgment.FAIL,
                judgment_engine=JudgmentEngine.RULE,
                description=f"监控发现 {asset.value} 开放 {port['protocol']}/{port['port']} {port.get('service') or ''}".strip(),
                remediation_suggestion="确认该端口是否为业务必要端口；若非必要，应通过防火墙/安全组限制访问。",
                status=FindingStatus.OPEN,
            )
            db.add(finding)
            created_findings.append(finding)

        ssl_payload = _result_payload(ssl_result)
        ssl_issues = ssl_payload.get("issues") or ssl_payload.get("findings") or []
        if ssl_issues:
            finding = Finding(
                project_id=scheduled_scan.project_id,
                scan_task_id=scan_task.id,
                clause_id="8.1.4.5",
                clause_name="通信传输安全",
                severity=_severity_for_port(443),
                judgment=Judgment.FAIL,
                judgment_engine=JudgmentEngine.RULE,
                description=f"监控发现 {asset.value} 存在 SSL/TLS 风险 {len(ssl_issues)} 项",
                remediation_suggestion="检查证书有效期、协议版本和弱加密套件配置。",
                status=FindingStatus.OPEN,
            )
            db.add(finding)
            created_findings.append(finding)
        await db.flush()
        
        # Update scan task
        scan_task.status = ScanTaskStatus.COMPLETED
        scan_task.control_state = "completed"
        scan_task.completed_at = datetime.utcnow()
        scan_task.findings_count = len(created_findings)
        scan_task.result_summary = {
            "target": asset.value,
            "open_ports": open_ports,
            "ssl_issues": ssl_issues,
            "findings_count": len(created_findings),
        }
        
        previous_result = await db.execute(
            select(ScanHistory)
            .where(ScanHistory.scheduled_scan_id == scheduled_scan.id)
            .order_by(ScanHistory.executed_at.desc())
            .limit(1)
        )
        previous_history = previous_result.scalar_one_or_none()
        changes = (
            _detect_port_changes(open_ports, previous_history.changes_summary)
            if previous_history else
            {"changes_detected": False, "added_ports": [], "removed_ports": []}
        )
        changes_summary = {
            "target": asset.value,
            "port_range": port_range,
            "open_ports": open_ports,
            "open_port_count": len(open_ports),
            "ssl_issue_count": len(ssl_issues),
            **changes,
        }

        # Record scan history
        history = ScanHistory(
            scheduled_scan_id=scheduled_scan.id,
            scan_task_id=scan_task.id,
            changes_detected=changes["changes_detected"],
            changes_summary=changes_summary,
        )
        db.add(history)
        
        # Update scheduled scan
        scheduled_scan.last_run_at = datetime.utcnow()
        scheduled_scan.next_run_at = calculate_next_run(scheduled_scan.frequency)
        
        await db.commit()
        
        return {
            "status": "completed",
            "scan_task_id": scan_task.id,
            "findings_count": len(created_findings),
            "next_run_at": scheduled_scan.next_run_at.isoformat(),
        }
        
    except Exception as e:
        scan_task.status = ScanTaskStatus.FAILED
        scan_task.control_state = "failed"
        scan_task.completed_at = datetime.utcnow()
        scan_task.error_message = str(e)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")


async def run_due_scheduled_scans(db: AsyncSession, limit: int = 5) -> int:
    """Run active scheduled scans whose next_run_at is due."""
    now = datetime.utcnow()
    result = await db.execute(
        select(ScheduledScan)
        .where(
            ScheduledScan.is_active == True,
            ScheduledScan.next_run_at.is_not(None),
            ScheduledScan.next_run_at <= now,
        )
        .order_by(ScheduledScan.next_run_at.asc())
        .limit(limit)
    )
    count = 0
    for scheduled_scan in result.scalars().all():
        due_at = scheduled_scan.next_run_at
        claim_result = await db.execute(
            update(ScheduledScan)
            .where(
                ScheduledScan.id == scheduled_scan.id,
                ScheduledScan.is_active == True,
                ScheduledScan.next_run_at == due_at,
            )
            .values(next_run_at=now + timedelta(minutes=10))
        )
        if claim_result.rowcount != 1:
            continue
        await db.commit()
        await db.refresh(scheduled_scan)
        try:
            await execute_scheduled_scan(db, scheduled_scan)
            count += 1
        except Exception:
            scheduled_scan.last_run_at = datetime.utcnow()
            scheduled_scan.next_run_at = calculate_next_run(scheduled_scan.frequency)
            await db.commit()
            raise
    return count
