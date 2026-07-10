from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.remediation import RemediationStatus


class RemediationTicketBase(BaseModel):
    title: str
    description: Optional[str] = None
    remediation_plan: Optional[str] = None
    priority: Optional[str] = "medium"
    assigned_to: Optional[int] = None
    due_date: Optional[datetime] = None


class RemediationTicketCreate(RemediationTicketBase):
    finding_id: int
    project_id: int


class RemediationTicketUpdate(BaseModel):
    status: Optional[RemediationStatus] = None
    assigned_to: Optional[int] = None
    resolution_notes: Optional[str] = None
    skip_reason: Optional[str] = None
    due_date: Optional[datetime] = None


class RemediationTicketResponse(RemediationTicketBase):
    id: int
    finding_id: int
    project_id: int
    assigned_by: Optional[int] = None
    status: RemediationStatus
    resolution_notes: Optional[str] = None
    skip_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class RemediationTicketListResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    remediation_plan: Optional[str] = None
    status: RemediationStatus
    priority: str
    finding_id: int
    source: Optional[str] = None
    source_label: Optional[str] = None
    finding_clause_id: Optional[str] = None
    finding_clause_name: Optional[str] = None
    finding_severity: Optional[str] = None
    finding_status: Optional[str] = None
    finding_description: Optional[str] = None
    judgment: Optional[str] = None
    confidence: Optional[float] = None
    scan_task_id: Optional[int] = None
    assigned_to: Optional[int] = None
    skip_reason: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    
    class Config:
        from_attributes = True
