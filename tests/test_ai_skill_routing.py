import asyncio
import json

import pytest

from app.services.ai_engine import AIEngine, INTENT_CATEGORIES, RouteContract
from app.services.ai_skill_registry import prompt_skill_registry
from app.services.capability_registry import capability_registry


class FakeAIEngine(AIEngine):
    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.calls = []

    async def _request_llm(self, db, user_id, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return {"content": response}


def context_with_history():
    return {
        "current_project": {"id": 7, "name": "演示项目", "compliance_level": "三级"},
        "project_assets": [{"name": "Web", "type": "domain", "value": "example.com"}],
        "assessment_state": {"has_assessment": True, "name": "自查", "status": "completed", "progress": 100},
        "recent_messages": [{"role": "user", "content": "扫描旧目标 203.0.113.9"}],
        "thread_summary": "旧目标是 203.0.113.9",
        "thread_handoff_summary": "",
    }


def test_router_catalog_contains_skills_not_full_capability_schemas():
    engine = AIEngine()
    prompt = engine._build_router_messages("这个项目能过等保吗", context_with_history())[0]["content"]["variable"]

    assert "project-status" in prompt
    assert "query_project_status" in prompt
    assert "nikto_scan" not in prompt
    assert "port_range" not in prompt


def test_every_prompt_skill_capability_exists_in_registry():
    missing = [
        (skill.name, capability)
        for skill in prompt_skill_registry._skills.values()
        for capabilities in skill.intent_capabilities.values()
        for capability in capabilities
        if not capability_registry.get(capability)
    ]

    assert missing == []


def test_route_schema_enums_match_registered_intents_and_skills():
    schema = RouteContract.model_json_schema()["properties"]

    assert set(schema["intents"]["items"]["enum"]) == set(INTENT_CATEGORIES)
    assert set(schema["skills"]["items"]["enum"]) == set(prompt_skill_registry._skills)


def test_route_json_extraction_ignores_model_preamble_and_extra_braces():
    content = '分析对象 {不是JSON}。最终结果：```json\n{"intents":["query_project_status"],"skills":["project-status"]}\n```'

    result = AIEngine()._extract_json_object(content)

    assert result["intents"] == ["query_project_status"]


def test_project_status_loads_only_status_skill_and_current_facts():
    engine = FakeAIEngine([
        json.dumps({
            "category": "project_query",
            "intents": ["query_compliance_readiness"],
            "skills": ["project-status"],
            "scope": "current_project",
            "entities": {},
            "confidence": 0.96,
            "needs_clarification": False,
            "clarification": "",
            "use_thread_context": False,
        }),
    ])

    result = asyncio.run(engine.decide("这个项目能过等保吗", context_with_history(), db=None, user_id=None))

    assert result["plan"] == [{
        "capability": "view_project_status",
        "parameters": {"view": "readiness", "assessment_code": "dengbao"},
    }]
    assert result["routing"]["skills"] == ["project-status"]
    assert len(engine.calls) == 1


def test_security_intent_loads_only_relevant_web_capabilities():
    skills = prompt_skill_registry.resolve(["security-scan"], ["scan_web"])
    prompt = prompt_skill_registry.format_for_planner(skills, ["scan_web"], AIEngine().registry)

    assert "nikto_scan" in prompt
    assert "sqlmap_scan" in prompt
    assert "scan_ports" not in prompt
    assert "database_security_scan" not in prompt


def test_planner_cannot_escape_selected_skill_capabilities():
    engine = FakeAIEngine([
        json.dumps({
            "category": "detection_execution",
            "intents": ["scan_web"],
            "skills": ["security-scan"],
            "scope": "current_project",
            "entities": {},
            "confidence": 0.9,
            "needs_clarification": False,
            "clarification": "",
            "use_thread_context": False,
        }),
        json.dumps({
            "plan": [{"capability": "scan_ports", "parameters": {"target": "项目资产"}}],
            "response": "开始扫描。",
        }),
    ])

    result = asyncio.run(engine.decide("对所有资产做 Web 扫描", context_with_history(), db=None, user_id=None))

    assert result["plan"][0]["capability"] == "chat"
    assert "超出所选业务能力范围" in result["response"]


def test_structured_quick_action_bypasses_llm_and_preserves_credentials():
    engine = FakeAIEngine([])
    request = json.dumps({
        "type": "multi_asset_scan",
        "capability": "baseline_check",
        "assets": [{"value": "192.0.2.10"}],
        "ssh_credential": {"username": "root", "password": "secret", "port": 22},
    })

    result = asyncio.run(engine.decide(request, context_with_history(), db=None, user_id=None))

    assert engine.calls == []
    assert result["plan"] == [{
        "capability": "baseline_check",
        "parameters": {"target": "192.0.2.10", "username": "root", "password": "secret", "port": 22},
    }]
    assert result["routing"]["confidence"] == 1.0
    assert result["routing"]["category"] == "detection_execution"


def test_pending_findings_have_only_one_router_intent():
    catalog = prompt_skill_registry.catalog_for_router()

    assert "query_findings" in catalog
    assert "remediation_status" not in catalog


@pytest.mark.parametrize(("intent", "expected_capability", "expected_parameters"), [
    ("query_project_status", "view_project_status", {"view": "status", "assessment_code": "dengbao"}),
    ("query_compliance_readiness", "view_project_status", {"view": "readiness", "assessment_code": "dengbao"}),
    ("query_major_gaps", "view_project_status", {"view": "gaps", "assessment_code": "dengbao"}),
    ("query_executive_summary", "view_project_status", {"view": "executive", "assessment_code": "dengbao"}),
    ("query_findings", "view_findings", {"assessment_code": "dengbao"}),
    ("query_open_ports", "view_open_ports", {}),
    ("query_vulnerabilities", "view_vulnerabilities", {}),
    ("query_scan_history", "view_scan_history", {}),
    ("query_scan_changes", "view_scan_changes", {}),
    ("asset_list", "list_assets", {}),
])
def test_project_queries_use_typed_deterministic_contracts(intent, expected_capability, expected_parameters):
    skill = "asset-management" if intent == "asset_list" else "project-status"
    engine = FakeAIEngine([json.dumps({
        "category": "project_query",
        "intents": [intent],
        "skills": [skill],
        "scope": "current_project",
        "entities": {},
        "confidence": 0.95,
        "needs_clarification": False,
    })])

    result = asyncio.run(engine.decide("自然语言查询", context_with_history(), db=None, user_id=None))

    assert result["plan"] == [{"capability": expected_capability, "parameters": expected_parameters}]
    assert result["routing"]["category"] == "project_query"
    assert len(engine.calls) == 1


@pytest.mark.parametrize(("intent", "action"), [
    ("assessment_start", "start"),
    ("assessment_retest", "retest"),
    ("assessment_reset", "reset"),
])
def test_flow_actions_use_deterministic_contracts(intent, action):
    engine = FakeAIEngine([json.dumps({
        "category": "flow_operation",
        "intents": [intent],
        "skills": ["assessment-flow"],
        "scope": "current_project",
        "entities": {},
        "confidence": 0.95,
        "needs_clarification": False,
    })])

    result = asyncio.run(engine.decide("开始操作", context_with_history(), db=None, user_id=None))

    assert result["plan"][0]["capability"] == "assessment_flow_action"
    assert result["plan"][0]["parameters"]["action"] == action
    assert result["plan"][0]["parameters"].get("confirm") is not True
    assert len(engine.calls) == 1


def test_reset_requires_explicit_confirmation_in_current_turn():
    route = json.dumps({
        "category": "flow_operation", "intents": ["assessment_reset"], "skills": ["assessment-flow"],
        "scope": "current_project", "entities": {}, "confidence": 0.99, "needs_clarification": False,
    })
    engine = FakeAIEngine([route])
    result = asyncio.run(engine.decide("确认彻底重置测评", context_with_history(), db=None, user_id=None))
    assert result["plan"][0]["parameters"]["confirm"] is True


def test_help_returns_complete_product_help_without_planner_call():
    engine = FakeAIEngine([json.dumps({
        "category": "help", "intents": ["help"], "skills": ["scope-guard"], "scope": "none",
        "entities": {}, "confidence": 0.99, "needs_clarification": False,
    })])
    result = asyncio.run(engine.decide("你能做什么", context_with_history(), db=None, user_id=None))
    assert result["plan"] == [{"capability": "help", "parameters": {}}]
    assert "项目查询" in result["response"]
    assert "检测执行" in result["response"]
    assert len(engine.calls) == 1


def test_out_of_scope_is_rejected_without_general_chat_or_planner_call():
    engine = FakeAIEngine([json.dumps({
        "category": "out_of_scope", "intents": ["out_of_scope"], "skills": ["scope-guard"], "scope": "none",
        "entities": {}, "confidence": 0.99, "needs_clarification": False,
    })])
    result = asyncio.run(engine.decide("帮我写一首诗", context_with_history(), db=None, user_id=None))
    assert result["plan"][0]["capability"] == "chat"
    assert "不属于 CertiProof 当前支持范围" in result["response"]
    assert len(engine.calls) == 1


def test_exhausted_models_return_explicit_non_execution_message():
    engine = FakeAIEngine([ValueError("所有模型均未生成有效结果：结构化校验失败")])

    result = asyncio.run(engine.decide("处理一下", context_with_history(), db=None, user_id=None))

    assert result["plan"][0]["capability"] == "chat"
    assert "连续未生成通过校验的执行计划" in result["response"]
    assert "没有执行任何工具" in result["response"]


def test_mismatched_model_category_is_corrected_from_valid_intent():
    route = AIEngine()._parse_route(json.dumps({
        "category": "help", "intents": ["scan_ports"], "skills": ["security-scan"],
        "confidence": 0.9, "needs_clarification": False,
    }))
    assert route["category"] == "detection_execution"


def test_unknown_model_intent_is_forced_out_of_scope():
    route = AIEngine()._parse_route(json.dumps({
        "category": "project_query", "intents": ["invented_tool"], "skills": ["security-scan"],
        "confidence": 0.9, "needs_clarification": False,
    }))
    assert route["category"] == "out_of_scope"
    assert route["intents"] == ["out_of_scope"]


def test_unknown_model_intent_is_repaired_once_from_the_same_semantics():
    engine = FakeAIEngine([
        json.dumps({
            "category": "help", "intents": ["scan_web_help"], "skills": ["scope-guard"],
            "scope": "none", "confidence": 0.9, "needs_clarification": False,
        }),
        json.dumps({
            "category": "help", "intents": ["help"], "skills": ["scope-guard"],
            "scope": "none", "confidence": 0.95, "needs_clarification": False,
        }),
    ])
    result = asyncio.run(engine.decide("Web 扫描应该怎么发起", context_with_history(), db=None, user_id=None))
    assert result["routing"]["category"] == "help"
    assert result["routing"]["intents"] == ["help"]
    assert len(engine.calls) == 2
    assert "不得翻译、改写或自造 intent" in engine.calls[1]["messages"][0]["content"]["variable"]


def test_clear_detection_intent_has_bounded_fallback_when_planner_times_out():
    engine = FakeAIEngine([
        json.dumps({
            "category": "detection_execution", "intents": ["scan_vulnerabilities"],
            "skills": ["security-scan"], "scope": "current_project", "confidence": 0.95,
            "needs_clarification": False,
        }),
        TimeoutError("planner timeout"),
    ])
    result = asyncio.run(engine.decide("检查所有资产有没有已知漏洞", context_with_history(), db=None, user_id=None))
    assert result["plan"] == [{
        "capability": "scan_vulnerabilities", "parameters": {"target": "项目资产"},
    }]
    assert result["routing"]["planner_fallback"] is True
    assert "默认安全参数" in result["response"]


@pytest.mark.parametrize(("text", "category", "intent"), [
    ("现在一共有哪些资产", "project_query", "asset_list"),
    ("测评做到哪一步了，分数是多少", "project_query", "query_project_status"),
    ("这个项目能过等保吗", "project_query", "query_compliance_readiness"),
    ("先解决哪些主要差距", "project_query", "query_major_gaps"),
    ("给领导汇报一下当前态势", "project_query", "query_executive_summary"),
    ("还有哪些问题没处理", "project_query", "query_findings"),
    ("以前做过哪些检测", "project_query", "query_scan_history"),
    ("当前检测结果和前面的检测结果有什么变化", "project_query", "query_scan_changes"),
    ("对所有资产扫描高危端口", "detection_execution", "scan_ports"),
    ("检查所有资产有没有漏洞", "detection_execution", "scan_vulnerabilities"),
    ("做一次 Web 安全检测", "detection_execution", "scan_web"),
    ("执行服务器基线核查", "detection_execution", "scan_baseline"),
    ("开始当前测评", "flow_operation", "assessment_start"),
    ("进入整改复测", "flow_operation", "assessment_retest"),
    ("重置这次测评", "flow_operation", "assessment_reset"),
    ("生成 HTML 报告", "flow_operation", "report_generate"),
    ("Web 扫描应该怎么发起", "help", "help"),
])
def test_router_unavailable_has_small_explicit_business_fallback(text, category, intent):
    route = AIEngine()._route_failure_fallback(text)
    assert route["category"] == category
    assert route["intents"] == [intent]
    assert route["router_fallback"] is True


def test_router_timeout_uses_business_fallback_and_still_builds_typed_query():
    engine = FakeAIEngine([TimeoutError("router timeout")])
    result = asyncio.run(engine.decide("现在一共有哪些资产", context_with_history(), db=None, user_id=None))
    assert result["plan"] == [{"capability": "list_assets", "parameters": {}}]
    assert result["routing"]["router_fallback"] is True


def test_router_repair_timeout_uses_business_fallback():
    engine = FakeAIEngine([
        json.dumps({"category": "help", "intents": ["web_scan_help"], "confidence": 0.9}),
        TimeoutError("repair timeout"),
    ])
    result = asyncio.run(engine.decide("Web 扫描应该怎么发起", context_with_history(), db=None, user_id=None))
    assert result["routing"]["category"] == "help"
    assert result["routing"]["router_fallback"] is True


def test_router_fallback_does_not_guess_unrelated_or_ambiguous_requests():
    engine = AIEngine()
    assert engine._route_failure_fallback("帮我算房贷") is None
    assert engine._route_failure_fallback("帮我看看") is None
