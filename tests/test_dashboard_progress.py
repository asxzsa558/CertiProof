from types import SimpleNamespace
from datetime import datetime, timedelta

from app.api.dashboard import _matrix_progress, _tool_health


def test_matrix_progress_matches_authoritative_phase_progress():
    assessment = SimpleNamespace(progress=70)
    phases = [
        SimpleNamespace(status="completed", total_tasks=27, completed_tasks=18, progress=67),
        SimpleNamespace(status="active", total_tasks=10, completed_tasks=4, progress=40),
    ]

    assert _matrix_progress(assessment, phases, 55) == 70


def test_matrix_progress_does_not_mix_in_task_completion_rate():
    assessment = SimpleNamespace(progress=88)
    phases = [SimpleNamespace(status="active", total_tasks=25, completed_tasks=22, progress=88)]

    assert _matrix_progress(assessment, phases, 88) == 88


def test_tool_health_uses_real_scan_status_and_duration():
    completed_at = datetime.utcnow()
    scans = [
        SimpleNamespace(
            parameters={"capability": "scan_ports"},
            status="completed",
            created_at=completed_at,
            started_at=completed_at - timedelta(seconds=12),
            completed_at=completed_at,
        ),
        SimpleNamespace(
            parameters={"capability": "nikto_scan"},
            status="failed",
            created_at=completed_at,
            started_at=completed_at - timedelta(seconds=5),
            completed_at=completed_at,
        ),
    ]

    telemetry = {item["name"]: item for item in _tool_health(scans)}

    assert telemetry["端口扫描"]["status"] == "healthy"
    assert telemetry["端口扫描"]["latency"] == "12s"
    assert telemetry["Web 检测"]["status"] == "warning"
    assert telemetry["Web 检测"]["failure_count"] == 1
