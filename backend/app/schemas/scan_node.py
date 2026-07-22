from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScanNodeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    location: str | None = Field(None, max_length=160)
    description: str | None = Field(None, max_length=1000)
    allowed_cidrs: list[str] = Field(default_factory=list, max_length=128)
    project_ids: list[int] = Field(default_factory=list, max_length=256)
    capabilities: list[str] = Field(default_factory=list, max_length=128)
    max_concurrency: int = Field(2, ge=1, le=16)
    priority: int = Field(100, ge=1, le=1000)

    @field_validator("allowed_cidrs", "capabilities")
    @classmethod
    def strip_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    @field_validator("project_ids")
    @classmethod
    def unique_projects(cls, values: list[int]) -> list[int]:
        return list(dict.fromkeys(values))


class ScanNodeCreate(ScanNodeBase):
    pass


class ScanNodeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    location: str | None = Field(None, max_length=160)
    description: str | None = Field(None, max_length=1000)
    enabled: bool | None = None
    allowed_cidrs: list[str] | None = Field(None, max_length=128)
    project_ids: list[int] | None = Field(None, max_length=256)
    capabilities: list[str] | None = Field(None, max_length=128)
    max_concurrency: int | None = Field(None, ge=1, le=16)
    priority: int | None = Field(None, ge=1, le=1000)

    @field_validator("allowed_cidrs", "capabilities")
    @classmethod
    def strip_values(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    @field_validator("project_ids")
    @classmethod
    def unique_projects(cls, values: list[int] | None) -> list[int] | None:
        return list(dict.fromkeys(values)) if values is not None else None


class ScanNodeResponse(ScanNodeBase):
    id: int
    organization_id: int
    enabled: bool
    status: str
    config_version: int
    enrolled_at: datetime | None = None
    last_seen_at: datetime | None = None
    runtime_info: dict[str, Any] | None = None
    active_jobs: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EnrollmentResponse(BaseModel):
    node_id: int
    node_token: str
    config: dict[str, Any]


class ScanNodeCreated(BaseModel):
    node: ScanNodeResponse
    enrollment_token: str
    enrollment_expires_at: datetime


class NodeHeartbeat(BaseModel):
    runtime_info: dict[str, Any] = Field(default_factory=dict)
    active_jobs: int = Field(0, ge=0, le=64)
    config_version: int = Field(0, ge=0)


class NodeEnrollRequest(BaseModel):
    enrollment_token: str = Field(..., min_length=32, max_length=256)
    runtime_info: dict[str, Any] = Field(default_factory=dict)


class NodeJobUpdate(BaseModel):
    progress: dict[str, Any] = Field(default_factory=dict)


class NodeJobResult(BaseModel):
    result: dict[str, Any]


class NodeJobFailure(BaseModel):
    error: str = Field(..., min_length=1, max_length=4000)


class RouteTestRequest(BaseModel):
    target: str = Field(..., min_length=1, max_length=500)
    project_id: int | None = None
    capability: str = Field("scan_ports", min_length=1, max_length=80)
