import asyncio
import importlib.util
from pathlib import Path

from app.services.llm_service import llm_service


SERVER_PATH = Path(__file__).resolve().parents[1] / "mcp-servers" / "embedding-server" / "server.py"
SPEC = importlib.util.spec_from_file_location("certiproof_embedding_server_test", SERVER_PATH)
embedding_server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(embedding_server)


class _Vector:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


def test_local_e5_service_uses_retrieval_prefix_and_expected_dimension(monkeypatch):
    seen = []

    class Model:
        def embed(self, values, batch_size):
            seen.extend(values)
            assert batch_size == 1
            return [_Vector([0.0] * embedding_server.MODEL_DIMENSION)]

    monkeypatch.setattr(embedding_server, "_load_model", lambda: Model())

    vectors = embedding_server._embed(["安全审计职责"], "query")

    assert seen == ["query: 安全审计职责"]
    assert len(vectors[0]) == 1024


def test_llm_service_uses_local_embedding_when_no_external_model(monkeypatch):
    async def no_models(_db, _capability):
        return []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "intfloat/multilingual-e5-large",
                "runtime": "FastEmbed-ONNXRuntime",
                "embeddings": [[0.0] * 1024],
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, json):
            assert json["input_type"] == "passage"
            return Response()

    monkeypatch.setattr(llm_service, "get_available_models", no_models)
    monkeypatch.setattr("httpx.AsyncClient", Client)

    result = asyncio.run(llm_service.embed_with_fallback(None, ["制度正文"], 1024))

    assert result["provider"] == "FastEmbed-ONNXRuntime"
    assert len(result["embeddings"][0]) == 1024
