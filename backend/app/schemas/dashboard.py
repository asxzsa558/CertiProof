from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class DashboardAssessmentType(BaseModel):
    code: str
    name: str
    level: Optional[str]
    status: str
    score: Optional[float]
    progress: float


class DashboardProject(BaseModel):
    id: int
    name: str
    system_name: Optional[str]
    description: Optional[str]
    assessment_types: List[DashboardAssessmentType]
    asset_count: int
    overall_score: Optional[float]
    overall_status: str
    updated_at: datetime


class DashboardSummary(BaseModel):
    total: int
    in_progress: int
    completed: int
    not_started: int
    avg_score: float


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    projects: List[DashboardProject]
    generated_at: datetime
