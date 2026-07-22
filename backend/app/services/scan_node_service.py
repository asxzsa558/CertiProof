"""Routing and lease helpers for outbound-only remote scan nodes."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redaction import redact_sensitive
from app.core.secret_box import encrypt_json
from app.models.project import Project
from app.models.scan_node import RemoteExecution, ScanNode
from app.services.execution_policy import NETWORK_CAPABILITIES


TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


class RemoteNodeUnavailable(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(40)


def validate_node_routes(allowed_cidrs: list[str], capabilities: list[str]) -> None:
    for cidr in allowed_cidrs:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError(f"无效网段：{cidr}") from exc
    unsupported = sorted(set(capabilities) - NETWORK_CAPABILITIES)
    if unsupported:
        raise ValueError(f"远端节点不支持这些能力：{', '.join(unsupported)}")


def target_host(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "://" in text:
        return urlsplit(text).hostname
    if "/" in text:
        try:
            return str(ipaddress.ip_network(text, strict=False).network_address)
        except ValueError:
            return text
    if text.count(":") == 1 and text.rsplit(":", 1)[1].isdigit():
        return text.rsplit(":", 1)[0]
    return text


def execution_targets(parameters: dict) -> list[str]:
    values = []
    for key in ("target", "url", "network"):
        if parameters.get(key):
            values.append(str(parameters[key]))
    values.extend(str(value) for value in parameters.get("targets") or [] if value)
    return list(dict.fromkeys(values))


def node_route_kind(node: ScanNode, *, project_id: int | None, targets: list[str], capability: str) -> str | None:
    if capability not in (node.capabilities or []):
        return None
    if project_id and project_id in (node.project_ids or []):
        return "project"
    if not targets or not node.allowed_cidrs:
        return None
    networks = [ipaddress.ip_network(value, strict=False) for value in node.allowed_cidrs]
    for value in targets:
        host = target_host(value)
        try:
            address = ipaddress.ip_address(host or "")
        except ValueError:
            return None
        if not any(address in network for network in networks):
            return None
    return "cidr"


def node_online(node: ScanNode, now: datetime | None = None) -> bool:
    if not node.enabled or not node.node_token_hash or not node.last_seen_at:
        return False
    seen = node.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (now or utcnow()) - seen <= timedelta(seconds=settings.REMOTE_NODE_OFFLINE_SECONDS)


def public_node_config(node: ScanNode) -> dict:
    return {
        "node_id": node.id,
        "name": node.name,
        "allowed_cidrs": node.allowed_cidrs or [],
        "project_ids": node.project_ids or [],
        "capabilities": node.capabilities or [],
        "max_concurrency": node.max_concurrency,
        "config_version": node.config_version,
        "heartbeat_seconds": settings.REMOTE_NODE_HEARTBEAT_SECONDS,
        "lease_seconds": settings.REMOTE_JOB_LEASE_SECONDS,
    }


async def select_scan_node(
    db: AsyncSession,
    *,
    organization_id: int,
    project_id: int | None,
    capability: str,
    targets: list[str],
) -> tuple[ScanNode | None, str | None]:
    nodes = list((await db.execute(
        select(ScanNode).where(
            ScanNode.organization_id == organization_id,
            ScanNode.enabled.is_(True),
        ).order_by(ScanNode.priority.asc(), ScanNode.id.asc())
    )).scalars().all())
    matches = []
    for node in nodes:
        kind = node_route_kind(node, project_id=project_id, targets=targets, capability=capability)
        if kind:
            matches.append((node, kind))
    if not matches:
        return None, None
    matches.sort(key=lambda item: (0 if item[1] == "project" else 1, item[0].priority, item[0].id))
    online = next(((node, kind) for node, kind in matches if node_online(node)), None)
    if online:
        return online
    names = "、".join(node.name for node, _ in matches[:3])
    raise RemoteNodeUnavailable(f"目标已配置远端扫描节点（{names}），但节点当前离线，未回退到其他网络执行以避免错误结论")


def _with_execution_node(result: dict, node: ScanNode, job_id: str, route_kind: str) -> dict:
    output = dict(result or {})
    metadata = dict(output.get("metadata") or {})
    metadata.update({
        "execution_node": {"id": node.id, "name": node.name, "location": node.location},
        "remote_job_id": job_id,
        "route": route_kind,
    })
    output["metadata"] = metadata
    return output


async def dispatch_remote_execution(
    db: AsyncSession,
    *,
    capability: str,
    parameters: dict,
    user_id: int,
    project_id: int,
) -> dict | None:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project or not project.organization_id:
        return None
    targets = execution_targets(parameters)
    node, route_kind = await select_scan_node(
        db,
        organization_id=project.organization_id,
        project_id=project_id,
        capability=capability,
        targets=targets,
    )
    if not node:
        return None

    job_id = str(uuid.uuid4())
    payload = {"capability": capability, "parameters": parameters, "user_id": user_id}
    async with AsyncSessionLocal() as queue_db:
        queue_db.add(RemoteExecution(
            id=job_id,
            scan_node_id=node.id,
            organization_id=project.organization_id,
            project_id=project_id,
            user_id=user_id,
            capability=capability,
            target=", ".join(targets)[:500] or "项目资产",
            payload_envelope=encrypt_json(payload),
            status="queued",
            progress={"stage": "等待远端节点领取", "percent": 0},
        ))
        await queue_db.commit()

    deadline = asyncio.get_running_loop().time() + settings.REMOTE_JOB_TIMEOUT_SECONDS
    try:
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(settings.REMOTE_JOB_POLL_SECONDS)
            async with AsyncSessionLocal() as poll_db:
                job = await poll_db.get(RemoteExecution, job_id)
                if not job:
                    raise RemoteNodeUnavailable("远端执行记录已被删除")
                if job.status == "completed":
                    return _with_execution_node(job.result or {}, node, job_id, route_kind or "remote")
                if job.status == "failed":
                    raise RemoteNodeUnavailable(f"远端节点执行失败：{job.error or '未返回错误详情'}")
                if job.status == "cancelled":
                    raise asyncio.CancelledError()
        async with AsyncSessionLocal() as timeout_db:
            job = await timeout_db.get(RemoteExecution, job_id)
            if job and job.status not in TERMINAL_JOB_STATUSES:
                job.status = "failed"
                job.control_state = "cancel_requested"
                job.error = f"远端执行超过 {settings.REMOTE_JOB_TIMEOUT_SECONDS} 秒"
                job.completed_at = utcnow()
                await timeout_db.commit()
        raise RemoteNodeUnavailable("远端节点执行超时，任务已停止")
    except asyncio.CancelledError:
        async with AsyncSessionLocal() as cancel_db:
            job = await cancel_db.get(RemoteExecution, job_id)
            if job and job.status not in TERMINAL_JOB_STATUSES:
                job.control_state = "cancel_requested"
                await cancel_db.commit()
        raise


async def node_active_jobs(db: AsyncSession, node_id: int) -> int:
    return int((await db.execute(select(func.count(RemoteExecution.id)).where(
        RemoteExecution.scan_node_id == node_id,
        RemoteExecution.status.in_(["queued", "running"]),
    ))).scalar() or 0)


async def node_running_jobs(db: AsyncSession, node_id: int) -> int:
    return int((await db.execute(select(func.count(RemoteExecution.id)).where(
        RemoteExecution.scan_node_id == node_id,
        RemoteExecution.status == "running",
    ))).scalar() or 0)


def safe_runtime_info(value: dict) -> dict:
    return redact_sensitive(value or {})
