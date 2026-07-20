import asyncio
from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from app.models.model_config import ProviderType
from app.services import llm_service as llm_module
from app.services.llm_service import LLMService


class ScanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["nikto_scan"]
    target: str


class Result:
    def __init__(self, provider):
        self.provider = provider

    def scalars(self):
        return self

    def all(self):
        return [self.provider]

    def scalar_one_or_none(self):
        return self.provider


class DB:
    def __init__(self, provider):
        self.provider = provider

    async def execute(self, _query):
        return Result(self.provider)


def _model(model_id, name):
    return SimpleNamespace(
        id=model_id,
        provider_id=1,
        model_name=name,
        display_name=name,
    )


def _response(content, **extra):
    return {
        "content": content,
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        **extra,
    }


def _service(monkeypatch, provider_type, models, adapter):
    service = LLMService()
    provider = SimpleNamespace(id=1, name="Test", provider_type=provider_type, is_active=True)

    async def candidates(_db, _task_type):
        return models

    async def usage(**_kwargs):
        return None

    async def resources(_db):
        return {"limits": {"model": 2}}

    monkeypatch.setattr(service, "_candidate_models", candidates)
    monkeypatch.setattr(service, "_get_provider", lambda _provider: adapter)
    monkeypatch.setattr(service, "record_usage", usage)
    monkeypatch.setattr(llm_module, "resource_runtime_status", resources)
    return service, DB(provider)


def test_structured_chain_retries_schema_and_business_failures(monkeypatch):
    calls = []
    responses = [
        _response("not-json"),
        _response('{"tool":"nikto_scan","target":"203.0.113.10"}'),
        _response('{"tool":"nikto_scan","target":"121.40.95.31"}'),
    ]

    class Adapter:
        async def chat(self, messages, _model_name, **kwargs):
            calls.append((messages, kwargs))
            return responses.pop(0)

    service, db = _service(monkeypatch, ProviderType.CUSTOM, [_model(1, "cloud")], Adapter())

    def business(value):
        if value.target != "121.40.95.31":
            raise ValueError("目标不属于当前项目")

    result = asyncio.run(service.chat_with_fallback(
        db,
        1,
        [{"role": "user", "content": "扫描项目资产"}],
        response_model=ScanDecision,
        business_validator=business,
    ))

    assert result["validated"] == {"tool": "nikto_scan", "target": "121.40.95.31"}
    assert result["attempt"] == 3
    assert len(calls) == 3
    assert all(call[1]["response_format"] == {"type": "json_object"} for call in calls)
    assert "上一次输出未通过校验" in calls[1][0][-1]["content"]


def test_structured_chain_falls_back_after_three_failed_attempts(monkeypatch):
    calls = []

    class Adapter:
        async def chat(self, _messages, model_name, **_kwargs):
            calls.append(model_name)
            if model_name == "broken":
                return _response("", thinking_only=True)
            return _response('{"tool":"nikto_scan","target":"121.40.95.31"}')

    service, db = _service(
        monkeypatch,
        ProviderType.OLLAMA,
        [_model(1, "broken"), _model(2, "working")],
        Adapter(),
    )

    result = asyncio.run(service.chat_with_fallback(
        db,
        1,
        [{"role": "user", "content": "test"}],
        response_model=ScanDecision,
    ))

    assert calls == ["broken", "broken", "broken", "working"]
    assert result["model_name"] == "working"
    assert result["fallback_used"] is True


def test_structured_chain_returns_explicit_failure(monkeypatch):
    class Adapter:
        async def chat(self, _messages, _model_name, **_kwargs):
            return _response('{"tool":"unknown","target":""}')

    service, db = _service(monkeypatch, ProviderType.CUSTOM, [_model(1, "broken")], Adapter())

    with pytest.raises(ValueError, match="所有模型均未生成有效结果.*第 3 次"):
        asyncio.run(service.chat_with_fallback(
            db,
            1,
            [{"role": "user", "content": "test"}],
            response_model=ScanDecision,
        ))


def test_provider_formats_keep_schema_validation_portable():
    schema = ScanDecision.model_json_schema()

    ollama = LLMService._structured_response_format(ProviderType.OLLAMA, schema, "ScanDecision")
    openai_first = LLMService._structured_response_format(ProviderType.OPENAI, schema, "ScanDecision", 1)
    openai_retry = LLMService._structured_response_format(ProviderType.OPENAI, schema, "ScanDecision", 2)
    custom = LLMService._structured_response_format(ProviderType.CUSTOM, schema, "ScanDecision")
    anthropic = LLMService._structured_response_format(ProviderType.ANTHROPIC, schema, "ScanDecision")

    assert ollama["json_schema"]["schema"] == schema
    assert openai_first["type"] == "json_schema"
    assert openai_retry == {"type": "json_object"}
    assert custom == {"type": "json_object"}
    assert anthropic is None


def test_pydantic_failure_detail_does_not_echo_model_input():
    with pytest.raises(Exception) as caught:
        ScanDecision.model_validate({"tool": "unknown", "target": {"password": "never-log-this"}})

    detail = LLMService._validation_error_detail(caught.value)

    assert "never-log-this" not in detail
    assert "tool" in detail
