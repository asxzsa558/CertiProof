import asyncio

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.results import _delete_scan_records
from app.core.database import Base
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance
from app.models.asset import Asset, AssetType
from app.models.change_snapshot import ChangeSnapshot
from app.models.evidence import Evidence, EvidenceType
from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.monitoring import ScanHistory, ScheduledScan, ScheduleFrequency
from app.models.organization import Organization
from app.models.project import Project
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy
from app.models.user import User
from app.models.verification import FindingEvent, VerificationItem, VerificationRun
from app.services.verification_service import create_verification_run


def test_scan_record_deletion_removes_all_dependents():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            user = User(email="delete-check@example.test", username="delete-check", hashed_password="test")
            organization = Organization(name="Delete Check", code="delete-check")
            db.add_all([user, organization])
            await db.flush()
            project = Project(user_id=user.id, organization_id=organization.id, name="Delete Check")
            template = FlowTemplate(name="Delete Check", compliance_level=3, phases_config=[])
            db.add_all([project, template])
            await db.flush()
            assessment = Assessment(
                project_id=project.id,
                template_id=template.id,
                name="Delete Check",
                assessment_level=3,
                status="in_progress",
                total_phases=4,
                completed_phases=2,
            )
            db.add(assessment)
            await db.flush()
            for order, (phase_id, status) in enumerate([
                ("gap_analysis", "completed"),
                ("field_assessment", "completed"),
                ("remediation_verification", "active"),
                ("report", "pending"),
            ], 1):
                db.add(PhaseInstance(
                    assessment_id=assessment.id,
                    phase_id=phase_id,
                    name=phase_id,
                    order=order,
                    status=status,
                ))
            await db.flush()
            asset = Asset(project_id=project.id, asset_type=AssetType.IP, value="192.0.2.8")
            db.add(asset)
            await db.flush()
            scheduled = ScheduledScan(project_id=project.id, asset_id=asset.id, name="check", frequency=ScheduleFrequency.DAILY)
            task = ScanTask(project_id=project.id, asset_id=asset.id, task_type=ScanTaskType.TARGETED, status=ScanTaskStatus.COMPLETED, triggered_by=TriggeredBy.MANUAL)
            second_task = ScanTask(project_id=project.id, asset_id=asset.id, task_type=ScanTaskType.TARGETED, status=ScanTaskStatus.FAILED, triggered_by=TriggeredBy.MANUAL)
            db.add_all([scheduled, task, second_task])
            await db.flush()
            finding = Finding(
                project_id=project.id,
                scan_task_id=task.id,
                fingerprint="a" * 64,
                source_type="technical",
                source_key="scan_ports",
                scope_key=asset.value,
                clause_id="TECH-TEST",
                clause_name="测试检测",
                severity=Severity.HIGH,
                judgment=Judgment.FAIL,
                judgment_engine=JudgmentEngine.RULE,
                status=FindingStatus.OPEN,
            )
            db.add(finding)
            await db.flush()
            db.add_all([
                Evidence(finding_id=finding.id, project_id=project.id, evidence_type=EvidenceType.TOOL_OUTPUT, file_path="evidence/test.txt", file_size=128),
                ScanHistory(scheduled_scan_id=scheduled.id, scan_task_id=task.id),
                ChangeSnapshot(project_id=project.id, scan_task_id=task.id, snapshot_type="port", subject=asset.value, scope="default", snapshot={}),
            ])
            await create_verification_run(
                db,
                project_id=project.id,
                findings=[finding],
                source_type="technical",
                actor_id=user.id,
            )
            await db.commit()

            assert await _delete_scan_records(db, [task.id, second_task.id]) == (["evidence/test.txt"], 128)
            await db.commit()
            for model in (
                ScanTask,
                Finding,
                VerificationRun,
                VerificationItem,
                FindingEvent,
                Evidence,
                ScanHistory,
                ChangeSnapshot,
            ):
                assert (await db.execute(select(model))).scalars().all() == []
            assert (await db.execute(select(ScheduledScan))).scalar_one().id == scheduled.id

        await engine.dispose()

    asyncio.run(run())
