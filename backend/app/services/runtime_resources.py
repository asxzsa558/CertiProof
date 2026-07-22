"""Hardware detection, resource profiles, and worker backpressure."""

import os
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.config_service import get_config_service


GB = 1024 ** 3
RESOURCE_PROFILES = {
    "light": {"interactive": 2, "assessment": 2, "document": 1, "verification": 1, "model": 2},
    "standard": {"interactive": 4, "assessment": 4, "document": 2, "verification": 2, "model": 4},
    "gpu": {"interactive": 5, "assessment": 5, "document": 2, "verification": 2, "model": 8},
}


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _memory_bytes() -> tuple[int, int, str]:
    limit_raw = _read_text("/sys/fs/cgroup/memory.max")
    current_raw = _read_text("/sys/fs/cgroup/memory.current")
    if limit_raw and current_raw and limit_raw != "max":
        limit, current = int(limit_raw), int(current_raw)
        if limit < 1 << 60:
            return limit, max(0, limit - current), "cgroup"

    info = {}
    for line in (_read_text("/proc/meminfo") or "").splitlines():
        key, _, value = line.partition(":")
        if value:
            info[key] = int(value.strip().split()[0]) * 1024
    if info.get("MemTotal"):
        return info["MemTotal"], info.get("MemAvailable", info["MemTotal"]), "host"

    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total = page_size * int(os.sysconf("SC_PHYS_PAGES"))
        available = page_size * int(os.sysconf("SC_AVPHYS_PAGES"))
        return total, available, "host"
    except (OSError, ValueError):
        # Some non-Linux hosts do not expose available pages through sysconf.
        return 0, 0, "unknown"


def gpu_available() -> bool:
    configured = settings.LLM_GPU_AVAILABLE.lower()
    if configured != "auto":
        return configured == "true"
    visible = os.getenv("NVIDIA_VISIBLE_DEVICES") or os.getenv("CUDA_VISIBLE_DEVICES")
    if visible and visible.lower() not in {"none", "void", "-1"}:
        return True
    return Path("/dev/nvidiactl").exists()


def hardware_snapshot() -> dict[str, Any]:
    cpu_count = max(1, os.cpu_count() or 1)
    memory_total, memory_available, memory_source = _memory_bytes()
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    memory_percent = round((1 - memory_available / memory_total) * 100, 1) if memory_total else 0.0
    cpu_pressure = round(load / cpu_count * 100, 1)
    return {
        "cpu_count": cpu_count,
        "memory_total_bytes": memory_total,
        "memory_available_bytes": memory_available,
        "memory_percent": max(0.0, min(memory_percent, 100.0)),
        "cpu_pressure_percent": max(0.0, cpu_pressure),
        "gpu_available": gpu_available(),
        "memory_source": memory_source,
    }


def recommended_profile(snapshot: dict[str, Any]) -> tuple[str, str]:
    if snapshot["gpu_available"]:
        return "gpu", "检测到 NVIDIA GPU，推荐 GPU 档位并优先使用 vLLM"
    if snapshot["cpu_count"] <= 4 or snapshot["memory_total_bytes"] <= 16 * GB:
        return "light", "CPU 或内存资源较少，推荐轻量档位"
    return "standard", "CPU 与内存满足常规并发，推荐标准档位"


async def runtime_status(db: AsyncSession) -> dict[str, Any]:
    service = get_config_service(db)
    configured = (await service.get_all()).get("runtime", {})

    def value(key: str, default: Any) -> Any:
        return configured.get(key, default)

    snapshot = hardware_snapshot()
    recommendation, reason = recommended_profile(snapshot)
    mode = value("runtime.resource_mode", "auto")
    configured_profile = value("runtime.resource_profile", "standard")
    profile = recommendation if mode == "auto" else configured_profile
    if profile == "custom":
        limits = {
            "interactive": int(value("runtime.interactive_concurrency", 2)),
            "assessment": int(value("runtime.assessment_concurrency", 2)),
            "document": int(value("runtime.document_concurrency", 1)),
            "verification": int(value("runtime.verification_concurrency", 1)),
            "model": int(value("runtime.model_concurrency", 2)),
        }
    else:
        limits = dict(RESOURCE_PROFILES.get(profile, RESOURCE_PROFILES["standard"]))
    memory_threshold = int(value("runtime.memory_pressure_percent", 90))
    cpu_threshold = int(value("runtime.cpu_pressure_percent", 95))
    pressure_reasons = []
    if snapshot["memory_percent"] >= memory_threshold:
        pressure_reasons.append("内存压力达到阈值")
    if snapshot["cpu_pressure_percent"] >= cpu_threshold:
        pressure_reasons.append("CPU 负载达到阈值")
    return {
        "hardware": snapshot,
        "mode": mode,
        "configured_profile": configured_profile,
        "recommended_profile": recommendation,
        "recommendation_reason": reason,
        "effective_profile": profile,
        "limits": limits,
        "pressure": {
            "paused": bool(pressure_reasons),
            "reasons": pressure_reasons,
            "memory_threshold": memory_threshold,
            "cpu_threshold": cpu_threshold,
        },
        "operational_limits": {
            "task_execution_mode": settings.TASK_EXECUTION_MODE,
            "task_recovery_attempts": settings.TASK_MAX_RECOVERY_ATTEMPTS,
            "document_recovery_attempts": settings.DOCUMENT_MAX_RECOVERY_ATTEMPTS,
            "document_file_retry_attempts": settings.DOCUMENT_FILE_RETRY_ATTEMPTS,
            "document_max_total_pages": settings.DOCUMENT_MAX_TOTAL_PAGES,
            "upload_max_file_mb": settings.UPLOAD_MAX_FILE_MB,
            "upload_max_batch_mb": settings.UPLOAD_MAX_BATCH_MB,
            "active_history_retention_days": settings.ACTIVE_HISTORY_RETENTION_DAYS,
        },
    }


async def concurrency_limit(db: AsyncSession, role: str) -> int:
    """Return the single effective concurrency limit used by every task producer."""
    limits = (await runtime_status(db))["limits"]
    if role not in limits:
        raise ValueError(f"Unsupported runtime role: {role}")
    return max(1, int(limits[role]))
