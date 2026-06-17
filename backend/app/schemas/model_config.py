from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.model_config import ProviderType


# --- Provider Schemas ---

class ModelProviderBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider_type: ProviderType
    api_key: Optional[str] = None
    api_base: Optional[str] = None


class ModelProviderCreate(ModelProviderBase):
    pass


class ModelProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    is_active: Optional[bool] = None


class ModelProviderResponse(ModelProviderBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# --- Config Schemas ---

class ModelConfigBase(BaseModel):
    provider_id: int
    model_name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    capabilities: Optional[List[str]] = None
    max_tokens: Optional[int] = 4096
    is_default: Optional[bool] = False
    priority: Optional[int] = 0


class ModelConfigCreate(ModelConfigBase):
    pass


class ModelConfigUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    capabilities: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    is_default: Optional[bool] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class ModelConfigResponse(ModelConfigBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ModelConfigWithProvider(ModelConfigResponse):
    provider: ModelProviderResponse


# --- Usage Schemas ---

class ModelUsageResponse(BaseModel):
    id: int
    user_id: int
    model_config_id: int
    prompt_tokens: int
    completion_tokens: int
    task_type: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class ModelUsageSummary(BaseModel):
    model_name: str
    display_name: str
    total_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int


class AvailableModel(BaseModel):
    id: int
    model_name: str
    display_name: str
    provider_name: str
    capabilities: Optional[List[str]]
    is_default: bool
    
    class Config:
        from_attributes = True
