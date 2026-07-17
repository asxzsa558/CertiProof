import asyncio
from types import SimpleNamespace

from app.api import diagnostics
from app.api.diagnostics import _diagnostic_error, _diagnostic_status, _overall_diagnostic_status
from app.models.scan_task import ScanTask, ScanTaskStatus


def test_diagnostic_status_preserves_service_degradation():
    assert _diagnostic_status({"status": "healthy"}) == "healthy"
    assert _diagnostic_status({"status": "ready"}) == "healthy"
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
