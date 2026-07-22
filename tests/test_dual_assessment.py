import asyncio

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base
from app.models.assessment import Assessment
from app.models.assessment_type import AssessmentType, ProjectAssessment
from app.models.finding import Finding, Judgment, JudgmentEngine, Severity
from app.models.organization import Organization
from app.models.project import ComplianceLevel, Project
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType
from app.models.user import User
from app.schemas.project import ProjectResponse
from app.services.ai_engine import AIEngine
from app.services.context_manager import ContextManager
from app.services.flow_engine import FlowEngine
from app.services.miping_matrix import build_miping_domain_matrix


def test_project_can_run_dengbao_and_miping_independently():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        previous_graph_required = settings.GRAPH_REQUIRED
        settings.GRAPH_REQUIRED = False
        try:
            async with sessions() as db:
                user = User(email="dual@example.test", username="dual", hashed_password="test")
                organization = Organization(name="Dual", code="dual")
                db.add_all([user, organization])
                await db.flush()
                project = Project(
                    user_id=user.id,
                    organization_id=organization.id,
                    name="双测评项目",
                    compliance_level=ComplianceLevel.LEVEL_3,
                )
                db.add(project)
                db.add_all([
                    AssessmentType(code="dengbao", name="等保", is_active=True),
                    AssessmentType(code="miping", name="密评", is_active=True),
                ])
                await db.commit()

                flow = FlowEngine(db)
                templates = await flow.upsert_default_templates()
                dengbao_template = next(item for item in templates if item.assessment_type_code == "dengbao" and item.compliance_level == 3)
                miping_template = next(item for item in templates if item.assessment_type_code == "miping" and item.compliance_level == 2)
                dengbao = await flow.create_assessment(project.id, dengbao_template.id, owner_id=user.id)
                miping = await flow.create_assessment(project.id, miping_template.id, owner_id=user.id)

                stale_phase = (await flow.get_phases(miping.id))[0]
                await db.delete((await flow.get_tasks(stale_phase.id))[0])
                await db.commit()
                await flow.upsert_default_templates()
                rebuilt_phases = await flow.get_phases(miping.id)
                assert [len(await flow.get_tasks(phase.id)) for phase in rebuilt_phases] == [9, 5, 0, 1]

                assert dengbao.id != miping.id
                assert {item.assessment_type_code for item in await flow.list_assessments(project.id)} == {"dengbao", "miping"}
                assert len(await flow.list_assessments(project.id, "miping")) == 1
                hydrated_project = (await db.execute(
                    select(Project)
                    .where(Project.id == project.id)
                    .options(selectinload(Project.assessments).selectinload(ProjectAssessment.assessment_type))
                )).scalar_one()
                project_payload = ProjectResponse.model_validate(hydrated_project).model_dump()
                assert {item["assessment_type"]["code"] for item in project_payload["assessment_types"]} == {
                    "dengbao",
                    "miping",
                }
                levels = {
                    item["assessment_type"]["code"]: item["level"]
                    for item in project_payload["assessment_types"]
                }
                assert levels == {"dengbao": "三级", "miping": "二级"}

                miping_context = await ContextManager(
                    db,
                    user.id,
                    project.id,
                    assessment_code="miping",
                ).build_context()
                assert miping_context["assessment_state"]["id"] == miping.id
                assert miping_context["assessment_state"]["assessment_type_code"] == "miping"
                assert miping_context["current_project"]["active_assessment_code"] == "miping"

                help_text = AIEngine()._help_response("我可以在这里进行密评检测吗？", miping_context)
                assert "当前项目已启用二级密评自查" in help_text
                assert "与等保共用资产" in help_text

                matrix = await build_miping_domain_matrix(db, miping)
                assert len(matrix["domains"]) == 8
                assert matrix["counts"]["pending"] == 8

                miping_phases = miping_template.phases_config
                gap_task_types = {item["type"] for item in miping_phases[0]["default_tasks"]}
                field_task_types = {item["type"] for item in miping_phases[1]["default_tasks"]}
                assert len(miping_phases[0]["default_tasks"]) == 9
                assert len(miping_phases[1]["default_tasks"]) == 5
                assert not gap_task_types.intersection({
                    "high_risk_port_scan", "basic_vulnerability_scan", "basic_baseline_check",
                    "basic_weak_password_scan", "basic_ssl_tls_scan",
                })
                assert field_task_types == {"crypto_network_communication_assessment", "doc_review"}

                db.add_all([
                    ScanTask(
                        project_id=project.id,
                        assessment_id=dengbao.id,
                        task_type=ScanTaskType.TARGETED,
                        status=ScanTaskStatus.COMPLETED,
                    ),
                    ScanTask(
                        project_id=project.id,
                        assessment_id=miping.id,
                        task_type=ScanTaskType.TARGETED,
                        status=ScanTaskStatus.COMPLETED,
                    ),
                    Finding(
                        project_id=project.id,
                        assessment_id=dengbao.id,
                        clause_id="DB-001",
                        severity=Severity.HIGH,
                        judgment=Judgment.FAIL,
                        judgment_engine=JudgmentEngine.RULE,
                    ),
                    Finding(
                        project_id=project.id,
                        assessment_id=miping.id,
                        clause_id="MP-001",
                        severity=Severity.HIGH,
                        judgment=Judgment.FAIL,
                        judgment_engine=JudgmentEngine.RULE,
                    ),
                ])
                await db.commit()

                await flow.restart_assessment(dengbao.id)
                remaining_assessments = list((await db.execute(select(Assessment))).scalars())
                remaining_scans = list((await db.execute(select(ScanTask))).scalars())
                remaining_findings = list((await db.execute(select(Finding))).scalars())
                assert {item.id for item in remaining_assessments} == {dengbao.id, miping.id}
                assert [item.assessment_id for item in remaining_scans] == [miping.id]
                assert [item.assessment_id for item in remaining_findings] == [miping.id]
        finally:
            settings.GRAPH_REQUIRED = previous_graph_required
            await engine.dispose()

    asyncio.run(run())
