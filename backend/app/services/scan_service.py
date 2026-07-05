"""
Scan Service - VeriSure
Business logic for scan task management.
"""

import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.project import Project
from app.models.asset import Asset, VerificationStatus
from app.models.scan_task import ScanTask, ScanTaskType, ScanTaskStatus, TriggeredBy
from app.models.finding import Finding
from app.orchestrator import orchestrator
from app.core.redaction import redact_sensitive

logger = logging.getLogger(__name__)


class ScanService:
    """Service for managing scan tasks."""

    async def create_scan_task(
        self,
        db: AsyncSession,
        project_id: int,
        user_id: int,
        asset_id: Optional[int] = None,
        task_type: ScanTaskType = ScanTaskType.FULL,
        parameters: Optional[dict] = None,
    ) -> ScanTask:
        """
        Create a new scan task.
        
        Args:
            db: Database session
            project_id: Project ID
            user_id: User ID (for permission check)
            asset_id: Optional asset ID (if None, scan all assets)
            task_type: Type of scan task
            parameters: Optional scan parameters
            
        Returns:
            Created ScanTask
        """
        # API routes enforce project RBAC before calling this service.
        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise ValueError("Project not found")
        
        # Verify asset if specified
        if asset_id:
            result = await db.execute(
                select(Asset).where(Asset.id == asset_id, Asset.project_id == project_id)
            )
            asset = result.scalar_one_or_none()
            if not asset:
                raise ValueError("Asset not found")
            if asset.verification_status != VerificationStatus.VERIFIED:
                raise ValueError("Asset must be verified before scanning")
        
        # Create scan task
        scan_task = ScanTask(
            project_id=project_id,
            asset_id=asset_id,
            task_type=task_type,
            status=ScanTaskStatus.PENDING,
            triggered_by=TriggeredBy.MANUAL,
            parameters=redact_sensitive(parameters),
        )
        db.add(scan_task)
        await db.commit()
        await db.refresh(scan_task)
        
        return scan_task

    async def execute_scan_task(
        self,
        db: AsyncSession,
        scan_task_id: int,
    ) -> ScanTask:
        """
        Execute a scan task asynchronously.
        
        Args:
            db: Database session
            scan_task_id: Scan task ID
            
        Returns:
            Updated ScanTask
        """
        # Get scan task
        result = await db.execute(
            select(ScanTask).where(ScanTask.id == scan_task_id)
        )
        scan_task = result.scalar_one_or_none()
        if not scan_task:
            raise ValueError("Scan task not found")
        
        # Get project
        result = await db.execute(
            select(Project).where(Project.id == scan_task.project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise ValueError("Project not found")
        
        # Get asset if specified
        asset_value = None
        if scan_task.asset_id:
            result = await db.execute(
                select(Asset).where(Asset.id == scan_task.asset_id)
            )
            asset = result.scalar_one_or_none()
            if asset:
                asset_value = asset.value
        
        parameters = scan_task.parameters or {}
        user_id = parameters.get("user_id") or project.owner_id or project.user_id

        await orchestrator.handle_user_input(
            user_input="执行等保合规检测",
            project_id=project.id,
            user_id=user_id,
            asset=asset_value or "unknown",
            db=db,
        )
        
        # Update scan task status
        scan_task.status = ScanTaskStatus.RUNNING
        scan_task.started_at = datetime.utcnow()
        await db.commit()
        
        return scan_task

    async def get_scan_task(
        self,
        db: AsyncSession,
        project_id: int,
        scan_task_id: int,
    ) -> Optional[ScanTask]:
        """Get scan task scoped to a project."""
        result = await db.execute(
            select(ScanTask)
            .where(ScanTask.id == scan_task_id, ScanTask.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def list_scan_tasks(
        self,
        db: AsyncSession,
        project_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ScanTask]:
        """List scan tasks for a project."""
        result = await db.execute(
            select(ScanTask)
            .where(ScanTask.project_id == project_id)
            .order_by(ScanTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_scan_findings(
        self,
        db: AsyncSession,
        project_id: int,
        scan_task_id: int,
    ) -> List[Finding]:
        """Get findings for a scan task."""
        result = await db.execute(
            select(Finding)
            .join(ScanTask)
            .where(
                Finding.scan_task_id == scan_task_id,
                ScanTask.project_id == project_id,
            )
        )
        return list(result.scalars().all())

    async def cancel_scan_task(
        self,
        db: AsyncSession,
        project_id: int,
        scan_task_id: int,
    ) -> ScanTask:
        """Cancel a pending or running scan task."""
        scan_task = await self.get_scan_task(db, project_id, scan_task_id)
        if not scan_task:
            raise ValueError("Scan task not found")
        
        if scan_task.status not in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING):
            raise ValueError("Can only cancel pending or running tasks")
        
        scan_task.status = ScanTaskStatus.CANCELLED
        scan_task.completed_at = datetime.utcnow()
        await db.commit()
        
        return scan_task


# Singleton instance
scan_service = ScanService()
