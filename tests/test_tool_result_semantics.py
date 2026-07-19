import asyncio
import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

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


def test_network_capability_enforces_scan_execute_permission(monkeypatch):
    engine = ExecutionEngine()

    async def denied(*_args, **_kwargs):
        return None

    async def must_not_scan(*_args, **_kwargs):
        raise AssertionError("tool must not run without scan:execute")

    monkeypatch.setattr(engine, "_project_for_user_id", denied)
    monkeypatch.setattr(engine, "_scan_ports", must_not_scan)
    with pytest.raises(ValueError, match="无权"):
        asyncio.run(engine._execute_capability(
            "scan_ports", {"target": "192.0.2.10"}, user_id=1, project_id=7, db=object(),
        ))


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
    assert scan_results["quality"]["failed"] == 0
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


def test_project_status_returns_deterministic_summary_and_query_result():
    execution = {
        "results": [{
            "capability": "view_project_status",
            "status": "success",
            "result": {
                "found": True,
                "project_name": "真实材料验收",
                "workflow_progress": 100.0,
                "compliance_score": 66.7,
                "grade": "一般",
                "coverage": 92.5,
                "current_phase": {"name": "生成报告", "status": "completed"},
                "findings": {"total": 30, "open": 20, "fixed": 8, "unable": 2},
                "report": {"available": True, "version": 2, "status": "current"},
                "phases": [],
            },
        }],
        "success_count": 1,
        "warning_count": 0,
        "failed_count": 0,
    }
    orchestrator = Orchestrator()

    description = orchestrator._generate_fallback_description(execution)
    scan_results = orchestrator._extract_scan_results_from_execution(execution)

    assert "流程进度：100.0%" in description
    assert "合规评分：66.7 分（一般）" in description
    assert "待处理 20" in description
    assert "报告：已生成 v2" in description
    assert scan_results["query_result"]["capability"] == "view_project_status"
    assert scan_results["query_result"]["data"]["compliance_score"] == 66.7
    assert scan_results["asset_results"] == {}


def _project_status_result(view, **overrides):
    data = {
        "found": True,
        "view": view,
        "project_name": "真实材料验收",
        "assessment_id": 9,
        "workflow_progress": 80.0,
        "compliance_score": 66.7,
        "grade": "一般",
        "coverage": 92.5,
        "current_phase": {"name": "整改与复测", "status": "active"},
        "findings": {"total": 30, "open": 20, "fixed": 8, "unable": 2},
        "finding_breakdown": {"severity": {"critical": 1, "high": 4}},
        "major_gaps": [{
            "id": 1, "title": "访问控制策略不完整", "severity": "high",
            "source_type": "document", "judgment": "fail",
        }],
        "report": {"available": False, "version": None, "status": None},
        "phases": [],
    }
    data.update(overrides)
    return {
        "results": [{"capability": "view_project_status", "status": "success", "result": data}],
        "success_count": 1, "warning_count": 0, "failed_count": 0,
    }


def test_readiness_query_gives_direct_conclusion_and_caveat():
    description = Orchestrator()._generate_fallback_description(_project_status_result("readiness"))
    assert description.startswith("当前不具备可靠的通过判断条件")
    assert "仍有 2 项无法验证" in description
    assert "不替代测评机构" in description
    assert "【汇总】" not in description


def test_major_gaps_query_lists_real_finding_instead_of_only_counts():
    description = Orchestrator()._generate_fallback_description(_project_status_result("gaps"))
    assert "访问控制策略不完整" in description
    assert "[高]" in description
    assert "另有 2 项无法验证" in description


def test_major_gaps_query_explains_group_count_scope_and_evidence():
    result = _project_status_result("gaps", major_gaps=[{
        "id": 1,
        "title": "SSL/TLS 检测",
        "severity": "critical",
        "source_type": "technical",
        "judgment": "fail",
        "count": 7,
        "scopes": ["192.0.2.10"],
        "descriptions": ["总体评级为 T，仍提供已废弃密码套件"],
    }])

    description = Orchestrator()._generate_fallback_description(result)

    assert "按问题类型" in description
    assert "7 项" in description
    assert "范围：192.0.2.10" in description
    assert "总体评级为 T" in description


def test_major_gaps_query_does_not_expose_internal_task_scope():
    result = _project_status_result("gaps", major_gaps=[{
        "title": "审计保护与留存",
        "severity": "medium",
        "source_type": "document",
        "count": 1,
        "scopes": [],
        "descriptions": ["安全审计管理制度：留存时间表述不一致"],
    }])

    description = Orchestrator()._generate_fallback_description(result)

    assert "安全审计管理制度" in description
    assert "task:" not in description


