import asyncio
import hashlib
import tempfile
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance, TaskInstance
from app.models.document_knowledge import DocumentAnalysisRun, DocumentBlock, DocumentFile, DocumentRunFile
from app.models.finding import Finding, Judgment
from app.models.project import ComplianceLevel, Project
from app.services.document_control_engine import DocumentControlEngine
from app.services.document_pipeline import create_document_batch_run, process_document_batch_run, process_document_run
from app.services.file_storage import file_storage
from app.services.knowledge_graph import knowledge_graph


LIBRARY = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "reference" / "compliance" / "document_controls.yaml").read_text(encoding="utf-8")
)


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    original_base_path = file_storage.base_path
    original_from_graph = DocumentControlEngine.from_graph
    original_graph_sync = knowledge_graph.sync_document_structure
    original_graph_expand = knowledge_graph.expand_block_ids

    async def engine_from_seed(cls, db):
        return cls(LIBRARY)

    async def no_graph(*args, **kwargs):
        return None

    async def seed_blocks(_db, block_ids, limit=12):
        return list(block_ids)[:limit]

    DocumentControlEngine.from_graph = classmethod(engine_from_seed)
    knowledge_graph.sync_document_structure = no_graph
    knowledge_graph.expand_block_ids = seed_blocks
    try:
        with tempfile.TemporaryDirectory() as directory:
            file_storage.base_path = Path(directory)
            path = Path(directory) / "制度包/安全事件管理制度V2-2026.txt"
            path.parent.mkdir()
            content = "安全事件管理制度\n安全事件应分级、报告、处置、复盘并持续改进。"
            path.write_text(content, encoding="utf-8")

            async with sessions() as db:
                project = Project(user_id=1, name="批量文档回归", compliance_level=ComplianceLevel.LEVEL_3)
                template = FlowTemplate(name="四阶段", compliance_level=3, phases_config=[])
                db.add_all([project, template])
                await db.flush()
                assessment = Assessment(project_id=project.id, template_id=template.id, name="回归测评")
                db.add(assessment)
                await db.flush()
                phase = PhaseInstance(
                    assessment_id=assessment.id,
                    phase_id="gap_analysis",
                    name="差距分析",
                    order=1,
                )
                db.add(phase)
                await db.flush()
                task = TaskInstance(
                    phase_id=phase.id,
                    task_type="doc_review",
                    name="文档检查：安全事件管理制度",
                )
                db.add(task)
                await db.flush()
                document_file = DocumentFile(
                    project_id=project.id,
                    assessment_id=assessment.id,
                    original_name="制度包/安全事件管理制度V2-2026.txt",
                    storage_path=str(path.relative_to(file_storage.base_path)),
                    mime_type="text/plain",
                    size_bytes=len(content.encode()),
                    sha256=hashlib.sha256(content.encode()).hexdigest(),
                )
                db.add(document_file)
                await db.commit()

                run = await create_document_batch_run(
                    db,
                    phase.id,
                    project.id,
                    [document_file.id],
                    user_id=0,
                )
                await process_document_batch_run(db, run)
                await db.refresh(document_file)
                await db.refresh(task)

                assert run.status == "completed"
                assert document_file.task_id == task.id
                assert document_file.classification["document_name"] == "安全事件管理制度"
                assert document_file.classification["naming_status"] == "matched"
                assert task.status == "in_progress"
                queued = (await db.execute(select(DocumentAnalysisRun).where(
                    DocumentAnalysisRun.task_id == task.id,
                    DocumentAnalysisRun.status == "queued",
                ))).scalar_one()
                linked_file = (await db.execute(select(DocumentRunFile.document_file_id).where(
                    DocumentRunFile.analysis_run_id == queued.id,
                ))).scalar_one()
                assert linked_file == document_file.id

                await process_document_run(db, queued)
                assert queued.status == "completed", "analysis execution should complete even when its conclusion is unable"
                assert queued.result_summary["status"] == "unable", "missing evidence model must be unable, never a false pass"
                assert task.status == "failed", "unable document conclusions must block assessment progress and report generation"
                assert task.result["status"] == "unable"
                findings = (await db.execute(select(Finding))).scalars().all()
                assert len(findings) == 1
                assert findings[0].judgment == Judgment.NOT_TESTED
                assert findings[0].source_type == "document"
                active_blocks = (await db.execute(select(DocumentBlock).where(
                    DocumentBlock.document_file_id == document_file.id,
                    DocumentBlock.is_active.is_(True),
                ))).scalars().all()
                assert active_blocks and {block.analysis_run_id for block in active_blocks} == {queued.id}
    finally:
        file_storage.base_path = original_base_path
        DocumentControlEngine.from_graph = original_from_graph
        knowledge_graph.sync_document_structure = original_graph_sync
        knowledge_graph.expand_block_ids = original_graph_expand
        await engine.dispose()

    print("gap batch orchestration check passed")


if __name__ == "__main__":
    asyncio.run(main())
