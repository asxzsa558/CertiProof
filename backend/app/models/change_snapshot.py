from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.core.database import Base


class ChangeSnapshot(Base):
    __tablename__ = "change_snapshots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    scan_task_id = Column(Integer, nullable=True, index=True)
    snapshot_type = Column(String(20), nullable=False, index=True)
    subject = Column(String(500), nullable=False)
    scope = Column(String(500), nullable=False, default="default")
    snapshot = Column(JSON, nullable=False)
    changes = Column(JSON, nullable=True)
    changes_detected = Column(Boolean, nullable=False, default=False)
    reliable = Column(Boolean, nullable=False, default=True)
    reassessment_required = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
