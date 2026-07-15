import asyncio
import base64
import importlib.util
from pathlib import Path


SERVER_PATH = Path(__file__).resolve().parents[1] / "mcp-servers" / "ocr-server" / "server.py"
SPEC = importlib.util.spec_from_file_location("certiproof_ocr_server_test", SERVER_PATH)
ocr_server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ocr_server)


def _params(**overrides):
    return {
        "image_base64": base64.b64encode(b"test-image").decode(),
        "file_name": "page.png",
        "analysis_mode": "standard",
        "cross_validate": False,
        "prefer_vision": False,
        **overrides,
    }


def _reset_state():
    ocr_server.DOCUMENT_OCR_ENGINE = "auto"
    ocr_server._document_pipeline_error = None
    ocr_server._rapidocr_error = None
    ocr_server._document_pipeline_verified = False
    ocr_server._rapidocr_verified = False


def test_standard_mode_uses_high_confidence_lightweight_ocr_without_vision(monkeypatch):
    _reset_state()
    calls = []

    def rapid(_path):
        calls.append("ocr")
        return [{"type": "text", "text": "制度正文", "confidence": 0.96, "source": "ocr"}]

    def vision(*_args):
        calls.append("vision")
        return []

    monkeypatch.setattr(ocr_server, "_parse_with_rapidocr", rapid)
    monkeypatch.setattr(ocr_server, "_parse_with_paddle_vl", vision)

    result = asyncio.run(ocr_server.document_page_parse(_params()))

    assert result["status"] == "success"
    assert calls == ["ocr"]
    assert result["data"]["models"] == ["RapidOCR-ONNXRuntime"]
    assert result["data"]["cross_validated"] is False


def test_deep_mode_cross_validates_lightweight_and_visual_models(monkeypatch):
    _reset_state()
    monkeypatch.setattr(
        ocr_server,
        "_parse_with_rapidocr",
        lambda _path: [{"type": "text", "text": "审计日志", "confidence": 0.91, "source": "ocr"}],
    )
    monkeypatch.setattr(
        ocr_server,
        "_parse_with_paddle_vl",
        lambda *_args: [{"content": "审计日志", "label": "text", "confidence": 0.88}],
    )

    result = asyncio.run(ocr_server.document_page_parse(_params(analysis_mode="deep", cross_validate=True)))

    assert result["status"] == "success"
    assert result["data"]["models"] == ["PaddleOCR-VL-1.6", "RapidOCR-ONNXRuntime"]
    assert result["data"]["cross_validated"] is True
    assert {block["source"] for block in result["data"]["blocks"]} == {"ocr", "vision"}


def test_visual_failure_returns_ocr_fallback_with_explicit_warning(monkeypatch):
    _reset_state()
    monkeypatch.setattr(
        ocr_server,
        "_parse_with_rapidocr",
        lambda _path: [{"type": "text", "text": "应急预案", "confidence": 0.93, "source": "ocr"}],
    )

    def fail_vision(*_args):
        raise RuntimeError("visual backend unavailable")

    monkeypatch.setattr(ocr_server, "_parse_with_paddle_vl", fail_vision)

    result = asyncio.run(ocr_server.document_page_parse(_params(prefer_vision=True)))

    assert result["status"] == "success"
    assert result["data"]["fallback"] is True
    assert "visual backend unavailable" in result["data"]["warnings"][0]
