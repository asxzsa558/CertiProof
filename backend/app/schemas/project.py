from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.project import ComplianceLevel, ProjectStatus
from app.schemas.assessment_type import ProjectAssessmentResponse, AssessmentTypeResponse


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    compliance_level: Optional[ComplianceLevel] = None


class ProjectCreate(ProjectBase):
    organization_id: int
    system_name: Optional[str] = Field(None, max_length=500)
    assessment_type_ids: List[int] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    system_name: Optional[str] = Field(None, max_length=500)
    status: Optional[ProjectStatus] = None


class ProjectOwnerBrief(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None

    class Config:
        from_attributes = True


class ProjectResponse(ProjectBase):
    id: int
    user_id: int
    organization_id: Optional[int]
    owner_id: Optional[int]
    system_name: Optional[str]
    status: ProjectStatus
    compliance_score: Optional[int] = None
    assessment_types: List[ProjectAssessmentResponse] = []
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    id: int
    name: str
    system_name: Optional[str] = None
    compliance_level: Optional[ComplianceLevel] = None
    status: ProjectStatus
    compliance_score: Optional[int] = None
    organization_id: Optional[int] = None
    assessment_types: List[ProjectAssessmentResponse] = []
    created_at: datetime
    
    class Config:
        from_attributes = True
