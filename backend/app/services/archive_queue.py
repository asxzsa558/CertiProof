"""Persisted archive and conversation-summary work handled by app.worker."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.context import ConversationArchive, ConversationSummary
from app.services.context_manager import ContextManager


WORKER_ID = f"archive-worker-{os.getenv('HOSTNAME', 'local')}-{os.getpid()}"


async def _claim(db: AsyncSession, model, record_id: int) -> bool:
    now = datetime.utcnow()
    result = await db.execute(
        update(model)
        .where(
            model.id == record_id,
            or_(
                model.status == "queued",
                and_(model.status == "processing", model.lease_expires_at < now),
            ),
        )
        .values(
            status="processing",
            attempts=model.attempts + 1,
            lease_owner=WORKER_ID,
            lease_expires_at=now + timedelta(minutes=settings.TASK_LEASE_MINUTES),
        )
    )
    return result.rowcount == 1


async def _run_archive(archive_id: int) -> None:
    async with AsyncSessionLocal() as db:
        archive = (await db.execute(select(ConversationArchive).where(ConversationArchive.id == archive_id))).scalar_one_or_none()
        if archive:
            await ContextManager(db, archive.user_id, archive.project_id, archive.thread_id).generate_archive_summary(archive.id)


async def _run_summary(summary_id: int) -> None:
    async with AsyncSessionLocal() as db:
        summary = (await db.execute(select(ConversationSummary).where(ConversationSummary.id == summary_id))).scalar_one_or_none()
        if summary:
            await ContextManager(db, summary.user_id, summary.project_id, summary.thread_id).generate_conversation_summary(summary.id)


async def process_pending_archive_jobs(db: AsyncSession, limit: int = 10) -> int:
    """Claim queued/stale archive work. Failed work requires an explicit user retry."""
    now = datetime.utcnow()
    records = list((await db.execute(
        select(ConversationArchive)
        .where(or_(
            ConversationArchive.status == "queued",
            and_(ConversationArchive.status == "processing", ConversationArchive.lease_expires_at < now),
        ))
        .order_by(ConversationArchive.archived_at.asc())
        .limit(limit)
    )).scalars().all())
    claimed = []
    for record in records:
        if await _claim(db, ConversationArchive, record.id):
            claimed.append(record.id)
    await db.commit()
    for archive_id in claimed:
        await _run_archive(archive_id)
    return len(claimed)


async def process_pending_conversation_summaries(db: AsyncSession, limit: int = 10) -> int:
    now = datetime.utcnow()
    records = list((await db.execute(
        select(ConversationSummary)
        .where(or_(
            ConversationSummary.status == "queued",
            and_(ConversationSummary.status == "processing", ConversationSummary.lease_expires_at < now),
        ))
        .order_by(ConversationSummary.created_at.asc())
        .limit(limit)
    )).scalars().all())
    claimed = []
    for record in records:
        if await _claim(db, ConversationSummary, record.id):
            claimed.append(record.id)
    await db.commit()
    for summary_id in claimed:
        await _run_summary(summary_id)
    return len(claimed)
