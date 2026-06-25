from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.organization import Organization, OrganizationMember, OrgRole
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationMemberResponse,
    OrganizationMemberCreate,
    OrganizationMemberUpdate,
)

router = APIRouter(prefix="/organizations", tags=["Organizations"])


async def get_user_org_role(db: AsyncSession, org_id: int, user_id: int) -> str:
    """获取用户在组织中的角色"""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    return member.role


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    org_data: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建组织"""
    code = org_data.code or org_data.name.upper().replace(" ", "_")[:50]

    result = await db.execute(select(Organization).where(Organization.code == code))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization code already exists",
        )

    org = Organization(
        name=org_data.name,
        code=code,
        description=org_data.description,
    )
    db.add(org)
    await db.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=current_user.id,
        role=OrgRole.ADMIN,
    )
    db.add(member)
    await db.commit()
    await db.refresh(org)

    return org


@router.get("/", response_model=List[OrganizationResponse])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的组织列表"""
    result = await db.execute(
        select(Organization)
        .join(OrganizationMember)
        .where(OrganizationMember.user_id == current_user.id)
        .order_by(Organization.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取组织详情"""
    await get_user_org_role(db, org_id, current_user.id)

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: int,
    org_data: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新组织（仅 admin）"""
    role = await get_user_org_role(db, org_id, current_user.id)
    if role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admin can update organization")

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if org_data.name is not None:
        org.name = org_data.name
    if org_data.description is not None:
        org.description = org_data.description

    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除组织（仅 admin）"""
    role = await get_user_org_role(db, org_id, current_user.id)
    if role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admin can delete organization")

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    await db.delete(org)
    await db.commit()
    return None


@router.get("/{org_id}/members", response_model=List[OrganizationMemberResponse])
async def list_members(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取组织成员列表"""
    await get_user_org_role(db, org_id, current_user.id)

    result = await db.execute(
        select(OrganizationMember, User)
        .join(User, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == org_id)
    )

    members = []
    for member, user in result.all():
        members.append(
            OrganizationMemberResponse(
                id=member.id,
                organization_id=member.organization_id,
                user_id=member.user_id,
                role=member.role,
                joined_at=member.joined_at,
                username=user.username,
                email=user.email,
            )
        )
    return members


@router.post("/{org_id}/members", response_model=OrganizationMemberResponse, status_code=201)
async def add_member(
    org_id: int,
    member_data: OrganizationMemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加成员（仅 admin）"""
    role = await get_user_org_role(db, org_id, current_user.id)
    if role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admin can add members")

    result = await db.execute(select(User).where(User.email == member_data.user_email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User already a member")

    member = OrganizationMember(
        organization_id=org_id,
        user_id=user.id,
        role=member_data.role,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    return OrganizationMemberResponse(
        id=member.id,
        organization_id=member.organization_id,
        user_id=member.user_id,
        role=member.role,
        joined_at=member.joined_at,
        username=user.username,
        email=user.email,
    )


@router.put("/{org_id}/members/{member_id}", response_model=OrganizationMemberResponse)
async def update_member_role(
    org_id: int,
    member_id: int,
    member_data: OrganizationMemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改成员角色（仅 admin）"""
    role = await get_user_org_role(db, org_id, current_user.id)
    if role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admin can update member roles")

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.role = member_data.role
    await db.commit()
    await db.refresh(member)

    result = await db.execute(select(User).where(User.id == member.user_id))
    user = result.scalar_one_or_none()

    return OrganizationMemberResponse(
        id=member.id,
        organization_id=member.organization_id,
        user_id=member.user_id,
        role=member.role,
        joined_at=member.joined_at,
        username=user.username if user else None,
        email=user.email if user else None,
    )


@router.delete("/{org_id}/members/{member_id}", status_code=204)
async def remove_member(
    org_id: int,
    member_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移除成员（仅 admin）"""
    role = await get_user_org_role(db, org_id, current_user.id)
    if role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admin can remove members")

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    await db.delete(member)
    await db.commit()
    return None
