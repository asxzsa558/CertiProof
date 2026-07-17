import asyncio
from pathlib import Path

import yaml

from app.services.document_control_engine import DocumentControlEngine
from app.services.llm_service import llm_service


LIBRARY_PATH = Path(__file__).resolve().parents[1] / "reference" / "compliance" / "document_controls.yaml"


def _engine():
    return DocumentControlEngine(yaml.safe_load(LIBRARY_PATH.read_text(encoding="utf-8")))


def test_llm_can_classify_clear_content_when_filename_is_nonstandard(monkeypatch):
    async def classify(**_kwargs):
        return {
            "content": (
                '<think>正文描述了安全委员会和组织职责</think>'
                '{"primary_key":"security_org_setup","confidence":0.93,'
                '"reason":"正文明确描述信息安全组织设置及职责"}'
            )
        }

    monkeypatch.setattr(llm_service, "chat_with_fallback", classify)
    engine = _engine()
    blocks = [{"type": "text", "page": 2, "text": "公司设立安全委员会，明确负责人、成员和职责分工。"}]

    result = asyncio.run(engine.classify_with_llm(None, 1, "A-0427.docx", blocks))

    assert result["status"] == "classified"
    assert result["document_name"] == "信息安全管理机构设置文件"
    assert result["naming_status"] == "filename_warning"
    assert result["classifier"] == "hybrid"


def test_model_failure_keeps_rule_result_and_reports_degradation(monkeypatch):
    async def fail(**_kwargs):
        raise RuntimeError("classification model unavailable")

    monkeypatch.setattr(llm_service, "chat_with_fallback", fail)
    engine = _engine()
    blocks = [{"type": "text", "page": 1, "text": "普通项目沟通材料。"}]

    result = asyncio.run(engine.classify_with_llm(None, 1, "未命名材料.docx", blocks))

    assert result["status"] == "unclassified"
    assert result["classifier"] == "rule_fallback"
    assert "classification model unavailable" in result["classification_warning"]


def test_exact_strategy_title_wins_over_incidental_organization_alias():
    engine = _engine()
    blocks = [
        {"type": "text", "page": None, "text": "信息安全策略文件"},
        {"type": "text", "page": None, "text": "企业等保三级自查制度文件"},
        {"type": "heading", "page": None, "text": "1. 目的与适用范围"},
        {"type": "text", "page": None, "text": "本文件由信息安全委员会归口管理。"},
    ]

    result = engine.classify_blocks("网络与信息安全总体策略V2.docx", blocks)

    assert result["status"] == "classified"
    assert result["document_key"] == "security_strategy"
