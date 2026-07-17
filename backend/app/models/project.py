from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class ComplianceLevel(str, enum.Enum):
    LEVEL_2 = "二级"
    LEVEL_3 = "三级"


class ProjectStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    # Basic info
    name = Column(String(200), nullable=False)
    system_name = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    compliance_level = Column(SQLEnum(ComplianceLevel), nullable=True)
    
    # Status
    status = Column(SQLEnum(ProjectStatus), default=ProjectStatus.ACTIVE, nullable=False)
    
    # Compliance score
    compliance_score = Column(Integer, nullable=True)  # 0-100
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="projects")
    owner = relationship("User", foreign_keys=[owner_id], backref="owned_projects")
    organization = relationship("Organization", back_populates="projects")
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")
    scan_tasks = relationship("ScanTask", back_populates="project", cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="project", cascade="all, delete-orphan")
    questionnaires = relationship("QuestionnaireRecord", back_populates="project", cascade="all, delete-orphan")
    assessments = relationship("ProjectAssessment", back_populates="project", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Project(id={self.id}, name={self.name}, level={self.compliance_level})>"
