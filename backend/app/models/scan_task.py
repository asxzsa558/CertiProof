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
    
    def __repr__(self):
        return f"<ScanTask(id={self.id}, type={self.task_type}, status={self.status})>"
