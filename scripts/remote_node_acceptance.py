"""End-to-end remote-node acceptance against an isolated Docker network."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.asset import Asset, AssetType, VerificationStatus
from app.models.organization import OrganizationMember
from app.models.project import ComplianceLevel, Project, ProjectStatus
from app.models.scan_node import ScanNode
from app.services.execution_engine import ExecutionEngine
from app.services.scan_node_service import new_token, token_hash, utcnow


PROJECT_NAME = "Remote Node Isolated Acceptance"
NODE_NAME = "Remote VPC Acceptance Node"


async def cleanup() -> None:
    async with AsyncSessionLocal() as db:
        nodes = list((await db.execute(select(ScanNode).where(ScanNode.name == NODE_NAME))).scalars().all())
        for node in nodes:
            await db.delete(node)
        projects = list((await db.execute(select(Project).where(Project.name == PROJECT_NAME))).scalars().all())
        for project in projects:
            await db.delete(project)
        await db.commit()


async def setup() -> dict:
    await cleanup()
    async with AsyncSessionLocal() as db:
        member = (await db.execute(select(OrganizationMember).where(
            OrganizationMember.role == "admin",
        ).order_by(OrganizationMember.id))).scalars().first()
        if not member:
            raise RuntimeError("验收需要至少一个现有组织成员")
        project = Project(
            user_id=member.user_id,
            owner_id=member.user_id,
            organization_id=member.organization_id,
            name=PROJECT_NAME,
            description="Only the remote scan-node network can resolve the target hostname.",
            compliance_level=ComplianceLevel.LEVEL_2,
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.flush()
        db.add(Asset(
            project_id=project.id,
            asset_type=AssetType.DOMAIN,
            value="remote-only-target",
            name="隔离网络 HTTP 靶标",
            verification_status=VerificationStatus.VERIFIED,
            is_active=True,
        ))
        enrollment = new_token()
        node = ScanNode(
            organization_id=member.organization_id,
            name=NODE_NAME,
            location="isolated-docker-network",
            enabled=True,
            project_ids=[project.id],
            allowed_cidrs=[],
            capabilities=["scan_ports"],
            max_concurrency=1,
            priority=1,
            enrollment_token_hash=token_hash(enrollment),
            enrollment_expires_at=utcnow().replace(microsecond=0) + timedelta(minutes=30),
            created_by=member.user_id,
        )
        db.add(node)
        await db.commit()
        return {"project_id": project.id, "user_id": member.user_id, "node_id": node.id, "enrollment_token": enrollment}


def contains_port(value, port: int) -> bool:
    if isinstance(value, dict):
        if value.get("port") == port and str(value.get("state", "open")).lower() == "open":
            return True
        return any(contains_port(item, port) for item in value.values())
    if isinstance(value, list):
        return any(contains_port(item, port) for item in value)
    return False


async def run(project_id: int, user_id: int, node_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        result = await ExecutionEngine()._execute_capability(
            "scan_ports",
            {"target": "remote-only-target", "port_range": "8080"},
            user_id,
            project_id=project_id,
            db=db,
        )
    metadata = result.get("metadata") or {}
    execution_node = metadata.get("execution_node") or {}
    if execution_node.get("id") != node_id:
        raise AssertionError(f"task did not use the expected remote node: {metadata}")
    if not contains_port(result, 8080):
        raise AssertionError(f"remote target port 8080 was not reported open: {json.dumps(result, ensure_ascii=False)[:3000]}")
    return {"status": result.get("status"), "remote_job_id": metadata.get("remote_job_id"), "execution_node": execution_node, "port_8080": "open"}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["setup", "run", "cleanup"])
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--node-id", type=int)
    args = parser.parse_args()
    if args.command == "setup":
        output = await setup()
    elif args.command == "cleanup":
        await cleanup()
        output = {"cleaned": True}
    else:
        if not all((args.project_id, args.user_id, args.node_id)):
            parser.error("run requires --project-id, --user-id and --node-id")
        output = await run(args.project_id, args.user_id, args.node_id)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
