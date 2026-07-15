from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.finding import Severity, Judgment, JudgmentEngine, FindingStatus


class FindingBase(BaseModel):
    clause_id: str = Field(..., max_length=50)
    clause_name: Optional[str] = Field(None, max_length=200)
    severity: Severity
    judgment: Judgment
    judgment_engine: JudgmentEngine
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    description: Optional[str] = None
    remediation_suggestion: Optional[str] = None


class FindingCreate(FindingBase):
    scan_task_id: Optional[int] = None
    document_run_id: Optional[int] = None
    evidence_ids: Optional[List[int]] = None


class FindingUpdate(BaseModel):
    status: Optional[FindingStatus] = None
    assigned_to: Optional[int] = None
    remediation_suggestion: Optional[str] = None


class FindingResponse(FindingBase):
    id: int
    project_id: int
    scan_task_id: Optional[int] = None
    document_run_id: Optional[int] = None
    status: FindingStatus
    assigned_to: Optional[int] = None
    evidence_ids: Optional[List[int]] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class FindingListResponse(BaseModel):
    id: int
    clause_id: str
    clause_name: Optional[str] = None
    severity: Severity
    judgment: Judgment
    status: FindingStatus
    created_at: datetime
    
    class Config:
        from_attributes = True
