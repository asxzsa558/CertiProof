import asyncio

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance, TaskInstance
from app.models.document_knowledge import DocumentFile
from app.models.finding import Finding, Judgment
from app.models.organization import Organization
from app.models.project import ComplianceLevel, Project
from app.models.user import User
from app.services.document_control_engine import DocumentControlEngine
from app.services.document_pipeline import (
    DocumentExtractionError,
    _extract_with_retry,
    create_document_batch_run,
    process_document_batch_run,
)


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_batch_extraction_failure_and_missing_material_become_visible_unable_results(monkeypatch):
    extraction_attempts = 0

    async def engine_from_seed(_cls, _db):
        return DocumentControlEngine({
            "documents": {
                "incident_response_plan": {"name": "信息安全事件应急预案", "controls": []},
                "personnel_security": {"name": "人员安全管理制度", "controls": []},
            },
        })

    async def extraction_failed(*_args, **_kwargs):
        nonlocal extraction_attempts
        extraction_attempts += 1
        raise DocumentExtractionError("视觉解析服务超时")

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(DocumentControlEngine, "from_graph", classmethod(engine_from_seed))
    monkeypatch.setattr("app.services.document_pipeline._extract_and_store", extraction_failed)
    monkeypatch.setattr("app.services.document_pipeline.asyncio.sleep", no_wait)

    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            user = User(email="batch@example.test", username="batch", hashed_password="test")
            organization = Organization(name="Batch", code="batch")
            db.add_all([user, organization])
            await db.flush()
            project = Project(
                user_id=user.id,
                organization_id=organization.id,
                name="Batch Project",
                compliance_level=ComplianceLevel.LEVEL_3,
            )
            template = FlowTemplate(name="Batch", compliance_level=3, phases_config=[])
            db.add_all([project, template])
            await db.flush()
            assessment = Assessment(
                project_id=project.id,
                template_id=template.id,
                name="Batch",
                assessment_level=3,
                status="in_progress",
                total_phases=1,
            )
            db.add(assessment)
            await db.flush()
            phase = PhaseInstance(
                assessment_id=assessment.id,
                phase_id="gap_analysis",
                name="差距分析",
                order=1,
                status="active",
            )
            db.add(phase)
            await db.flush()
            emergency = TaskInstance(
                phase_id=phase.id,
                task_type="doc_review",
                name="文档检查：信息安全事件应急预案",
            )
            personnel = TaskInstance(
                phase_id=phase.id,
                task_type="doc_review",
                name="文档检查：人员安全管理制度",
            )
            db.add_all([emergency, personnel])
            await db.flush()
            document = DocumentFile(
                project_id=project.id,
                assessment_id=assessment.id,
                original_name="信息安全事件应急预案（盖章扫描件）.pdf",
                storage_path="unused.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                sha256="a" * 64,
            )
            db.add(document)
            await db.commit()

            batch = await create_document_batch_run(
                db, phase.id, project.id, [document.id], user.id,
            )
            await process_document_batch_run(db, batch)
            await db.refresh(document)
            await db.refresh(emergency)
            await db.refresh(personnel)

            findings = list((await db.execute(select(Finding).order_by(Finding.id))).scalars().all())
            assert document.task_id == emergency.id
            assert document.parse_status == "failed"
            assert document.extraction_summary["attempts"] == 3
            assert "已尝试 3 次" in document.extraction_summary["display_error"]
            assert extraction_attempts == 3
            assert emergency.status == personnel.status == "failed"
            assert emergency.result["analysis"]["status"] == "unable"
            assert "视觉解析服务超时" in emergency.result["error"]
            assert "未提供或未能可靠归类" in personnel.result["error"]
            assert len(findings) == 2
            assert all(finding.judgment == Judgment.NOT_TESTED for finding in findings)
            assert batch.result_summary["classified"][0]["extraction_status"] == "unable"
            assert batch.result_summary["classified"][0]["extraction_attempts"] == 3
            assert "已尝试 3 次" in batch.result_summary["classified"][0]["extraction_error"]
            assert batch.result_summary["missing"] == [{
                "task_id": personnel.id,
                "document_name": "人员安全管理制度",
            }]
        await engine.dispose()

    asyncio.run(run())


def test_transient_extraction_recovers_without_a_false_failure(monkeypatch):
    attempts = 0

    async def flaky_extraction(_db, _run, _document):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise DocumentExtractionError("OCR service timeout")
        return [{"text": "recovered"}], {"page_count": 1}

    async def no_wait(_seconds):
        return None

    async def no_touch(_db, _run):
        return None

    monkeypatch.setattr("app.services.document_pipeline._extract_and_store", flaky_extraction)
    monkeypatch.setattr("app.services.document_pipeline.asyncio.sleep", no_wait)
    monkeypatch.setattr("app.services.document_pipeline._touch_run", no_touch)

    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            run_record = type("Run", (), {"analysis_mode": "standard", "progress": {}})()
            document = DocumentFile(
                project_id=1,
                original_name="恢复成功.pdf",
                storage_path="unused.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                sha256="b" * 64,
            )
            blocks, summary = await _extract_with_retry(db, run_record, document)
            assert blocks == [{"text": "recovered"}]
            assert summary["attempts"] == 2
            assert summary["recovered_after_retry"] is True
            assert attempts == 2
        await engine.dispose()

    asyncio.run(run())


def test_deterministic_extraction_error_is_not_retried(monkeypatch):
    attempts = 0

    async def broken_file(_db, _run, _document):
        nonlocal attempts
        attempts += 1
        raise DocumentExtractionError("文件损坏或格式不支持")

    monkeypatch.setattr("app.services.document_pipeline._extract_and_store", broken_file)

    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            run_record = type("Run", (), {"analysis_mode": "standard", "progress": {}})()
            document = DocumentFile(
                project_id=1,
                original_name="损坏文件.pdf",
                storage_path="unused.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                sha256="c" * 64,
            )
            try:
                await _extract_with_retry(db, run_record, document)
                raise AssertionError("deterministic extraction failure must propagate")
            except DocumentExtractionError as exc:
                assert "文件损坏" in str(exc)
            assert document.extraction_summary["attempts"] == 1
            assert document.extraction_summary["retryable"] is False
            assert attempts == 1
        await engine.dispose()

    asyncio.run(run())
