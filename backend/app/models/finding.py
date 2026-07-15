from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Text, Float, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class Severity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Judgment(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    NOT_TESTED = "not_tested"
    PAPER_COMPLIANT = "paper_compliant"


class JudgmentEngine(str, enum.Enum):
    RULE = "rule"
    LLM = "llm"
    HYBRID = "hybrid"
    MANUAL = "manual"


class FindingStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class Finding(Base):
    __tablename__ = "findings"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    scan_task_id = Column(Integer, ForeignKey("scan_tasks.id"), nullable=True, index=True)
    document_run_id = Column(Integer, ForeignKey("document_analysis_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Finding info
    clause_id = Column(String(50), nullable=False, index=True)  # e.g., "8.1.4.1"
    clause_name = Column(String(200), nullable=True)
    severity = Column(SQLEnum(Severity), nullable=False)
    
    # Judgment
    judgment = Column(SQLEnum(Judgment), nullable=False)
    judgment_engine = Column(SQLEnum(JudgmentEngine), nullable=False)
    confidence = Column(Float, nullable=True)  # For LLM judgments, 0.0-1.0
    
    # Details
    description = Column(Text, nullable=True)
    remediation_suggestion = Column(Text, nullable=True)
    
    # Status
    status = Column(SQLEnum(FindingStatus), default=FindingStatus.OPEN, nullable=False)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Evidence references
    evidence_ids = Column(JSON, nullable=True)  # List of evidence IDs
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="findings")
    scan_task = relationship("ScanTask", back_populates="findings")
    document_run = relationship("DocumentAnalysisRun", back_populates="findings")
    evidences = relationship("Evidence", back_populates="finding", cascade="all, delete-orphan")
    remediation_ticket = relationship("RemediationTicket", back_populates="finding", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Finding(id={self.id}, clause={self.clause_id}, judgment={self.judgment})>"
