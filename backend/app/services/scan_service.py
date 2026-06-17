"""
Scan Service - CertiProof
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
from app.agent.dispatcher import agent_dispatcher

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
        # Verify project exists and belongs to user
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise ValueError("Project not found or access denied")
        
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
            parameters=parameters,
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
        return await agent_dispatcher.run_scan(db, scan_task_id)

    async def get_scan_task(
        self,
        db: AsyncSession,
        scan_task_id: int,
        user_id: int,
    ) -> Optional[ScanTask]:
        """Get scan task with permission check."""
        result = await db.execute(
            select(ScanTask)
            .join(Project)
            .where(ScanTask.id == scan_task_id, Project.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_scan_tasks(
        self,
        db: AsyncSession,
        project_id: int,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ScanTask]:
        """List scan tasks for a project."""
        # Verify project access
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        if not result.scalar_one_or_none():
            raise ValueError("Project not found or access denied")
        
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
        scan_task_id: int,
        user_id: int,
    ) -> List[Finding]:
        """Get findings for a scan task."""
        result = await db.execute(
            select(Finding)
            .join(ScanTask)
            .join(Project)
            .where(
                Finding.scan_task_id == scan_task_id,
                Project.user_id == user_id,
            )
        )
        return list(result.scalars().all())

    async def cancel_scan_task(
        self,
        db: AsyncSession,
        scan_task_id: int,
        user_id: int,
    ) -> ScanTask:
        """Cancel a pending or running scan task."""
        scan_task = await self.get_scan_task(db, scan_task_id, user_id)
        if not scan_task:
            raise ValueError("Scan task not found or access denied")
        
        if scan_task.status not in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING):
            raise ValueError("Can only cancel pending or running tasks")
        
        scan_task.status = ScanTaskStatus.CANCELLED
        scan_task.completed_at = datetime.utcnow()
        await db.commit()
        
        return scan_task


# Singleton instance
scan_service = ScanService()
