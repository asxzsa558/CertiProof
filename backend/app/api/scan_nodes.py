"""Organization management and outbound runtime protocol for scan nodes."""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rbac import require_any_org_permission, require_org_permission
from app.core.secret_box import decrypt_json
from app.core.security import get_current_user
from app.models.project import Project
from app.models.scan_node import RemoteExecution, ScanNode
from app.models.user import User
from app.schemas.scan_node import (
    EnrollmentResponse,
    NodeEnrollRequest,
    NodeHeartbeat,
    NodeJobFailure,
    NodeJobResult,
    NodeJobUpdate,
    RouteTestRequest,
    ScanNodeCreate,
    ScanNodeCreated,
    ScanNodeResponse,
    ScanNodeUpdate,
)
from app.services.audit import record_audit_event
from app.services.execution_policy import NETWORK_CAPABILITIES
from app.services.scan_node_service import (
    TERMINAL_JOB_STATUSES,
    new_token,
    node_active_jobs,
    node_online,
    node_running_jobs,
    public_node_config,
    safe_runtime_info,
    select_scan_node,
    token_hash,
    utcnow,
    validate_node_routes,
)


router = APIRouter(prefix="/scan-nodes", tags=["Remote Scan Nodes"])


async def _validate_projects(db: AsyncSession, organization_id: int, project_ids: list[int]) -> None:
    if not project_ids:
        return
    count = int((await db.execute(select(func.count(Project.id)).where(
        Project.organization_id == organization_id,
        Project.id.in_(project_ids),
    ))).scalar() or 0)
    if count != len(set(project_ids)):
        raise HTTPException(status_code=400, detail="项目绑定中包含不属于当前组织的项目")


async def _node_response(db: AsyncSession, node: ScanNode) -> ScanNodeResponse:
    return ScanNodeResponse(
        id=node.id,
        organization_id=node.organization_id,
        name=node.name,
        location=node.location,
        description=node.description,
        enabled=node.enabled,
        allowed_cidrs=node.allowed_cidrs or [],
        project_ids=node.project_ids or [],
        capabilities=node.capabilities or [],
        max_concurrency=node.max_concurrency,
        priority=node.priority,
        config_version=node.config_version,
        status="disabled" if not node.enabled else "online" if node_online(node) else "offline" if node.enrolled_at else "unenrolled",
        enrolled_at=node.enrolled_at,
        last_seen_at=node.last_seen_at,
        runtime_info=node.runtime_info,
        active_jobs=await node_active_jobs(db, node.id),
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


async def _managed_node(db: AsyncSession, org_id: int, node_id: int) -> ScanNode:
    node = (await db.execute(select(ScanNode).where(
        ScanNode.id == node_id,
        ScanNode.organization_id == org_id,
    ))).scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="扫描节点不存在")
    return node


async def _runtime_node(
    db: AsyncSession,
    node_id: int | None,
    authorization: str | None,
) -> ScanNode:
    if not node_id or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少节点认证信息")
    node = await db.get(ScanNode, node_id)
    supplied = token_hash(authorization[7:].strip())
    if not node or not node.enabled or not node.node_token_hash or not secrets.compare_digest(node.node_token_hash, supplied):
        raise HTTPException(status_code=401, detail="节点凭证无效或节点已停用")
    return node


async def _owned_job(db: AsyncSession, node: ScanNode, job_id: str) -> RemoteExecution:
    job = (await db.execute(select(RemoteExecution).where(
        RemoteExecution.id == job_id,
        RemoteExecution.scan_node_id == node.id,
    ))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="远端任务不存在")
    return job


@router.post("/runtime/enroll", response_model=EnrollmentResponse)
async def enroll_node(payload: NodeEnrollRequest, db: AsyncSession = Depends(get_db)):
    now = utcnow()
    node = (await db.execute(select(ScanNode).where(
        ScanNode.enrollment_token_hash == token_hash(payload.enrollment_token),
        ScanNode.enrollment_expires_at > now,
        ScanNode.enabled.is_(True),
    ))).scalar_one_or_none()
    if not node or not secrets.compare_digest(node.enrollment_token_hash or "", token_hash(payload.enrollment_token)):
        raise HTTPException(status_code=401, detail="注册令牌无效、已使用或已过期")
    node_token = new_token()
    node.node_token_hash = token_hash(node_token)
    node.enrollment_token_hash = None
    node.enrollment_expires_at = None
    node.enrolled_at = now
    node.last_seen_at = now
    node.runtime_info = safe_runtime_info(payload.runtime_info)
    await db.commit()
    return EnrollmentResponse(node_id=node.id, node_token=node_token, config=public_node_config(node))


