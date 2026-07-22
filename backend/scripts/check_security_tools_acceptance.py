"""Repeatable security-tool acceptance against the isolated Docker target."""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path
from urllib import error, request


GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway:9000").rstrip("/")
TARGET = os.getenv("CP_ACCEPTANCE_TARGET", "e2e-target")
ASYNC_TOOLS = {
    "nmap_scan", "masscan_scan", "nuclei_scan", "hydra_bruteforce", "testssl_scan",
    "crypto_transport_scan", "nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan",
    "snmp_walk", "snmp_bruteforce", "snmp_get", "enum4linux_scan", "crackmapexec_scan",
    "smb_enum", "linux_baseline", "password_policy_check", "ssh_config_check",
    "audit_config_check", "service_port_check", "file_permission_check", "mac_check",
}

CAPABILITY_MATRIX = [
    {"group": "快速矩阵", "capabilities": "存活、端口、TLS、目录、SSH 基线、弱口令、五类数据库、SNMP", "coverage": "完整受控场景"},
    {"group": "完整矩阵", "capabilities": "Nikto、Nuclei、SQLMap", "coverage": "执行链路和代表性问题，不穷尽全部漏洞"},
    {"group": "外部环境", "capabilities": "Windows/AD/SMB", "coverage": "需要 Windows VM"},
    {"group": "实机环境", "capabilities": "交换机、密码机、国密硬件", "coverage": "需要授权实机"},
]


