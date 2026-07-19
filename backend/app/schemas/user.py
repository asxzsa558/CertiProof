from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime
from app.models.user import UserRole, SubscriptionTier
import re


def validate_password_strength(password: str) -> str:
    """Validate password strength for security."""
    if len(password) < 12:
        raise ValueError("密码长度至少为 12 个字符")
    
    if not re.search(r'[A-Z]', password):
        raise ValueError("密码必须包含至少一个大写字母")
    
    if not re.search(r'[a-z]', password):
        raise ValueError("密码必须包含至少一个小写字母")
    
    if not re.search(r'\d', password):
        raise ValueError("密码必须包含至少一个数字")
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValueError("密码必须包含至少一个特殊字符 (!@#$%^&*等)")
    
    # Check for common weak passwords
    weak_passwords = ['password', '123456', 'qwerty', 'admin', 'letmein', 'welcome']
    if password.lower() in weak_passwords:
        raise ValueError("密码过于简单，请使用更复杂的密码")
    
    return password


class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    full_name: Optional[str] = None
    phone: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=12)
    organization_name: str = Field(..., min_length=1, max_length=200)
    
    @field_validator('password')
    @classmethod
    def password_strength(cls, v):
        return validate_password_strength(v)


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None


class OrganizationBrief(BaseModel):
    id: int
    name: str
    code: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class UserResponse(UserBase):
    id: int
    role: UserRole
    subscription_tier: SubscriptionTier
    is_active: bool
    is_verified: bool
    organizations: List[OrganizationBrief] = []
    created_at: datetime
    last_login_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
    organizations: List[OrganizationBrief] = []


class RefreshTokenRequest(BaseModel):
    refresh_token: str
