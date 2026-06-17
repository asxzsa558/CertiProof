from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class EvidenceType(str, enum.Enum):
    TOOL_OUTPUT = "tool_output"
    SCREENSHOT = "screenshot"
    API_RESPONSE = "api_response"
    LOG = "log"
    DOCUMENT = "document"


class Evidence(Base):
    __tablename__ = "evidences"
    
    id = Column(Integer, primary_key=True, index=True)
    finding_id = Column(Integer, ForeignKey("findings.id"), nullable=False, index=True)
    
    # Evidence info
    evidence_type = Column(SQLEnum(EvidenceType), nullable=False)
    source = Column(String(200), nullable=True)  # Tool name or "manual"
    
    # Content
    content = Column(JSON, nullable=True)  # Structured data
    file_path = Column(String(500), nullable=True)  # For screenshots, documents
    raw_output = Column(Text, nullable=True)  # Raw tool output
    
    # Integrity
    hash_sha256 = Column(String(64), nullable=True)  # SHA-256 hash for integrity
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    finding = relationship("Finding", back_populates="evidences")
    
    def __repr__(self):
        return f"<Evidence(id={self.id}, type={self.evidence_type}, source={self.source})>"
