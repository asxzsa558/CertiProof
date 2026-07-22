import asyncio
import importlib.util
import inspect
from pathlib import Path

from app.services.execution_engine import ExecutionEngine


ROOT = Path(__file__).resolve().parents[1]

LONG_ASYNC_TOOLS = {
    "nmap_scan",
    "masscan_scan",
    "nuclei_scan",
    "hydra_bruteforce",
    "testssl_scan",
    "crypto_transport_scan",
    "nikto_scan",
    "sqlmap_scan",
    "gobuster_scan",
    "ffuf_scan",
    "snmp_walk",
    "snmp_bruteforce",
    "snmp_get",
    "enum4linux_scan",
    "crackmapexec_scan",
    "smb_enum",
    "linux_baseline",
    "password_policy_check",
    "ssh_config_check",
    "audit_config_check",
    "service_port_check",
    "file_permission_check",
    "mac_check",
}

BOUNDED_PROBES = {
    "ping_host",
    "fping_scan",
    "redis_check",
    "oracle_check",
    "mongodb_check",
    "memcached_check",
    "mysql_check",
}


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gateway_routes_every_long_tool_through_async_contract():
    gateway = load_module("certiproof_gateway_async_contract", "mcp-servers/gateway/server.py")
    assert LONG_ASYNC_TOOLS <= set(gateway.ASYNC_TOOLS)
    assert LONG_ASYNC_TOOLS <= set(gateway.TOOL_ROUTES)
    assert BOUNDED_PROBES.isdisjoint(set(gateway.ASYNC_TOOLS))


def test_long_tool_servers_expose_start_progress_result_and_cancel():
    for relative_path in (
        "mcp-servers/security-tools/server.py",
        "mcp-servers/fast-scanner/server.py",
        "mcp-servers/web-tools/server.py",
        "mcp-servers/network-tools/server.py",
        "mcp-servers/windows-tools/server.py",
        "mcp-servers/ssh-checker/server.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert '@app.post("/scan/start")' in source, relative_path
        assert '@app.get("/scan/{task_id}/progress")' in source, relative_path
        assert '@app.get("/scan/{task_id}/result")' in source, relative_path
        assert '@app.post("/scan/{task_id}/cancel")' in source, relative_path
        assert '"heartbeat_at"' in source, relative_path
        assert '"alive"' in source, relative_path


def test_execution_engine_uses_progress_route_for_every_atomic_long_tool():
    method_names = (
        "_scan_ports",
        "_masscan_scan",
        "_nikto_scan",
        "_sqlmap_scan",
        "_gobuster_scan",
        "_ffuf_scan",
        "_snmp_walk",
        "_snmp_bruteforce",
        "_snmp_get",
        "_enum4linux_scan",
        "_crackmapexec_scan",
        "_smb_enum",
        "_scan_ssl",
        "_scan_vulnerabilities",
        "_scan_weak_passwords",
        "_crypto_transport_scan",
        "_call_ssh_checker",
    )
    for method_name in method_names:
        source = inspect.getsource(getattr(ExecutionEngine, method_name))
        assert "call_with_progress" in source, method_name


def test_gateway_rejects_sync_bypass_for_long_tools():
    source = (ROOT / "mcp-servers/gateway/server.py").read_text(encoding="utf-8")
    sync_handler = source.split('@app.post("/call", response_model=ToolCallResponse)', 1)[1].split(
        '@app.post("/call/async")', 1
    )[0]
    assert "if tool_name in ASYNC_TOOLS" in sync_handler
    assert "status_code=409" in sync_handler


def test_gateway_client_transparently_upgrades_sync_long_calls():
    source = (ROOT / "backend/app/mcp/gateway_client.py").read_text(encoding="utf-8")
    call_method = source.split("    async def call(self,", 1)[1].split("    async def call_async", 1)[0]
    assert "e.response.status_code == 409" in call_method
    assert "return await self.call_with_progress(tool_name, params)" in call_method


def test_web_continuous_mode_does_not_apply_default_wall_clock_timeout(monkeypatch):
    module = load_module("certiproof_web_continuous", "mcp-servers/web-tools/server.py")

    class Process:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def create_process(*_args, **_kwargs):
        return Process()

    async def must_not_wait_for(*_args, **_kwargs):
        raise AssertionError("continuous web scans must follow process liveness")

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(module.asyncio, "wait_for", must_not_wait_for)
    result = asyncio.run(module.nikto_scan({"target": "example.test"}, continuous=True))
    assert result["data"]["scan_completed"] is True


def test_masscan_continuous_mode_does_not_apply_default_wall_clock_timeout(monkeypatch):
    module = load_module("certiproof_masscan_continuous", "mcp-servers/fast-scanner/server.py")

    class Process:
        returncode = 0

        async def communicate(self):
            return b"[]", b""

    async def create_process(*_args, **_kwargs):
        return Process()

    async def must_not_wait_for(*_args, **_kwargs):
        raise AssertionError("continuous masscan must follow process liveness")

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(module.asyncio, "wait_for", must_not_wait_for)
    result = asyncio.run(module.masscan_scan({"target": "192.0.2.10"}, continuous=True))
    assert result["data"]["scan_completed"] is True
