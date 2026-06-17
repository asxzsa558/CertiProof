from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class ScheduleFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduledScan(Base):
    __tablename__ = "scheduled_scans"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    
    # Schedule configuration
    name = Column(String(200), nullable=False)
    frequency = Column(SQLEnum(ScheduleFrequency), nullable=False)
    cron_expression = Column(String(100), nullable=True)  # For future custom schedules
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    
    # Configuration
    scan_parameters = Column(JSON, nullable=True)
    notify_on_change = Column(Boolean, default=True, nullable=False)
    notify_emails = Column(JSON, nullable=True)  # List of emails
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    project = relationship("Project", backref="scheduled_scans")
    asset = relationship("Asset", backref="scheduled_scans")
    
    def __repr__(self):
        return f"<ScheduledScan(id={self.id}, name={self.name}, frequency={self.frequency})>"


class ScanHistory(Base):
    __tablename__ = "scan_history"
    
    id = Column(Integer, primary_key=True, index=True)
    scheduled_scan_id = Column(Integer, ForeignKey("scheduled_scans.id"), nullable=False)
    scan_task_id = Column(Integer, ForeignKey("scan_tasks.id"), nullable=False)
    
    # Change detection
    changes_detected = Column(Boolean, default=False, nullable=False)
    changes_summary = Column(JSON, nullable=True)
    
    # Timestamps
    executed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    scheduled_scan = relationship("ScheduledScan", backref="scan_history")
    scan_task = relationship("ScanTask", backref="scan_history")
    
    def __repr__(self):
        return f"<ScanHistory(id={self.id}, changes={self.changes_detected})>"
