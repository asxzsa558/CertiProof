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
    due_date: Optional[datetime] = None


class RemediationTicketResponse(RemediationTicketBase):
    id: int
    finding_id: int
    project_id: int
    assigned_by: Optional[int] = None
    status: RemediationStatus
    resolution_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class RemediationTicketListResponse(BaseModel):
    id: int
    title: str
    status: RemediationStatus
    priority: str
    finding_id: int
    assigned_to: Optional[int] = None
    created_at: datetime
    due_date: Optional[datetime] = None
    
    class Config:
        from_attributes = True
