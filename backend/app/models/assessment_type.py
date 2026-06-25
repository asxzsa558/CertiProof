from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class AssessmentType(Base):
    __tablename__ = "assessment_types"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    projects = relationship("ProjectAssessment", back_populates="assessment_type")

    def __repr__(self):
        return f"<AssessmentType(id={self.id}, code={self.code}, name={self.name})>"


class ProjectAssessment(Base):
    __tablename__ = "project_assessments"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    assessment_type_id = Column(Integer, ForeignKey("assessment_types.id"), nullable=False, index=True)

    status = Column(String(20), default="not_started", nullable=False)
    level = Column(String(20), nullable=True)
    score = Column(Float, nullable=True)
    progress = Column(Float, default=0.0, nullable=False)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="assessments")
    assessment_type = relationship("AssessmentType", back_populates="projects")

    def __repr__(self):
        return f"<ProjectAssessment(project_id={self.project_id}, type_id={self.assessment_type_id}, status={self.status})>"