def test_executive_query_has_judgment_risk_and_next_step():
    description = Orchestrator()._generate_fallback_description(_project_status_result("executive"))
    assert "管理层摘要" in description
    assert "风险存量" in description
    assert "建议" in description
    assert "高危 4" in description


def test_findings_query_renders_titles_and_states_without_generic_tool_name():
    execution = {
        "results": [{
            "capability": "view_findings", "status": "success", "result": {
                "total": 2,
                "groups": [
                    {"title": "日志留存周期不足", "severity": "high", "status": "open", "source_type": "technical", "count": 1, "targets": ["10.0.0.1"]},
                    {"title": "制度已补充", "severity": "medium", "status": "fixed", "source_type": "document", "count": 1, "targets": ["安全审计管理制度"]},
                ],
                "findings": [
                    {"id": 1, "clause_name": "日志留存周期不足", "severity": "high", "status": "open", "judgment": "fail", "source_type": "technical"},
                    {"id": 2, "clause_name": "制度已补充", "severity": "medium", "status": "fixed", "judgment": "pass", "source_type": "document"},
                ],
            },
        }],
        "success_count": 1, "warning_count": 0, "failed_count": 0,
    }
    description = Orchestrator()._generate_fallback_description(execution)
    assert "日志留存周期不足" in description
    assert "制度已补充" in description
    assert "资产 1 个" in description
    assert "文档范围 1 个" in description
    assert "view_findings" not in description
    assert "unknown" not in description


def test_scan_history_uses_business_labels_instead_of_internal_enums():
    execution = {
        "results": [{"capability": "view_scan_history", "status": "success", "result": {
            "scan_history": [{
                "id": 12, "name": "Web 安全扫描", "targets": ["example.com"],
                "status": "completed", "status_label": "已完成", "quality_label": "结果完整",
                "confirmed_count": 2, "unverified_count": 0, "incomplete_checks_count": 0,
                "conclusion_status": "issues", "conclusion_label": "发现问题",
                "conclusion_summary": "已发现明确安全问题",
            }],
        }}],
        "success_count": 1, "warning_count": 0, "failed_count": 0,
    }
    description = Orchestrator()._generate_fallback_description(execution)
    assert "Web 安全扫描" in description
    assert "发现问题" in description
    assert "completed" not in description


def test_scan_history_resolves_assessment_and_tool_names_without_leaking_enums():
    class Task:
        id = 1
        status = "completed"
        result_summary = {}
        findings_count = 0
        created_at = None
        completed_at = None

        def __init__(self, task_type):
            self.parameters = {"task_type": task_type}

    expected = {
        "full_asset_assessment": "全资产组合扫描",
        "web_vulnerability_assessment": "Web 漏洞扫描",
        "network_device_assessment": "网络设备检测",
        "gobuster_scan": "目录爆破",
        "unregistered_internal_task": "安全检测",
    }
    for internal_name, display_name in expected.items():
        result = ExecutionEngine._scan_task_descriptor(Task(internal_name))
        assert result["name"] == display_name
        assert internal_name not in result["name"]


def test_scan_history_separates_confirmed_findings_from_incomplete_checks():
    task = SimpleNamespace(
        id=44,
        status="completed",
        triggered_by="manual",
        findings_count=99,
        parameters={"source": "assessment_task", "task_type": "network_device_assessment", "target": "192.0.2.10"},
        result_summary={
            "outcome": "partial",
            "results": [{"status": "warning", "result": {"summary": {"warning": 2, "failed": 0, "skipped": 0}}}],
        },
        created_at=None,
        completed_at=None,
    )
    result = ExecutionEngine._scan_task_descriptor(task, {"confirmed": 0, "unverified": 1})
    assert result["findings_count"] == 0
    assert result["confirmed_count"] == 0
    assert result["unverified_count"] == 1
    assert result["incomplete_checks_count"] == 2
    assert result["quality_label"] == "结果需复核"
    assert result["source_label"] == "等保测评"
    assert result["conclusion_status"] == "incomplete"
    assert result["conclusion_label"] == "检测不完整"
    assert "不能判断目标安全" in result["conclusion_summary"]


