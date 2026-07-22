from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from typing import List
import json
from app.core.database import get_db
from app.core.rbac import PERMISSION_GROUPS, require_org_permission
from app.core.security import get_current_user
from app.models.user import User
from app.models.organization import Organization, OrganizationMember, OrganizationRole, OrganizationRoleAudit, OrgRole
from app.models.project import Project
from app.services.audit import record_audit_event
from app.services.data_lifecycle import (
    delete_organization_records,
    delete_project_records,
    delete_storage_files,
    storage_usage,
)
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationMemberResponse,
    OrganizationMemberCreate,
    OrganizationMemberUpdate,
    OrganizationRoleCreate,
    OrganizationRoleUpdate,
    OrganizationRoleResponse,
    OrganizationRoleAuditResponse,
)

router = APIRouter(prefix="/organizations", tags=["Organizations"])


DEFAULT_ROLE_TEMPLATES = [
    ("管理员", "组织全局配置、角色授权和所有项目操作", [p for values in PERMISSION_GROUPS.values() for p in values]),
    ("测评负责人", "推进等保测评、证据和整改闭环", ["project:read", "asset:read", "scan:read", "assessment:read", "assessment:manage", "evidence:manage", "report:read", "report:export"]),
    ("安全工程师", "执行检测、查看工具状态和处理风险", ["project:read", "asset:read", "asset:update", "scan:execute", "scan:read", "scan:cancel", "node:read", "assessment:read", "tool:diagnose"]),
    ("审计查看者", "查看项目、证据、风险和报告", ["project:read", "asset:read", "scan:read", "assessment:read", "report:read"]),
    ("客户只读", "受限查看项目状态和报告", ["project:read", "assessment:read", "report:read"]),
]


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


