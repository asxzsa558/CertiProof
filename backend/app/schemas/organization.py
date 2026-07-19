from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional, List
from datetime import datetime


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None


class OrganizationResponse(BaseModel):
    id: int
    name: str
    code: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationBrief(BaseModel):
    id: int
    name: str
    code: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberResponse(BaseModel):
    id: int
    organization_id: int
    user_id: int
    role: str
    custom_role_id: Optional[int] = None
    custom_role_name: Optional[str] = None
    joined_at: datetime
    username: Optional[str] = None
    email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberCreate(BaseModel):
    user_email: str
    role: Literal["admin", "manager", "member", "viewer"] = "member"
    custom_role_id: Optional[int] = None


class OrganizationMemberUpdate(BaseModel):
    role: Literal["admin", "manager", "member", "viewer"]
    custom_role_id: Optional[int] = None


class OrganizationRoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)


class OrganizationRoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = None
    permissions: Optional[List[str]] = None


class OrganizationRoleResponse(BaseModel):
    id: int
    organization_id: int
    name: str
    description: Optional[str] = None
    permissions: List[str]
    is_system: bool
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class OrganizationRoleAuditResponse(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: Optional[int] = None
    detail: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