@router.post("/runtime/heartbeat")
async def heartbeat_node(
    payload: NodeHeartbeat,
    x_node_id: int | None = Header(None, alias="X-Node-ID"),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    node = await _runtime_node(db, x_node_id, authorization)
    node.last_seen_at = utcnow()
    node.runtime_info = safe_runtime_info(payload.runtime_info)
    await db.commit()
    return {"status": "ok", "config": public_node_config(node), "config_changed": payload.config_version != node.config_version}


@router.post("/runtime/jobs/claim")
async def claim_job(
    x_node_id: int | None = Header(None, alias="X-Node-ID"),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    node = await _runtime_node(db, x_node_id, authorization)
    now = utcnow()
    node.last_seen_at = now
    await db.execute(update(RemoteExecution).where(
        RemoteExecution.scan_node_id == node.id,
        RemoteExecution.status == "running",
        RemoteExecution.lease_expires_at < now,
        RemoteExecution.control_state == "active",
    ).values(status="queued", lease_expires_at=None, progress={"stage": "节点租约过期，等待重新领取", "percent": 0}))
    running = await node_running_jobs(db, node.id)
    if running >= node.max_concurrency:
        await db.commit()
        return {"job": None, "config": public_node_config(node)}
    job = (await db.execute(
        select(RemoteExecution).where(
            RemoteExecution.scan_node_id == node.id,
            RemoteExecution.status == "queued",
            RemoteExecution.control_state == "active",
        ).order_by(RemoteExecution.created_at.asc()).with_for_update(skip_locked=True).limit(1)
    )).scalar_one_or_none()
    if not job:
        await db.commit()
        return {"job": None, "config": public_node_config(node)}
    job.status = "running"
    job.claimed_at = job.claimed_at or now
    job.lease_expires_at = now + timedelta(seconds=settings.REMOTE_JOB_LEASE_SECONDS)
    job.progress = {"stage": "远端节点已领取", "percent": 1}
    payload = decrypt_json(job.payload_envelope)
    await db.commit()
    return {
        "job": {
            "id": job.id,
            "capability": job.capability,
            "parameters": payload.get("parameters") or {},
            "user_id": payload.get("user_id") or 0,
            "project_id": job.project_id,
            "target": job.target,
        },
        "config": public_node_config(node),
    }


@router.post("/runtime/jobs/{job_id}/heartbeat")
async def heartbeat_job(
    job_id: str,
    payload: NodeJobUpdate,
    x_node_id: int | None = Header(None, alias="X-Node-ID"),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    node = await _runtime_node(db, x_node_id, authorization)
    job = await _owned_job(db, node, job_id)
    if job.status not in TERMINAL_JOB_STATUSES:
        job.progress = safe_runtime_info(payload.progress)
        job.lease_expires_at = utcnow() + timedelta(seconds=settings.REMOTE_JOB_LEASE_SECONDS)
    node.last_seen_at = utcnow()
    await db.commit()
    return {"status": job.status, "control_state": job.control_state, "config": public_node_config(node)}


@router.post("/runtime/jobs/{job_id}/complete")
async def complete_job(
    job_id: str,
    payload: NodeJobResult,
    x_node_id: int | None = Header(None, alias="X-Node-ID"),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    node = await _runtime_node(db, x_node_id, authorization)
    job = await _owned_job(db, node, job_id)
    if job.status not in TERMINAL_JOB_STATUSES:
        job.status = "cancelled" if job.control_state == "cancel_requested" else "completed"
        job.result = safe_runtime_info(payload.result)
        job.progress = {"stage": "执行完成", "percent": 100}
        job.completed_at = utcnow()
        job.lease_expires_at = None
    await db.commit()
    return {"status": job.status}


@router.post("/runtime/jobs/{job_id}/fail")
async def fail_job(
    job_id: str,
    payload: NodeJobFailure,
    x_node_id: int | None = Header(None, alias="X-Node-ID"),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    node = await _runtime_node(db, x_node_id, authorization)
    job = await _owned_job(db, node, job_id)
    if job.status not in TERMINAL_JOB_STATUSES:
        job.status = "cancelled" if job.control_state == "cancel_requested" else "failed"
        job.error = payload.error
        job.completed_at = utcnow()
        job.lease_expires_at = None
    await db.commit()
    return {"status": job.status}


@router.get("/capabilities")
async def list_node_capabilities(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_any_org_permission(db, current_user, "node:read")
    return {"capabilities": sorted(NETWORK_CAPABILITIES)}


@router.get("/{org_id}", response_model=list[ScanNodeResponse])
async def list_nodes(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "node:read")
    nodes = list((await db.execute(select(ScanNode).where(
        ScanNode.organization_id == org_id,
    ).order_by(ScanNode.priority.asc(), ScanNode.id.asc()))).scalars().all())
    return [await _node_response(db, node) for node in nodes]


@router.post("/{org_id}", response_model=ScanNodeCreated, status_code=status.HTTP_201_CREATED)
async def create_node(
    org_id: int,
    payload: ScanNodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "node:manage")
    capabilities = payload.capabilities or sorted(NETWORK_CAPABILITIES)
    try:
        validate_node_routes(payload.allowed_cidrs, capabilities)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _validate_projects(db, org_id, payload.project_ids)
    enrollment_token = new_token()
    expires_at = utcnow() + timedelta(minutes=30)
    node = ScanNode(
        organization_id=org_id,
        created_by=current_user.id,
        enrollment_token_hash=token_hash(enrollment_token),
        enrollment_expires_at=expires_at,
        capabilities=capabilities,
        **payload.model_dump(exclude={"capabilities"}),
    )
    db.add(node)
    await db.flush()
    await record_audit_event(
        db,
        event_type="scan_node.create",
        resource_type="scan_node",
        resource_id=node.id,
        actor_user_id=current_user.id,
        organization_id=org_id,
        details={"name": node.name, "allowed_cidrs": node.allowed_cidrs, "project_ids": node.project_ids},
    )
    await db.commit()
    await db.refresh(node)
    return ScanNodeCreated(node=await _node_response(db, node), enrollment_token=enrollment_token, enrollment_expires_at=expires_at)


@router.put("/{org_id}/{node_id}", response_model=ScanNodeResponse)
async def update_node(
    org_id: int,
    node_id: int,
    payload: ScanNodeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "node:manage")
    node = await _managed_node(db, org_id, node_id)
    values = payload.model_dump(exclude_unset=True)
    if "capabilities" in values and not values["capabilities"]:
        values["capabilities"] = sorted(NETWORK_CAPABILITIES)
    cidrs = values.get("allowed_cidrs", node.allowed_cidrs or [])
    capabilities = values.get("capabilities", node.capabilities or [])
    try:
        validate_node_routes(cidrs, capabilities)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _validate_projects(db, org_id, values.get("project_ids", node.project_ids or []))
    for key, value in values.items():
        setattr(node, key, value)
    node.config_version += 1
    await record_audit_event(
        db,
        event_type="scan_node.update",
        resource_type="scan_node",
        resource_id=node.id,
        actor_user_id=current_user.id,
        organization_id=org_id,
        details={"fields": sorted(values)},
    )
    await db.commit()
    await db.refresh(node)
    return await _node_response(db, node)


@router.post("/{org_id}/{node_id}/rotate-enrollment")
async def rotate_enrollment(
    org_id: int,
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "node:manage")
    node = await _managed_node(db, org_id, node_id)
    if await node_active_jobs(db, node.id):
        raise HTTPException(status_code=409, detail="节点仍有执行中的任务，不能轮换凭证")
    enrollment_token = new_token()
    expires_at = utcnow() + timedelta(minutes=30)
    node.enrollment_token_hash = token_hash(enrollment_token)
    node.enrollment_expires_at = expires_at
    node.node_token_hash = None
    node.last_seen_at = None
    node.config_version += 1
    await db.commit()
    return {"node_id": node.id, "enrollment_token": enrollment_token, "enrollment_expires_at": expires_at}


@router.post("/{org_id}/route-test")
async def test_route(
    org_id: int,
    payload: RouteTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "node:read")
    try:
        node, route = await select_scan_node(
            db,
            organization_id=org_id,
            project_id=payload.project_id,
            capability=payload.capability,
            targets=[payload.target],
        )
    except ValueError as exc:
        return {"route": "remote_offline", "message": str(exc), "node": None}
    if not node:
        return {"route": "local", "message": "未命中远端节点规则，将由中心工具执行", "node": None}
    return {"route": route, "message": f"将由远端节点 {node.name} 执行", "node": {"id": node.id, "name": node.name, "location": node.location}}


@router.get("/{org_id}/{node_id}/jobs")
async def list_node_jobs(
    org_id: int,
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "node:read")
    node = await _managed_node(db, org_id, node_id)
    jobs = list((await db.execute(select(RemoteExecution).where(
        RemoteExecution.scan_node_id == node.id,
    ).order_by(RemoteExecution.created_at.desc()).limit(50))).scalars().all())
    return [{
        "id": job.id,
        "capability": job.capability,
        "target": job.target,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "project_id": job.project_id,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    } for job in jobs]


@router.post("/{org_id}/{node_id}/jobs/{job_id}/cancel")
async def cancel_node_job(
    org_id: int,
    node_id: int,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "node:manage")
    node = await _managed_node(db, org_id, node_id)
    job = await _owned_job(db, node, job_id)
    if job.status not in TERMINAL_JOB_STATUSES:
        job.control_state = "cancel_requested"
        if job.status == "queued":
            job.status = "cancelled"
            job.completed_at = utcnow()
    await db.commit()
    return {"status": job.status, "control_state": job.control_state}


@router.delete("/{org_id}/{node_id}", status_code=204)
async def delete_node(
    org_id: int,
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_org_permission(db, org_id, current_user, "node:manage")
    node = await _managed_node(db, org_id, node_id)
    if await node_active_jobs(db, node.id):
        raise HTTPException(status_code=409, detail="节点仍有等待或执行中的任务")
    await record_audit_event(
        db,
        event_type="scan_node.delete",
        resource_type="scan_node",
        resource_id=node.id,
        actor_user_id=current_user.id,
        organization_id=org_id,
        details={"name": node.name},
    )
    await db.delete(node)
    await db.commit()
