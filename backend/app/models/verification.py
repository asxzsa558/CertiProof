import enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


def _enum_values(values):
    return [item.value for item in values]


class VerificationRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VerificationOutcome(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    FIXED = "fixed"
    STILL_PRESENT = "still_present"
    NEW = "new"
    UNABLE = "unable"
    CANCELLED = "cancelled"


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    phase_id = Column(Integer, ForeignKey("phase_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(24), nullable=False, index=True)
    status = Column(
        SQLEnum(VerificationRunStatus, native_enum=False, values_callable=_enum_values),
        default=VerificationRunStatus.QUEUED,
        nullable=False,
        index=True,
    )
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=True)
    document_file_ids = Column(JSON, nullable=False, default=list)
    credential_envelope = Column(Text, nullable=True)
    summary = Column(JSON, nullable=False, default=dict)
    lease_owner = Column(String(128), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items = relationship("VerificationItem", back_populates="run", cascade="all, delete-orphan")


class VerificationItem(Base):
    __tablename__ = "verification_items"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_id = Column(Integer, ForeignKey("findings.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(24), nullable=False, index=True)
    target = Column(String(500), nullable=True, index=True)
    capability = Column(String(120), nullable=True, index=True)
    fingerprint = Column(String(64), nullable=False, index=True)
    outcome = Column(
        SQLEnum(VerificationOutcome, native_enum=False, values_callable=_enum_values),
        default=VerificationOutcome.QUEUED,
        nullable=False,
        index=True,
    )
    baseline_scan_task_id = Column(Integer, ForeignKey("scan_tasks.id", ondelete="SET NULL"), nullable=True)
    current_scan_task_id = Column(Integer, ForeignKey("scan_tasks.id", ondelete="SET NULL"), nullable=True)
    baseline_document_run_id = Column(Integer, ForeignKey("document_analysis_runs.id", ondelete="SET NULL"), nullable=True)
    current_document_run_id = Column(Integer, ForeignKey("document_analysis_runs.id", ondelete="SET NULL"), nullable=True)
    baseline_observation = Column(JSON, nullable=False, default=dict)
    current_observation = Column(JSON, nullable=False, default=dict)
    comparison = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run = relationship("VerificationRun", back_populates="items")
    finding = relationship("Finding", back_populates="verification_items")
    events = relationship("FindingEvent", back_populates="verification_item")


class FindingEvent(Base):
    __tablename__ = "finding_events"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_id = Column(Integer, ForeignKey("findings.id", ondelete="CASCADE"), nullable=False, index=True)
    verification_item_id = Column(Integer, ForeignKey("verification_items.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(40), nullable=False, index=True)
    event_data = Column(JSON, nullable=False, default=dict)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    finding = relationship("Finding", back_populates="events")
    verification_item = relationship("VerificationItem", back_populates="events")
