import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.document_knowledge import DocumentBlock
from app.services.document_control_engine import DocumentControlEngine
from app.services.knowledge_graph import knowledge_graph
from app.services.llm_service import llm_service


async def main():
    async with AsyncSessionLocal() as db:
        block = (await db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.is_active.is_(True), DocumentBlock.text != "")
            .order_by(DocumentBlock.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if not block:
            raise RuntimeError("没有可用于混合检索烟测的文档块")

        passage = await llm_service.embed_with_fallback(
            db,
            [block.text[:4000]],
            settings.DOCUMENT_EMBEDDING_DIMENSION,
            input_type="passage",
        )
        block.embedding = passage["embeddings"][0]
        block.embedding_model = passage["model"]
        await db.commit()

        query = await llm_service.embed_with_fallback(
            db,
            [block.text[:500]],
            settings.DOCUMENT_EMBEDDING_DIMENSION,
            input_type="query",
        )
        engine = await DocumentControlEngine.from_graph(db)
        candidates = await engine._vector_candidates(db, block.analysis_run_id, query["embeddings"][0])
        if not candidates or candidates[0]["block_id"] != block.id:
            raise RuntimeError("pgvector 未召回刚写入的文档块")
        exact = engine._exact_candidates(
            {"evidence_keywords": [block.text[: min(8, len(block.text))]]},
            [candidates[0]],
        )
        merged = engine._merge_candidates(exact, candidates)
        if set(merged[0]["retrieval_sources"]) != {"exact", "vector"}:
            raise RuntimeError("关键词与向量检索结果未正确融合")

        graph_rows = await knowledge_graph._cypher_rows(db, f"""
            MATCH (b:Block {{block_id: {int(block.id)}}})
            RETURN b.project_id, b.assessment_id, b.run_id, b.file_id
        """, ("project_id", "assessment_id", "run_id", "file_id"))
        if not graph_rows:
            raise RuntimeError("Apache AGE 中缺少对应文档块")
        graph = graph_rows[0]
        expected = {
            "project_id": block.project_id,
            "assessment_id": block.assessment_id,
            "run_id": block.analysis_run_id,
            "file_id": block.document_file_id,
        }
        if graph != expected:
            raise RuntimeError(f"图谱归属不一致: expected={expected}, actual={graph}")

        candidate = candidates[0]
        print({
            "status": "passed",
            "model": passage["model"],
            "dimension": len(passage["embeddings"][0]),
            "retrieval_sources": merged[0]["retrieval_sources"],
            "file_name": candidate["file_name"],
            "page": candidate["page"],
            "section": candidate["section"],
            "graph_scope": graph,
        })


if __name__ == "__main__":
    asyncio.run(main())
