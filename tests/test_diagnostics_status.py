import asyncio
from types import SimpleNamespace

from app.api import diagnostics
from app.api.diagnostics import (
    _diagnostic_error,
    _diagnostic_status,
    _health_get,
    _overall_diagnostic_status,
    _safe_log_text,
    _scan_outcome,
)
from app.models.scan_task import ScanTask, ScanTaskStatus


def test_diagnostic_status_preserves_service_degradation():
    assert _diagnostic_status({"status": "healthy"}) == "healthy"
    assert _diagnostic_status({"status": "ready"}) == "healthy"
    assert _diagnostic_status({"status": "running"}) == "healthy"
    assert _diagnostic_status({"status": "degraded"}) == "degraded"
    assert _diagnostic_status({"status": "failed"}) == "unhealthy"


def test_overall_diagnostic_status_only_fails_for_core_routing():
    results = {
        "mcp_gateway": {"status": "degraded"},
        "gateway_routes": {"status": "healthy"},
        "windows_tools": {"status": "unhealthy"},
    }
    assert _overall_diagnostic_status(results) == "degraded"
    results["gateway_routes"] = {"status": "unhealthy"}
    assert _overall_diagnostic_status(results) == "unhealthy"


def test_empty_timeout_error_remains_actionable():
    assert _diagnostic_error(TimeoutError()) == "TimeoutError: 请求超时或连接被中断"


def test_terminal_scan_status_overrides_stale_control_state():
    scan = ScanTask(status=ScanTaskStatus.COMPLETED, control_state="running")
    assert scan.effective_control_state == "completed"


def test_operational_logs_redact_credentials():
    text = _safe_log_text("password=hunter2 api_key:abc https://user:secret@example.com")
    assert "hunter2" not in text
    assert "api_key=[REDACTED]" in text
    assert "secret@example" not in text


def test_scan_outcome_keeps_incomplete_separate_from_success():
    complete = ScanTask(status=ScanTaskStatus.COMPLETED, findings_count=0, result_summary={})
    incomplete = ScanTask(
        status=ScanTaskStatus.COMPLETED,
        findings_count=0,
        result_summary={"scan_completed": False, "incomplete_checks_count": 2},
    )
    risky = ScanTask(status=ScanTaskStatus.COMPLETED, findings_count=3, result_summary={})
    assert _scan_outcome(complete) == "completed"
    assert _scan_outcome(incomplete) == "incomplete"
    assert _scan_outcome(risky) == "risk"


def test_health_probe_retries_one_transient_timeout():
    class Client:
        calls = 0

        async def get(self, _url):
            self.calls += 1
            if self.calls == 1:
                raise diagnostics.httpx.ReadTimeout("temporary")
            return "healthy"

    client = Client()
    assert asyncio.run(_health_get(client, "http://service/health")) == "healthy"
    assert client.calls == 2


def test_mcp_health_checks_services_concurrently(monkeypatch):
    active = 0
    max_active = 0

    class Response:
        status_code = 200

        def __init__(self, url):
            self.url = url

        def json(self):
            return {"status": "healthy", "url": self.url}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0)
            active -= 1
            return Response(url)

    async def allow(*args, **kwargs):
        return None

    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", Client)
    monkeypatch.setattr(diagnostics, "require_any_org_permission", allow)
    result = asyncio.run(diagnostics.test_mcp_health(
        current_user=SimpleNamespace(id=1),
        db=object(),
    ))
    assert result["status"] == "healthy"
    assert len(result["services"]) == 11
    assert max_active == 11
