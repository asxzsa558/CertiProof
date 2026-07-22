import asyncio
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.scan_nodes import enroll_node
from app.core.database import Base
from app.models.scan_node import RemoteExecution, ScanNode
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.remote_node_worker import job_allowed
from app.schemas.scan_node import NodeEnrollRequest
from app.services.scan_node_service import (
    execution_targets,
    node_online,
    node_active_jobs,
    node_running_jobs,
    node_route_kind,
    target_host,
    token_hash,
    utcnow,
    validate_node_routes,
)
from app.services.data_lifecycle import delete_organization_records, delete_project_records


def node(**overrides):
    values = {
        "id": 1,
        "enabled": True,
        "node_token_hash": token_hash("node-secret"),
        "last_seen_at": utcnow(),
        "allowed_cidrs": ["10.20.0.0/16"],
        "project_ids": [7],
        "capabilities": ["scan_ports", "nikto_scan"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_route_prefers_explicit_project_and_supports_domains():
    assert node_route_kind(node(), project_id=7, targets=["https://internal.example"], capability="nikto_scan") == "project"
    assert node_route_kind(node(), project_id=8, targets=["https://internal.example"], capability="nikto_scan") is None


def test_cidr_route_requires_every_target_to_match():
    candidate = node(project_ids=[])
    assert node_route_kind(candidate, project_id=8, targets=["10.20.1.8", "https://10.20.2.9:8443"], capability="scan_ports") == "cidr"
    assert node_route_kind(candidate, project_id=8, targets=["10.20.1.8", "10.21.0.4"], capability="scan_ports") is None


def test_offline_status_uses_heartbeat_deadline():
    assert node_online(node()) is True
    assert node_online(node(last_seen_at=utcnow() - timedelta(hours=1))) is False
    assert node_online(node(enabled=False)) is False


def test_worker_rechecks_capability_and_route_before_execution():
    config = {
        "capabilities": ["scan_ports"],
        "project_ids": [],
        "allowed_cidrs": ["10.20.0.0/16"],
    }
    allowed = {"capability": "scan_ports", "project_id": 8, "parameters": {"target": "10.20.1.4"}}
    forbidden_target = {**allowed, "parameters": {"target": "192.0.2.4"}}
    forbidden_capability = {**allowed, "capability": "view_findings"}
    assert job_allowed(config, allowed) is True
    assert job_allowed(config, forbidden_target) is False
    assert job_allowed(config, forbidden_capability) is False


def test_route_input_validation_and_target_normalization():
    validate_node_routes(["10.0.0.0/8", "2001:db8::/32"], ["scan_ports"])
    assert target_host("https://10.20.1.5:8443/path") == "10.20.1.5"
    assert execution_targets({"target": "10.0.0.1", "targets": ["10.0.0.2", "10.0.0.1"]}) == ["10.0.0.1", "10.0.0.2"]

    try:
        validate_node_routes(["not-a-cidr"], ["scan_ports"])
    except ValueError as exc:
        assert "无效网段" in str(exc)
    else:
        raise AssertionError("invalid CIDR was accepted")


def test_queued_job_does_not_consume_running_capacity():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)
        async with session() as db:
            scan_node = ScanNode(organization_id=1, name="node", capabilities=["scan_ports"])
            db.add(scan_node)
            await db.flush()
            db.add(RemoteExecution(
                id="job-1",
                scan_node_id=scan_node.id,
                organization_id=1,
                capability="scan_ports",
                target="10.0.0.1",
                payload_envelope="encrypted",
                status="queued",
            ))
            await db.commit()
            assert await node_active_jobs(db, scan_node.id) == 1
            assert await node_running_jobs(db, scan_node.id) == 0
        await engine.dispose()

    asyncio.run(scenario())


def test_enrollment_token_is_single_use():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)
        token = "x" * 40
        async with session() as db:
            db.add(ScanNode(
                organization_id=1,
                name="node",
                enabled=True,
                capabilities=["scan_ports"],
                enrollment_token_hash=token_hash(token),
                enrollment_expires_at=utcnow() + timedelta(minutes=5),
            ))
            await db.commit()
            response = await enroll_node(NodeEnrollRequest(enrollment_token=token), db)
            assert response.node_token
            try:
                await enroll_node(NodeEnrollRequest(enrollment_token=token), db)
            except HTTPException as exc:
                assert exc.status_code == 401
            else:
                raise AssertionError("enrollment token was accepted twice")
        await engine.dispose()

    asyncio.run(scenario())


def test_project_and_organization_cleanup_remove_remote_routes_and_history():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session = async_sessionmaker(engine, expire_on_commit=False)
        async with session() as db:
            user = User(email="remote-cleanup@example.test", username="remote-cleanup", hashed_password="test")
            organization = Organization(name="Remote Cleanup", code="remote-cleanup")
            db.add_all([user, organization])
            await db.flush()
            project = Project(user_id=user.id, organization_id=organization.id, name="Remote Cleanup")
            db.add(project)
            await db.flush()
            scan_node = ScanNode(
                organization_id=organization.id,
                name="node",
                project_ids=[project.id],
                capabilities=["scan_ports"],
            )
            db.add(scan_node)
            await db.flush()
            organization_id = organization.id
            project_id = project.id
            node_id = scan_node.id
            db.add(RemoteExecution(
                id="completed-job",
                scan_node_id=scan_node.id,
                organization_id=organization.id,
                project_id=project.id,
                capability="scan_ports",
                target="10.0.0.1",
                payload_envelope="encrypted",
                status="running",
            ))
            await db.commit()

            try:
                await delete_project_records(db, project)
            except ValueError as exc:
                assert "远端执行 1 个" in str(exc)
                await db.rollback()
            else:
                raise AssertionError("project deletion accepted a running remote execution")
            job = await db.get(RemoteExecution, "completed-job")
            job.status = "completed"
            await db.commit()

            project = await db.get(Project, project_id)
            await delete_project_records(db, project)
            await db.commit()
            assert await db.get(Project, project_id) is None
            assert (await db.execute(select(RemoteExecution))).scalars().all() == []
            scan_node = await db.get(ScanNode, node_id)
            await db.refresh(scan_node)
            assert scan_node.project_ids == []

            organization = await db.get(Organization, organization_id)
            await delete_organization_records(db, organization)
            await db.commit()
            assert await db.get(Organization, organization_id) is None
            assert await db.get(ScanNode, node_id) is None
        await engine.dispose()

    asyncio.run(scenario())
