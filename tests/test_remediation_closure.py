import asyncio

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance, TaskInstance
from app.models.assessment_type import ProjectAssessment
from app.models.document_knowledge import DocumentFile
from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.models.verification import VerificationItem, VerificationOutcome, VerificationRun
from app.services.verification_queue import _document_clause_statuses
from app.services.flow_engine import FlowEngine
from app.services.verification_service import (
    apply_verification_outcome,
    create_verification_run,
    finish_verification_run,
    make_finding_fingerprint,
    queue_document_task_verification,
    reset_verification_data,
    reopen_finding,
    reconcile_verification_phase,
    scrub_sensitive_parameters,
)
from app.services.document_pipeline import create_document_batch_run, _replace_batch_document_versions


async def _project(db):
    user = User(email="closure@example.test", username="closure", hashed_password="test")
    organization = Organization(name="Closure", code="closure")
    db.add_all([user, organization])
    await db.flush()
    project = Project(user_id=user.id, organization_id=organization.id, name="Closure")
    template = FlowTemplate(name="Closure", compliance_level=3, phases_config=[])
    db.add_all([project, template])
    await db.flush()
    assessment = Assessment(
        project_id=project.id,
        template_id=template.id,
        name="Closure",
        assessment_level=3,
        status="in_progress",
        total_phases=4,
        completed_phases=2,
    )
    db.add(assessment)
    await db.flush()
    phases = {}
    for order, (key, name, state) in enumerate([
        ("gap_analysis", "差距分析", "completed"),
        ("field_assessment", "现场测评", "completed"),
        ("remediation_verification", "整改与复测", "active"),
        ("report", "生成报告", "pending"),
    ], 1):
        phase = PhaseInstance(
            assessment_id=assessment.id,
            phase_id=key,
            name=name,
            order=order,
            status=state,
        )
        db.add(phase)
        await db.flush()
        phases[key] = phase
    return user, project, phases


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _finding(project_id: int, **overrides) -> Finding:
    values = {
        "project_id": project_id,
        "fingerprint": make_finding_fingerprint("technical", "192.0.2.10", "scan_ports", "port:22/tcp"),
        "source_type": "technical",
        "source_key": "scan_ports",
        "scope_key": "192.0.2.10",
        "clause_id": "TECH-SCAN_PORTS",
        "clause_name": "端口扫描",
        "severity": Severity.HIGH,
        "judgment": Judgment.FAIL,
        "judgment_engine": JudgmentEngine.RULE,
        "description": "192.0.2.10 暴露高风险端口 22/tcp",
        "status": FindingStatus.OPEN,
    }
    values.update(overrides)
    return Finding(**values)


def test_assessment_creation_reuses_the_project_workflow():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            user = User(email="single@example.test", username="single", hashed_password="test")
            organization = Organization(name="Single", code="single")
            db.add_all([user, organization])
            await db.flush()
            project = Project(user_id=user.id, organization_id=organization.id, name="Single")
            template = FlowTemplate(
                name="Single",
                compliance_level=3,
                phases_config=[{
                    "id": "gap_analysis",
                    "name": "差距分析",
                    "order": 1,
                    "default_tasks": [],
                }],
            )
            db.add_all([project, template])
            await db.flush()

            flow = FlowEngine(db)
            first = await flow.create_assessment(project.id, template.id, "First", user.id)
            second = await flow.create_assessment(project.id, template.id, "Second", user.id)

            assert first.id == second.id
            assert await db.scalar(select(func.count(Assessment.id))) == 1

        await engine.dispose()

    asyncio.run(run())


def test_reliable_verification_is_the_only_path_that_closes_a_finding():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            user, project, phases = await _project(db)
            finding = _finding(project.id, assessment_id=phases["remediation_verification"].assessment_id)
            db.add(finding)
            await db.flush()

            verification = await create_verification_run(
                db,
                project_id=project.id,
                findings=[finding],
                source_type="technical",
                actor_id=user.id,
            )
            item = (await db.execute(
                select(VerificationItem).where(VerificationItem.run_id == verification.id)
            )).scalar_one()
            assert finding.status == FindingStatus.OPEN

            await apply_verification_outcome(
                db,
                item,
                VerificationOutcome.FIXED,
                comparison={"before": "present", "after": "absent"},
            )
            await finish_verification_run(db, verification)
            await db.commit()

            assert finding.status == FindingStatus.FIXED
            assert phases["remediation_verification"].status == "completed"
            assert phases["report"].status == "active"
        await engine.dispose()

    asyncio.run(run())


