from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.finding import Severity, Judgment, JudgmentEngine, FindingStatus
from app.models.evidence import EvidenceType
from app.models.scan_task import ScanTaskStatus, ScanTaskType, TriggeredBy


# Finding schemas
class FindingBase(BaseModel):
    clause_id: str
    clause_name: Optional[str] = None
    severity: Severity
    judgment: Judgment
    judgment_engine: JudgmentEngine
    confidence: Optional[float] = None
    description: Optional[str] = None
    remediation_suggestion: Optional[str] = None
    status: FindingStatus


class FindingResponse(FindingBase):
    id: int
    project_id: int
    scan_task_id: Optional[int] = None
    document_run_id: Optional[int] = None
    evidence_ids: Optional[List[int]] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class FindingDetail(FindingResponse):
    evidences: List['EvidenceResponse'] = []
    document_evidences: List[Dict[str, Any]] = []


# Evidence schemas
class EvidenceBase(BaseModel):
    evidence_type: EvidenceType
    project_id: Optional[int] = None
    source: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    description: Optional[str] = None
    clause_id: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    file_path: Optional[str] = None
    raw_output: Optional[str] = None
    hash_sha256: Optional[str] = None


class EvidenceResponse(EvidenceBase):
    id: int
    finding_id: Optional[int] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ScanTask schemas
class ScanTaskBase(BaseModel):
    task_type: ScanTaskType
    status: ScanTaskStatus
    parameters: Optional[Dict[str, Any]] = None


class ScanTaskResponse(ScanTaskBase):
    id: int
    project_id: int
    asset_id: Optional[int] = None
    triggered_by: TriggeredBy
    result_summary: Optional[Dict[str, Any]] = None
    progress: Optional[Dict[str, Any]] = None
    findings_count: int = 0
    high_severity_count: int = 0
    medium_severity_count: int = 0
    low_severity_count: int = 0
    confirmed_count: int = 0
    unverified_count: int = 0
    incomplete_checks_count: int = 0
    conclusion_status: Optional[str] = None
    conclusion_label: Optional[str] = None
    conclusion_summary: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class ScanTaskDetail(ScanTaskResponse):
    findings: List[FindingResponse] = []


# Result summary
class ResultSummary(BaseModel):
    scan_task: ScanTaskResponse
    findings: List[FindingResponse]
    total_findings: int
    passed: int
    failed: int
    partial: int
    compliance_score: Optional[float] = None


# Forward references
FindingDetail.model_rebuild()
