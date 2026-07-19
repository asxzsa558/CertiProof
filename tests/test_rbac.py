import asyncio

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.organizations import remove_member, update_member_role, validate_permissions
from app.core.database import Base
from app.core.rbac import ALL_PERMISSIONS, require_org_permission, resolve_member_permissions
from app.models.organization import Organization, OrganizationMember, OrganizationRole
from app.models.user import User
from app.schemas.organization import OrganizationMemberUpdate


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_custom_role_permissions_are_enforced():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            admin = User(email="admin-rbac@example.test", username="admin-rbac", hashed_password="test")
            engineer = User(email="engineer-rbac@example.test", username="engineer-rbac", hashed_password="test")
            organization = Organization(name="RBAC", code="rbac-test")
            db.add_all([admin, engineer, organization])
            await db.flush()

            role = OrganizationRole(
                organization_id=organization.id,
                name="扫描执行者",
                permissions='["project:read", "scan:execute"]',
            )
            db.add(role)
            await db.flush()
            admin_member = OrganizationMember(
                organization_id=organization.id,
                user_id=admin.id,
                role="admin",
            )
            engineer_member = OrganizationMember(
                organization_id=organization.id,
                user_id=engineer.id,
                role="viewer",
                custom_role_id=role.id,
            )
            db.add_all([admin_member, engineer_member])
            await db.commit()

            assert await resolve_member_permissions(db, admin_member) == ALL_PERMISSIONS
            assert await resolve_member_permissions(db, engineer_member) == {"project:read", "scan:execute"}
            await require_org_permission(db, organization.id, engineer, "scan:execute")
            try:
                await require_org_permission(db, organization.id, engineer, "asset:update")
                raise AssertionError("custom role must reject permissions it does not contain")
            except HTTPException as exc:
                assert exc.status_code == 403
        await engine.dispose()

    asyncio.run(run())


def test_last_admin_and_self_removal_are_protected():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            admin = User(email="last-admin@example.test", username="last-admin", hashed_password="test")
            organization = Organization(name="Protected", code="protected-admin")
            db.add_all([admin, organization])
            await db.flush()
            member = OrganizationMember(
                organization_id=organization.id,
                user_id=admin.id,
                role="admin",
            )
            db.add(member)
            await db.commit()

            try:
                await update_member_role(
                    organization.id,
                    member.id,
                    OrganizationMemberUpdate(role="viewer"),
                    db,
                    admin,
                )
                raise AssertionError("the final organization admin must not be demoted")
            except HTTPException as exc:
                assert exc.status_code == 409
                assert "至少保留一名管理员" in exc.detail

            try:
                await remove_member(organization.id, member.id, db, admin)
                raise AssertionError("the current user must not remove themselves")
            except HTTPException as exc:
                assert exc.status_code == 409
                assert "移除自己" in exc.detail
        await engine.dispose()

    asyncio.run(run())


def test_role_permissions_reject_unknown_values():
    assert validate_permissions(["scan:read", "scan:read"]) == ["scan:read"]
    try:
        validate_permissions(["scan:read", "root:everything"])
        raise AssertionError("unknown permissions must be rejected")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "root:everything" in exc.detail
