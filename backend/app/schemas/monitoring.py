from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.monitoring import ScheduleFrequency


class ScheduledScanBase(BaseModel):
    name: str
    asset_id: int
    frequency: ScheduleFrequency
    scan_parameters: Optional[Dict[str, Any]] = None
    notify_on_change: bool = True
    notify_emails: Optional[List[str]] = None


class ScheduledScanCreate(ScheduledScanBase):
    pass


class ScheduledScanUpdate(BaseModel):
    name: Optional[str] = None
    frequency: Optional[ScheduleFrequency] = None
    is_active: Optional[bool] = None
    scan_parameters: Optional[Dict[str, Any]] = None
    notify_on_change: Optional[bool] = None
    notify_emails: Optional[List[str]] = None


class ScheduledScanResponse(ScheduledScanBase):
    id: int
    project_id: int
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ScanHistoryResponse(BaseModel):
    id: int
    scheduled_scan_id: int
    scan_task_id: int
    changes_detected: bool
    changes_summary: Optional[Dict[str, Any]] = None
    executed_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
