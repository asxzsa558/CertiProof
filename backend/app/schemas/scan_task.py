from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from app.models.scan_task import ScanTaskType, ScanTaskStatus, TriggeredBy


class ScanTaskBase(BaseModel):
    task_type: ScanTaskType
    parameters: Optional[Dict[str, Any]] = None


class ScanTaskCreate(ScanTaskBase):
    asset_id: Optional[int] = None


class ScanTaskResponse(ScanTaskBase):
    id: int
    project_id: int
    asset_id: Optional[int] = None
    status: ScanTaskStatus
    triggered_by: TriggeredBy
    orchestrator_task_id: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    result_summary: Optional[Dict[str, Any]] = None
    findings_count: int = 0
    high_severity_count: int = 0
    medium_severity_count: int = 0
    low_severity_count: int = 0
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ScanTaskListResponse(BaseModel):
    id: int
    task_type: ScanTaskType
    status: ScanTaskStatus
    triggered_by: TriggeredBy
    orchestrator_task_id: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    result_summary: Optional[Dict[str, Any]] = None
    findings_count: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
