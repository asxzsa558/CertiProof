import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from app.api.assessments import _sync_document_gap_findings
from app.services.document_control_engine import DocumentControlEngine
from app.services.document_pipeline import _visual_coverage_state, build_retest_comparison
from app.services.llm_service import llm_service


LIBRARY_PATH = Path(__file__).resolve().parents[1] / "reference" / "compliance" / "document_controls.yaml"


def _engine():
    return DocumentControlEngine(yaml.safe_load(LIBRARY_PATH.read_text(encoding="utf-8")))


def _analysis():
    return {
        "type": "document_control_analysis",
        "status": "partial",
        "controls": [{
            "id": "C1",
            "title": "职责与执行",
            "points": [
                {"uid": "R1", "id": "P1", "text": "明确责任人", "status": "partial", "evidence": [{"text": "安全员负责审计", "confidence": 0.95}]},
                {"uid": "R2", "id": "P2", "text": "保留审计记录", "status": "partial", "evidence": [{"text": "制度写明无需留存", "confidence": 0.9}]},
            ],
        }],
    }


def test_llm_only_judges_evidence_and_rule_engine_aggregates_confidence(monkeypatch):
    async def review(**kwargs):
        assert kwargs["max_tokens"] == 4096
        return {"content": json.dumps([
            {"control_id": "C1", "point_id": "P1", "decision": "pass", "confidence": 0.92, "reason": "职责明确"},
            {"control_id": "C1", "point_id": "P2", "decision": "contradict", "confidence": 0.88, "reason": "明确拒绝留存"},
        ], ensure_ascii=False)}

    monkeypatch.setattr(llm_service, "chat_with_fallback", review)
    result = asyncio.run(_engine().review_with_llm(None, 1, _analysis()))

    assert result["evidence_engine"] == "hybrid"
    assert result["status"] == "partial"
    assert result["confidence"] == 0.9
    assert result["controls"][0]["points"][1]["contradiction"] is True


def test_incomplete_model_judgment_becomes_unable(monkeypatch):
    async def review(**_kwargs):
        return {"content": '[{"control_id":"C1","point_id":"P1","decision":"pass","reason":"缺少置信度"}]'}

    monkeypatch.setattr(llm_service, "chat_with_fallback", review)
    result = asyncio.run(_engine().review_with_llm(None, 1, _analysis()))

    assert result["status"] == "unable"
    assert result["confidence"] == 0


def test_truncated_model_judgment_is_reported_as_unable(monkeypatch):
    async def review(**_kwargs):
        return {"content": '[{"control_id":"C1"', "finish_reason": "length"}

    monkeypatch.setattr(llm_service, "chat_with_fallback", review)
    result = asyncio.run(_engine().review_with_llm(None, 1, _analysis()))

    assert result["status"] == "unable"
    assert "输出被截断" in result["message"]
    assert "长度上限" in result["llm_review_error"]


def test_llm_fallback_rejects_invalid_structured_response(monkeypatch):
    models = [
        SimpleNamespace(id=1, provider_id=1, model_name="broken", display_name="Broken"),
        SimpleNamespace(id=2, provider_id=2, model_name="valid", display_name="Valid"),
    ]
    calls = []

    class Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(is_active=True)

    class DB:
        async def execute(self, *_args, **_kwargs):
            return Result()

    class Adapter:
        def __init__(self, model_name):
            self.model_name = model_name

        async def chat(self, *_args, **_kwargs):
            calls.append(self.model_name)
            content = "not-json" if self.model_name == "broken" else '{"decisions": []}'
            return {"content": content, "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    async def available(*_args, **_kwargs):
        return models

    async def usage(**_kwargs):
        return None

    monkeypatch.setattr(llm_service, "get_available_models", available)
    monkeypatch.setattr(llm_service, "_get_provider", lambda _provider: Adapter(models[len(calls)].model_name))
    monkeypatch.setattr(llm_service, "record_usage", usage)

    result = asyncio.run(llm_service._chat_with_fallback_impl(
        DB(),
        1,
        [{"role": "user", "content": "test"}],
        models=models,
        response_validator=lambda response: _engine()._parse_llm_json(response["content"]),
    ))

    assert calls == ["broken", "valid"]
    assert result["model_name"] == "valid"


def test_unreliable_retest_never_claims_fixed_or_new_gaps():
    previous = {
        "status": "partial",
        "coverage": 0.4,
        "gap_items": [{"uid": "R1", "reason": "缺少责任人"}],
    }
    current = {
        "status": "unable",
        "coverage": 0.8,
        "gap_items": [],
    }

    comparison = build_retest_comparison(previous, current)

    assert comparison["status"] == "unable"
    assert comparison["comparison_reliable"] is False
    assert comparison["fixed_gaps"] == []
    assert comparison["new_gaps"] == []
    assert comparison["remaining_gaps"] == ["缺少责任人"]


def test_visual_failure_is_only_fatal_when_native_and_ocr_coverage_are_insufficient():
    native = [{"text": "信息安全管理制度规定责任、审批、审计、留痕、复核和持续改进。" * 3}]

    native_fallback = _visual_coverage_state(native, 3, 0, ["PaddleOCR-VL unavailable"])
    ocr_fallback = _visual_coverage_state([], 3, 3, ["PaddleOCR-VL unavailable"])
    missing_scan_page = _visual_coverage_state([], 3, 2, ["page-2 OCR timeout"])

    assert native_fallback == {"visual_required": False, "visual_incomplete": False, "visual_degraded": True}
    assert ocr_fallback == {"visual_required": True, "visual_incomplete": False, "visual_degraded": True}
    assert missing_scan_page == {"visual_required": True, "visual_incomplete": True, "visual_degraded": True}


def test_unable_analysis_creates_retriable_blocker_without_claiming_noncompliance():
    added = []

    class Result:
        def scalar_one_or_none(self):
            return None

    class DB:
        async def get(self, _model, run_id):
            return SimpleNamespace(id=run_id)

        async def execute(self, *_args, **_kwargs):
            return Result()

        def add(self, item):
            added.append(item)

        async def flush(self):
            added[0].id = 9

        async def commit(self):
            return None

    result = asyncio.run(_sync_document_gap_findings(
        DB(),
        project_id=1,
        task=SimpleNamespace(id=2, name="文档检查：信息安全事件应急预案"),
        analysis={"type": "document_control_analysis", "status": "unable", "run_id": 3},
        user_id=4,
    ))

    assert result["analysis_blocker"] is True
    assert result["created_or_updated"] == 1
    assert result["fixed"] == 0
    finding = added[0]
    assert finding.judgment.value == "not_tested"
    assert finding.status.value == "open"
    assert finding.clause_id == "DOC-TASK-2-ANALYSIS-UNABLE"
