import asyncio
import os
import threading
import time
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


MODEL_NAME = os.getenv("DOCUMENT_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
MODEL_DIMENSION = int(os.getenv("DOCUMENT_EMBEDDING_DIMENSION", "1024"))
MODEL_CACHE_DIR = os.getenv("EMBEDDING_CACHE_DIR", "/models")
MODEL_THREADS = max(1, int(os.getenv("EMBEDDING_THREADS", "2")))
MAX_INPUTS = max(1, int(os.getenv("EMBEDDING_MAX_INPUTS", "64")))
MAX_TOTAL_CHARS = max(1000, int(os.getenv("EMBEDDING_MAX_TOTAL_CHARS", "200000")))

app = FastAPI(title="CertiProof Local Embedding Service", version="1.0")
_model = None
_model_error: str | None = None
_model_lock = threading.Lock()


class EmbedRequest(BaseModel):
    inputs: list[str] = Field(min_length=1)
    input_type: Literal["query", "passage"] = "passage"
    dimensions: int = MODEL_DIMENSION


def _load_model():
    global _model, _model_error
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from fastembed import TextEmbedding

            _model = TextEmbedding(
                model_name=MODEL_NAME,
                cache_dir=MODEL_CACHE_DIR,
                threads=MODEL_THREADS,
                providers=["CPUExecutionProvider"],
            )
            _model_error = None
            return _model
        except Exception as exc:
            _model_error = str(exc)
            raise


def _embed(inputs: list[str], input_type: str) -> list[list[float]]:
    model = _load_model()
    values = [str(value or "").strip() for value in inputs]
    if "e5" in MODEL_NAME.lower():
        values = [f"{input_type}: {value}" for value in values]
    vectors = [vector.tolist() for vector in model.embed(values, batch_size=min(16, len(values)))]
    if len(vectors) != len(values) or any(len(vector) != MODEL_DIMENSION for vector in vectors):
        raise RuntimeError(f"模型必须返回 {MODEL_DIMENSION} 维向量")
    return vectors


@app.get("/health")
async def health():
    return {
        "status": "ready" if _model is not None else ("failed" if _model_error else "lazy"),
        "model": MODEL_NAME,
        "dimension": MODEL_DIMENSION,
        "loaded": _model is not None,
        "error": _model_error,
        "runtime": "FastEmbed-ONNXRuntime",
    }


@app.post("/embed")
async def embed(request: EmbedRequest):
    if request.dimensions != MODEL_DIMENSION:
        raise HTTPException(status_code=400, detail=f"仅支持 {MODEL_DIMENSION} 维向量")
    if len(request.inputs) > MAX_INPUTS:
        raise HTTPException(status_code=400, detail=f"单次最多处理 {MAX_INPUTS} 段文本")
    if any(not str(value or "").strip() for value in request.inputs):
        raise HTTPException(status_code=400, detail="向量输入不得为空")
    if sum(len(str(value)) for value in request.inputs) > MAX_TOTAL_CHARS:
        raise HTTPException(status_code=400, detail="单次文本总长度超过限制")
    started = time.monotonic()
    try:
        vectors = await asyncio.to_thread(_embed, request.inputs, request.input_type)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"本地向量模型不可用: {exc}") from exc
    return {
        "status": "success",
        "model": MODEL_NAME,
        "dimension": MODEL_DIMENSION,
        "runtime": "FastEmbed-ONNXRuntime",
        "embeddings": vectors,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
