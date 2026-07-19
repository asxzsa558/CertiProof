from types import SimpleNamespace

from app.services.verification_service import controlled_remediation_plan


def finding(**overrides):
    values = {
        "source_type": "technical",
        "source_key": "scan_ssl",
        "scope_key": "example.com:443",
        "description": "HSTS: not offered",
        "clause_name": "SSL/TLS 检测",
        "clause_id": "TECH-SSL",
        "remediation_suggestion": "修复 TLS 配置",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_tls_guidance_has_prerequisite_verification_and_rollback():
    plan = controlled_remediation_plan(finding())
    assert plan["steps"]
    assert "重新执行" in plan["verification"]
    assert plan["rollback"]
    assert plan["requires_context"] is True


def test_tool_timeout_is_a_verification_blocker_not_a_clean_result():
    plan = controlled_remediation_plan(finding(
        source_key="scan_vulnerabilities",
        description="nuclei 扫描超过 180 秒仍未完成，已停止",
    ))
    assert "不是“未发现风险”" in plan["applicability"]
    assert "完整执行" in plan["verification"]


def test_document_guidance_requires_full_category_reanalysis():
    plan = controlled_remediation_plan(finding(
        source_type="document",
        source_key="DOC-SMP-001",
        description="证据不完整，未明确责任主体",
        clause_name="职责与执行要求",
    ))
    assert "责任主体" in "".join(plan["steps"])
    assert "所有检查点" in plan["verification"]
    assert plan["requires_context"] is False
