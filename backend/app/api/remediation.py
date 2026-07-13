import re
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.finding import Finding, FindingStatus
from app.models.remediation import RemediationTicket, RemediationStatus
from app.models.scan_task import ScanTask
from app.models.evidence import Evidence, EvidenceType
from app.schemas.remediation import (
    RemediationTicketCreate,
    RemediationTicketUpdate,
    RemediationTicketResponse,
    RemediationTicketListResponse,
)
from app.services.config_service import get_config_service
from app.services.document_pipeline import (
    SUPPORTED_SUFFIXES,
    create_document_run,
    normalize_analysis_mode,
)
from app.services.file_storage import file_storage
from app.services.upload_validation import read_limited_upload

router = APIRouter(prefix="/projects/{project_id}/remediation", tags=["Remediation"])
MAX_RETEST_UPLOAD_SIZE = 100 * 1024 * 1024


def _enum_value(value):
    return getattr(value, "value", value)


def _finding_source(finding: Finding | None) -> tuple[str, str]:
    if not finding:
        return "manual", "人工问题"

    clause_id = finding.clause_id or ""
    if clause_id.startswith("DOC-TASK-"):
        return "document", "文档差距"

    scan_task = finding.__dict__.get("scan_task")
    parameters = getattr(scan_task, "parameters", None) or {}
    source = parameters.get("source")
    if source == "document_control_analysis":
        return "document", "文档差距"
    if finding.scan_task_id:
        return "technical", "技术检测"

    return "manual", "人工问题"


def _ticket_payload(ticket: RemediationTicket, finding: Finding | None = None) -> dict:
    finding = finding or getattr(ticket, "finding", None)
    source, source_label = _finding_source(finding)
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "remediation_plan": ticket.remediation_plan,
        "status": ticket.status,
        "priority": ticket.priority,
        "finding_id": ticket.finding_id,
        "source": source,
        "source_label": source_label,
        "finding_clause_id": finding.clause_id if finding else None,
        "finding_clause_name": finding.clause_name if finding else None,
        "finding_severity": _enum_value(finding.severity) if finding else None,
        "finding_status": _enum_value(finding.status) if finding else None,
        "finding_description": finding.description if finding else None,
        "judgment": _enum_value(finding.judgment) if finding else None,
        "confidence": finding.confidence if finding else None,
        "scan_task_id": finding.scan_task_id if finding else None,
        "assigned_to": ticket.assigned_to,
        "skip_reason": ticket.skip_reason,
        "resolution_notes": ticket.resolution_notes,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "resolved_at": ticket.resolved_at,
        "verified_at": ticket.verified_at,
        "due_date": ticket.due_date,
    }


def _apply_finding_status(ticket: RemediationTicket, finding: Finding | None):
    if not finding:
        return

    if ticket.status == RemediationStatus.IN_PROGRESS:
        finding.status = FindingStatus.IN_PROGRESS
    elif ticket.status in (
        RemediationStatus.RESOLVED,
        RemediationStatus.VERIFIED,
        RemediationStatus.CLOSED,
    ):
        finding.status = FindingStatus.RESOLVED
        finding.resolved_at = finding.resolved_at or datetime.utcnow()


async def _resolve_document_analysis_mode(db: AsyncSession, mode: str | None) -> str:
    if not mode or mode == "default":
        mode = await get_config_service(db).get("document.analysis_mode", settings.DOCUMENT_ANALYSIS_MODE)
    return normalize_analysis_mode(mode)


