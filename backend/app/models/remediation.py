from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class RemediationStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    VERIFIED = "verified"
    CLOSED = "closed"
    SKIPPED = "skipped"


class RemediationTicket(Base):
    __tablename__ = "remediation_tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    finding_id = Column(Integer, ForeignKey("findings.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    
    # Assignment
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Status
    status = Column(SQLEnum(RemediationStatus), default=RemediationStatus.OPEN, nullable=False)
    priority = Column(String(20), default="medium")  # low, medium, high, critical
    
    # Details
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    remediation_plan = Column(Text, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    skip_reason = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    finding = relationship("Finding", back_populates="remediation_ticket")
    project = relationship("Project", back_populates="remediation_tickets")
    assignee = relationship("User", foreign_keys=[assigned_to], backref="assigned_tickets")
    assigner = relationship("User", foreign_keys=[assigned_by])
    
    def __repr__(self):
        return f"<RemediationTicket(id={self.id}, status={self.status})>"
