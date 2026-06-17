from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.models.project import ComplianceLevel, ProjectStatus


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    compliance_level: ComplianceLevel


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None


class ProjectResponse(ProjectBase):
    id: int
    user_id: int
    status: ProjectStatus
    compliance_score: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    id: int
    name: str
    compliance_level: ComplianceLevel
    status: ProjectStatus
    compliance_score: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True
