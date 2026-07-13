from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from fastapi.responses import Response, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.core.database import get_db
from app.core.rbac import require_org_permission_for_user_id
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project, ComplianceLevel, ProjectStatus
from app.models.asset import Asset, AssetType, VerificationMethod, VerificationStatus
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy
from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.remediation import RemediationTicket, RemediationStatus
from app.models.evidence import Evidence, EvidenceType
from app.models.questionnaire import QuestionnaireRecord
from app.models.evidence import Evidence
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance, TaskInstance, FlowEvent
from app.models.assessment_type import ProjectAssessment
from app.models.monitoring import ScheduledScan, ScanHistory
from app.models.change_snapshot import ChangeSnapshot
from app.models.organization import OrganizationMember
from app.models.context import (
    ConversationHistory, ActionHistory, ResultCache,
    ProjectMemory, ConversationArchive, ConversationThread,
)
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListResponse
from app.services.report_service import generate_html_report, generate_json_report
from app.services.flow_engine import get_flow_engine
from app.services.audit import record_audit_event

router = APIRouter(prefix="/projects", tags=["Projects"])


async def check_org_member(db: AsyncSession, org_id: int, user_id: int, permission: str = "project:read") -> None:
    """检查用户是否属于该组织"""
    await require_org_permission_for_user_id(db, org_id, user_id, permission)


