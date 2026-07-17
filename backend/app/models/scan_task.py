from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class ScanTaskType(str, enum.Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    TARGETED = "targeted"
    SCHEDULED = "scheduled"


class ScanTaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriggeredBy(str, enum.Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    EVENT = "event"


class ScanTask(Base):
    __tablename__ = "scan_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True, index=True)
    
    # Task info
    task_type = Column(SQLEnum(ScanTaskType), nullable=False)
    status = Column(SQLEnum(ScanTaskStatus), default=ScanTaskStatus.PENDING, nullable=False)
    triggered_by = Column(SQLEnum(TriggeredBy), default=TriggeredBy.MANUAL, nullable=False)
    
    # Task parameters
    parameters = Column(JSON, nullable=True)  # Scan configuration
    orchestrator_task_id = Column(String(64), nullable=True, index=True)
    progress = Column(JSON, nullable=True)
    result_summary = Column(JSON, nullable=True)
    lease_owner = Column(String(128), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # Control state remains durable across API/worker restarts.  Status stays
    # compatible with the public scan lifecycle while this captures pause intent.
    control_state = Column(String(24), nullable=False, default="queued", index=True)
    checkpoint = Column(JSON, nullable=True)
    paused_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested_at = Column(DateTime(timezone=True), nullable=True)
    
    # Results summary
    findings_count = Column(Integer, default=0)
    high_severity_count = Column(Integer, default=0)
    medium_severity_count = Column(Integer, default=0)
    low_severity_count = Column(Integer, default=0)
    
    # Error info
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="scan_tasks")
    asset = relationship("Asset", back_populates="scan_tasks")
    findings = relationship("Finding", back_populates="scan_task", cascade="all, delete-orphan")

    @property
    def effective_control_state(self) -> str:
        status = self.status.value if hasattr(self.status, "value") else str(self.status)
        if status in {"completed", "failed", "cancelled"}:
            return status
        return self.control_state or (self.progress or {}).get("status") or status
    
    def __repr__(self):
        return f"<ScanTask(id={self.id}, type={self.task_type}, status={self.status})>"
