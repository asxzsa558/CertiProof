"""Deep post-deployment checks executed inside the backend container."""

import asyncio
import json

import httpx
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.model_config import ModelConfig
from app.services.llm_service import llm_service


async def check() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT 1"))
        models = list((await db.execute(
            select(ModelConfig).where(ModelConfig.is_active.is_(True)).order_by(
                ModelConfig.is_default.desc(), ModelConfig.priority.asc(), ModelConfig.id.asc()
            )
        )).scalars().all())
        model = next((item for item in models if "chat" in (item.capabilities or [])), None)
        if model is None:
            raise RuntimeError("没有可用的对话模型配置")
        model_result = await llm_service.test_model(db, model.id)
        if not model_result.get("success"):
            raise RuntimeError(model_result.get("error") or "模型结构化输出验收失败")

    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{settings.EMBEDDING_SERVER_URL}/embed",
            json={
                "inputs": ["CertiProof 部署验收"],
                "input_type": "query",
                "dimensions": settings.DOCUMENT_EMBEDDING_DIMENSION,
            },
        )
        response.raise_for_status()
        embedding = response.json()
        vectors = embedding.get("embeddings") or []
        if len(vectors) != 1 or len(vectors[0]) != settings.DOCUMENT_EMBEDDING_DIMENSION:
            raise RuntimeError("向量服务返回维度不正确")

    print(json.dumps({"model": model_result, "embedding": {
        "status": "ready",
        "model": embedding.get("model"),
        "dimension": embedding.get("dimension"),
    }}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(check())
