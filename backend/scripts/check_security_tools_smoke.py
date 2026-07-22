"""Regression smoke test for the security-tool execution layer.

Runs only against Docker-internal services. It verifies that a real open port
is detected, async progress completes, and unreachable/non-matching services
are reported as incomplete instead of a clean no-findings result.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib import error, request

# Support `python scripts/...` from Docker Compose as well as module execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.execution_engine import ExecutionEngine


GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway:9000").rstrip("/")
CURRENT_STEP = "startup"
_ASYNC_TOOLS: set[str] | None = None


def _request(method: str, path: str, body: dict | None = None, timeout: int = 180) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = request.Request(f"{GATEWAY_URL}{path}", data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


def _call(tool: str, params: dict, timeout: int = 180) -> dict:
    global CURRENT_STEP, _ASYNC_TOOLS
    CURRENT_STEP = f"gateway:{tool}"
    if _ASYNC_TOOLS is None:
        registry = _request("GET", "/tools")
        _ASYNC_TOOLS = {
            item["name"] for item in registry.get("tools", []) if item.get("supports_async")
        }

    if tool in _ASYNC_TOOLS:
        started = _request("POST", "/call/async", {"tool": tool, "params": params}, 30)
        task_id = started.get("task_id")
        assert task_id, started
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            progress = _request("GET", f"/progress/{tool}/{task_id}", timeout=15)
            assert "heartbeat_at" in progress and "alive" in progress, progress
            if progress.get("status") == "completed":
                result = _request("GET", f"/result/{tool}/{task_id}", timeout=30)
                break
            assert progress.get("status") == "running", progress
            time.sleep(1)
        else:
            _request("POST", f"/cancel/{tool}/{task_id}", {}, 15)
            raise AssertionError(f"async tool did not finish within smoke-test deadline: {tool}")
    else:
        result = _request("POST", "/call", {"tool": tool, "params": params}, timeout)
    assert result.get("tool"), result
    assert result.get("status") in {"success", "failed"}, result
    assert isinstance(result.get("data"), dict), result
    assert isinstance(result.get("metadata"), dict), result
    return result


def _completed(result: dict) -> None:
    data = result["data"]
    assert data.get("scan_completed") is not False, result
    assert not data.get("tool_error"), result


def _incomplete(result: dict) -> None:
    data = result["data"]
    assert data.get("scan_completed") is False or data.get("reachable") is False or result.get("status") == "failed", result
    assert data.get("tool_error") or result.get("error") or result.get("metadata", {}).get("error"), result


def _async_port_scan() -> None:
    global CURRENT_STEP
    CURRENT_STEP = "gateway:async_scan_ports"
    started = _request("POST", "/call/async", {
        "tool": "scan_ports",
        "params": {"target": "redis", "port_range": "6379", "host_timeout": 30},
    })
    task_id = started.get("task_id")
    assert task_id and started.get("status") == "running", started

    observed_progress = []
    deadline = time.time() + 60
    while time.time() < deadline:
        progress = _request("GET", f"/progress/scan_ports/{task_id}")
        observed_progress.append(progress.get("progress"))
        if progress.get("status") == "completed":
            result = _request("GET", f"/result/scan_ports/{task_id}")
            data = result.get("data") or {}
            ports = {item.get("port") for item in data.get("open_ports", [])}
            assert 6379 in ports, result
            assert any(value is not None for value in observed_progress), observed_progress
            return
        assert progress.get("status") == "running", progress
        time.sleep(1)
    raise AssertionError(f"async nmap scan did not complete: {task_id}")


async def _engine_combo_checks() -> None:
    global CURRENT_STEP
    engine = ExecutionEngine()
    CURRENT_STEP = "engine:database_security_scan"
    database = await engine._execute_capability(
        "database_security_scan", {"target": "redis"}, user_id=0
    )
    assert database["summary"]["total"] == 5, database
    assert len(database["sub_results"]) == 5, database
    assert any(item["data"].get("unauthorized") for item in database["sub_results"]), database
    assert any(item["status"] != "success" for item in database["sub_results"]), database

    CURRENT_STEP = "engine:baseline_check"
    baseline = await engine._execute_capability(
        "baseline_check",
        {"target": "backend", "username": "root", "password": "definitely-wrong"},
        user_id=0,
    )
    assert baseline.get("scan_completed") is False or baseline.get("connection_error"), baseline
    assert baseline.get("tool_error") or baseline.get("error_detail"), baseline

    CURRENT_STEP = "engine:nikto_timeout"
    web_timeout = await engine._execute_capability(
        "nikto_scan", {"target": "backend", "port": 8000, "timeout": 1}, user_id=0
    )
    assert web_timeout.get("scan_completed") is False, web_timeout
    assert web_timeout.get("tool_error"), web_timeout


def _run() -> None:
    health = _request("GET", "/health")
    assert health.get("status") in {"healthy", "degraded"}, health

    _async_port_scan()

    ping = _call("ping_asset", {"target": "redis", "count": 1, "timeout": 1})
    assert ping["data"].get("reachable") is True, ping

    fping = _call("fping_scan", {"targets": ["redis"]})
    _completed(fping)

    masscan = _call("masscan_scan", {"target": "redis", "port_range": "6379", "rate": 100, "timeout": 20})
    assert "scan_completed" in masscan["data"], masscan
    if masscan["data"].get("scan_completed") is False:
        _incomplete(masscan)

    ssl = _call("scan_ssl", {"target": "backend", "port": 8000})
    _incomplete(ssl)

    weak_password = _call("scan_weak_passwords", {"target": "backend", "service": "ssh", "port": 22})
    _incomplete(weak_password)

    nuclei = _call("scan_vulnerabilities", {
        "target": "http://backend:8000", "templates": "tech", "severity": "critical",
    })
    assert "scan_completed" in nuclei["data"], nuclei
    if nuclei["data"].get("scan_completed") is False:
        _incomplete(nuclei)

    nikto = _call("nikto_scan", {"target": "backend", "port": 8000, "timeout": 90})
    assert "scan_completed" in nikto["data"], nikto
    if nikto["data"].get("scan_completed") is False:
        _incomplete(nikto)

    sqlmap = _call("sqlmap_scan", {"url": "http://backend:8000/health", "timeout": 60})
    assert "scan_completed" in sqlmap["data"], sqlmap
    if sqlmap["data"].get("scan_completed") is False:
        _incomplete(sqlmap)

    gobuster = _call("gobuster_scan", {"url": "http://backend:8000", "threads": 2, "timeout": 90})
    assert "scan_completed" in gobuster["data"], gobuster
    if gobuster["data"].get("scan_completed") is False:
        _incomplete(gobuster)

    ffuf = _call("ffuf_scan", {"url": "http://backend:8000/FUZZ", "timeout": 90})
    assert "scan_completed" in ffuf["data"], ffuf
    if ffuf["data"].get("scan_completed") is False:
        _incomplete(ffuf)

    redis = _call("redis_check", {"target": "redis", "port": 6379, "timeout": 5})
    _completed(redis)
    assert redis["data"].get("unauthorized") is True, redis

    for tool, params in [
        ("mysql_check", {"target": "backend", "port": 3306, "timeout": 5}),
        ("mongodb_check", {"target": "backend", "port": 27017, "timeout": 5}),
        ("memcached_check", {"target": "backend", "port": 11211, "timeout": 5}),
        ("oracle_check", {"target": "backend", "port": 1521, "timeout": 5}),
        ("snmp_walk", {"target": "backend", "timeout": 12}),
        ("snmp_bruteforce", {"target": "backend", "timeout": 12}),
        ("snmp_get", {"target": "backend", "oid": "1.3.6.1.2.1.1.1.0", "timeout": 12}),
        ("enum4linux_scan", {"target": "backend", "timeout": 12}),
        ("crackmapexec_scan", {"target": "backend", "timeout": 12}),
        ("smb_enum", {"target": "backend", "timeout": 12}),
    ]:
        _incomplete(_call(tool, params))

    asyncio.run(_engine_combo_checks())
    payload = {"status": "security tools smoke ok", "gateway": GATEWAY_URL}
    output_path = os.getenv("SECURITY_TOOLS_SMOKE_OUTPUT")
    if output_path:
        Path(output_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


def main() -> None:
    try:
        _run()
    except Exception as exc:
        output_path = os.getenv("SECURITY_TOOLS_SMOKE_OUTPUT")
        if output_path:
            Path(output_path).write_text(json.dumps({
                "status": "security tools smoke failed",
                "step": CURRENT_STEP,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }, ensure_ascii=False), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
