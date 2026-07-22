import asyncio
from datetime import datetime

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.core.config import settings
from app.models.assessment import Assessment, FlowEvent, FlowTemplate, PhaseInstance, TaskInstance
from app.models.asset import Asset, AssetType
from app.models.audit import AuditEvent
from app.models.change_snapshot import ChangeSnapshot
from app.models.context import ActionHistory, ConversationHistory, ResultCache
from app.models.document_knowledge import DocumentAnalysisRun, DocumentFile
from app.models.evidence import Evidence, EvidenceType
from app.models.finding import Finding, Judgment, JudgmentEngine, Severity
from app.models.monitoring import ScanHistory, ScheduledScan, ScheduleFrequency
from app.models.organization import Organization, OrganizationMember
from app.models.project import Project
from app.models.report import ReportArtifact
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType
from app.models.user import User
from app.models.verification import VerificationItem, VerificationOutcome, VerificationRun, VerificationRunStatus
from app.services.file_storage import file_storage
from app.services.flow_engine import FlowEngine


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _project(db, user, organization, template, name):
    project = Project(
        user_id=user.id,
        organization_id=organization.id,
        name=name,
        compliance_score=88,
    )
    db.add(project)
    await db.flush()
    asset = Asset(project_id=project.id, asset_type=AssetType.IP, value=f"192.0.2.{project.id}")
    assessment = Assessment(
        project_id=project.id,
        template_id=template.id,
        name=name,
        assessment_level=3,
        status="completed",
        total_phases=1,
        completed_phases=1,
        progress=100,
    )
    db.add_all([asset, assessment])
    await db.flush()
    phase = PhaseInstance(
        assessment_id=assessment.id,
        phase_id="gap_analysis",
        name="差距分析",
        order=1,
        status="completed",
        total_tasks=1,
        completed_tasks=1,
        progress=100,
    )
    db.add(phase)
    await db.flush()
    task = TaskInstance(
        phase_id=phase.id,
        task_type="doc_review",
        name="文档检查：信息安全管理制度",
        status="completed",
        result={"status": "completed"},
    )
    db.add(task)
    await db.flush()
    return project, asset, assessment, phase, task