async def get_project_for_user(
    db: AsyncSession,
    project_id: int,
    user_id: int,
    permission: str = "project:read",
    allow_archived: bool = False,
) -> Project:
    """获取项目并验证用户有权限访问（通过组织成员关系）"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.organization_id:
        await check_org_member(db, project.organization_id, user_id, permission)
    else:
        # Fallback: old projects without org
        if project.user_id != user_id:
            raise HTTPException(status_code=403, detail="No access to this project")

    read_only_permissions = {"project:read", "scan:read", "assessment:read", "report:export"}
    if project.status == ProjectStatus.ARCHIVED and not allow_archived and permission not in read_only_permissions:
        raise HTTPException(
            status_code=409,
            detail="项目已归档并处于只读状态。请先恢复项目后再执行扫描、上传或整改操作。",
        )

    return project


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify user is member of organization
    await check_org_member(db, project_data.organization_id, current_user.id, "project:create")

    project = Project(
        user_id=current_user.id,
        organization_id=project_data.organization_id,
        owner_id=current_user.id,
        name=project_data.name,
        system_name=project_data.system_name,
        description=project_data.description,
        compliance_level=project_data.compliance_level,
    )
    db.add(project)
    await db.flush()

    # New projects use the single 5-stage flow. The legacy ProjectAssessment
    # records are retained only for historical projects and are not initialized here.
    engine = get_flow_engine(db)
    templates = await engine.upsert_default_templates()
    target_level = 2 if project.compliance_level == ComplianceLevel.LEVEL_2 else 3
    template = next((item for item in templates if item.compliance_level == target_level), None)
    if not template:
        raise HTTPException(status_code=500, detail="未找到对应等级的 5 阶段测评模板")
    level_name = project.compliance_level.value if project.compliance_level else ComplianceLevel.LEVEL_3.value
    await engine.create_assessment(
        project_id=project.id,
        template_id=template.id,
        name=f"{project.name} - 等保{level_name}测评",
        owner_id=current_user.id,
    )

    result = await db.execute(
        select(Project)
        .where(Project.id == project.id)
        .options(selectinload(Project.assessments).selectinload(ProjectAssessment.assessment_type))
    )
    project = result.scalar_one()
    return project


@router.post("/demo", status_code=status.HTTP_201_CREATED)
async def create_demo_project(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create one isolated sample project for product walkthroughs and local testing."""
    organization_id = payload.get("organization_id")
    if not isinstance(organization_id, int):
        raise HTTPException(status_code=422, detail="organization_id is required")
    await check_org_member(db, organization_id, current_user.id, "project:create")

    existing = (await db.execute(
        select(Project).where(
            Project.organization_id == organization_id,
            Project.user_id == current_user.id,
            Project.name == "CertiProof 演示测评项目",
        )
    )).scalar_one_or_none()
    if existing:
        return {"project_id": existing.id, "created": False, "message": "演示项目已存在"}

    engine = get_flow_engine(db)
    templates = await engine.upsert_default_templates()
    template = next((item for item in templates if item.compliance_level == 3), None)
    if not template:
        raise HTTPException(status_code=500, detail="未找到三级测评模板")

    project = Project(
        user_id=current_user.id,
        organization_id=organization_id,
        owner_id=current_user.id,
        name="CertiProof 演示测评项目",
        system_name="样例企业门户系统",
        description="样例数据，仅用于演示 5 阶段测评、整改与复测闭环。",
        compliance_level=ComplianceLevel.LEVEL_3,
        compliance_score=58,
    )
    db.add(project)
    await db.flush()

    assets = []
    for asset_type, value, name in (
        (AssetType.DOMAIN, "demo-web.local", "样例 Web 门户"),
        (AssetType.IP, "127.0.0.1", "本地测试服务"),
        (AssetType.IP, "192.0.2.10", "不可达样例资产"),
    ):
        asset = Asset(
            project_id=project.id,
            asset_type=asset_type,
            value=value,
            name=name,
            verification_status=VerificationStatus.VERIFIED,
            verification_method=VerificationMethod.PORT_RESPONSE,
        )
        db.add(asset)
        assets.append(asset)
    await db.flush()

    scan = ScanTask(
        project_id=project.id,
        asset_id=assets[0].id,
        task_type=ScanTaskType.TARGETED,
        status=ScanTaskStatus.COMPLETED,
        triggered_by=TriggeredBy.MANUAL,
        parameters={"demo": True, "capability": "scan_ports"},
        result_summary={"demo": True, "message": "样例检测记录，不代表真实资产结论。"},
        findings_count=2,
        high_severity_count=1,
        medium_severity_count=1,
    )
    db.add(scan)
    await db.flush()

    finding_specs = (
        ("8.1.4.1", "安全事件管理", Severity.MEDIUM, Judgment.PARTIAL,
         "样例制度缺少事件分级和处置时限。", "补充事件分级、处置时限和责任人。", RemediationStatus.IN_PROGRESS),
        ("8.1.4.2", "网络与通信安全", Severity.HIGH, Judgment.FAIL,
         "样例资产存在待核实的对外服务暴露。", "确认服务必要性并配置访问控制策略。", RemediationStatus.OPEN),
    )
    for clause_id, clause_name, severity, judgment, description, suggestion, ticket_status in finding_specs:
        finding = Finding(
            project_id=project.id,
            scan_task_id=scan.id,
            clause_id=clause_id,
            clause_name=clause_name,
            severity=severity,
            judgment=judgment,
            judgment_engine=JudgmentEngine.RULE,
            confidence=0.92,
            description=description,
            remediation_suggestion=suggestion,
            status=FindingStatus.IN_PROGRESS if ticket_status == RemediationStatus.IN_PROGRESS else FindingStatus.OPEN,
        )
        db.add(finding)
        await db.flush()
        db.add(Evidence(
            project_id=project.id,
            finding_id=finding.id,
            evidence_type=EvidenceType.DOCUMENT if judgment == Judgment.PARTIAL else EvidenceType.TOOL_OUTPUT,
            source="demo-seed",
            file_name="样例安全事件管理制度.md" if judgment == Judgment.PARTIAL else None,
            content={"demo": True, "summary": description},
            description="演示证据，用于展示整改与复测闭环。",
            clause_id=clause_id,
            uploaded_by=current_user.id,
        ))
        db.add(RemediationTicket(
            finding_id=finding.id,
            project_id=project.id,
            assigned_to=current_user.id,
            assigned_by=current_user.id,
            status=ticket_status,
            priority="high" if severity == Severity.HIGH else "medium",
            title=f"样例整改：{clause_name}",
            description=description,
            remediation_plan=suggestion,
        ))

    assessment = await engine.create_assessment(
        project_id=project.id,
        template_id=template.id,
        name="样例企业门户系统 - 等保三级测评",
        owner_id=current_user.id,
    )
    await engine.start_assessment(assessment.id)
    await db.commit()

    return {
        "project_id": project.id,
        "assessment_id": assessment.id,
        "created": True,
        "message": "演示项目已创建：包含样例资产、文档证据、问题与整改项。",
    }


