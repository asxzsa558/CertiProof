from datetime import datetime, timezone
from types import SimpleNamespace

from app.core import secret_box
from app.models.model_config import InferenceRuntime, ProviderType
from app.schemas.model_config import ModelProviderResponse
from app.services import llm_service as llm_module
from app.services import runtime_resources
from app.services.llm_service import LLMService


def test_provider_response_masks_encrypted_key(monkeypatch):
    monkeypatch.setattr(secret_box.settings, "SECRET_KEY", "test-secret-key-with-at-least-32-characters")
    encrypted = secret_box.encrypt_secret("cloud-secret")
    provider = SimpleNamespace(
        id=1,
        name="Cloud",
        provider_type=ProviderType.OPENAI,
        api_base="https://example.test/v1",
        runtime_kind=InferenceRuntime.CLOUD.value,
        api_key=encrypted,
        api_key_configured=True,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    payload = ModelProviderResponse.model_validate(provider).model_dump(mode="json")

    assert payload["api_key_configured"] is True
    assert "api_key" not in payload
    assert secret_box.decrypt_secret(encrypted) == "cloud-secret"


def test_auto_runtime_selects_cloud_on_cpu_and_vllm_on_gpu(monkeypatch):
    service = LLMService()
    monkeypatch.setattr(llm_module, "gpu_available", lambda: False)
    assert service.runtime_preference("auto")[0] == "cloud"
    assert service.runtime_preference("local")[0] == "llama_cpp"

    monkeypatch.setattr(llm_module, "gpu_available", lambda: True)
    assert service.runtime_preference("auto")[0] == "vllm"
    assert service.runtime_preference("local")[0] == "vllm"


def test_resource_recommendation_uses_detected_hardware(monkeypatch):
    monkeypatch.setattr(runtime_resources, "_memory_bytes", lambda: (8 * runtime_resources.GB, 6 * runtime_resources.GB, "test"))
    monkeypatch.setattr(runtime_resources.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(runtime_resources.os, "getloadavg", lambda: (1.0, 1.0, 1.0))
    monkeypatch.setattr(runtime_resources, "gpu_available", lambda: False)

    snapshot = runtime_resources.hardware_snapshot()
    profile, _ = runtime_resources.recommended_profile(snapshot)

    assert profile == "light"
    assert snapshot["memory_percent"] == 25.0

    snapshot["gpu_available"] = True
    assert runtime_resources.recommended_profile(snapshot)[0] == "gpu"


def test_openai_compatible_local_runtime_does_not_require_api_key():
    service = LLMService()
    provider = SimpleNamespace(
        id=9,
        provider_type=ProviderType.CUSTOM,
        runtime_kind=InferenceRuntime.VLLM.value,
        api_key=None,
        api_base="http://vllm:8000/v1",
    )

    adapter = service._get_provider(provider)

    assert adapter.api_key == "local"
