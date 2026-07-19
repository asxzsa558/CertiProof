from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime
from app.models.asset import AssetType, VerificationStatus, VerificationMethod


class AssetBase(BaseModel):
    asset_type: AssetType
    value: str = Field(..., min_length=1, max_length=500)
    name: Optional[str] = Field(None, max_length=200)


class AssetCreate(AssetBase):
    pass


class AssetVerify(BaseModel):
    verification_method: VerificationMethod


class AssetScopeConfirmation(BaseModel):
    confirmed: bool


class AssetResponse(AssetBase):
    id: int
    project_id: int
    verification_status: VerificationStatus
    verification_method: Optional[VerificationMethod] = None
    verification_token: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    verified_at: Optional[datetime] = None
    scope_confirmed_by: Optional[int] = None
    scope_confirmed_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class AssetListResponse(BaseModel):
    id: int
    asset_type: AssetType
    value: str
    name: Optional[str] = None
    verification_status: VerificationStatus
    is_active: bool
    created_at: datetime
    scope_confirmed_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)