def request_json(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 30) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(
        f"{GATEWAY_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"HTTP {exc.code}: {detail[:1000]}") from exc


def call(tool: str, params: dict, timeout: int = 240) -> dict:
    if tool in ASYNC_TOOLS:
        started = request_json(
            "/call/async", "POST", {"tool": tool, "params": params}, timeout=30,
        )
        task_id = started.get("task_id")
        if not task_id:
            raise AssertionError(f"missing async task id: {started}")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            progress = request_json(f"/progress/{tool}/{task_id}", timeout=15)
            if "alive" not in progress or "heartbeat_at" not in progress:
                raise AssertionError(f"missing liveness fields: {progress}")
            status = progress.get("status")
            if status == "completed":
                result = request_json(f"/result/{tool}/{task_id}", timeout=30)
                break
            if status in {"failed", "cancelled"}:
                raise AssertionError(progress.get("error") or f"async task {status}")
            time.sleep(1)
        else:
            request_json(f"/cancel/{tool}/{task_id}", "POST", {}, timeout=15)
            raise AssertionError(f"acceptance harness exceeded {timeout}s while tool remained active")
    else:
        result = request_json(
            "/call", "POST", {"tool": tool, "params": params}, timeout=timeout,
        )
    data = result.get("data")
    if not isinstance(data, dict):
        raise AssertionError(f"missing normalized data: {result}")
    return data


def complete(data: dict) -> bool:
    return data.get("scan_completed") is not False and not data.get("tool_error")


def has_open_ports(data: dict) -> bool:
    expected = {22, 80, 443, 1521, 3306, 6379, 11211, 27017}
    actual = {int(item["port"]) for item in data.get("open_ports", []) if item.get("port") is not None}
    return expected.issubset(actual)


def web_paths(data: dict) -> bool:
    discovered = data.get("discovered") or []
    values = {
        str(item.get("path") or item.get("input") or item.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
        for item in discovered
    }
    return bool(values & {"admin", "login", "backup", "api", "server-status"})


def run_case(name: str, tool: str, params: dict, validator=complete, timeout: int = 240) -> dict:
    started = time.monotonic()
    try:
        data = call(tool, params, timeout=timeout)
        if not validator(data):
            raise AssertionError(data.get("tool_error") or "result did not satisfy the acceptance condition")
        result = {
            "name": name,
            "tool": tool,
            "status": "passed",
            "duration_seconds": round(time.monotonic() - started, 2),
            "summary": {
                key: data.get(key)
                for key in ("target", "scan_completed", "reachable", "total_findings", "total_discovered", "unauthorized", "empty_password")
                if key in data
            },
        }
        print(f"[PASS] {name} ({result['duration_seconds']}s)", flush=True)
        return result
    except Exception as exc:
        result = {
            "name": name,
            "tool": tool,
            "status": "failed",
            "duration_seconds": round(time.monotonic() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }
        print(f"[FAIL] {name}: {result['error']}", flush=True)
        return result


def run_cancel_control() -> dict:
    """Prove that cancellation reaches the actual long-running async task."""
    tool = "nuclei_scan"
    started = request_json(
        "/call/async",
        "POST",
        {"tool": tool, "params": {"target": f"http://{TARGET}", "templates": "misconfig,exposure"}},
        timeout=30,
    )
    task_id = started.get("task_id")
    if not task_id:
        return {"name": "异步停止贯通", "status": "failed", "error": f"missing task id: {started}"}
    try:
        deadline = time.monotonic() + 15
        before = {}
        while time.monotonic() < deadline:
            before = request_json(f"/progress/{tool}/{task_id}", timeout=15)
            if before.get("status") == "running" and before.get("heartbeat_at"):
                break
            time.sleep(0.5)
        if before.get("status") != "running":
            raise AssertionError(f"task did not enter running state: {before}")
        stopped = request_json(f"/cancel/{tool}/{task_id}", "POST", {}, timeout=15)
        after = request_json(f"/progress/{tool}/{task_id}", timeout=15)
        if stopped.get("status") != "cancelled" or after.get("status") != "cancelled" or after.get("alive"):
            raise AssertionError({"cancel": stopped, "progress": after})
        return {"name": "异步停止贯通", "status": "passed", "tool": tool}
    except Exception as exc:
        return {"name": "异步停止贯通", "status": "failed", "tool": tool, "error": str(exc)}


def quick_cases() -> list[tuple]:
    masscan_target = socket.gethostbyname(TARGET)
    return [
        ("主机存活", "ping_host", {"target": TARGET, "count": 1, "timeout": 2}, lambda d: d.get("reachable") is True, 30),
        ("批量存活", "fping_scan", {"targets": [TARGET], "timeout": 10}, complete, 30),
        ("端口扫描", "nmap_scan", {"target": TARGET, "port_range": "22,80,443,1521,3306,6379,11211,27017", "host_timeout": 60}, has_open_ports, 90),
        ("高速端口扫描", "masscan_scan", {"target": masscan_target, "port_range": "22,80,443,1521,3306,6379,11211,27017", "rate": 1000}, has_open_ports, 90),
        ("SSL/TLS", "testssl_scan", {"target": TARGET, "port": 443}, complete, 240),
        ("密码协议与证书", "crypto_transport_scan", {"target": TARGET, "port": 443}, complete, 240),
        ("Gobuster 目录", "gobuster_scan", {"url": f"http://{TARGET}", "threads": 4}, web_paths, 120),
        ("FFUF 目录", "ffuf_scan", {"url": f"http://{TARGET}/FUZZ"}, web_paths, 120),
        ("Linux 基线", "linux_baseline", {"target": TARGET, "username": "audit", "password": "CertiProof-E2E-2026!"}, lambda d: d.get("supported") is True and bool(d.get("results")), 180),
        ("SSH 弱口令", "hydra_bruteforce", {"target": TARGET, "service": "ssh", "port": 22, "usernames": ["root"], "passwords": ["P@ssw0rd"]}, lambda d: complete(d) and any(item.get("username") == "root" for item in d.get("found", [])), 120),
        ("Redis 未授权", "redis_check", {"target": TARGET, "timeout": 8}, lambda d: complete(d) and d.get("unauthorized") is True, 30),
        ("MySQL 空口令", "mysql_check", {"target": TARGET, "timeout": 8}, lambda d: complete(d) and d.get("empty_password") is True, 30),
        ("MongoDB 未授权", "mongodb_check", {"target": TARGET, "timeout": 8}, lambda d: complete(d) and d.get("unauthorized") is True, 30),
        ("Memcached 未授权", "memcached_check", {"target": TARGET, "timeout": 8}, lambda d: complete(d) and d.get("unauthorized") is True, 30),
        ("Oracle TNS", "oracle_check", {"target": TARGET, "timeout": 8}, lambda d: complete(d) and bool(d.get("version_info")), 30),
        ("SNMP Walk", "snmp_walk", {"target": TARGET, "community": "public"}, lambda d: complete(d) and bool(d.get("results")), 40),
        ("SNMP OID", "snmp_get", {"target": TARGET, "community": "public", "oid": "1.3.6.1.2.1.1.1.0"}, lambda d: complete(d) and bool(d.get("value")), 30),
        ("SNMP 团体字", "snmp_bruteforce", {"target": TARGET}, lambda d: complete(d) and bool(d.get("found")), 45),
    ]


def full_cases() -> list[tuple]:
    return [
        ("Nikto Web 扫描", "nikto_scan", {"target": TARGET, "port": 80}, complete, 240),
        ("Nuclei 代表性漏洞", "nuclei_scan", {"target": f"http://{TARGET}", "templates": "misconfig,exposure", "severity": "critical,high,medium"}, complete, 360),
        ("SQLMap 执行链路", "sqlmap_scan", {"url": f"http://{TARGET}/item?id=1"}, complete, 240),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("quick", "full"), default="quick")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.list:
        print(json.dumps(CAPABILITY_MATRIX, ensure_ascii=False, indent=2))
        return

    cases = quick_cases() + (full_cases() if args.profile == "full" else [])
    results = [run_case(*case) for case in cases]
    controls = [run_cancel_control()]
    payload = {
        "status": "passed" if all(item["status"] == "passed" for item in results + controls) else "failed",
        "profile": args.profile,
        "target": TARGET,
        "passed": sum(item["status"] == "passed" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "results": results,
        "control_checks": controls,
        "limitations": CAPABILITY_MATRIX[2:],
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    if payload["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
