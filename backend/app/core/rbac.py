import json
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import OrganizationMember, OrganizationRole, OrgRole
from app.models.project import Project
from app.models.user import User


PERMISSION_GROUPS = {
    "project": ["project:read", "project:create", "project:update", "project:delete"],
    "asset": ["asset:read", "asset:create", "asset:update", "asset:delete"],
    "scan": ["scan:execute", "scan:read", "scan:cancel"],
    "assessment": ["assessment:read", "assessment:manage", "evidence:manage"],
    "report": ["report:read", "report:export", "report:delete"],
    "rbac": ["role:read", "role:manage", "member:manage"],
    "system": ["system:config", "tool:diagnose"],
}

ALL_PERMISSIONS = {permission for permissions in PERMISSION_GROUPS.values() for permission in permissions}

DEFAULT_ROLE_PERMISSIONS = {
    OrgRole.ADMIN: ALL_PERMISSIONS,
    OrgRole.MANAGER: ALL_PERMISSIONS - {"role:manage", "member:manage", "system:config"},
    OrgRole.MEMBER: {
        "project:read",
        "asset:read",
        "asset:create",
        "asset:update",
        "scan:execute",
        "scan:read",
        "scan:cancel",
        "assessment:read",
        "assessment:manage",
        "evidence:manage",
        "report:read",
    },
    OrgRole.VIEWER: {"project:read", "asset:read", "scan:read", "assessment:read", "report:read"},
}


async def get_org_member(db: AsyncSession, org_id: int, user_id: int) -> OrganizationMember:
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
    return member


def normalize_permissions(raw_permissions: str | None) -> set[str]:
    try:
        permissions = json.loads(raw_permissions or "[]")
    except json.JSONDecodeError:
        return set()
    if not isinstance(permissions, list):
        return set()
    return {permission for permission in permissions if isinstance(permission, str)}


async def resolve_member_permissions(db: AsyncSession, member: OrganizationMember) -> set[str]:
    role = OrgRole(member.role) if member.role in OrgRole._value2member_map_ else OrgRole.VIEWER
    permissions = set(DEFAULT_ROLE_PERMISSIONS.get(role, set()))
    if role == OrgRole.ADMIN:
        return set(ALL_PERMISSIONS)
    if not member.custom_role_id:
        return permissions

    result = await db.execute(
        select(OrganizationRole).where(
            OrganizationRole.id == member.custom_role_id,
            OrganizationRole.organization_id == member.organization_id,
        )
    )
    custom_role = result.scalar_one_or_none()
    if custom_role:
        return normalize_permissions(custom_role.permissions)
    return permissions


async def require_org_permission(
    db: AsyncSession,
    org_id: int,
    user: User,
    required: str | Iterable[str],
) -> OrganizationMember:
    member = await get_org_member(db, org_id, user.id)
    permissions = await resolve_member_permissions(db, member)
    required_permissions = {required} if isinstance(required, str) else set(required)
    if not required_permissions.issubset(permissions):
        missing = ", ".join(sorted(required_permissions - permissions))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions: {missing}",
        )
    return member


async def require_org_permission_for_user_id(
    db: AsyncSession,
    org_id: int,
    user_id: int,
    required: str | Iterable[str],
) -> OrganizationMember:
    member = await get_org_member(db, org_id, user_id)
    permissions = await resolve_member_permissions(db, member)
    required_permissions = {required} if isinstance(required, str) else set(required)
    if not required_permissions.issubset(permissions):
        missing = ", ".join(sorted(required_permissions - permissions))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions: {missing}",
        )
    return member


async def require_any_org_permission(
    db: AsyncSession,
    user: User,
    required: str | Iterable[str],
) -> OrganizationMember:
    result = await db.execute(
        select(OrganizationMember).where(OrganizationMember.user_id == user.id)
    )
    memberships = result.scalars().all()
    required_permissions = {required} if isinstance(required, str) else set(required)
    for member in memberships:
        permissions = await resolve_member_permissions(db, member)
        if required_permissions.issubset(permissions):
            return member

    missing = ", ".join(sorted(required_permissions))
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Insufficient permissions: {missing}",
    )


async def get_project_for_user(
    db: AsyncSession,
    project_id: int,
    user: User,
    permission: str | Iterable[str] = "project:read",
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.organization_id:
        await require_org_permission(db, project.organization_id, user, permission)
    elif project.user_id != user.id:
        raise HTTPException(status_code=403, detail="No access to this project")
    return project
