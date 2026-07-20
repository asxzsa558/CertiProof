import asyncio
from types import SimpleNamespace

from app.core.config import settings
from app.models.model_config import ProviderType
from app.services import llm_service as llm_module
from app.services.llm_service import LLMService, OllamaProvider


def test_ollama_payload_maps_shared_options_to_native_api():
    payload = OllamaProvider._build_chat_payload(
        [{"role": "user", "content": "test"}],
        "qwen3:14b",
        max_tokens=512,
        temperature=0,
        top_p=0.8,
        response_format={"type": "json_object"},
    )

    assert payload["model"] == "qwen3:14b"
    assert payload["think"] is False
    assert payload["format"] == "json"
    assert payload["options"] == {"num_predict": 512, "temperature": 0, "top_p": 0.8}
    assert "max_tokens" not in payload
    assert "response_format" not in payload


def test_ollama_payload_accepts_json_schema_and_explicit_thinking():
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    payload = OllamaProvider._build_chat_payload(
        [],
        "qwen3:14b",
        think=True,
        response_format={"type": "json_schema", "json_schema": {"schema": schema}},
    )

    assert payload["think"] is True
    assert payload["format"] == schema


def test_local_model_uses_local_timeout_floor(monkeypatch):
    service = LLMService()
    captured = {}

    class Result:
        @staticmethod
        def scalars():
            return Result()

        @staticmethod
        def all():
            return [SimpleNamespace(provider_type=ProviderType.OLLAMA, runtime_kind="ollama")]

    class DB:
        async def execute(self, _query):
            return Result()

    async def candidates(_db, _task_type):
        return [SimpleNamespace(provider_id=1)]

    async def execute(*_args, **_kwargs):
        return {"content": "ok"}

    async def resources(_db):
        return {"limits": {"model": 1}}

    real_wait_for = asyncio.wait_for

    async def wait_for(awaitable, timeout):
        captured["timeout"] = timeout
        return await real_wait_for(awaitable, timeout=1)

    monkeypatch.setattr(service, "_candidate_models", candidates)
    monkeypatch.setattr(service, "_chat_with_fallback_impl", execute)
    monkeypatch.setattr(llm_module, "resource_runtime_status", resources)
    monkeypatch.setattr(asyncio, "wait_for", wait_for)

    result = asyncio.run(service.chat_with_fallback(DB(), 1, [], timeout=45))

    assert result == {"content": "ok"}
    assert captured["timeout"] == max(45, settings.OLLAMA_REQUEST_TIMEOUT_SECONDS)
