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
from app.models.evidence import Evidence, EvidenceType
from app.models.questionnaire import QuestionnaireRecord
from app.models.assessment import Assessment, FlowTemplate, PhaseInstance, TaskInstance, FlowEvent
from app.models.document_knowledge import DocumentAnalysisRun, DocumentFile
from app.models.assessment_type import ProjectAssessment
from app.models.monitoring import ScheduledScan, ScanHistory
from app.models.change_snapshot import ChangeSnapshot
from app.models.organization import OrganizationMember
from app.models.context import (
    ConversationHistory, ActionHistory, ResultCache,
    ProjectMemory, ConversationArchive, ConversationThread,
)
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListResponse
from app.services.report_service import (
    get_latest_report_artifact,
    read_report_artifact_html,
    report_artifact_payload,
)
from app.services.flow_engine import get_flow_engine
from app.services.audit import record_audit_event
from app.services.data_lifecycle import (
    clear_project_documents,
    delete_project_records,
    delete_storage_files,
    storage_usage,
)

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

    # New projects use the single four-stage enterprise self-assessment flow.
    engine = get_flow_engine(db)
    templates = await engine.upsert_default_templates()
    target_level = 2 if project.compliance_level == ComplianceLevel.LEVEL_2 else 3
    template = next((item for item in templates if item.compliance_level == target_level), None)
    if not template:
        raise HTTPException(status_code=500, detail="未找到对应等级的四阶段测评模板")
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
        description="样例数据，仅用于演示四阶段等保企业自查流程。",
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
        control_state="completed",
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
         "样例制度缺少事件分级和处置时限。", "补充事件分级、处置时限和责任人。", "document"),
        ("8.1.4.2", "网络与通信安全", Severity.HIGH, Judgment.FAIL,
         "样例资产存在待核实的对外服务暴露。", "确认服务必要性并配置访问控制策略。", "technical"),
    )
    for clause_id, clause_name, severity, judgment, description, suggestion, source_type in finding_specs:
        finding = Finding(
            project_id=project.id,
            scan_task_id=scan.id,
            source_type=source_type,
            clause_id=clause_id,
            clause_name=clause_name,
            severity=severity,
            judgment=judgment,
            judgment_engine=JudgmentEngine.RULE,
            confidence=0.92,
            description=description,
            remediation_suggestion=suggestion,
            status=FindingStatus.OPEN,
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
        "message": "演示项目已创建：包含样例资产、证据和待复测问题。",
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


@router.get("/{project_id}/storage")
async def get_project_storage(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_project_for_user(db, project_id, current_user.id, "assessment:read", allow_archived=True)
    return {"project_id": project.id, **await storage_usage(db, [project.id])}


@router.delete("/{project_id}/documents")
async def clear_project_document_data(
    project_id: int,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_project_for_user(db, project_id, current_user.id, "evidence:manage")
    if payload.get("confirmation") != project.name:
        raise HTTPException(status_code=400, detail="请输入完整项目名称以确认清空文档数据")
    try:
        cleanup = await clear_project_documents(db, project.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit_event(
        db,
        event_type="project.documents_cleared",
        resource_type="project_documents",
        resource_id=project.id,
        actor_user_id=current_user.id,
        organization_id=project.organization_id,
        project_id=project.id,
        details={key: value for key, value in cleanup.items() if key != "file_paths"},
    )
    await db.commit()
    files = await delete_storage_files(cleanup.pop("file_paths"))
    if files["failed_file_paths"]:
        await record_audit_event(
            db,
            event_type="project.document_file_cleanup_partial",
            resource_type="project_documents",
            resource_id=project.id,
            actor_user_id=current_user.id,
            organization_id=project.organization_id,
            project_id=project.id,
            outcome="partial",
            details=files,
        )
        await db.commit()
    return {"status": "cleared", **cleanup, **files}


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await get_project_for_user(db, project_id, current_user.id, "project:delete")

    try:
        cleanup = await delete_project_records(db, project)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit_event(
        db,
        event_type="project.deleted",
        resource_type="project",
        resource_id=project_id,
        actor_user_id=current_user.id,
        organization_id=project.organization_id,
        details={"released_file_bytes": cleanup["released_file_bytes"]},
    )
    await db.commit()
    files = await delete_storage_files(cleanup.pop("file_paths"))
    return {"status": "deleted", **cleanup, **files}


@router.get("/{project_id}/report")
async def download_report(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the latest immutable HTML report artifact."""
    await get_project_for_user(db, project_id, current_user.id, "report:export")

    try:
        artifact = await get_latest_report_artifact(db, project_id)
        if not artifact:
            raise HTTPException(status_code=409, detail="该项目尚未生成正式报告")
        return Response(
            content=await read_report_artifact_html(artifact),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=certiproof-report-{project_id}-v{artifact.version}.html",
                "X-Report-Version": str(artifact.version),
                "X-Report-Status": artifact.status,
            }
        )
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))
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
    """Download the JSON snapshot used by the latest HTML artifact."""
    await get_project_for_user(db, project_id, current_user.id, "report:export")

    try:
        artifact = await get_latest_report_artifact(db, project_id)
        if not artifact:
            raise HTTPException(status_code=409, detail="该项目尚未生成正式报告")

        return JSONResponse(
            content=artifact.snapshot,
            headers={
                "Content-Disposition": f"attachment; filename=certiproof-report-{project_id}-v{artifact.version}.json",
                "X-Report-Version": str(artifact.version),
                "X-Report-Status": artifact.status,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )


@router.get("/{project_id}/report/status")
async def get_report_status(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_project_for_user(db, project_id, current_user.id, "report:export")
    return report_artifact_payload(await get_latest_report_artifact(db, project_id))