def test_single_task_rerun_preserves_verified_finding():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _user, project, phases = await _project(db)
            task = TaskInstance(
                phase_id=phases["field_assessment"].id,
                task_type="ssh_baseline_assessment",
                name="SSH/主机基线核查",
                status="completed",
            )
            finding = _finding(
                project.id,
                assessment_id=phases["field_assessment"].assessment_id,
                status=FindingStatus.FIXED,
            )
            db.add_all([task, finding])
            await db.commit()

            await FlowEngine(db).reset_task(task.id, reset_downstream=False)
            await db.refresh(finding)
            assert finding.status == FindingStatus.FIXED
            assert phases["remediation_verification"].status == "active"

        await engine.dispose()

    asyncio.run(run())


def test_single_task_rerun_recalculates_project_score_after_completion():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _user, project, phases = await _project(db)
            phases["remediation_verification"].status = "completed"
            phases["report"].status = "completed"
            assessment = await db.get(Assessment, phases["field_assessment"].assessment_id)
            assessment.status = "completed"
            task = TaskInstance(
                phase_id=phases["field_assessment"].id,
                task_type="ssh_baseline_assessment",
                name="SSH/主机基线核查",
                status="completed",
            )
            db.add_all([task, _finding(
                project.id,
                assessment_id=assessment.id,
                status=FindingStatus.OPEN,
            )])
            await db.commit()

            flow = FlowEngine(db)
            await flow.reset_task(task.id, reset_downstream=False)
            await db.refresh(project)
            assert project.compliance_score is None
            await flow.start_task(task.id)
            await flow.complete_task(task.id, {"status": "completed"})
            await db.refresh(project)
            assert project.compliance_score == 50.0

        await engine.dispose()

    asyncio.run(run())


def test_failed_task_deducts_score_instead_of_suppressing_it():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _user, project, phases = await _project(db)
            assessment = await db.get(Assessment, phases["field_assessment"].assessment_id)
            db.add_all([
                TaskInstance(
                    phase_id=phases["field_assessment"].id,
                    task_type="database_security_assessment",
                    name="数据库安全检测",
                    status="completed",
                ),
                TaskInstance(
                    phase_id=phases["field_assessment"].id,
                    task_type="ssh_baseline_assessment",
                    name="SSH/主机基线核查",
                    status="failed",
                    result={
                        "error": "缺少凭据",
                        "asset_results": {"192.0.2.10": {"outcome": "not_applicable"}},
                    },
                ),
            ])
            await db.commit()

            metrics = await FlowEngine(db)._calculate_compliance_metrics(assessment)

            assert metrics == {
                "score": 50.0,
                "coverage": 50.0,
                "reliable": 1,
                "unable": 1,
                "not_applicable": 0,
            }
        await engine.dispose()

    asyncio.run(run())


def test_not_applicable_task_is_excluded_from_score():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _user, project, phases = await _project(db)
            assessment = await db.get(Assessment, phases["field_assessment"].assessment_id)
            db.add_all([
                TaskInstance(
                    phase_id=phases["field_assessment"].id,
                    task_type="web_vulnerability_assessment",
                    name="Web 漏洞扫描",
                    status="completed",
                ),
                TaskInstance(
                    phase_id=phases["field_assessment"].id,
                    task_type="database_security_assessment",
                    name="数据库安全检测",
                    status="completed",
                    result={"asset_results": {"192.0.2.10": {"outcome": "not_applicable"}}},
                ),
                TaskInstance(
                    phase_id=phases["field_assessment"].id,
                    task_type="windows_ad_smb_assessment",
                    name="Windows/AD/SMB 检测",
                    status="completed",
                    result={
                        "asset_results": {
                            "192.0.2.10": {"outcome": "not_applicable"},
                            "192.0.2.11": {"outcome": "completed"},
                        },
                    },
                ),
            ])
            await db.commit()

            metrics = await FlowEngine(db)._calculate_compliance_metrics(assessment)

            assert metrics == {
                "score": 100.0,
                "coverage": 100.0,
                "reliable": 2,
                "unable": 0,
                "not_applicable": 1,
            }
        await engine.dispose()

    asyncio.run(run())


def test_older_assessment_cannot_overwrite_latest_project_score():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _user, project, phases = await _project(db)
            older = await db.get(Assessment, phases["field_assessment"].assessment_id)
            newer = Assessment(
                project_id=project.id,
                template_id=older.template_id,
                name="Latest",
                assessment_level=3,
                status="completed",
                total_phases=1,
                completed_phases=1,
                progress=100,
            )
            db.add(newer)
            await db.flush()
            phase = PhaseInstance(
                assessment_id=newer.id,
                phase_id="field_assessment",
                name="现场测评",
                order=1,
                status="completed",
                progress=100,
            )
            db.add(phase)
            await db.flush()
            db.add(TaskInstance(
                phase_id=phase.id,
                task_type="database_security_assessment",
                name="数据库安全检测",
                status="completed",
            ))
            await db.commit()

            flow = FlowEngine(db)
            await flow._sync_project_assessment(newer)
            await flow._sync_project_assessment(older)
            await db.commit()
            await db.refresh(project)

            assert project.compliance_score == 100.0
            project_assessment = (await db.execute(select(ProjectAssessment).where(
                ProjectAssessment.project_id == project.id,
            ))).scalar_one()
            assert project_assessment.status == "completed"
            assert project_assessment.progress == 100
            assert project_assessment.score == 100.0
        await engine.dispose()

    asyncio.run(run())


def test_unable_verification_keeps_problem_open_but_allows_an_honest_report():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            user, project, phases = await _project(db)
            finding = _finding(
                project.id,
                assessment_id=phases["remediation_verification"].assessment_id,
                source_key="baseline_check",
                clause_id="TECH-BASELINE",
            )
            db.add(finding)
            await db.flush()
            verification = await create_verification_run(
                db,
                project_id=project.id,
                findings=[finding],
                source_type="technical",
                actor_id=user.id,
            )
            item = (await db.execute(
                select(VerificationItem).where(VerificationItem.run_id == verification.id)
            )).scalar_one()

            await apply_verification_outcome(
                db,
                item,
                VerificationOutcome.UNABLE,
                error="SSH authentication failed",
            )
            await finish_verification_run(db, verification)

            assert finding.status == FindingStatus.OPEN
            assert phases["remediation_verification"].status == "completed"
            assert phases["report"].status == "active"
        await engine.dispose()

    asyncio.run(run())


def test_unreviewed_problem_still_locks_report():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, project, phases = await _project(db)
            db.add(_finding(project.id, assessment_id=phases["remediation_verification"].assessment_id))
            await db.flush()

            await reconcile_verification_phase(db, project.id)

            assert phases["remediation_verification"].status == "active"
            assert phases["report"].status == "pending"
        await engine.dispose()

    asyncio.run(run())


def test_user_can_continue_to_an_honest_report_with_unreviewed_problems():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, project, phases = await _project(db)
            db.add(_finding(project.id, assessment_id=phases["remediation_verification"].assessment_id))
            await db.flush()

            await FlowEngine(db).complete_phase(phases["remediation_verification"].id)
            await reconcile_verification_phase(db, project.id)

            assert phases["remediation_verification"].status == "completed"
            assert phases["remediation_verification"].outputs["continued_to_report"] is True
            assert phases["remediation_verification"].outputs["finding_summary"]["open"] == 1
            assert phases["remediation_verification"].outputs["review_progress"] == 0
            assert phases["remediation_verification"].progress == 100
            assert phases["remediation_verification"].completed_tasks == 0
            assert phases["report"].status == "active"
        await engine.dispose()

    asyncio.run(run())


def test_failed_required_check_blocks_verification_and_report_without_findings():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, project, phases = await _project(db)
            db.add(TaskInstance(
                phase_id=phases["field_assessment"].id,
                task_type="web_vulnerability_assessment",
                name="Web 漏洞扫描",
                status="failed",
                result={"error": "工具连接失败"},
            ))
            await db.flush()

            await reconcile_verification_phase(db, project.id)

            assert phases["remediation_verification"].status == "active"
            assert phases["remediation_verification"].total_tasks == 1
            assert phases["report"].status == "pending"
        await engine.dispose()

    asyncio.run(run())


