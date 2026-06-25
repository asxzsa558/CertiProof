from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AssessmentTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str]
    icon: Optional[str]
    is_active: bool
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectAssessmentCreate(BaseModel):
    assessment_type_id: int
    level: Optional[str] = None


class ProjectAssessmentResponse(BaseModel):
    id: int
    project_id: int
    assessment_type_id: int
    status: str
    level: Optional[str]
    score: Optional[float]
    progress: float
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    assessment_type: Optional[AssessmentTypeResponse] = None

    class Config:
        from_attributes = True