async def _get_ticket_and_finding(db: AsyncSession, project_id: int, ticket_id: int) -> tuple[RemediationTicket, Finding]:
    result = await db.execute(
        select(RemediationTicket, Finding)
        .join(Finding, RemediationTicket.finding_id == Finding.id)
        .where(RemediationTicket.id == ticket_id, RemediationTicket.project_id == project_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return row[0], row[1]


async def _execute_technical_retest(
    db: AsyncSession,
    project_id: int,
    user_id: int,
    ticket: RemediationTicket,
    finding: Finding,
) -> dict:
    scan_task = await db.get(ScanTask, finding.scan_task_id)
    parameters = dict(scan_task.parameters or {}) if scan_task else {}
    task_type = parameters.pop("task_type", None)
    target = parameters.pop("target", None)
    if not task_type or not target:
        raise HTTPException(status_code=400, detail="缺少原检测任务或目标信息，无法自动复测")

    ticket.status = RemediationStatus.IN_PROGRESS
    finding.status = FindingStatus.IN_PROGRESS
    await db.commit()

    from app.services.task_executor import TaskExecutor
    result = await TaskExecutor(db).execute_task(
        task_type=task_type,
        target=target,
        project_id=project_id,
        user_id=user_id,
        params=parameters,
    )
    refreshed_ticket = await db.get(RemediationTicket, ticket.id)
    refreshed_finding = await db.get(Finding, finding.id)
    return {
        "ticket": _ticket_payload(refreshed_ticket, refreshed_finding) if refreshed_ticket else None,
        "result": result,
    }


@router.post("/", response_model=RemediationTicketResponse, status_code=status.HTTP_201_CREATED)
async def create_remediation_ticket(
    project_id: int,
    ticket_data: RemediationTicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new remediation ticket for a finding."""
    # Verify project access
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:manage")
    
    # Verify finding exists
    result = await db.execute(
        select(Finding).where(Finding.id == ticket_data.finding_id, Finding.project_id == project_id)
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    
    # Check if ticket already exists for this finding
    result = await db.execute(
        select(RemediationTicket).where(RemediationTicket.finding_id == ticket_data.finding_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Remediation ticket already exists for this finding")
    
    # Create ticket
    ticket = RemediationTicket(
        finding_id=ticket_data.finding_id,
        project_id=project_id,
        title=ticket_data.title,
        description=ticket_data.description,
        remediation_plan=ticket_data.remediation_plan or finding.remediation_suggestion,
        priority=ticket_data.priority,
        assigned_to=ticket_data.assigned_to,
        assigned_by=current_user.id,
        due_date=ticket_data.due_date,
        status=RemediationStatus.OPEN,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    
    return ticket


@router.get("/", response_model=List[RemediationTicketListResponse])
async def list_remediation_tickets(
    project_id: int,
    status_filter: Optional[RemediationStatus] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all remediation tickets for a project."""
    # Verify project access
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:read")
    
    query = (
        select(RemediationTicket, Finding)
        .join(Finding, RemediationTicket.finding_id == Finding.id)
        .where(RemediationTicket.project_id == project_id)
    )
    if status_filter:
        query = query.where(RemediationTicket.status == status_filter)
    
    result = await db.execute(query.order_by(RemediationTicket.created_at.desc()))
    rows = result.all()
    
    return [_ticket_payload(ticket, finding) for ticket, finding in rows]


@router.get("/summary")
async def get_remediation_summary(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Summarize remediation and retest state for a project."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:read")

    result = await db.execute(
        select(RemediationTicket, Finding)
        .join(Finding, RemediationTicket.finding_id == Finding.id)
        .where(RemediationTicket.project_id == project_id)
        .order_by(RemediationTicket.updated_at.desc())
    )
    tickets = [_ticket_payload(ticket, finding) for ticket, finding in result.all()]

    counts = {
        "total": len(tickets),
        "open": 0,
        "in_progress": 0,
        "resolved": 0,
        "verified": 0,
        "closed": 0,
        "skipped": 0,
        "fixed": 0,
        "still_exists": 0,
        "pending_verification": 0,
    }
    by_source = {"document": 0, "technical": 0, "manual": 0}
    by_priority = {}

    for item in tickets:
        status_value = _enum_value(item["status"])
        counts[status_value] = counts.get(status_value, 0) + 1
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
        by_priority[item["priority"]] = by_priority.get(item["priority"], 0) + 1

        if status_value in {"resolved", "verified", "closed"}:
            counts["fixed"] += 1
        elif status_value in {"open", "in_progress"}:
            counts["still_exists"] += 1
        if status_value == "resolved":
            counts["pending_verification"] += 1

    return {
        "counts": counts,
        "by_source": by_source,
        "by_priority": by_priority,
        "tickets": tickets[:30],
    }


@router.get("/{ticket_id}", response_model=RemediationTicketResponse)
async def get_remediation_ticket(
    project_id: int,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific remediation ticket."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:read")

    result = await db.execute(
        select(RemediationTicket).where(
            RemediationTicket.id == ticket_id,
            RemediationTicket.project_id == project_id
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return ticket


@router.put("/{ticket_id}", response_model=RemediationTicketResponse)
async def update_remediation_ticket(
    project_id: int,
    ticket_id: int,
    ticket_data: RemediationTicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a remediation ticket."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:manage")

    result = await db.execute(
        select(RemediationTicket).where(
            RemediationTicket.id == ticket_id,
            RemediationTicket.project_id == project_id
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Update fields
    if ticket_data.status is not None:
        if ticket_data.status == RemediationStatus.RESOLVED and not (
            (ticket_data.resolution_notes or "").strip() or (ticket.resolution_notes or "").strip()
        ):
            raise HTTPException(status_code=400, detail="提交整改前必须填写整改说明")
        ticket.status = ticket_data.status
        if ticket_data.status == RemediationStatus.RESOLVED:
            ticket.resolved_at = datetime.utcnow()
        elif ticket_data.status == RemediationStatus.VERIFIED:
            ticket.verified_at = datetime.utcnow()
        elif ticket_data.status == RemediationStatus.SKIPPED:
            ticket.resolved_at = datetime.utcnow()
    
    if ticket_data.assigned_to is not None:
        ticket.assigned_to = ticket_data.assigned_to
    if ticket_data.resolution_notes is not None:
        ticket.resolution_notes = ticket_data.resolution_notes
    if ticket_data.skip_reason is not None:
        ticket.skip_reason = ticket_data.skip_reason
    if ticket_data.due_date is not None:
        ticket.due_date = ticket_data.due_date

    finding_result = await db.execute(select(Finding).where(Finding.id == ticket.finding_id))
    _apply_finding_status(ticket, finding_result.scalar_one_or_none())
    
    await db.commit()
    await db.refresh(ticket)
    
    return ticket


@router.post("/{ticket_id}/document-retest")
async def document_retest(
    project_id: int,
    ticket_id: int,
    file: UploadFile = File(...),
    analysis_mode: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交新版文档，自动复测同一文档任务下的所有整改项。"""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "evidence:manage")

    ticket, finding = await _get_ticket_and_finding(db, project_id, ticket_id)
    match = re.match(r"^DOC-TASK-(\d+)-", finding.clause_id or "")
    if not match:
        raise HTTPException(status_code=400, detail="该整改项不是文档类问题，不能提交文档复测")

    task_id = int(match.group(1))
    from app.services.flow_engine import get_flow_engine

    engine = get_flow_engine(db)
    task = await engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="关联的文档检查任务不存在")
    if task.status == "in_progress":
        raise HTTPException(status_code=409, detail="文档正在分析，请等待完成后再提交复测")

    phase = await engine.get_phase(task.phase_id)
    assessment = await engine.get_assessment(phase.assessment_id) if phase else None
    if not assessment or assessment.project_id != project_id:
        raise HTTPException(status_code=400, detail="文档任务不属于当前项目")

    file_name = file.filename or "retest-document"
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        detail = "暂不支持旧版 DOC，请转换为 DOCX 或 PDF" if suffix == ".doc" else f"不支持的文件格式：{suffix or '未知'}"
        raise HTTPException(status_code=415, detail=detail)

    try:
        content = await read_limited_upload(file, MAX_RETEST_UPLOAD_SIZE, SUPPORTED_SUFFIXES)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=413 if "超过" in detail else 400, detail=detail) from exc

    clause_id = f"DOC-TASK-{task.id}"
    old_evidences = (await db.execute(
        select(Evidence).where(Evidence.project_id == project_id, Evidence.clause_id == clause_id)
    )).scalars().all()
    for evidence in old_evidences:
        if evidence.file_path:
            await file_storage.delete_file(evidence.file_path)
        await db.delete(evidence)

    file_path, digest, file_size = await file_storage.save_file(project_id, file_name, content)
    evidence = Evidence(
        project_id=project_id,
        evidence_type=EvidenceType.DOCUMENT,
        source="document_compliance_retest",
        file_name=file_name,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type or "application/octet-stream",
        clause_id=clause_id,
        hash_sha256=digest,
        uploaded_by=current_user.id,
        description=f"复测：{task.name}",
    )
    db.add(evidence)
    await db.commit()

    configured_mode = await _resolve_document_analysis_mode(db, analysis_mode)
    run = await create_document_run(db, task, project_id, current_user.id, configured_mode)
    refreshed_ticket = await db.get(RemediationTicket, ticket.id)
    return {
        "status": "queued",
        "message": "新版文档已提交复测，后台分析完成后会自动更新关联整改项",
        "run_id": run.id,
        "analysis_mode": configured_mode,
        "replaced_documents": len(old_evidences),
        "ticket": _ticket_payload(refreshed_ticket, finding) if refreshed_ticket else None,
    }


@router.post("/technical-retest-all")
async def technical_retest_all(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量复测当前项目可自动执行的技术整改项；文档项需上传新版文件。"""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:manage")

    result = await db.execute(
        select(RemediationTicket, Finding)
        .join(Finding, RemediationTicket.finding_id == Finding.id)
        .where(
            RemediationTicket.project_id == project_id,
            RemediationTicket.status.in_([
                RemediationStatus.OPEN,
                RemediationStatus.IN_PROGRESS,
                RemediationStatus.RESOLVED,
            ]),
        )
        .order_by(RemediationTicket.updated_at.desc())
    )

    technical_items = []
    document_items = []
    for ticket, finding in result.all():
        source, _ = _finding_source(finding)
        if source == "technical":
            technical_items.append((ticket, finding))
        elif source == "document":
            document_items.append(_ticket_payload(ticket, finding))

    items = []
    for ticket, finding in technical_items:
        try:
            retest = await _execute_technical_retest(db, project_id, current_user.id, ticket, finding)
            items.append({
                "ticket_id": ticket.id,
                "status": "completed",
                "message": "技术复测已完成",
                **retest,
            })
        except HTTPException as exc:
            items.append({"ticket_id": ticket.id, "status": "skipped", "message": exc.detail})
        except Exception as exc:
            items.append({"ticket_id": ticket.id, "status": "failed", "message": str(exc)})

    return {
        "status": "completed",
        "message": f"已复测 {len(items)} 个技术整改项，{len(document_items)} 个文档整改项需要上传新版文件",
        "technical": items,
        "documents_need_upload": document_items,
    }


@router.post("/{ticket_id}/technical-retest")
async def technical_retest(
    project_id: int,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按原检测任务、目标和参数重新检测，由检测结果自动更新整改状态。"""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:manage")

    ticket, finding = await _get_ticket_and_finding(db, project_id, ticket_id)
    source, _ = _finding_source(finding)
    if source != "technical":
        raise HTTPException(status_code=400, detail="该整改项不是技术检测问题，不能执行技术复测")

    retest = await _execute_technical_retest(db, project_id, current_user.id, ticket, finding)
    return {
        "status": "completed",
        "message": "技术复测已完成，整改状态已按检测结果更新",
        **retest,
    }


@router.post("/{ticket_id}/verify", response_model=RemediationTicketResponse)
async def verify_remediation(
    project_id: int,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify that a remediation has been completed successfully."""
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:manage")

    result = await db.execute(
        select(RemediationTicket).where(
            RemediationTicket.id == ticket_id,
            RemediationTicket.project_id == project_id
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if ticket.status != RemediationStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Ticket must be in RESOLVED status to verify")
    
    ticket.status = RemediationStatus.VERIFIED
    ticket.verified_at = datetime.utcnow()
    
    # Update finding status
    finding_result = await db.execute(
        select(Finding).where(Finding.id == ticket.finding_id)
    )
    finding = finding_result.scalar_one_or_none()
    _apply_finding_status(ticket, finding)
    
    await db.commit()
    await db.refresh(ticket)
    
    return ticket