@pytest.mark.parametrize(("status", "summary", "stats", "expected_status", "expected_label"), [
    ("completed", {"scan_results": {"quality": {"verdict": "complete"}}}, {"confirmed": 0, "unverified": 0}, "clean", "检测完成"),
    ("completed", {"scan_results": {"quality": {"verdict": "complete"}}}, {"confirmed": 2, "unverified": 0}, "issues", "发现问题"),
    ("completed", {"scan_results": {"quality": {"verdict": "conditional"}}}, {"confirmed": 0, "unverified": 0}, "incomplete", "检测不完整"),
    ("failed", {}, {"confirmed": 0, "unverified": 0}, "failed", "执行失败"),
])
def test_scan_history_uses_the_four_terminal_business_conclusions(status, summary, stats, expected_status, expected_label):
    task = SimpleNamespace(
        id=45,
        status=status,
        triggered_by="manual",
        findings_count=0,
        parameters={"task_type": "scan_ports", "target": "192.0.2.20"},
        result_summary=summary,
        created_at=None,
        completed_at=None,
    )
    result = ExecutionEngine._scan_task_descriptor(task, stats)
    assert result["conclusion_status"] == expected_status
    assert result["conclusion_label"] == expected_label


def test_scan_history_treats_reachable_host_with_no_open_ports_as_complete():
    task = SimpleNamespace(
        id=46,
        status="completed",
        triggered_by="manual",
        findings_count=0,
        parameters={"plan": [{"capability": "scan_ports", "parameters": {"target": "192.0.2.30"}}]},
        result_summary={"scan_results": {"quality": {"verdict": "conditional"}, "asset_results": {
            "192.0.2.30": {"status": "success", "display_status": "warning", "result": {
                "host_status": "up", "open_ports": [], "filtered_count": 0,
            }},
        }}},
        created_at=None,
        completed_at=None,
    )
    result = ExecutionEngine._scan_task_descriptor(task, {"confirmed": 0, "unverified": 0})
    assert result["conclusion_status"] == "clean"
    assert result["conclusion_label"] == "检测完成"


def test_scan_history_keeps_unreachable_scan_incomplete():
    payload = {"status": "warning", "result": {"reachable": False, "scan_completed": False, "findings": []}}
    assert ExecutionEngine._scan_asset_result_state(payload) == "incomplete"
    filtered = {"status": "success", "capability": "scan_ports", "result": {"host_status": "up", "filtered_count": 3}}
    assert ExecutionEngine._scan_asset_result_state(filtered) == "incomplete"


def test_scan_change_query_does_not_fall_back_to_history_list():
    execution = {
        "results": [{"capability": "view_scan_changes", "status": "success", "result": {
            "comparable": True, "reliable": True,
            "current": {"id": 12, "name": "漏洞扫描"}, "previous": {"id": 11},
            "changes": {"added": ["CVE-A"], "resolved": ["CVE-B"], "persistent": ["CVE-C"]},
        }}],
        "success_count": 1, "warning_count": 0, "failed_count": 0,
    }
    description = Orchestrator()._generate_fallback_description(execution)
    assert "新增问题 1 项" in description
    assert "已消失问题 1 项" in description
    assert "CVE-A" in description


def test_composite_summary_counts_child_outcomes_not_successful_wrapper():
    execution = {
        "results": [{
            "capability": "tech_assessment", "target": "192.0.2.10", "status": "success",
            "result": {
                "summary": {"success": 1, "warning": 1, "failed": 1, "skipped": 1},
                "sub_results": [
                    {"capability": "scan_ports", "status": "success", "target": "192.0.2.10", "data": {"open_ports": [{"port": 22}]}},
                    {"capability": "scan_vulnerabilities", "status": "warning", "target": "192.0.2.10", "data": {"scan_completed": False, "tool_error": "timeout"}},
                    {"capability": "nikto_scan", "status": "failed", "target": "192.0.2.10", "error": "connection failed", "data": {}},
                    {"capability": "baseline_check", "status": "skipped", "target": "192.0.2.10", "error": "missing credentials", "data": {}},
                ],
            },
        }],
        "success_count": 1, "warning_count": 0, "failed_count": 0,
    }
    orchestrator = Orchestrator()
    description = orchestrator._generate_fallback_description(execution)
    scan_results = orchestrator._extract_scan_results_from_execution(execution)
    assert "共 4 个执行项，成功 1，未完成/不可判定 1，失败 1，跳过 1" in description
    assert scan_results["quality"]["verdict"] == "partial"
    assert scan_results["quality"]["warning"] == 2
    assert scan_results["quality"]["failed"] == 1
    assert "组合检测未完整覆盖" in scan_results["asset_results"]["192.0.2.10"]["error"]


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