def test_full_reset_deletes_assessment_outputs_only(tmp_path):
    async def run():
        engine, session_factory = await _database()
        previous_path = file_storage.base_path
        previous_graph_required = settings.GRAPH_REQUIRED
        file_storage.base_path = tmp_path
        settings.GRAPH_REQUIRED = False
        try:
            async with session_factory() as db:
                user = User(email="reset@example.test", username="reset", hashed_password="test")
                organization = Organization(name="Reset", code="reset")
                template = FlowTemplate(name="Reset", compliance_level=3, phases_config=[])
                db.add_all([user, organization, template])
                await db.flush()
                membership = OrganizationMember(organization_id=organization.id, user_id=user.id, role="admin")
                db.add(membership)
                reset_project, asset, assessment, phase, task = await _project(
                    db, user, organization, template, "Reset Project"
                )
                assessment.status = "in_progress"
                assessment.completed_phases = 0
                assessment.progress = 50
                phase.status = "active"
                phase.completed_tasks = 0
                phase.progress = 50
                task.status = "in_progress"
                other_project, _, _, _, _ = await _project(db, user, organization, template, "Other Project")

                document_path, document_hash, document_size = await file_storage.save_file(
                    reset_project.id, "policy.docx", b"document"
                )
                evidence_path, _, evidence_size = await file_storage.save_file(
                    reset_project.id, "evidence.txt", b"evidence"
                )
                report_path, report_hash, report_size = await file_storage.save_file(
                    reset_project.id, "report.html", b"<html>report</html>"
                )
                run_row = DocumentAnalysisRun(
                    project_id=reset_project.id,
                    assessment_id=assessment.id,
                    phase_id=phase.id,
                    task_id=task.id,
                    requested_by=user.id,
                    run_kind="initial",
                    analysis_mode="standard",
                    parameters={},
                    status="running",
                    progress={"percent": 50},
                )
                db.add(run_row)
                await db.flush()
                document = DocumentFile(
                    project_id=reset_project.id,
                    assessment_id=assessment.id,
                    task_id=task.id,
                    uploaded_in_run_id=run_row.id,
                    original_name="policy.docx",
                    storage_path=document_path,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    size_bytes=document_size,
                    sha256=document_hash,
                    parse_status="completed",
                )
                scan = ScanTask(
                    project_id=reset_project.id,
                    assessment_id=assessment.id,
                    asset_id=asset.id,
                    task_type=ScanTaskType.TARGETED,
                    status=ScanTaskStatus.RUNNING,
                    control_state="running",
                    result_summary={"status": "running"},
                )
                other_scan = ScanTask(
                    project_id=other_project.id,
                    task_type=ScanTaskType.TARGETED,
                    status=ScanTaskStatus.COMPLETED,
                    result_summary={"status": "completed"},
                )
                db.add_all([document, scan, other_scan])
                await db.flush()
                finding = Finding(
                    project_id=reset_project.id,
                    assessment_id=assessment.id,
                    scan_task_id=scan.id,
                    document_run_id=run_row.id,
                    clause_id="TEST-001",
                    severity=Severity.HIGH,
                    judgment=Judgment.FAIL,
                    judgment_engine=JudgmentEngine.RULE,
                )
                schedule = ScheduledScan(
                    project_id=reset_project.id,
                    asset_id=asset.id,
                    name="Daily",
                    frequency=ScheduleFrequency.DAILY,
                    last_run_at=datetime.utcnow(),
                )
                db.add_all([finding, schedule])
                await db.flush()
                verification = VerificationRun(
                    project_id=reset_project.id,
                    assessment_id=assessment.id,
                    phase_id=phase.id,
                    source_type="technical",
                    status=VerificationRunStatus.RUNNING,
                    requested_by=user.id,
                    summary={},
                )
                db.add(verification)
                await db.flush()
                db.add_all([
                    Evidence(
                        project_id=reset_project.id,
                        finding_id=finding.id,
                        evidence_type=EvidenceType.DOCUMENT,
                        file_path=evidence_path,
                        file_size=evidence_size,
                    ),
                    VerificationItem(
                        run_id=verification.id,
                        project_id=reset_project.id,
                        finding_id=finding.id,
                        source_type="technical",
                        fingerprint="reset-test",
                        outcome=VerificationOutcome.FIXED,
                    ),
                    ReportArtifact(
                        project_id=reset_project.id,
                        assessment_id=assessment.id,
                        task_id=task.id,
                        version=1,
                        status="current",
                        html_path=report_path,
                        html_sha256=report_hash,
                        html_size=report_size,
                        snapshot={},
                    ),
                    ChangeSnapshot(
                        project_id=reset_project.id,
                        scan_task_id=scan.id,
                        snapshot_type="port",
                        subject=asset.value,
                        scope="default",
                        snapshot={"ports": [22]},
                    ),
                    ScanHistory(scheduled_scan_id=schedule.id, scan_task_id=scan.id),
                    ResultCache(user_id=user.id, project_id=reset_project.id, cache_key="scan:test", result_data={}),
                    ActionHistory(user_id=user.id, project_id=reset_project.id, action_type="scan_ports", parameters={}, status="success"),
                    ConversationHistory(
                        user_id=user.id,
                        project_id=reset_project.id,
                        role="assistant",
                        content="扫描完成",
                        context_snapshot={"scan_results": {"ports": [22]}, "is_multi_asset": True},
                    ),
                    FlowEvent(assessment_id=assessment.id, event_type="assessment_completed", event_data={}),
                    AuditEvent(
                        organization_id=organization.id,
                        project_id=reset_project.id,
                        actor_user_id=user.id,
                        event_type="assessment.reset.test",
                        resource_type="assessment",
                        resource_id=str(assessment.id),
                    ),
                ])
                await db.commit()

                reset_assessment, cleanup = await FlowEngine(db).restart_assessment(assessment.id)
                await db.refresh(reset_project)
                await db.refresh(asset)
                await db.refresh(membership)
                await db.refresh(schedule)

                assert reset_assessment.status == "not_started"
                assert reset_assessment.progress == 0
                rebuilt_phases = list((await db.execute(select(PhaseInstance).where(
                    PhaseInstance.assessment_id == assessment.id
                ).order_by(PhaseInstance.order))).scalars())
                assert [item.phase_id for item in rebuilt_phases] == [
                    "gap_analysis", "field_assessment", "remediation_verification", "report",
                ]
                assert all(item.status == "pending" for item in rebuilt_phases)
                rebuilt_tasks = list((await db.execute(select(TaskInstance).where(
                    TaskInstance.phase_id.in_([item.id for item in rebuilt_phases])
                ))).scalars())
                assert rebuilt_tasks and all(item.status == "todo" and item.result is None for item in rebuilt_tasks)
                assert reset_project.compliance_score is None
                assert asset.project_id == reset_project.id
                assert membership.organization_id == organization.id
                assert schedule.last_run_at is not None
                assert cleanup["scan_tasks"] == 1
                assert cleanup["reports"] == 1
                assert cleanup["deleted_file_count"] == 3
                assert cleanup["failed_file_paths"] == []
                assert cleanup["cancelled_jobs"] == {
                    "scan_tasks": 1,
                    "document_runs": 1,
                    "verification_runs": 1,
                    "assessment_tasks": 1,
                }

                for model in (
                    ScanTask,
                    Finding,
                    Evidence,
                    DocumentAnalysisRun,
                    DocumentFile,
                    VerificationRun,
                    ReportArtifact,
                ):
                    assert int((await db.execute(select(func.count()).select_from(model).where(
                        model.project_id == reset_project.id
                    ))).scalar_one()) == 0

                assert int((await db.execute(select(func.count(ScanHistory.id)).where(
                    ScanHistory.scheduled_scan_id == schedule.id
                ))).scalar_one()) == 0
                events = list((await db.execute(select(FlowEvent).where(
                    FlowEvent.assessment_id == assessment.id
                ))).scalars())
                assert [item.event_type for item in events] == ["assessment_reset"]
                conversation = (await db.execute(select(ConversationHistory).where(
                    ConversationHistory.project_id == reset_project.id
                ))).scalar_one()
                assert conversation.context_snapshot["scan_results"] == {"ports": [22]}
                assert int((await db.execute(select(func.count(ChangeSnapshot.id)).where(
                    ChangeSnapshot.project_id == reset_project.id
                ))).scalar_one()) == 1
                assert int((await db.execute(select(func.count(ResultCache.id)).where(
                    ResultCache.project_id == reset_project.id
                ))).scalar_one()) == 1
                assert int((await db.execute(select(func.count(ActionHistory.id)).where(
                    ActionHistory.project_id == reset_project.id
                ))).scalar_one()) == 1
                assert int((await db.execute(select(func.count(AuditEvent.id)).where(
                    AuditEvent.project_id == reset_project.id
                ))).scalar_one()) == 1
                assert int((await db.execute(select(func.count(ScanTask.id)).where(
                    ScanTask.project_id == other_project.id
                ))).scalar_one()) == 1
                assert await file_storage.read_file(document_path) is None
                assert await file_storage.read_file(evidence_path) is None
                assert await file_storage.read_file(report_path) is None
        finally:
            file_storage.base_path = previous_path
            settings.GRAPH_REQUIRED = previous_graph_required
            await engine.dispose()

    asyncio.run(run())
