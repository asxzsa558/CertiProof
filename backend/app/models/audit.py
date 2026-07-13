"""Append-only operational audit records."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.core.database import Base


class AuditEvent(Base):
    """Security-relevant action record; application code only ever inserts rows."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    resource_type = Column(String(80), nullable=False)
    resource_id = Column(String(80), nullable=True, index=True)
    outcome = Column(String(20), nullable=False, default="success", index=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
