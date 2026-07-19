from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from app.models.evidence import EvidenceType


class EvidenceBase(BaseModel):
    evidence_type: EvidenceType
    source: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    file_path: Optional[str] = None
    raw_output: Optional[str] = None
    hash_sha256: Optional[str] = None


class EvidenceCreate(EvidenceBase):
    finding_id: int


class EvidenceResponse(EvidenceBase):
    id: int
    finding_id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
