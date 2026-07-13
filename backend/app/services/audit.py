"""Small, shared writer for security-relevant audit events."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact_sensitive
from app.models.audit import AuditEvent


async def record_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    resource_type: str,
    resource_id: str | int | None = None,
    actor_user_id: int | None = None,
    organization_id: int | None = None,
    project_id: int | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> None:
    """Queue an append-only, redacted audit event in the caller transaction."""
    db.add(AuditEvent(
        organization_id=organization_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome,
        details=redact_sensitive(details or {}),
    ))
