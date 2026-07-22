"""
Diagnostics API - 诊断和连通性测试
"""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.config import settings
from app.core.rbac import require_any_org_permission, require_org_permission
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.scan_task import ScanTask, ScanTaskStatus
from app.models.scan_node import RemoteExecution, ScanNode
from app.models.context import ConversationArchive, ConversationSummary
from app.models.model_config import ModelConfig
from app.models.config import SystemConfig
from app.models.audit import AuditEvent
from app.mcp.gateway_client import MCPGatewayClient
from app.services.knowledge_graph import knowledge_graph
from app.services.runtime_resources import runtime_status
import httpx

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])

SERVICE_ENDPOINTS = {
    "mcp_gateway": "http://mcp-gateway:9000",
    "security_tools": "http://security-tools:8010",
    "fast_scanner": "http://fast-scanner:8011",
    "web_tools": "http://web-tools:8012",
    "network_tools": "http://network-tools:8013",
    "windows_tools": "http://windows-tools:8014",
    "db_tools": "http://db-tools:8015",
    "ssh_checker": "http://ssh-checker:8016",
    "ocr_server": "http://ocr-server:8005",
    "embedding_server": settings.EMBEDDING_SERVER_URL,
}
WORKER_ROLES = ("interactive", "document", "assessment", "verification", "maintenance")


def _diagnostic_status(payload: dict) -> str:
    declared = payload.get("status")
    if declared in {"healthy", "ready", "lazy", "running"}:
        return "healthy"
    if declared in {"degraded", "fallback"}:
        return "degraded"
    return "unhealthy"


def _overall_diagnostic_status(results: dict[str, dict]) -> str:
    core_statuses = {
        results.get(name, {}).get("status", "unhealthy")
        for name in ("mcp_gateway", "gateway_routes")
    }
    if "unhealthy" in core_statuses:
        return "unhealthy"
    statuses = {result.get("status") for result in results.values()}
    return "degraded" if statuses & {"degraded", "unhealthy"} else "healthy"


def _diagnostic_error(exc: Exception) -> str:
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail or '请求超时或连接被中断'}"


def _safe_log_text(value: object, limit: int = 800) -> str:
    text_value = value if isinstance(value, str) else json.dumps(value or {}, ensure_ascii=False, default=str)
    text_value = re.sub(
        r"(?i)(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text_value,
    )
    text_value = re.sub(r"(://[^:/\s]+:)[^@/\s]+(@)", r"\1[REDACTED]\2", text_value)
    return text_value[:limit]


def _scan_outcome(scan: ScanTask) -> str:
    status_name = scan.status.value if hasattr(scan.status, "value") else str(scan.status)
    if status_name == "failed":
        return "failed"
    if status_name == "cancelled":
        return "incomplete"
    if status_name in {"pending", "running"}:
        return "running"
    summary = scan.result_summary or {}
    quality = summary.get("quality") if isinstance(summary.get("quality"), dict) else {}
    failed = int(summary.get("failed_count") or quality.get("failed") or 0)
    incomplete = sum(int(summary.get(key) or 0) for key in (
        "warning_count", "skipped_count", "unverified_count", "incomplete_checks_count"
    )) + int(quality.get("warning") or 0) + int(quality.get("skipped") or 0)
    if failed:
        return "failed"
    if incomplete or summary.get("scan_completed") is False or summary.get("outcome") in {"incomplete", "warning", "not_applicable"}:
        return "incomplete"
    if scan.findings_count:
        return "risk"
    return "completed"


async def _health_get(client: httpx.AsyncClient, url: str):
    for attempt in range(2):
        try:
            return await client.get(url)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt:
                raise
            await asyncio.sleep(0.15)


