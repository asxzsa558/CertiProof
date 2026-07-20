from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from app.core.database import get_db
from app.core.config import settings
from app.core.security import get_password_hash, verify_password, create_access_token, create_refresh_token, get_current_user
from app.models.user import User
from app.models.organization import Organization, OrganizationMember, OrgRole
from app.schemas.user import UserCreate, UserLogin, UserResponse, TokenResponse, RefreshTokenRequest, OrganizationBrief
from app.core.security import decode_token
import re
import asyncio
import time

router = APIRouter(prefix="/auth", tags=["Authentication"])
_login_failures: dict[str, list[float]] = {}
_login_lock = asyncio.Lock()


def _login_client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _enforce_login_rate_limit(request: Request) -> None:
    key = _login_client_key(request)
    now = time.monotonic()
    cutoff = now - settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    async with _login_lock:
        failures = [stamp for stamp in _login_failures.get(key, []) if stamp >= cutoff]
        _login_failures[key] = failures
        if len(failures) >= settings.LOGIN_RATE_LIMIT_ATTEMPTS:
            retry_after = max(1, int(failures[0] + settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS - now))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="登录尝试过于频繁，请稍后再试",
                headers={"Retry-After": str(retry_after)},
            )


async def _record_login_result(request: Request, success: bool) -> None:
    key = _login_client_key(request)
    async with _login_lock:
        if success:
            _login_failures.pop(key, None)
        else:
            _login_failures.setdefault(key, []).append(time.monotonic())


async def get_user_organizations(db: AsyncSession, user_id: int) -> list[OrganizationBrief]:
    """获取用户所属的所有组织"""
    result = await db.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.created_at.desc())
    )
    orgs = []
    for org, role in result.all():
        orgs.append(OrganizationBrief(
            id=org.id,
            name=org.name,
            code=org.code,
            role=role,
        ))
    return orgs


def generate_org_code(name: str) -> str:
    """从组织名称生成 code"""
    code = re.sub(r'[^A-Za-z0-9]', '', name).upper()[:50]
    if not code:
        code = "ORG"
    return code


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(status_code=403, detail="公开注册已关闭，请联系组织管理员")
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )
    
    # Create user
    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        phone=user_data.phone,
    )
    db.add(user)
    await db.flush()
    
    # Create organization
    base_code = generate_org_code(user_data.organization_name)
    code = base_code
    counter = 1
    while True:
        result = await db.execute(select(Organization).where(Organization.code == code))
        if not result.scalar_one_or_none():
            break
        code = f"{base_code}{counter}"
        counter += 1
    
    org = Organization(
        name=user_data.organization_name,
        code=code,
    )
    db.add(org)
    await db.flush()
    
    # Add user as admin of organization
    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrgRole.ADMIN,
    )
    db.add(member)
    
    await db.commit()
    await db.refresh(user)
    
    # Build response with organizations
    orgs = await get_user_organizations(db, user.id)
    user_response = UserResponse.model_validate(user)
    user_response.organizations = orgs
    return user_response


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    await _enforce_login_rate_limit(request)
    # Find user
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        await _record_login_result(request, False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    await _record_login_result(request, True)
    
    # Update last login
    user.last_login_at = datetime.utcnow()
    await db.commit()
    
    # Create tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    # Get user's organizations
    orgs = await get_user_organizations(db, user.id)
    
    user_response = UserResponse.model_validate(user)
    user_response.organizations = orgs
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user_response,
        organizations=orgs,
    )


@router.get("/registration-status")
async def registration_status():
    return {"enabled": settings.ALLOW_PUBLIC_REGISTRATION}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(request.refresh_token)
    
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    # Create new tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    # Get user's organizations
    orgs = await get_user_organizations(db, user.id)
    user_response = UserResponse.model_validate(user)
    user_response.organizations = orgs
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        user=user_response,
        organizations=orgs,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    orgs = await get_user_organizations(db, current_user.id)
    user_response = UserResponse.model_validate(current_user)
    user_response.organizations = orgs
    return user_response


@router.get("/organizations")
async def get_my_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户所属的所有组织"""
    orgs = await get_user_organizations(db, current_user.id)
    return {"organizations": orgs}
