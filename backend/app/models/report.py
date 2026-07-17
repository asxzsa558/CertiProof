from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class ReportArtifact(Base):
    """Immutable report snapshot; status changes only when a newer input invalidates it."""

    __tablename__ = "report_artifacts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("task_instances.id", ondelete="SET NULL"), nullable=True, index=True)
    version = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="current", index=True)
    html_path = Column(String(1000), nullable=False)
    html_sha256 = Column(String(64), nullable=False)
    html_size = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    generated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    stale_reason = Column(Text, nullable=True)
    invalidated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_report_artifact_project_version"),
    )
