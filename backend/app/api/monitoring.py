from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime, timedelta
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.models.monitoring import ScheduledScan, ScanHistory, ScheduleFrequency
from app.schemas.monitoring import (
    ScheduledScanCreate,
    ScheduledScanUpdate,
    ScheduledScanResponse,
    ScanHistoryResponse,
)

router = APIRouter(prefix="/projects/{project_id}/monitoring", tags=["Monitoring"])


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


@router.post("/scheduled", response_model=ScheduledScanResponse, status_code=status.HTTP_201_CREATED)
async def create_scheduled_scan(
    project_id: int,
    scan_data: ScheduledScanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new scheduled scan."""
    # Verify project access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")
    
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
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")
    
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
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")
    
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
    result = await db.execute(
        select(ScheduledScan).where(
            ScheduledScan.id == scan_id,
            ScheduledScan.project_id == project_id
        )
    )
    scheduled_scan = result.scalar_one_or_none()
    if not scheduled_scan:
        raise HTTPException(status_code=404, detail="Scheduled scan not found")
    
    # Import here to avoid circular imports
    from app.services.real_scan_service import scan_host, check_ssl, generate_compliance_findings
    from app.models.scan_task import ScanTask, ScanTaskType, ScanTaskStatus, TriggeredBy
    from app.models.finding import Finding, Severity, Judgment, JudgmentEngine, FindingStatus
    from app.models.evidence import Evidence, EvidenceType
    
    # Get asset
    result = await db.execute(
        select(Asset).where(Asset.id == scheduled_scan.asset_id)
    )
    asset = result.scalar_one_or_none()
    
    # Create scan task
    scan_task = ScanTask(
        project_id=project_id,
        asset_id=scheduled_scan.asset_id,
        task_type=ScanTaskType.SCHEDULED,
        status=ScanTaskStatus.RUNNING,
        triggered_by=TriggeredBy.SCHEDULED,
        started_at=datetime.utcnow(),
    )
    db.add(scan_task)
    await db.flush()
    
    try:
        # Execute scan
        scan_result = scan_host(asset.value)
        
        # Check SSL if HTTPS is open
        ssl_result = None
        if any(p["port"] == 443 for p in scan_result["open_ports"]):
            ssl_result = check_ssl(asset.value, 443)
        
        # Generate findings
        mock_findings = generate_compliance_findings(scan_result, asset.value)
        
        # Create findings
        created_findings = []
        for mock in mock_findings:
            severity_map = {
                "critical": Severity.CRITICAL,
                "high": Severity.HIGH,
                "medium": Severity.MEDIUM,
                "low": Severity.LOW,
                "info": Severity.INFO,
            }
            judgment_map = {
                "pass": Judgment.PASS,
                "fail": Judgment.FAIL,
                "partial": Judgment.PARTIAL,
            }
            
            finding = Finding(
                project_id=project_id,
                scan_task_id=scan_task.id,
                clause_id=mock["clause_id"],
                clause_name=mock["clause_name"],
                severity=severity_map.get(mock["severity"], Severity.INFO),
                judgment=judgment_map.get(mock["judgment"], Judgment.FAIL),
                judgment_engine=JudgmentEngine.RULE,
                description=mock["description"],
                remediation_suggestion=mock["remediation"],
                status=FindingStatus.OPEN,
            )
            db.add(finding)
            await db.flush()
            created_findings.append(finding)
        
        # Update scan task
        scan_task.status = ScanTaskStatus.COMPLETED
        scan_task.completed_at = datetime.utcnow()
        scan_task.findings_count = len(created_findings)
        
        # Record scan history
        history = ScanHistory(
            scheduled_scan_id=scheduled_scan.id,
            scan_task_id=scan_task.id,
            changes_detected=False,  # TODO: Implement change detection
            changes_summary={"open_ports": len(scan_result["open_ports"])},
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
        scan_task.error_message = str(e)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")
