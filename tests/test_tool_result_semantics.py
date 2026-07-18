import asyncio
import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path

from app.services.execution_engine import ExecutionEngine
from app.mcp.gateway_client import MCPGatewayClient
from app.services.task_executor import TaskExecutor
from app.orchestrator.orchestrator import Orchestrator


def test_gateway_errors_keep_the_original_target_and_reason():
    path = Path(__file__).resolve().parents[1] / "mcp-servers" / "gateway" / "server.py"
    spec = importlib.util.spec_from_file_location("certiproof_gateway_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    detail = "Timeout: No Response from 192.0.2.10"
    assert module.friendly_tool_error(detail) == f"工具执行超时：{detail}"
    assert "document_page_parse" in module.TOOL_ROUTES


def test_all_skipped_subtools_are_not_execution_failures():
    result = {
        "sub_results": [
            {"status": "skipped", "label": "Redis", "data": {"tool_error": "Connection refused"}},
            {"status": "skipped", "label": "MySQL", "data": {"tool_error": "Connection refused"}},
        ]
    }
    assert TaskExecutor._tool_issue("database_security_scan", result) is None


def test_incomplete_subtool_keeps_specific_reason_and_becomes_coverage_finding():
    result = {
        "sub_results": [{
            "status": "warning",
            "label": "SNMP 信息读取",
            "data": {"tool_error": "Timeout: No Response from 192.0.2.10"},
        }]
    }
    reason = TaskExecutor._tool_issue("network_device_scan", result)
    risks = TaskExecutor._risk_items(
        "network_device_scan",
        {"status": "warning", "warning": reason, "result": result},
        "192.0.2.10",
    )
    assert reason == "SNMP 信息读取：Timeout: No Response from 192.0.2.10"
    assert risks[0]["judgment"] == "not_tested"


def test_closed_service_is_skipped_but_timeout_is_warning():
    engine = ExecutionEngine()
    assert engine._tool_display_status({
        "reachable": False,
        "scan_completed": False,
        "tool_error": "[Errno 111] Connection refused",
    }) == "skipped"
    assert engine._tool_display_status({
        "reachable": False,
        "scan_completed": False,
        "tool_error": "Timeout: No Response",
    }) == "warning"


def test_redis_and_memcached_checks_use_matching_gateway_routes(monkeypatch):
    called = []

    async def call(_self, tool_name, params):
        called.append((tool_name, params))
        port = 6379 if tool_name == "redis_check" else 11211
        return {"status": "success", "data": {"target": params["target"], "port": port}}

    monkeypatch.setattr(MCPGatewayClient, "call", call)
    engine = ExecutionEngine()
    redis_result = asyncio.run(engine._redis_check(
        {"target": "192.0.2.10"}, user_id=1, project_id=1, db=None,
    ))
    memcached_result = asyncio.run(engine._memcached_check(
        {"target": "192.0.2.10"}, user_id=1, project_id=1, db=None,
    ))

    assert called == [
        ("redis_check", {"target": "192.0.2.10"}),
        ("memcached_check", {"target": "192.0.2.10"}),
    ]
    assert redis_result["port"] == 6379
    assert memcached_result["port"] == 11211


def test_baseline_non_compliance_becomes_traceable_findings():
    risks = TaskExecutor._risk_items(
        "baseline_check",
        {
            "status": "completed",
            "result": {
                "results": {
                    "max_auth_tries": {"description": "最大认证尝试次数", "requirement": "<= 5", "output": "8", "compliant": False},
                    "pass_min_len": {"description": "密码最小长度", "requirement": ">= 8", "output": "12", "compliant": True},
                },
            },
        },
        "192.0.2.10",
    )
    assert len(risks) == 1
    assert risks[0]["risk_key"] == "baseline:max_auth_tries"
    assert "当前值：8" in risks[0]["description"]


def test_structured_ssl_finding_keeps_identifier_and_value():
    risks = TaskExecutor._risk_items(
        "scan_ssl",
        {
            "status": "completed",
            "result": {"vulnerabilities": [{"id": "overall_grade", "finding": "T", "severity": "critical"}]},
        },
        "192.0.2.10",
    )

    assert risks[0]["description"] == "192.0.2.10: testssl 总体评级：T（工具原始等级）"


def test_ssh_directive_checks_are_case_insensitive(monkeypatch):
    monkeypatch.setitem(sys.modules, "asyncssh", SimpleNamespace())
    path = Path(__file__).resolve().parents[1] / "mcp-servers" / "ssh-checker" / "server.py"
    spec = importlib.util.spec_from_file_location("certiproof_ssh_checker_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SSH_CONFIG_CHECKS["max_auth_tries"]["compliant"]("MaxAuthTries 3") is True
    assert module.SSH_CONFIG_CHECKS["login_grace_time"]["compliant"]("LoginGraceTime 60") is True
    assert module.SSH_CONFIG_CHECKS["max_auth_tries"]["compliant"]("MaxAuthTries 8") is False


def test_nikto_parser_excludes_scan_metadata():
    path = Path(__file__).resolve().parents[1] / "mcp-servers" / "web-tools" / "server.py"
    spec = importlib.util.spec_from_file_location("certiproof_web_tools_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    findings = module.parse_nikto_findings("""
+ Start Time: 2026-07-16
+ Server: Example/1.0
+ [013587] /: Suggested security header missing: permissions-policy.
+ 8224 requests: 0 errors and 1 item reported
+ End Time: 2026-07-16
+ 1 host(s) tested
""")
    assert [item["description"] for item in findings] == [
        "+ [013587] /: Suggested security header missing: permissions-policy."
    ]


def test_top_level_timeout_is_warning_not_clean_success(monkeypatch):
    engine = ExecutionEngine()

    async def incomplete(*_args, **_kwargs):
        return {
            "target": "http://192.0.2.10:80",
            "scan_completed": False,
            "tool_status": "warning",
            "tool_error": "Web 漏洞扫描在 120 秒后超时",
            "findings": [],
        }

    monkeypatch.setattr(engine, "_execute_capability", incomplete)
    execution = asyncio.run(engine.execute_plan(
        [{"capability": "nikto_scan", "parameters": {"target": "192.0.2.10"}}],
        user_id=1,
    ))

    assert execution["results"][0]["status"] == "warning"
    assert execution["success_count"] == 0
    assert execution["warning_count"] == 1

    orchestrator = Orchestrator()
    description = orchestrator._generate_fallback_description(execution)
    scan_results = orchestrator._extract_scan_results_from_execution(execution)
    assert "未完成/无法判定" in description
    assert "Web 安全扫描" in description
    assert "成功 0，未完成/不可判定 1，失败 0" in description
    assert scan_results["quality"]["verdict"] == "conditional"
    assert scan_results["quality"]["warning"] == 1
    assert scan_results["asset_results"]["192.0.2.10"]["error"] == "Web 漏洞扫描在 120 秒后超时"


def test_list_assets_returns_deterministic_summary_and_query_result():
    execution = {
        "results": [{
            "capability": "list_assets",
            "status": "success",
            "result": {
                "message": "项目共有 2 个资产",
                "assets": [
                    {
                        "id": 1,
                        "name": "业务入口",
                        "type": "domain",
                        "value": "example.test",
                        "verification_status": "verified",
                    },
                    {
                        "id": 2,
                        "name": "",
                        "type": "ip",
                        "value": "192.0.2.10",
                        "verification_status": "pending",
                    },
                ],
            },
        }],
        "success_count": 1,
        "warning_count": 0,
        "failed_count": 0,
    }
    orchestrator = Orchestrator()

    description = orchestrator._generate_fallback_description(execution)
    scan_results = orchestrator._extract_scan_results_from_execution(execution)

    assert "当前项目共有 2 个资产" in description
    assert "业务入口（域名）：example.test，已验证" in description
    assert "未命名资产（IP）：192.0.2.10，待验证" in description
    assert scan_results["query_result"]["capability"] == "list_assets"
    assert len(scan_results["query_result"]["assets"]) == 2
    assert scan_results["asset_results"] == {}
    assert scan_results["quality"]["total_assets"] == 2


def test_web_tool_timeout_contract_is_warning():
    path = Path(__file__).resolve().parents[1] / "mcp-servers" / "web-tools" / "server.py"
    spec = importlib.util.spec_from_file_location("certiproof_web_tools_timeout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.timeout_result("nikto_scan", "http://192.0.2.10", 120000, "timeout")

    assert result["status"] == "warning"
    assert result["data"]["scan_completed"] is False


def test_nuclei_unreachable_target_is_warning_before_scan(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "mcp-servers" / "security-tools" / "server.py"
    spec = importlib.util.spec_from_file_location("certiproof_security_tools_unreachable", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def no_open_ports(*_args, **_kwargs):
        return []

    async def must_not_start(*_args, **_kwargs):
        raise AssertionError("nuclei must not start for an unreachable target")

    monkeypatch.setattr(module, "verify_tcp_open_ports", no_open_ports)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", must_not_start)
    result = asyncio.run(module.nuclei_scan({"target": "203.0.113.10"}))

    assert result["status"] == "warning"
    assert result["data"]["reachable"] is False
    assert result["data"]["scan_completed"] is False
    assert "无法验证" in result["data"]["tool_error"]


def test_nuclei_reachable_target_can_complete_with_no_findings(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "mcp-servers" / "security-tools" / "server.py"
    spec = importlib.util.spec_from_file_location("certiproof_security_tools_reachable", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Process:
        returncode = 0
        pid = 1

        async def communicate(self):
            return b"", b""

    async def open_port(*_args, **_kwargs):
        return [{"port": 443, "protocol": "tcp", "state": "open"}]

    async def create_process(*_args, **_kwargs):
        return Process()

    monkeypatch.setattr(module, "verify_tcp_open_ports", open_port)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create_process)
    result = asyncio.run(module.nuclei_scan({"target": "https://example.test"}))

    assert result["status"] == "success"
    assert result["data"]["reachable"] is True
    assert result["data"]["scan_completed"] is True
    assert result["data"]["findings"] == []


def test_snmp_no_response_is_failed_and_hides_library_setup_noise(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "mcp-servers" / "network-tools" / "server.py"
    spec = importlib.util.spec_from_file_location("certiproof_network_tools_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Process:
        returncode = 0

        async def communicate(self):
            return b"", b"Created directory: /var/lib/snmp/cert_indexes\nTimeout: No Response\n"

    async def create_process(*_args, **_kwargs):
        return Process()

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create_process)
    result = asyncio.run(module.snmp_bruteforce({"target": "192.0.2.10"}))

    assert result["status"] == "failed"
    assert result["data"]["scan_completed"] is False
    assert result["data"]["tool_error"] == "Timeout: No Response"