async def _collect_service_health(timeout: float = 5.0) -> dict[str, dict]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        async def check_service(name: str, base_url: str) -> tuple[str, dict]:
            try:
                response = await _health_get(client, base_url if name == "mcp_gateway" else f"{base_url}/health")
                if response.status_code == 200:
                    payload = response.json()
                    return name, {"status": _diagnostic_status(payload), "details": payload}
                return name, {"status": "unhealthy", "error": f"HTTP {response.status_code}"}
            except Exception as exc:
                return name, {"status": "unhealthy", "error": _diagnostic_error(exc)}

        async def check_routes() -> tuple[str, dict]:
            try:
                response = await _health_get(client, "http://mcp-gateway:9000/tools")
                if response.status_code == 200:
                    return "gateway_routes", {"status": "healthy", "details": response.json()}
                return "gateway_routes", {"status": "unhealthy", "error": f"HTTP {response.status_code}"}
            except Exception as exc:
                return "gateway_routes", {"status": "unhealthy", "error": _diagnostic_error(exc)}

        checks = [check_service(name, base_url) for name, base_url in SERVICE_ENDPOINTS.items()]
        checks.append(check_routes())
        return dict(await asyncio.gather(*checks))


@router.get("/operations")
async def get_operations_snapshot(
    organization_id: int | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persisted queue health, failure rate and the latest security audit events."""
    if organization_id is None:
        member = await require_any_org_permission(db, current_user, "tool:diagnose")
        organization_id = member.organization_id
    else:
        await require_org_permission(db, organization_id, current_user, "tool:diagnose")

    since = datetime.utcnow() - timedelta(hours=hours)
    project_rows = list((await db.execute(
        select(Project.id, Project.name).where(Project.organization_id == organization_id)
    )).all())
    project_names = {row.id: row.name for row in project_rows}
    project_ids = list(project_names)
    scans = list((await db.execute(
        select(ScanTask).where(ScanTask.project_id.in_(project_ids), ScanTask.created_at >= since)
    )).scalars().all()) if project_ids else []
    status_counts: dict[str, int] = {}
    control_counts: dict[str, int] = {}
    for scan in scans:
        status_name = scan.status.value if hasattr(scan.status, "value") else str(scan.status)
        status_counts[status_name] = status_counts.get(status_name, 0) + 1
        control = scan.effective_control_state
        control_counts[control] = control_counts.get(control, 0) + 1
    terminal = status_counts.get("completed", 0) + status_counts.get("failed", 0) + status_counts.get("cancelled", 0)
    failures = status_counts.get("failed", 0) + status_counts.get("cancelled", 0)
    stale_before = datetime.utcnow() - timedelta(minutes=5)
    stale_leases = sum(
        1 for scan in scans
        if scan.status in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING)
        and scan.control_state != "paused"
        and scan.lease_expires_at is not None
        and scan.lease_expires_at < stale_before
    )

    archive_queue = 0
    summary_queue = 0
    if project_ids:
        archive_queue = (await db.execute(
            select(ConversationArchive).where(
                ConversationArchive.project_id.in_(project_ids),
                ConversationArchive.status.in_(["queued", "processing"]),
            )
        )).scalars().all()
        archive_queue = len(archive_queue)
        summary_queue = len((await db.execute(
            select(ConversationSummary).where(
                ConversationSummary.project_id.in_(project_ids),
                ConversationSummary.status.in_(["queued", "processing"]),
            )
        )).scalars().all())

    events = (await db.execute(
        select(AuditEvent)
        .where(or_(
            AuditEvent.organization_id == organization_id,
            AuditEvent.project_id.in_(project_ids),
        ))
        .order_by(AuditEvent.created_at.desc())
        .limit(40)
    )).scalars().all()
    embedding_models = (await db.execute(
        select(ModelConfig).where(ModelConfig.is_active.is_(True))
    )).scalars().all()
    embedding_models = [model for model in embedding_models if "embedding" in (model.capabilities or [])]
    service_results = await _collect_service_health()
    embedding_health = service_results.get("embedding_server", {})
    local_embedding = embedding_health.get("details") or {
        "status": "unavailable",
        "error": embedding_health.get("error"),
        "model": settings.DOCUMENT_EMBEDDING_MODEL,
    }
    local_available = embedding_health.get("status") in {"healthy", "degraded"} and local_embedding.get("status") != "failed"
    retrieval_available = bool(embedding_models) or local_available

    heartbeat_rows = list((await db.execute(select(SystemConfig).where(
        SystemConfig.key.in_([f"worker.heartbeat.{role}" for role in WORKER_ROLES])
    ))).scalars().all())
    heartbeat_values = {row.key.rsplit(".", 1)[-1]: row.value for row in heartbeat_rows}
    now = datetime.now(timezone.utc)
    workers = {}
    max_heartbeat_age = max(30, settings.TASK_WORKER_POLL_SECONDS * 5)
    for role in WORKER_ROLES:
        value = heartbeat_values.get(role) if isinstance(heartbeat_values.get(role), dict) else {}
        recorded = None
        try:
            recorded = datetime.fromisoformat(str(value.get("at", "")).replace("Z", "+00:00"))
            if recorded.tzinfo is None:
                recorded = recorded.replace(tzinfo=timezone.utc)
        except ValueError:
            recorded = None
        age = (now - recorded).total_seconds() if recorded else None
        if age is None or age > max_heartbeat_age:
            worker_status = "unhealthy"
        elif value.get("state") == "error":
            worker_status = "degraded"
        else:
            worker_status = "healthy"
        workers[role] = {
            "status": worker_status,
            "last_seen": value.get("at"),
            "age_seconds": round(age) if age is not None else None,
            "processed": value.get("processed", 0),
            "error": _safe_log_text(value.get("error")) if value.get("error") else None,
        }

    recent_scans = sorted(scans, key=lambda item: item.created_at.timestamp() if item.created_at else 0, reverse=True)[:40]
    recent_tasks = [
        {
            "id": scan.id,
            "project_id": scan.project_id,
            "project_name": project_names.get(scan.project_id, f"项目 #{scan.project_id}"),
            "capability": (scan.parameters or {}).get("capability") or (scan.parameters or {}).get("tool") or scan.task_type.value,
            "status": scan.status.value if hasattr(scan.status, "value") else str(scan.status),
            "outcome": _scan_outcome(scan),
            "findings_count": scan.findings_count or 0,
            "error": _safe_log_text(scan.error_message) if scan.error_message else None,
            "created_at": scan.created_at.isoformat() if scan.created_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        }
        for scan in recent_scans
    ]

    scan_node_rows = list((await db.execute(select(ScanNode).where(
        ScanNode.organization_id == organization_id,
        ScanNode.enabled.is_(True),
    ).order_by(ScanNode.priority.asc(), ScanNode.id.asc()))).scalars().all())
    scan_nodes = []
    for node in scan_node_rows:
        last_seen = node.last_seen_at
        if last_seen and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        online = bool(last_seen and node.node_token_hash and (now - last_seen).total_seconds() <= settings.REMOTE_NODE_OFFLINE_SECONDS)
        scan_nodes.append({
            "id": node.id,
            "name": node.name,
            "location": node.location,
            "status": "online" if online else "offline" if node.enrolled_at else "unenrolled",
            "last_seen": node.last_seen_at.isoformat() if node.last_seen_at else None,
            "max_concurrency": node.max_concurrency,
        })
    remote_jobs = list((await db.execute(select(RemoteExecution).where(
        RemoteExecution.organization_id == organization_id,
        RemoteExecution.created_at >= since,
    ).order_by(RemoteExecution.created_at.desc()).limit(40))).scalars().all())

    alerts = []
    for name, result in {**service_results, **{f"worker_{key}": value for key, value in workers.items()}}.items():
        if result.get("status") in {"degraded", "unhealthy"}:
            alerts.append({
                "id": f"service:{name}",
                "severity": "high" if result.get("status") == "unhealthy" else "medium",
                "source": "service",
                "title": f"{name.replace('_', ' ')} {result.get('status')}",
                "detail": _safe_log_text(result.get("error") or result.get("details") or "服务处于降级状态"),
                "created_at": now.isoformat(),
            })
    if stale_leases:
        alerts.append({
            "id": "queue:stale-leases",
            "severity": "high",
            "source": "queue",
            "title": f"{stale_leases} 个任务租约已过期",
            "detail": "运行中的任务长时间未刷新租约，可能需要自动恢复或人工终止。",
            "created_at": now.isoformat(),
        })
    offline_nodes = [node for node in scan_nodes if node["status"] == "offline"]
    if offline_nodes:
        alerts.append({
            "id": "scan-node:offline",
            "severity": "high",
            "source": "scan_node",
            "title": f"{len(offline_nodes)} 个远端扫描节点离线",
            "detail": "、".join(node["name"] for node in offline_nodes[:5]),
            "created_at": now.isoformat(),
        })
    failed_remote_jobs = [job for job in remote_jobs if job.status == "failed"]
    if failed_remote_jobs:
        alerts.append({
            "id": "scan-node:failed-jobs",
            "severity": "medium",
            "source": "scan_node",
            "title": f"最近 {hours} 小时有 {len(failed_remote_jobs)} 个远端任务失败",
            "detail": _safe_log_text(failed_remote_jobs[0].error or "请检查节点连通性和目标路由"),
            "created_at": failed_remote_jobs[0].created_at.isoformat(),
        })
    failed_tasks = [task for task in recent_tasks if task["outcome"] == "failed"]
    if failed_tasks:
        alerts.append({
            "id": "task:recent-failures",
            "severity": "medium",
            "source": "task",
            "title": f"最近 {hours} 小时有 {len(failed_tasks)} 个检测执行失败",
            "detail": "失败与检测不完整分开统计，可在运行日志中查看项目、能力和错误原因。",
            "created_at": failed_tasks[0]["created_at"],
        })

    resources = await runtime_status(db)
    if resources["pressure"]["paused"]:
        alerts.append({
            "id": "resource:pressure",
            "severity": "high",
            "source": "resource",
            "title": "资源压力已触发任务背压",
            "detail": "、".join(resources["pressure"]["reasons"]),
            "created_at": now.isoformat(),
        })

    event_log = [
        {
            "id": f"scan:{task['id']}",
            "type": "scan",
            "level": "error" if task["outcome"] == "failed" else "warning" if task["outcome"] == "incomplete" else "info",
            "source": task["capability"],
            "title": f"{task['project_name']} · {task['capability']}",
            "detail": task["error"] or f"状态 {task['outcome']}，发现 {task['findings_count']} 项",
            "project_id": task["project_id"],
            "created_at": task["completed_at"] or task["created_at"],
        }
        for task in recent_tasks
    ]
    event_log.extend({
        "id": f"audit:{event.id}",
        "type": "audit",
        "level": "error" if event.outcome == "failed" else "warning" if event.outcome == "partial" else "info",
        "source": event.event_type,
        "title": f"{event.resource_type} · {event.event_type}",
        "detail": _safe_log_text(event.details),
        "project_id": event.project_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    } for event in events)
    event_log.extend({
        "id": f"remote:{job.id}",
        "type": "scan_node",
        "level": "error" if job.status == "failed" else "warning" if job.status == "cancelled" else "info",
        "source": job.capability,
        "title": f"远端节点 #{job.scan_node_id} · {job.capability}",
        "detail": _safe_log_text(job.error or f"目标 {job.target}，状态 {job.status}"),
        "project_id": job.project_id,
        "created_at": (job.completed_at or job.created_at).isoformat(),
    } for job in remote_jobs)
    event_log.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "release": {"version": settings.CERTIPROOF_VERSION, "generated_at": now.isoformat()},
        "window_hours": hours,
        "overall_status": _overall_diagnostic_status(service_results),
        "services": service_results,
        "workers": workers,
        "scan_nodes": scan_nodes,
        "alerts": alerts,
        "event_log": event_log[:80],
        "runtime_resources": resources,
        "knowledge_graph": await knowledge_graph.status(db),
        "document_retrieval": {
            "embedding_configured": retrieval_available,
            "embedding_dimension": settings.DOCUMENT_EMBEDDING_DIMENSION,
            "models": [
                *[model.display_name for model in embedding_models],
                *([local_embedding.get("model")] if local_available else []),
            ],
            "local_service": local_embedding,
            "status": "configured" if retrieval_available else "unavailable",
            "message": (
                "本地向量模型将在首次文档分析时下载并加载。"
                if local_embedding.get("status") == "lazy" and not embedding_models
                else (None if retrieval_available else "文本向量服务不可用；无精确证据的检查项将标记为无法判断。")
            ),
        },
        "scan_tasks": {
            "total": len(scans),
            "by_status": status_counts,
            "by_control_state": control_counts,
            "failure_rate": round(failures / terminal, 4) if terminal else 0,
            "stale_leases": stale_leases,
            "recent": recent_tasks,
        },
        "queues": {"archives": archive_queue, "conversation_summaries": summary_queue},
        "recent_audit_events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "outcome": event.outcome,
                "project_id": event.project_id,
                "actor_user_id": event.actor_user_id,
                "details": event.details or {},
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }


@router.get("/mcp/health")
async def test_mcp_health(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """测试 MCP Gateway 健康状态"""
    await require_any_org_permission(db, current_user, "tool:diagnose")
    results = await _collect_service_health(timeout=15.0)
    
    return {
        "status": _overall_diagnostic_status(results),
        "services": results,
    }


@router.post("/mcp/test-tool")
async def test_mcp_tool(
    tool_name: str = "ping_host",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """测试具体工具是否可用"""
    await require_any_org_permission(db, current_user, "tool:diagnose")
    client = MCPGatewayClient()
    
    # 根据工具类型使用不同的测试参数
    test_params = {
        "ping_host": {"target": "127.0.0.1", "count": 1},
        "ping_asset": {"target": "127.0.0.1", "count": 1},
        "nmap_scan": {"target": "127.0.0.1", "port_range": "high-risk"},
        "scan_ports": {"target": "127.0.0.1", "port_range": "high-risk"},
        "masscan_scan": {"target": "127.0.0.1", "port_range": "1-100", "rate": 100},
        "fping_scan": {"targets": ["127.0.0.1"]},
        "testssl_scan": {"target": "127.0.0.1", "port": 443},
        "scan_ssl": {"target": "127.0.0.1", "port": 443},
        "nuclei_scan": {"target": "http://127.0.0.1", "severity": "low,medium,high,critical"},
        "scan_vulnerabilities": {"target": "http://127.0.0.1"},
        "hydra_bruteforce": {"target": "127.0.0.1", "service": "ssh", "port": 22},
        "scan_weak_passwords": {"target": "127.0.0.1", "service": "ssh", "port": 22},
        "nikto_scan": {"target": "127.0.0.1"},
        "sqlmap_scan": {"url": "http://127.0.0.1/?id=1"},
        "gobuster_scan": {"url": "http://127.0.0.1"},
        "ffuf_scan": {"url": "http://127.0.0.1/FUZZ"},
        "redis_check": {"target": "127.0.0.1"},
        "mysql_check": {"target": "127.0.0.1"},
        "mongodb_check": {"target": "127.0.0.1"},
        "memcached_check": {"target": "127.0.0.1"},
        "oracle_check": {"target": "127.0.0.1"},
        "snmp_walk": {"target": "127.0.0.1"},
        "snmp_bruteforce": {"target": "127.0.0.1"},
        "snmp_get": {"target": "127.0.0.1", "oid": "1.3.6.1.2.1.1.1.0"},
        "enum4linux_scan": {"target": "127.0.0.1"},
        "crackmapexec_scan": {"target": "127.0.0.1"},
        "smb_enum": {"target": "127.0.0.1"},
    }
    
    params = test_params.get(tool_name, {"target": "localhost"})
    
    try:
        result = await client.call(tool_name, params)
        return {
            "tool": tool_name,
            "status": "available",
            "result": result,
        }
    except Exception as e:
        return {
            "tool": tool_name,
            "status": "unavailable",
            "error": str(e),
        }