def validate_permissions(permissions: List[str]) -> List[str]:
    allowed = {permission for values in PERMISSION_GROUPS.values() for permission in values}
    unknown = sorted(set(permissions) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知权限：{', '.join(unknown)}")
    return sorted(set(permissions))


async def organization_admin_count(db: AsyncSession, org_id: int) -> int:
    return int((await db.execute(select(func.count(OrganizationMember.id)).where(
        OrganizationMember.organization_id == org_id,
        OrganizationMember.role == OrgRole.ADMIN,
    ))).scalar() or 0)


async def write_role_audit(
    db: AsyncSession,
    org_id: int,
    actor_user_id: int,
    action: str,
    target_type: str,
    target_id: int | None,
    detail: str,
) -> None:
    db.add(OrganizationRoleAudit(
        organization_id=org_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    ))


async def seed_default_roles(db: AsyncSession, org_id: int, actor_user_id: int | None = None) -> None:
    for name, description, permissions in DEFAULT_ROLE_TEMPLATES:
        result = await db.execute(
            select(OrganizationRole.id).where(
                OrganizationRole.organization_id == org_id,
                OrganizationRole.name == name,
            )
        )
        if result.scalar_one_or_none():
            continue
        db.add(OrganizationRole(
            organization_id=org_id,
            name=name,
            description=description,
            permissions=json.dumps(permissions, ensure_ascii=False),
            is_system=True,
            created_by=actor_user_id,
        ))
        try:
            await db.flush()
        except IntegrityError:
            # ponytail: concurrent role-list calls can race on first org load; the
            # unique key is the lock, and the winner's row is good enough.
            await db.rollback()


@router.get("/{org_id}/storage")
async def get_organization_storage(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "system:config")
    project_ids = list((await db.execute(select(Project.id).where(
        Project.organization_id == org_id
    ))).scalars().all())
    return {"organization_id": org_id, "project_count": len(project_ids), **await storage_usage(db, project_ids)}


@router.post("/{org_id}/initialize")
async def initialize_organization_business_data(
    org_id: int,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "system:config")
    organization = await db.get(Organization, org_id)
    if not organization:
        raise HTTPException(status_code=404, detail="组织不存在")
    if payload.get("confirmation") != organization.name:
        raise HTTPException(status_code=400, detail="请输入完整组织名称以确认初始化")

    projects = list((await db.execute(select(Project).where(
        Project.organization_id == org_id
    ))).scalars().all())
    cleanups = []
    try:
        for project in projects:
            cleanups.append(await delete_project_records(db, project))
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await record_audit_event(
        db,
        event_type="organization.business_data_initialized",
        resource_type="organization",
        resource_id=org_id,
        actor_user_id=current_user.id,
        organization_id=org_id,
        details={
            "deleted_projects": len(cleanups),
            "released_file_bytes": sum(item["released_file_bytes"] for item in cleanups),
            "standard_graph_preserved": True,
            "roles_preserved": True,
        },
    )
    await db.commit()
    files = await delete_storage_files(path for item in cleanups for path in item["file_paths"])
    if files["failed_file_paths"]:
        await record_audit_event(
            db,
            event_type="organization.file_cleanup_partial",
            resource_type="organization",
            resource_id=org_id,
            actor_user_id=current_user.id,
            organization_id=org_id,
            outcome="partial",
            details=files,
        )
        await db.commit()
    return {
        "status": "initialized",
        "deleted_projects": len(cleanups),
        "released_file_bytes": sum(item["released_file_bytes"] for item in cleanups),
        "standard_graph_preserved": True,
        "roles_preserved": True,
        **files,
    }


def serialize_role(role: OrganizationRole, member_count: int = 0) -> OrganizationRoleResponse:
    try:
        permissions = json.loads(role.permissions or "[]")
    except json.JSONDecodeError:
        permissions = []
    return OrganizationRoleResponse(
        id=role.id,
        organization_id=role.organization_id,
        name=role.name,
        description=role.description,
        permissions=permissions,
        is_system=role.is_system,
        member_count=member_count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


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


@router.delete("/{org_id}")
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

    try:
        cleanup = await delete_organization_records(db, org)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit_event(
        db,
        event_type="organization.deleted",
        resource_type="organization",
        resource_id=org_id,
        actor_user_id=current_user.id,
        details={
            "organization_name": org.name,
            "deleted_projects": cleanup["deleted_projects"],
            "released_file_bytes": cleanup["released_file_bytes"],
        },
    )
    await db.commit()
    files = await delete_storage_files(cleanup["file_paths"])
    if files["failed_file_paths"]:
        await record_audit_event(
            db,
            event_type="organization.file_cleanup_partial",
            resource_type="organization",
            resource_id=org_id,
            actor_user_id=current_user.id,
            outcome="partial",
            details=files,
        )
        await db.commit()
    return {
        "status": "deleted",
        "deleted_projects": cleanup["deleted_projects"],
        "released_file_bytes": cleanup["released_file_bytes"],
        **files,
    }


@router.get("/{org_id}/members", response_model=List[OrganizationMemberResponse])
async def list_members(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取组织成员列表"""
    await require_org_permission(db, org_id, current_user, "role:read")

    result = await db.execute(
        select(OrganizationMember, User)
        .join(User, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == org_id)
    )

    members = []
    for member, user in result.all():
        role_name = None
        if member.custom_role_id:
            role_result = await db.execute(select(OrganizationRole).where(OrganizationRole.id == member.custom_role_id))
            custom_role = role_result.scalar_one_or_none()
            role_name = custom_role.name if custom_role else None
        members.append(
            OrganizationMemberResponse(
                id=member.id,
                organization_id=member.organization_id,
                user_id=member.user_id,
                role=member.role,
                custom_role_id=member.custom_role_id,
                custom_role_name=role_name,
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
    """添加组织成员。"""
    actor = await require_org_permission(db, org_id, current_user, "member:manage")
    if member_data.role == OrgRole.ADMIN and actor.role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有组织管理员可以授予管理员身份")

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

    role_name = None
    custom_role_id = None if member_data.role == OrgRole.ADMIN else member_data.custom_role_id
    if custom_role_id:
        role_result = await db.execute(
            select(OrganizationRole).where(
                OrganizationRole.id == custom_role_id,
                OrganizationRole.organization_id == org_id,
            )
        )
        custom_role = role_result.scalar_one_or_none()
        if not custom_role:
            raise HTTPException(status_code=404, detail="Custom role not found")
        role_name = custom_role.name

    member = OrganizationMember(
        organization_id=org_id,
        user_id=user.id,
        role=member_data.role,
        custom_role_id=custom_role_id,
    )
    db.add(member)
    await db.flush()
    await write_role_audit(
        db,
        org_id,
        current_user.id,
        "add_member",
        "member",
        member.id,
        f"Added {user.email} role={member.role}, custom_role_id={member.custom_role_id}",
    )
    await db.commit()
    await db.refresh(member)

    return OrganizationMemberResponse(
        id=member.id,
        organization_id=member.organization_id,
        user_id=member.user_id,
        role=member.role,
        custom_role_id=member.custom_role_id,
        custom_role_name=role_name,
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
    """修改成员基础身份和权限模板。"""
    actor = await require_org_permission(db, org_id, current_user, "member:manage")

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if member.role == OrgRole.ADMIN and actor.role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有组织管理员可以修改管理员")
    if member_data.role == OrgRole.ADMIN and actor.role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有组织管理员可以授予管理员身份")
    if (
        member.role == OrgRole.ADMIN
        and member_data.role != OrgRole.ADMIN
        and await organization_admin_count(db, org_id) <= 1
    ):
        raise HTTPException(status_code=409, detail="组织必须至少保留一名管理员")

    custom_role_id = None if member_data.role == OrgRole.ADMIN else member_data.custom_role_id
    if custom_role_id:
        role_result = await db.execute(
            select(OrganizationRole).where(
                OrganizationRole.id == custom_role_id,
                OrganizationRole.organization_id == org_id,
            )
        )
        if not role_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Custom role not found")

    member.role = member_data.role
    member.custom_role_id = custom_role_id
    await write_role_audit(
        db,
        org_id,
        current_user.id,
        "assign_member_role",
        "member",
        member.id,
        f"Set member {member.id} role={member.role}, custom_role_id={member.custom_role_id}",
    )
    await db.commit()
    await db.refresh(member)

    result = await db.execute(select(User).where(User.id == member.user_id))
    user = result.scalar_one_or_none()

    role_name = None
    if member.custom_role_id:
        role_result = await db.execute(select(OrganizationRole).where(OrganizationRole.id == member.custom_role_id))
        custom_role = role_result.scalar_one_or_none()
        role_name = custom_role.name if custom_role else None

    return OrganizationMemberResponse(
        id=member.id,
        organization_id=member.organization_id,
        user_id=member.user_id,
        role=member.role,
        custom_role_id=member.custom_role_id,
        custom_role_name=role_name,
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
    """移除组织成员。"""
    actor = await require_org_permission(db, org_id, current_user, "member:manage")

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.user_id == current_user.id:
        raise HTTPException(status_code=409, detail="不能在访问控制页移除自己")
    if member.role == OrgRole.ADMIN and actor.role != OrgRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有组织管理员可以移除管理员")
    if member.role == OrgRole.ADMIN and await organization_admin_count(db, org_id) <= 1:
        raise HTTPException(status_code=409, detail="不能移除组织最后一名管理员")

    await write_role_audit(
        db,
        org_id,
        current_user.id,
        "remove_member",
        "member",
        member.id,
        f"Removed member {member.id} user_id={member.user_id}",
    )
    await db.delete(member)
    await db.commit()
    return None


@router.get("/{org_id}/permissions")
async def list_permissions(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "role:read")
    return {"permission_groups": PERMISSION_GROUPS}


@router.get("/{org_id}/roles", response_model=List[OrganizationRoleResponse])
async def list_roles(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "role:read")
    await seed_default_roles(db, org_id, current_user.id)
    await db.flush()

    result = await db.execute(
        select(OrganizationRole)
        .where(OrganizationRole.organization_id == org_id)
        .order_by(OrganizationRole.is_system.desc(), OrganizationRole.created_at.asc())
    )
    roles = result.scalars().all()
    responses = []
    for role in roles:
        count_result = await db.execute(
            select(func.count(OrganizationMember.id)).where(OrganizationMember.custom_role_id == role.id)
        )
        responses.append(serialize_role(role, count_result.scalar() or 0))
    return responses


@router.post("/{org_id}/roles", response_model=OrganizationRoleResponse, status_code=201)
async def create_role(
    org_id: int,
    role_data: OrganizationRoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "role:manage")
    permissions = validate_permissions(role_data.permissions)
    role = OrganizationRole(
        organization_id=org_id,
        name=role_data.name,
        description=role_data.description,
        permissions=json.dumps(permissions, ensure_ascii=False),
        is_system=False,
        created_by=current_user.id,
    )
    db.add(role)
    await db.flush()
    await write_role_audit(db, org_id, current_user.id, "create_role", "role", role.id, f"Created role {role.name}")
    await db.commit()
    await db.refresh(role)
    return serialize_role(role)


@router.put("/{org_id}/roles/{role_id}", response_model=OrganizationRoleResponse)
async def update_role(
    org_id: int,
    role_id: int,
    role_data: OrganizationRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "role:manage")
    result = await db.execute(select(OrganizationRole).where(OrganizationRole.id == role_id, OrganizationRole.organization_id == org_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=409, detail="系统角色模板不可编辑，请创建自定义角色")
    if role_data.name is not None:
        role.name = role_data.name
    if role_data.description is not None:
        role.description = role_data.description
    if role_data.permissions is not None:
        role.permissions = json.dumps(validate_permissions(role_data.permissions), ensure_ascii=False)
    await write_role_audit(db, org_id, current_user.id, "update_role", "role", role.id, f"Updated role {role.name}")
    await db.commit()
    await db.refresh(role)
    count_result = await db.execute(select(func.count(OrganizationMember.id)).where(OrganizationMember.custom_role_id == role.id))
    return serialize_role(role, count_result.scalar() or 0)


@router.delete("/{org_id}/roles/{role_id}", status_code=204)
async def delete_role(
    org_id: int,
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "role:manage")
    result = await db.execute(select(OrganizationRole).where(OrganizationRole.id == role_id, OrganizationRole.organization_id == org_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System role cannot be deleted")
    await db.execute(
        OrganizationMember.__table__.update()
        .where(OrganizationMember.custom_role_id == role.id)
        .values(custom_role_id=None)
    )
    await write_role_audit(db, org_id, current_user.id, "delete_role", "role", role.id, f"Deleted role {role.name}")
    await db.delete(role)
    await db.commit()
    return None


@router.get("/{org_id}/role-audits", response_model=List[OrganizationRoleAuditResponse])
async def list_role_audits(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "role:read")
    result = await db.execute(
        select(OrganizationRoleAudit)
        .where(OrganizationRoleAudit.organization_id == org_id)
        .order_by(OrganizationRoleAudit.created_at.desc())
        .limit(20)
    )
    return result.scalars().all()