def test_official_flow_cannot_be_skipped_or_manually_bypassed():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, _, phases = await _project(db)
            task = TaskInstance(
                phase_id=phases["field_assessment"].id,
                task_type="sql_injection_assessment",
                name="SQL 注入检测",
                status="todo",
            )
            db.add(task)
            await db.flush()
            flow = FlowEngine(db)

            for action in (
                lambda: flow.skip_phase(phases["report"].id, "暂时不做"),
                lambda: flow.jump_to_phase(phases["report"].id, "直接生成报告"),
                lambda: flow.skip_task(task.id, "暂时不做"),
            ):
                try:
                    await action()
                    raise AssertionError("official flow bypass must be rejected")
                except ValueError:
                    pass

            assert task.status == "todo"
            await flow.skip_task(task.id, "不适用：资产不是带查询参数的 URL")
            assert task.status == "cancelled"
        await engine.dispose()

    asyncio.run(run())


def test_manual_phase_activation_requires_all_prior_phases():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, _, phases = await _project(db)
            phases["gap_analysis"].status = "active"
            phases["field_assessment"].status = "pending"
            await db.commit()

            try:
                await FlowEngine(db).activate_phase(phases["field_assessment"].id)
                raise AssertionError("manual phase activation must not bypass prior phases")
            except ValueError as exc:
                assert "差距分析" in str(exc)
        await engine.dispose()

    asyncio.run(run())


def test_progress_reconciliation_demotes_out_of_order_downstream_phases():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, _, phases = await _project(db)
            assessment = await db.get(Assessment, phases["gap_analysis"].assessment_id)
            phases["gap_analysis"].status = "active"
            phases["gap_analysis"].progress = 80
            phases["field_assessment"].status = "completed"
            phases["field_assessment"].progress = 100
            phases["remediation_verification"].status = "completed"
            phases["report"].status = "completed"
            await db.commit()

            await FlowEngine(db).reconcile_all_assessment_progress()

            assert phases["gap_analysis"].status == "active"
            assert phases["field_assessment"].status == "pending"
            assert phases["remediation_verification"].status == "pending"
            assert phases["report"].status == "pending"
            assert assessment.completed_phases == 0
            assert assessment.progress == 45
        await engine.dispose()

    asyncio.run(run())


def test_failed_task_with_an_unable_finding_is_not_counted_twice():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            _, project, phases = await _project(db)
            task = TaskInstance(
                phase_id=phases["field_assessment"].id,
                task_type="ssh_baseline_assessment",
                name="SSH/主机基线核查",
                status="failed",
            )
            finding = _finding(
                project.id,
                assessment_id=phases["field_assessment"].assessment_id,
                fingerprint=make_finding_fingerprint("technical", "192.0.2.10", "baseline_check", "unable"),
                source_key="baseline_check",
                clause_id="TECH-BASELINE-UNABLE",
                judgment=Judgment.NOT_TESTED,
            )
            db.add_all([task, finding])
            await db.flush()

            await reconcile_verification_phase(db, project.id)

            assert phases["remediation_verification"].total_tasks == 1
            assert phases["remediation_verification"].completed_tasks == 0
        await engine.dispose()

    asyncio.run(run())


def test_reopening_finding_invalidates_generated_report_state():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            user, project, phases = await _project(db)
            report_task = TaskInstance(
                phase_id=phases["report"].id,
                task_type="html_report",
                name="HTML 报告生成",
                status="completed",
                result={"format": "html"},
            )
            finding = _finding(
                project.id,
                assessment_id=phases["remediation_verification"].assessment_id,
                status=FindingStatus.FIXED,
            )
            db.add_all([report_task, finding])
            phases["remediation_verification"].status = "completed"
            phases["report"].status = "completed"
            await db.flush()

            await reopen_finding(db, finding, user.id)

            assert phases["remediation_verification"].status == "active"
            assert phases["report"].status == "pending"
            assert report_task.status == "todo"
            assert report_task.result is None
        await engine.dispose()

    asyncio.run(run())


def test_sensitive_parameters_are_removed_recursively():
    cleaned = scrub_sensitive_parameters({
        "target": "192.0.2.10",
        "password": "secret",
        "nested": {"token": "secret", "port": 22},
        "_verification_run_id": 9,
    })
    assert cleaned == {"target": "192.0.2.10", "nested": {"port": 22}}


