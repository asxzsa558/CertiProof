import asyncio

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance, TaskInstance
from app.models.organization import Organization
from app.models.project import Project
from app.models.report import ReportArtifact
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy
from app.models.user import User
from app.orchestrator.orchestrator import Orchestrator
from app.services.file_storage import file_storage
from app.services.report_service import (
    _asset_verification_badge,
    create_report_artifact,
    ensure_report_generation_ready,
    generate_json_report,
    get_latest_report_artifact,
    get_report_artifact_version,
    invalidate_report_artifacts,
    list_report_artifacts,
    read_report_artifact_html,
    report_artifact_payload,
)


def test_report_translates_asset_verification_states():
    assert "待验证" in _asset_verification_badge("pending")
    assert "验证失败" in _asset_verification_badge("failed")
    assert "pending" not in _asset_verification_badge("pending")


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _assessment(db):
    user = User(email="report@example.test", username="report", hashed_password="test")
    organization = Organization(name="Report", code="report")
    db.add_all([user, organization])
    await db.flush()
    project = Project(user_id=user.id, organization_id=organization.id, name="Report Project")
    template = FlowTemplate(name="Report", compliance_level=3, phases_config=[])
    db.add_all([project, template])
    await db.flush()
    assessment = Assessment(
        project_id=project.id,
        template_id=template.id,
        name="Report",
        assessment_level=3,
        status="in_progress",
        total_phases=4,
        completed_phases=3,
        progress=75,
    )
    db.add(assessment)
    await db.flush()
    for order, (key, name, status) in enumerate((
        ("gap_analysis", "差距分析", "completed"),
        ("field_assessment", "现场测评", "completed"),
        ("remediation_verification", "整改与复测", "completed"),
        ("report", "生成报告", "active"),
    ), 1):
        phase = PhaseInstance(
            assessment_id=assessment.id,
            phase_id=key,
            name=name,
            order=order,
            status=status,
            total_tasks=1 if key == "report" else 0,
        )
        db.add(phase)
        await db.flush()
        if key == "report":
            task = TaskInstance(phase_id=phase.id, task_type="html_report", name="HTML 报告生成", status="todo")
            db.add(task)
            await db.flush()
            report_phase = phase
            report_task = task
    await db.commit()
    return user, project, assessment, report_phase, report_task


def test_report_artifact_is_versioned_and_invalidated(tmp_path):
    async def run():
        engine, session_factory = await _database()
        previous_path = file_storage.base_path
        file_storage.base_path = tmp_path
        try:
            async with session_factory() as db:
                user, project, assessment, report_phase, report_task = await _assessment(db)
                first = await create_report_artifact(
                    db,
                    project_id=project.id,
                    assessment_id=assessment.id,
                    task_id=report_task.id,
                    generated_by=user.id,
                )
                await db.commit()

                html = (await read_report_artifact_html(first)).decode("utf-8")
                assert first.version == 1
                assert first.status == "current"
                assert first.snapshot["assessment"]["progress"] == 100
                assert first.snapshot["score_metrics"]["score"] is None
                assert "HTML / V1" in html
                assert "流程进度：100%" in html

                assert await invalidate_report_artifacts(db, project.id, "已发起新的技术检测") == 1
                await db.commit()
                assert first.status == "stale"
                assert report_phase.status == "active"
                assert report_task.status == "todo"
                assert assessment.progress == 75

                second = await create_report_artifact(
                    db,
                    project_id=project.id,
                    assessment_id=assessment.id,
                    task_id=report_task.id,
                    generated_by=user.id,
                )
                await db.commit()
                assert second.version == 2
                assert second.status == "current"
                assert (await get_latest_report_artifact(db, project.id)).id == second.id
                artifacts = list((await db.execute(select(ReportArtifact).order_by(ReportArtifact.version))).scalars())
                assert [(item.version, item.status) for item in artifacts] == [(1, "stale"), (2, "current")]
                assert [item.version for item in await list_report_artifacts(db, project.id)] == [2, 1]
                assert (await get_report_artifact_version(db, project.id, 1)).id == first.id
                payload = report_artifact_payload(second)
                assert payload["score"] is None
                assert payload["coverage"] == 0.0

                await db.delete(second)
                await db.commit()
                third = await create_report_artifact(
                    db,
                    project_id=project.id,
                    assessment_id=assessment.id,
                    task_id=report_task.id,
                    generated_by=user.id,
                )
                await db.commit()
                assert third.version == 3
        finally:
            file_storage.base_path = previous_path
            await engine.dispose()

    asyncio.run(run())


