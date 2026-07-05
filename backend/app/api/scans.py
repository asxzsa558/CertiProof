"""
Scan API - VeriSure
API endpoints for scan task management.
"""

import asyncio
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.scan_task import ScanTaskType
from app.schemas.scan_task import ScanTaskCreate, ScanTaskResponse, ScanTaskListResponse
from app.schemas.finding import FindingResponse
from app.services.scan_service import scan_service
from app.core.database import AsyncSessionLocal
from app.api.projects import get_project_for_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/scans", tags=["Scans"])


async def execute_scan_background(scan_task_id: int):
    """Background task to execute scan."""
    async with AsyncSessionLocal() as db:
        try:
            await scan_service.execute_scan_task(db, scan_task_id)
        except Exception as e:
            logger.error(f"Background scan {scan_task_id} failed: {e}")


@router.post("/", response_model=ScanTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_scan(
    project_id: int,
    scan_data: ScanTaskCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create and start a new scan task."""
    await get_project_for_user(db, project_id, current_user.id, "scan:execute")
    try:
        scan_task = await scan_service.create_scan_task(
            db=db,
            project_id=project_id,
            user_id=current_user.id,
            asset_id=scan_data.asset_id,
            task_type=scan_data.task_type,
            parameters=scan_data.parameters,
        )
        
        # Start scan in background
        background_tasks.add_task(execute_scan_background, scan_task.id)
        
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
            user_id=current_user.id,
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
    scan_task = await scan_service.get_scan_task(db, scan_id, current_user.id)
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
        findings = await scan_service.get_scan_findings(db, scan_id, current_user.id)
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
        scan_task = await scan_service.cancel_scan_task(db, scan_id, current_user.id)
        return scan_task
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