def test_document_verification_requires_an_explicit_point_result():
    run = type("Run", (), {
        "task_id": 7,
        "result_summary": {
            "status": "completed",
            "controls": [{"id": "CTRL", "points": [{"id": "A", "status": "pass"}]}],
        },
    })()
    statuses, reliable = _document_clause_statuses(run)
    assert reliable is True
    assert statuses == {"DOC-TASK-7-CTRL-A": "pass"}
    assert statuses.get("DOC-TASK-7-CTRL-MISSING") is None


def test_batch_remediation_replaces_document_version_and_queues_the_whole_group(monkeypatch):
    async def ignore_graph_purge(_db, _file_id):
        return None

    monkeypatch.setattr("app.services.document_pipeline.knowledge_graph.purge_file", ignore_graph_purge)

    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            user, project, phases = await _project(db)
            assessment = await db.get(Assessment, phases["gap_analysis"].assessment_id)
            task = TaskInstance(
                phase_id=phases["gap_analysis"].id,
                task_type="doc_review",
                name="文档检查：信息安全管理制度",
                status="completed",
            )
            db.add(task)
            await db.flush()
            old_file = DocumentFile(
                project_id=project.id,
                assessment_id=assessment.id,
                task_id=task.id,
                original_name="信息安全管理制度-v1.docx",
                storage_path="old.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size_bytes=10,
                sha256="a" * 64,
                parse_status="completed",
            )
            new_file = DocumentFile(
                project_id=project.id,
                assessment_id=assessment.id,
                task_id=task.id,
                original_name="信息安全管理制度-v2.docx",
                storage_path="new.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size_bytes=12,
                sha256="b" * 64,
                parse_status="completed",
            )
            findings = [
                _finding(
                    project.id,
                    assessment_id=assessment.id,
                    fingerprint=make_finding_fingerprint("document", f"task:{task.id}", "CTRL", point),
                    source_type="document",
                    source_key="CTRL",
                    scope_key=f"task:{task.id}",
                    clause_id=f"DOC-TASK-{task.id}-CTRL-{point}",
                    clause_name="管理制度检查",
                )
                for point in ("A", "B")
            ]
            db.add_all([old_file, new_file, *findings])
            await db.flush()
            batch = await create_document_batch_run(
                db,
                phases["remediation_verification"].id,
                project.id,
                [new_file.id],
                user.id,
                "standard",
                run_parameters={
                    "verification_batch": True,
                    "document_task_phase_id": phases["gap_analysis"].id,
                },
            )

            replaced = await _replace_batch_document_versions(db, batch, [{
                "task_id": task.id,
                "document_file_id": new_file.id,
            }])
            verification, document_run, active_ids, group_size = await queue_document_task_verification(
                db,
                project_id=project.id,
                task=task,
                actor_id=user.id,
                analysis_mode="standard",
                notes="批量整改材料自动复测",
            )
            items = list((await db.execute(select(VerificationItem).where(
                VerificationItem.run_id == verification.id
            ))).scalars().all())

            assert batch.parameters["verification_batch"] is True
            assert replaced == 1
            assert old_file.is_active is False
            assert old_file.replaced_by_id == new_file.id
            assert active_ids == [new_file.id]
            assert group_size == 2
            assert len(items) == 2
            assert all(item.current_document_run_id == document_run.id for item in items)
        await engine.dispose()

    asyncio.run(run())


def test_reset_clears_verification_history_and_reopens_findings():
    async def run():
        engine, session_factory = await _database()
        async with session_factory() as db:
            user, project, phases = await _project(db)
            finding = _finding(project.id, assessment_id=phases["remediation_verification"].assessment_id)
            db.add(finding)
            await db.flush()
            verification = await create_verification_run(
                db,
                project_id=project.id,
                findings=[finding],
                source_type="technical",
                actor_id=user.id,
            )
            item = (await db.execute(
                select(VerificationItem).where(VerificationItem.run_id == verification.id)
            )).scalar_one()
            await apply_verification_outcome(db, item, VerificationOutcome.FIXED)
            await finish_verification_run(db, verification)
            assert finding.status == FindingStatus.FIXED

            await reset_verification_data(db, project.id)

            assert finding.status == FindingStatus.OPEN
            assert (await db.execute(select(VerificationRun))).scalars().all() == []
            assert (await db.execute(select(VerificationItem))).scalars().all() == []
        await engine.dispose()

    asyncio.run(run())