@router.get("/", response_model=List[ProjectListResponse])
async def list_projects(
    organization_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if organization_id:
        # Verify user is member of organization
        await check_org_member(db, organization_id, current_user.id, "project:read")
        result = await db.execute(
            select(Project)
            .where(Project.organization_id == organization_id)
            .order_by(Project.created_at.desc())
        )
    else:
        # Return all projects from all organizations the user belongs to
        org_ids_result = await db.execute(
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == current_user.id)
        )
        org_ids = [row[0] for row in org_ids_result.all()]
        if not org_ids:
            return []
        result = await db.execute(
            select(Project)
            .where(Project.organization_id.in_(org_ids))
            .order_by(Project.created_at.desc())
        )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_project_for_user(db, project_id, current_user.id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project_data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_project_for_user(db, project_id, current_user.id, "project:update")

    # Update fields
    if project_data.name is not None:
        project.name = project_data.name
    if project_data.description is not None:
        project.description = project_data.description
    if project_data.system_name is not None:
        project.system_name = project_data.system_name
    if project_data.status is not None and project_data.status != project.status:
        raise HTTPException(status_code=400, detail="请使用项目归档或恢复操作变更项目状态")

    await db.commit()
    await db.refresh(project)
    return project


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_project_for_user(db, project_id, current_user.id, "project:update", allow_archived=True)
    project.status = ProjectStatus.ARCHIVED
    await record_audit_event(
        db,
        event_type="project.archived",
        resource_type="project",
        resource_id=project.id,
        actor_user_id=current_user.id,
        organization_id=project.organization_id,
        project_id=project.id,
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def restore_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_project_for_user(db, project_id, current_user.id, "project:update", allow_archived=True)
    project.status = ProjectStatus.ACTIVE
    await record_audit_event(
        db,
        event_type="project.restored",
        resource_type="project",
        resource_id=project.id,
        actor_user_id=current_user.id,
        organization_id=project.organization_id,
        project_id=project.id,
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_project_for_user(db, project_id, current_user.id, "project:delete")

    await db.execute(delete(RemediationTicket).where(RemediationTicket.project_id == project_id))
    await db.execute(delete(Evidence).where(Evidence.project_id == project_id))
    await db.execute(
        delete(Evidence).where(
            Evidence.finding_id.in_(
                select(Finding.id).where(Finding.project_id == project_id)
            )
        )
    )
    await db.execute(
        delete(Evidence).where(
            Evidence.questionnaire_record_id.in_(
                select(QuestionnaireRecord.id).where(QuestionnaireRecord.project_id == project_id)
            )
        )
    )
    await db.execute(delete(QuestionnaireRecord).where(QuestionnaireRecord.project_id == project_id))
    await db.execute(delete(Finding).where(Finding.project_id == project_id))
    await db.execute(delete(ProjectAssessment).where(ProjectAssessment.project_id == project_id))

    # 删除测评流程相关记录
    assessment_ids = await db.execute(
        select(Assessment.id).where(Assessment.project_id == project_id)
    )
    assessment_id_list = [row[0] for row in assessment_ids.all()]

    if assessment_id_list:
        await db.execute(
            delete(FlowEvent).where(FlowEvent.assessment_id.in_(assessment_id_list))
        )
        phase_ids = await db.execute(
            select(PhaseInstance.id).where(PhaseInstance.assessment_id.in_(assessment_id_list))
        )
        phase_id_list = [row[0] for row in phase_ids.all()]
        if phase_id_list:
            await db.execute(
                delete(TaskInstance).where(TaskInstance.phase_id.in_(phase_id_list))
            )
            await db.execute(
                delete(PhaseInstance).where(PhaseInstance.assessment_id.in_(assessment_id_list))
            )
        await db.execute(delete(Assessment).where(Assessment.project_id == project_id))

    # 删除监控相关记录
    scheduled_scan_ids = await db.execute(
        select(ScheduledScan.id).where(ScheduledScan.project_id == project_id)
    )
    scheduled_scan_id_list = [row[0] for row in scheduled_scan_ids.all()]

    if scheduled_scan_id_list:
        await db.execute(
            delete(ScanHistory).where(ScanHistory.scheduled_scan_id.in_(scheduled_scan_id_list))
        )
        await db.execute(delete(ScheduledScan).where(ScheduledScan.project_id == project_id))

    await db.execute(delete(ChangeSnapshot).where(ChangeSnapshot.project_id == project_id))
    await db.execute(delete(ScanTask).where(ScanTask.project_id == project_id))
    await db.execute(delete(Asset).where(Asset.project_id == project_id))

    await db.execute(delete(ProjectMemory).where(ProjectMemory.project_id == project_id))
    await db.execute(delete(ActionHistory).where(ActionHistory.project_id == project_id))
    await db.execute(delete(ResultCache).where(ResultCache.project_id == project_id))

    await db.execute(
        delete(ConversationHistory).where(ConversationHistory.project_id == project_id)
    )
    await db.execute(
        delete(ConversationArchive).where(ConversationArchive.project_id == project_id)
    )
    await db.execute(
        delete(ConversationThread).where(ConversationThread.project_id == project_id)
    )

    await db.delete(project)
    await db.commit()
    return None


@router.get("/{project_id}/report")
async def download_report(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate and download HTML self-assessment report."""
    await get_project_for_user(db, project_id, current_user.id, "report:export")

    try:
        return Response(
            content=await generate_html_report(db, project_id),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=certiproof-report-{project_id}.html"
            }
        )
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Report generation error: {error_detail}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )


@router.get("/{project_id}/report/json")
async def download_json_report(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate and download JSON compliance report."""
    await get_project_for_user(db, project_id, current_user.id, "report:export")

    try:
        report_data = await generate_json_report(db, project_id)

        return JSONResponse(
            content=report_data,
            headers={
                "Content-Disposition": f"attachment; filename=verisure_report_{project_id}.json"
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )
