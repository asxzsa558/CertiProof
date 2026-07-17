"""Build a self-contained four-stage report and check the HTML contract."""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance
from app.models.organization import Organization
from app.models.project import ComplianceLevel, Project
from app.models.user import User
from app.services.report_service import generate_html_report


async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as db:
        user = User(email="report@example.test", username="report", hashed_password="test")
        organization = Organization(name="Report Contract", code="report-contract")
        db.add_all([user, organization])
        await db.flush()
        project = Project(
            user_id=user.id,
            owner_id=user.id,
            organization_id=organization.id,
            name="四阶段报告契约",
            compliance_level=ComplianceLevel.LEVEL_3,
        )
        template = FlowTemplate(name="四阶段", compliance_level=3, phases_config=[])
        db.add_all([project, template])
        await db.flush()
        assessment = Assessment(
            project_id=project.id,
            template_id=template.id,
            name="报告契约测评",
            assessment_level=3,
            total_phases=4,
        )
        db.add(assessment)
        await db.flush()
        for order, (phase_id, name) in enumerate((
            ("gap_analysis", "差距分析"),
            ("field_assessment", "现场测评"),
            ("remediation_verification", "整改与复测"),
            ("report", "生成报告"),
        ), 1):
            db.add(PhaseInstance(
                assessment_id=assessment.id,
                phase_id=phase_id,
                name=name,
                order=order,
                status="pending",
            ))
        await db.commit()
        html = await generate_html_report(db, project.id)

    await engine.dispose()
    required = (
        "自查结论",
        "当前待整改事项",
        "整改与复测记录",
        "检测覆盖与执行结果",
        "执行状态",
        "检测结论",
        "文档合规核查",
        "问题闭环明细",
        "测评范围与变更",
    )
    assert all(section in html for section in required)
    assert "差距分析" in html and "整改与复测" in html
    assert "整改加固" not in html and "复测验证" not in html
    assert "<html" in html and "</html>" in html
    print(f"report contract ok: bytes={len(html.encode())}")


if __name__ == "__main__":
    asyncio.run(main())
