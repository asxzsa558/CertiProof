"""
Diagnostics API - 诊断和连通性测试
"""

import asyncio
from datetime import datetime, timedelta

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
from app.models.context import ConversationArchive, ConversationSummary
from app.models.model_config import ModelConfig
from app.models.audit import AuditEvent
from app.mcp.gateway_client import MCPGatewayClient
from app.services.knowledge_graph import knowledge_graph
import httpx

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])


def _diagnostic_status(payload: dict) -> str:
    declared = payload.get("status")
    if declared in {"healthy", "ready", "lazy"}:
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
    project_ids = list((await db.execute(
        select(Project.id).where(Project.organization_id == organization_id)
    )).scalars().all())
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
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            local_embedding = (await client.get(f"{settings.EMBEDDING_SERVER_URL}/health")).json()
        local_available = local_embedding.get("status") in {"lazy", "ready"}
    except Exception as exc:
        local_embedding = {"status": "unavailable", "error": str(exc), "model": settings.DOCUMENT_EMBEDDING_MODEL}
        local_available = False
    retrieval_available = bool(embedding_models) or local_available
    return {
        "window_hours": hours,
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
    results = {}
    services = {
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
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        async def check_service(name: str, base_url: str) -> tuple[str, dict]:
            try:
                response = await client.get(f"{base_url}/health")
                if response.status_code == 200:
                    payload = response.json()
                    return name, {"status": _diagnostic_status(payload), "details": payload}
                return name, {"status": "unhealthy", "error": f"HTTP {response.status_code}"}
            except Exception as e:
                return name, {"status": "unhealthy", "error": _diagnostic_error(e)}

        async def check_routes() -> tuple[str, dict]:
            try:
                response = await client.get("http://mcp-gateway:9000/tools")
                if response.status_code == 200:
                    return "gateway_routes", {"status": "healthy", "details": response.json()}
                return "gateway_routes", {"status": "unhealthy", "error": f"HTTP {response.status_code}"}
            except Exception as e:
                return "gateway_routes", {"status": "unhealthy", "error": _diagnostic_error(e)}

        checks = [check_service(name, base_url) for name, base_url in services.items()]
        checks.append(check_routes())
        results.update(dict(await asyncio.gather(*checks)))
    
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