def test_interactive_scan_does_not_invalidate_current_report(tmp_path):
    async def run():
        engine, session_factory = await _database()
        previous_path = file_storage.base_path
        file_storage.base_path = tmp_path
        try:
            async with session_factory() as db:
                user, project, assessment, report_phase, report_task = await _assessment(db)
                artifact = await create_report_artifact(
                    db,
                    project_id=project.id,
                    assessment_id=assessment.id,
                    task_id=report_task.id,
                    generated_by=user.id,
                )
                report_phase.status = "completed"
                report_phase.progress = 100
                report_phase.completed_tasks = report_phase.total_tasks
                report_task.status = "completed"
                assessment.status = "completed"
                assessment.progress = 100
                assessment.completed_phases = assessment.total_phases
                await db.commit()

                scan_task_id = await Orchestrator()._create_scan_task_record(
                    db,
                    project.id,
                    [{"capability": "scan_ports", "parameters": {"target": "127.0.0.1"}}],
                    "interactive-test",
                    user_id=user.id,
                    user_input="扫描端口",
                )

                assert scan_task_id is not None
                assert artifact.status == "current"
                assert report_phase.status == "completed"
                assert report_task.status == "completed"
                assert assessment.progress == 100
                scan_task = await db.get(ScanTask, scan_task_id)
                assert scan_task.parameters["source"] == "interactive"
        finally:
            file_storage.base_path = previous_path
            await engine.dispose()

    asyncio.run(run())


def test_report_gate_and_snapshot_ignore_independent_scans():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            user, project, assessment, _, _ = await _assessment(db)
            interactive = ScanTask(
                project_id=project.id,
                task_type=ScanTaskType.TARGETED,
                status=ScanTaskStatus.RUNNING,
                triggered_by=TriggeredBy.MANUAL,
                parameters={"source": "interactive", "target": "127.0.0.1"},
            )
            assessment_scan = ScanTask(
                project_id=project.id,
                assessment_id=assessment.id,
                task_type=ScanTaskType.TARGETED,
                status=ScanTaskStatus.COMPLETED,
                triggered_by=TriggeredBy.MANUAL,
                parameters={"source": "assessment_task", "target": "127.0.0.1"},
            )
            db.add_all([interactive, assessment_scan])
            await db.commit()

            await ensure_report_generation_ready(db, project.id, assessment.id)
            report = await generate_json_report(db, project.id)
            assert [task["id"] for task in report["scan_tasks"]] == [assessment_scan.id]

            assessment_scan.status = ScanTaskStatus.RUNNING
            await db.commit()
            try:
                await ensure_report_generation_ready(db, project.id, assessment.id)
                raise AssertionError("running assessment scans must block the report")
            except ValueError as exc:
                assert "技术检测 1 个" in str(exc)
        await engine.dispose()

    asyncio.run(run())


def test_report_generation_rejects_an_incomplete_upstream_phase():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, project, assessment, _, _ = await _assessment(db)
            gap = (await db.execute(select(PhaseInstance).where(
                PhaseInstance.assessment_id == assessment.id,
                PhaseInstance.phase_id == "gap_analysis",
            ))).scalar_one()
            gap.status = "active"
            await db.commit()

            try:
                await ensure_report_generation_ready(db, project.id, assessment.id)
                raise AssertionError("incomplete upstream phases must block the official report")
            except ValueError as exc:
                assert "差距分析" in str(exc)
        await engine.dispose()

    asyncio.run(run())


def test_report_requires_every_official_check_to_reach_a_terminal_result():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, project, assessment, _, _ = await _assessment(db)
            gap = (await db.execute(select(PhaseInstance).where(
                PhaseInstance.assessment_id == assessment.id,
                PhaseInstance.phase_id == "gap_analysis",
            ))).scalar_one()
            task = TaskInstance(
                phase_id=gap.id,
                task_type="high_risk_port_scan",
                name="基础技术检测：高危端口扫描",
                status="todo",
            )
            db.add(task)
            await db.commit()

            try:
                await ensure_report_generation_ready(db, project.id, assessment.id)
                raise AssertionError("unattempted official checks must block the report")
            except ValueError as exc:
                assert "高危端口扫描" in str(exc)

            task.status = "failed"
            await db.commit()
            await ensure_report_generation_ready(db, project.id, assessment.id)
        await engine.dispose()

    asyncio.run(run())
