import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.mcp.gateway_client import MCPGatewayClient
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance, TaskInstance
from app.models.document_knowledge import DocumentAnalysisRun, DocumentBlock, DocumentFile
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.models.verification import VerificationRun, VerificationRunStatus
from app.services.document_pipeline import (
    _extract_and_store,
    cancel_document_run,
    recover_incomplete_document_runs,
)
from app.services.flow_engine import get_flow_engine
from app.services.assessment_task_queue import _aggregate
from app.services.verification_queue import WORKER_ID, _renew_verification_lease


async def _records(db):
    user = User(email="task-control@example.test", username="task-control", hashed_password="test")
    organization = Organization(name="Task Control", code="task-control")
    db.add_all([user, organization])
    await db.flush()
    project = Project(user_id=user.id, organization_id=organization.id, name="Task Control")
    template = FlowTemplate(name="Task Control", compliance_level=3, phases_config=[])
    db.add_all([project, template])
    await db.flush()
    assessment = Assessment(project_id=project.id, template_id=template.id, name="Task Control", assessment_level=3)
    db.add(assessment)
    await db.flush()
    phase = PhaseInstance(assessment_id=assessment.id, phase_id="gap_analysis", name="差距分析", order=1)
    db.add(phase)
    await db.flush()
    task = TaskInstance(phase_id=phase.id, task_type="doc_review", name="文档检查：信息安全管理制度", status="in_progress")
    db.add(task)
    await db.flush()
    return user, project, assessment, phase, task


def test_document_cancel_wins_and_expired_runs_recover_from_checkpoint():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            user, project, assessment, phase, task = await _records(db)
            cancelled = DocumentAnalysisRun(
                project_id=project.id,
                assessment_id=assessment.id,
                phase_id=phase.id,
                task_id=task.id,
                requested_by=user.id,
                status="running",
                progress={"stage": "fusion", "percent": 25},
            )
            recoverable = DocumentAnalysisRun(
                project_id=project.id,
                assessment_id=assessment.id,
                phase_id=phase.id,
                requested_by=user.id,
                run_kind="batch",
                status="running",
                attempt_count=1,
                lease_expires_at=datetime.utcnow() - timedelta(minutes=1),
                progress={"stage": "classification", "percent": 40},
            )
            db.add_all([cancelled, recoverable])
            await db.commit()

            await cancel_document_run(db, cancelled, "测试停止")
            with pytest.raises(ValueError, match="stopped"):
                await get_flow_engine(db).complete_task(task.id, {"late": True})
            assert cancelled.status == "cancelled"
            assert task.status == "failed"

            assert await recover_incomplete_document_runs(db) == 1
            await db.refresh(recoverable)
            assert recoverable.status == "queued"
            assert recoverable.progress["percent"] == 40

        await engine.dispose()

    asyncio.run(run())


def test_same_document_run_reuses_completed_file_blocks():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            user, project, assessment, phase, task = await _records(db)
            analysis_run = DocumentAnalysisRun(
                project_id=project.id,
                assessment_id=assessment.id,
                phase_id=phase.id,
                task_id=task.id,
                requested_by=user.id,
                status="running",
            )
            document = DocumentFile(
                project_id=project.id,
                assessment_id=assessment.id,
                task_id=task.id,
                original_name="制度.txt",
                storage_path="missing-is-not-read.txt",
                mime_type="text/plain",
                size_bytes=10,
                sha256="a" * 64,
                parse_status="parsed",
                extraction_summary={"page_count": 1, "analysis_mode": "standard"},
            )
            db.add_all([analysis_run, document])
            await db.flush()
            db.add(DocumentBlock(
                project_id=project.id,
                assessment_id=assessment.id,
                analysis_run_id=analysis_run.id,
                document_file_id=document.id,
                ordinal=0,
                block_type="text",
                source="native",
                source_confidence=1,
                text="已完成内容",
                content_sha256="b" * 64,
            ))
            await db.commit()

            blocks, summary = await _extract_and_store(db, analysis_run, document)
            assert blocks[0]["text"] == "已完成内容"
            assert summary["cache_hit"] is True

        await engine.dispose()

    asyncio.run(run())


def test_gateway_cancels_remote_task_when_caller_is_cancelled(monkeypatch):
    async def run():
        client = MCPGatewayClient("http://gateway.invalid")
        cancelled = []

        async def call_async(_tool, _params):
            return "remote-task"

        async def get_progress(_tool, _task_id):
            await asyncio.sleep(60)

        async def cancel(tool, task_id):
            cancelled.append((tool, task_id))
            return {"status": "cancelled"}

        monkeypatch.setattr(client, "call_async", call_async)
        monkeypatch.setattr(client, "get_progress", get_progress)
        monkeypatch.setattr(client, "cancel", cancel)
        task = asyncio.create_task(client.call_with_progress("nmap_scan", {"target": "192.0.2.1"}))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled == [("nmap_scan", "remote-task")]

    asyncio.run(run())


def test_gateway_keeps_running_after_transient_progress_disconnect(monkeypatch):
    async def run():
        client = MCPGatewayClient("http://gateway.invalid")
        attempts = 0
        progress_events = []

        async def call_async(_tool, _params):
            return "remote-task"

        async def get_progress(_tool, _task_id):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise Exception("temporary gateway disconnect")
            return {"status": "completed", "progress": 100, "alive": False}

        async def get_result(_tool, _task_id):
            return {"status": "success", "data": {"findings": []}}

        monkeypatch.setattr(client, "call_async", call_async)
        monkeypatch.setattr(client, "get_progress", get_progress)
        monkeypatch.setattr(client, "get_result", get_result)
        result = await client.call_with_progress(
            "nuclei_scan",
            {"target": "example.test"},
            on_progress=progress_events.append,
            poll_interval=0,
        )

        assert attempts == 3
        assert result["status"] == "success"
        assert [event.get("connection_state") for event in progress_events[:2]] == [
            "reconnecting",
            "reconnecting",
        ]
        assert progress_events[-1]["status"] == "completed"

    asyncio.run(run())


def test_partial_technical_results_are_not_reported_as_complete():
    result = _aggregate(
        "basic_baseline_check",
        ["192.0.2.10", "192.0.2.11"],
        [
            {"status": "completed", "results": []},
            {"status": "partial", "warnings": [{"error": "SSH authentication failed"}]},
        ],
    )
    assert result["status"] == "partial"
    assert result["warnings"][0]["target"] == "192.0.2.11"


def test_authentication_failure_remains_a_blocking_task_failure():
    result = _aggregate(
        "basic_baseline_check",
        ["192.0.2.10"],
        [{
            "status": "partial",
            "blocking": True,
            "warnings": [{"error": "SSH authentication failed"}],
        }],
    )
    assert result["status"] == "failed"
    assert result["failed"][0]["blocking"] is True


def test_long_verification_renews_its_lease():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            user, project, assessment, phase, _task = await _records(db)
            verification = VerificationRun(
                project_id=project.id,
                assessment_id=assessment.id,
                phase_id=phase.id,
                source_type="technical",
                status=VerificationRunStatus.RUNNING,
                requested_by=user.id,
                lease_owner=WORKER_ID,
                lease_expires_at=datetime.utcnow() - timedelta(seconds=1),
            )
            db.add(verification)
            await db.commit()

            assert await _renew_verification_lease(db, verification.id) is True
            await db.refresh(verification)
            assert verification.heartbeat_at is not None
            assert verification.lease_expires_at > datetime.utcnow()

        await engine.dispose()

    asyncio.run(run())
