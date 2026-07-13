"""Scan API - VeriSure."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.scan_task import ScanTaskType
from app.models.asset import Asset
from app.schemas.scan_task import ScanTaskCreate, ScanTaskResponse, ScanTaskListResponse
from app.schemas.finding import FindingResponse
from app.services.scan_service import scan_service
from app.api.projects import get_project_for_user
from app.orchestrator import orchestrator
from app.services.asset_scope import list_scannable_assets
from app.services.audit import record_audit_event

router = APIRouter(prefix="/projects/{project_id}/scans", tags=["Scans"])


async def _build_scan_plan(db: AsyncSession, project_id: int, scan_data: ScanTaskCreate) -> tuple[list[dict], Optional[int]]:
    parameters = dict(scan_data.parameters or {})
    capability = parameters.pop("capability", None)
    if not capability:
        capability = "full_compliance_scan" if scan_data.task_type == ScanTaskType.FULL else "scan_ports"

    query = select(Asset).where(Asset.project_id == project_id)
    if scan_data.asset_id:
        query = query.where(Asset.id == scan_data.asset_id)
    result = await db.execute(query.order_by(Asset.created_at.asc()))
    assets = result.scalars().all()
    if scan_data.asset_id and not assets:
        raise ValueError("Asset not found")
    scannable_ids = {asset.id for asset in await list_scannable_assets(db, project_id)}
    if scan_data.asset_id and assets[0].id not in scannable_ids:
        raise ValueError("Asset is inactive and cannot be scanned")
    if not scan_data.asset_id:
        assets = [asset for asset in assets if asset.id in scannable_ids]
    if not assets:
        raise ValueError("No assets found for this project")

    plan = [
        {
            "capability": capability,
            "parameters": {**parameters, "target": asset.value},
        }
        for asset in assets
    ]
    return plan, scan_data.asset_id


@router.post("/", response_model=ScanTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_scan(
    project_id: int,
    scan_data: ScanTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create and start a new scan task."""
    await get_project_for_user(db, project_id, current_user.id, "scan:execute")
    try:
        plan, asset_id = await _build_scan_plan(db, project_id, scan_data)
        task_info = await orchestrator.start_async_plan(
            plan=plan,
            user_id=current_user.id,
            project_id=project_id,
            db=db,
            ai_response="已创建扫描任务，正在排队执行。",
            user_input="通过扫描 API 创建任务",
            task_type=scan_data.task_type,
            asset_id=asset_id,
        )
        scan_task = await scan_service.get_scan_task(db, project_id, task_info["scan_task_id"])
        if not scan_task:
            raise ValueError("Scan task was not created")
        return scan_task
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/", response_model=List[ScanTaskListResponse])
async def list_scans(
    project_id: int,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List scan tasks for a project."""
    await get_project_for_user(db, project_id, current_user.id, "scan:read")
    try:
        scans = await scan_service.list_scan_tasks(
            db=db,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        return scans
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get("/{scan_id}", response_model=ScanTaskResponse)
async def get_scan(
    project_id: int,
    scan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get scan task details."""
    await get_project_for_user(db, project_id, current_user.id, "scan:read")
    scan_task = await scan_service.get_scan_task(db, project_id, scan_id)
    if not scan_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scan task not found",
        )
    return scan_task


@router.get("/{scan_id}/findings", response_model=List[FindingResponse])
async def get_scan_findings(
    project_id: int,
    scan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get findings for a scan task."""
    await get_project_for_user(db, project_id, current_user.id, "scan:read")
    try:
        findings = await scan_service.get_scan_findings(db, project_id, scan_id)
        return findings
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post("/{scan_id}/cancel", response_model=ScanTaskResponse)
async def cancel_scan(
    project_id: int,
    scan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending or running scan task."""
    await get_project_for_user(db, project_id, current_user.id, "scan:cancel")
    try:
        scan_task = await scan_service.cancel_scan_task(db, project_id, scan_id)
        await record_audit_event(
            db,
            event_type="scan.cancelled",
            resource_type="scan_task",
            resource_id=scan_task.id,
            actor_user_id=current_user.id,
            project_id=project_id,
            outcome="cancelled",
        )
        await db.commit()
        return scan_task
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
