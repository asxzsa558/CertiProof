import json
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.assessment import Assessment, PhaseInstance, TaskInstance
from app.models.document_knowledge import DocumentBlock, DocumentFile
from app.models.finding import Finding, FindingStatus, Judgment
from app.models.user import User
from app.models.verification import FindingEvent, VerificationItem, VerificationOutcome, VerificationRun, VerificationRunStatus
from app.services.config_service import get_config_service
from app.services.document_pipeline import SUPPORTED_SUFFIXES, normalize_analysis_mode, safe_document_name
from app.services.file_storage import file_storage
from app.services.upload_validation import read_limited_upload
from app.services.verification_service import (
    controlled_remediation_plan,
    create_verification_run,
    queue_document_task_verification,
    reopen_finding,
)


router = APIRouter(prefix="/projects/{project_id}/verification", tags=["Verification"])
MAX_VERIFICATION_UPLOAD_SIZE = 100 * 1024 * 1024


class TechnicalVerificationRequest(BaseModel):
    finding_ids: list[int] = Field(min_length=1)
    notes: str = Field(default="", max_length=10000)
    credentials: dict[str, dict] = Field(default_factory=dict)


class DocumentReanalysisRequest(BaseModel):
    finding_id: int
    notes: str = Field(default="", max_length=10000)
    analysis_mode: str | None = None


def _value(value):
    return getattr(value, "value", value)


async def _require_project(db: AsyncSession, project_id: int, current_user: User, permission: str):
    from app.api.projects import get_project_for_user
    return await get_project_for_user(db, project_id, current_user.id, permission)


async def _findings(db: AsyncSession, project_id: int, finding_ids: list[int] | None = None) -> list[Finding]:
    query = select(Finding).where(Finding.project_id == project_id)
    if finding_ids is not None:
        query = query.where(Finding.id.in_(finding_ids))
    return list((await db.execute(query.order_by(Finding.created_at.desc()))).scalars().all())


def _finding_payload(finding: Finding, latest: VerificationItem | None = None) -> dict:
    return {
        "id": finding.id,
        "source_type": finding.source_type,
        "source_key": finding.source_key,
        "scope_key": finding.scope_key,
        "clause_id": finding.clause_id,
        "clause_name": finding.clause_name,
        "severity": _value(finding.severity),
        "judgment": _value(finding.judgment),
        "confidence": finding.confidence,
        "description": finding.description,
        "remediation_suggestion": finding.remediation_suggestion,
        "remediation_plan": controlled_remediation_plan(finding),
        "status": _value(finding.status),
        "scan_task_id": finding.scan_task_id,
        "document_run_id": finding.document_run_id,
        "created_at": finding.created_at,
        "resolved_at": finding.resolved_at,
        "latest_verification": {
            "run_id": latest.run_id,
            "outcome": _value(latest.outcome),
            "error": latest.error_message,
            "comparison": latest.comparison or {},
            "completed_at": latest.completed_at,
        } if latest else None,
    }


def _run_payload(run: VerificationRun, items: list[VerificationItem]) -> dict:
    return {
        "id": run.id,
        "source_type": run.source_type,
        "status": _value(run.status),
        "notes": run.notes,
        "summary": run.summary or {},
        "attempt_count": run.attempt_count,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
        "items": [{
            "id": item.id,
            "finding_id": item.finding_id,
            "source_type": item.source_type,
            "target": item.target,
            "capability": item.capability,
            "outcome": _value(item.outcome),
            "current_scan_task_id": item.current_scan_task_id,
            "current_document_run_id": item.current_document_run_id,
            "baseline_observation": item.baseline_observation or {},
            "current_observation": item.current_observation or {},
            "comparison": item.comparison or {},
            "error": item.error_message,
        } for item in items],
    }


@router.get("/workspace")
async def verification_workspace(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "assessment:read")
    findings = await _findings(db, project_id)
    assessment = (await db.execute(select(Assessment).where(
        Assessment.project_id == project_id,
    ).order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1))).scalar_one_or_none()
    blocker_rows = (await db.execute(
        select(TaskInstance, PhaseInstance)
        .join(PhaseInstance, PhaseInstance.id == TaskInstance.phase_id)
        .where(
            PhaseInstance.assessment_id == assessment.id,
            PhaseInstance.phase_id.in_(["gap_analysis", "field_assessment"]),
            TaskInstance.status == "failed",
        )
        .order_by(PhaseInstance.order, TaskInstance.created_at)
    )).all() if assessment else []
    finding_ids = [finding.id for finding in findings]
    items = (await db.execute(select(VerificationItem).where(
        VerificationItem.finding_id.in_(finding_ids)
    ).order_by(VerificationItem.id.desc()))).scalars().all() if finding_ids else []
    latest = {}
    for item in items:
        latest.setdefault(item.finding_id, item)

    document_task_ids = {
        int(match.group(1))
        for finding in findings
        if finding.source_type == "document"
        and (match := re.match(r"^task:(\d+)$", finding.scope_key or ""))
    }
    document_tasks = (await db.execute(select(TaskInstance).where(
        TaskInstance.id.in_(document_task_ids)
    ))).scalars().all() if document_task_ids else []
    task_by_id = {task.id: task for task in document_tasks}
    active_documents = (await db.execute(select(DocumentFile).where(
        DocumentFile.task_id.in_(document_task_ids),
        DocumentFile.is_active.is_(True),
    ).order_by(DocumentFile.created_at))).scalars().all() if document_task_ids else []
    documents_by_task = {}
    for document in active_documents:
        documents_by_task.setdefault(document.task_id, []).append({
            "id": document.id,
            "file_name": document.original_name,
            "file_size": document.size_bytes,
            "parse_status": document.parse_status,
        })

    document_groups = {}
    technical_groups = {}
    for finding in findings:
        payload = _finding_payload(finding, latest.get(finding.id))
        if finding.source_type == "document":
            key = finding.scope_key or "document:unknown"
            task_id = int(key.split(":", 1)[1]) if re.fullmatch(r"task:\d+", key) else None
            task = task_by_id.get(task_id)
            task_name = task.name.removeprefix("文档检查：") if task else None
            group = document_groups.setdefault(key, {
                "key": key,
                "task_id": task_id,
                "title": task_name or finding.clause_name or "文档合规问题",
                "files": documents_by_task.get(task_id, []),
                "findings": [],
            })
            group["findings"].append(payload)
        else:
            key = f"{finding.scope_key or '未知资产'}::{finding.source_key or '未知检测'}"
            group = technical_groups.setdefault(key, {
                "key": key,
                "target": finding.scope_key,
                "capability": finding.source_key,
                "title": finding.clause_name or finding.source_key or "技术问题",
                "findings": [],
            })
            group["findings"].append(payload)

    runs = (await db.execute(select(VerificationRun).where(
        VerificationRun.project_id == project_id
    ).order_by(VerificationRun.created_at.desc()).limit(30))).scalars().all()
    run_ids = [run.id for run in runs]
    run_items = (await db.execute(select(VerificationItem).where(
        VerificationItem.run_id.in_(run_ids)
    ).order_by(VerificationItem.id))).scalars().all() if run_ids else []
    by_run = {}
    for item in run_items:
        by_run.setdefault(item.run_id, []).append(item)

    counts = {"total": len(findings), "open": 0, "fixed": 0, "unable": 0}
    for finding in findings:
        key = _value(finding.status)
        if key in counts:
            counts[key] += 1
        if finding.judgment == Judgment.NOT_TESTED or (
            latest.get(finding.id) and latest[finding.id].outcome == VerificationOutcome.UNABLE
        ):
            counts["unable"] += 1
    return {
        "summary": counts,
        "execution_blockers": [{
            "task_id": task.id,
            "phase_id": phase.id,
            "phase": phase.name,
            "name": task.name,
            "error": (task.result or {}).get("error")
                or next((item.get("error") for item in (task.result or {}).get("failed", []) if item.get("error")), None)
                or "检测未可靠完成，请返回对应阶段重试",
        } for task, phase in blocker_rows],
        "document_groups": list(document_groups.values()),
        "technical_groups": list(technical_groups.values()),
        "runs": [_run_payload(run, by_run.get(run.id, [])) for run in runs],
    }


@router.post("/technical", status_code=status.HTTP_202_ACCEPTED)
async def technical_verification(
    project_id: int,
    request: TechnicalVerificationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "assessment:manage")
    findings = await _findings(db, project_id, request.finding_ids)
    if len(findings) != len(set(request.finding_ids)):
        raise HTTPException(status_code=404, detail="部分问题不存在或不属于当前项目")
    if any(finding.source_type != "technical" for finding in findings):
        raise HTTPException(status_code=400, detail="所选问题中包含非技术检测问题")
    if any(finding.status != FindingStatus.OPEN for finding in findings):
        raise HTTPException(status_code=400, detail="只能复测当前仍未解决的技术问题")
    try:
        run = await create_verification_run(
            db, project_id=project_id, findings=findings, source_type="technical",
            actor_id=current_user.id, notes=request.notes, credentials=request.credentials,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "queued", "message": f"已创建技术复测，共 {len(findings)} 个问题", "run_id": run.id}


async def _analysis_mode(db: AsyncSession, mode: str | None) -> str:
    if not mode or mode == "default":
        mode = await get_config_service(db).get("document.analysis_mode", settings.DOCUMENT_ANALYSIS_MODE)
    return normalize_analysis_mode(mode)


@router.post("/document", status_code=status.HTTP_202_ACCEPTED)
async def document_verification(
    project_id: int,
    finding_id: int = Form(...),
    notes: str = Form(""),
    replace_file_ids: str = Form("[]"),
    analysis_mode: str | None = Form(None),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "evidence:manage")
    finding = (await db.execute(select(Finding).where(
        Finding.id == finding_id, Finding.project_id == project_id,
    ))).scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="问题不存在")
    match = re.match(r"^DOC-TASK-(\d+)-", finding.clause_id or "")
    if finding.source_type != "document" or not match:
        raise HTTPException(status_code=400, detail="该问题不是文档合规问题")
    if finding.status != FindingStatus.OPEN:
        raise HTTPException(status_code=400, detail="只能复测当前仍未解决的文档问题")
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个改进后的文档")
    try:
        replace_ids = {int(value) for value in json.loads(replace_file_ids)}
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="replace_file_ids 必须是文件 ID 数组") from exc

    task_id = int(match.group(1))
    task = await db.get(TaskInstance, task_id)
    if not task:
        raise HTTPException(status_code=400, detail="原文档检查任务不存在")
    from app.services.flow_engine import get_flow_engine
    phase = await get_flow_engine(db).get_phase(task.phase_id)
    assessment = await get_flow_engine(db).get_assessment(phase.assessment_id) if phase else None
    if not assessment or assessment.project_id != project_id:
        raise HTTPException(status_code=400, detail="原文档检查任务不属于当前项目")
    if task.status == "in_progress":
        raise HTTPException(status_code=409, detail="该文档正在分析，请先停止或等待完成")

    active_documents = (await db.execute(select(DocumentFile).where(
        DocumentFile.assessment_id == assessment.id,
        DocumentFile.task_id == task.id,
        DocumentFile.is_active.is_(True),
    ))).scalars().all()
    active_by_id = {document.id: document for document in active_documents}
    if not replace_ids.issubset(active_by_id):
        raise HTTPException(status_code=400, detail="要替换的文件不属于当前文档检查")

    new_document_ids = []
    for upload in files:
        file_name = safe_document_name(upload.filename or "improved-document")
        suffix = Path(file_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            detail = "暂不支持旧版 DOC，请转换为 DOCX 或 PDF" if suffix == ".doc" else f"不支持的文件格式：{suffix or '未知'}"
            raise HTTPException(status_code=415, detail=detail)
        try:
            content = await read_limited_upload(upload, MAX_VERIFICATION_UPLOAD_SIZE, SUPPORTED_SUFFIXES)
        except ValueError as exc:
            raise HTTPException(status_code=413 if "超过" in str(exc) else 400, detail=str(exc)) from exc
        path, digest, size = await file_storage.save_file(project_id, file_name, content)
        duplicate = next((document for document in active_documents if document.sha256 == digest and document.id not in replace_ids), None)
        if duplicate:
            await file_storage.delete_file(path)
            new_document_ids.append(duplicate.id)
            continue
        document = DocumentFile(
            project_id=project_id,
            assessment_id=assessment.id,
            task_id=task.id,
            original_name=file_name,
            storage_path=path,
            size_bytes=size,
            mime_type=upload.content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
            sha256=digest,
            parse_status="queued",
        )
        db.add(document)
        await db.flush()
        new_document_ids.append(document.id)

    for file_id in replace_ids:
        document = active_by_id[file_id]
        document.is_active = False
        document.replaced_by_id = new_document_ids[0] if new_document_ids else None
        await db.execute(DocumentBlock.__table__.update().where(
            DocumentBlock.document_file_id == document.id
        ).values(is_active=False, embedding=None))
        from app.services.knowledge_graph import knowledge_graph
        await knowledge_graph.purge_file(db, document.id)

    try:
        verification, run, active_ids, group_size = await queue_document_task_verification(
            db,
            project_id=project_id,
            task=task,
            actor_id=current_user.id,
            notes=notes,
            analysis_mode=await _analysis_mode(db, analysis_mode),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "queued",
        "message": f"改进文档已提交，将重新检查本类文档的 {group_size} 个问题",
        "verification_run_id": verification.id,
        "document_run_id": run.id,
        "document_file_ids": active_ids,
    }


@router.post("/document/reanalyze", status_code=status.HTTP_202_ACCEPTED)
async def reanalyze_verification_document(
    project_id: int,
    request: DocumentReanalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "evidence:manage")
    finding = (await db.execute(select(Finding).where(
        Finding.id == request.finding_id,
        Finding.project_id == project_id,
        Finding.source_type == "document",
        Finding.status == FindingStatus.OPEN,
    ))).scalar_one_or_none()
    match = re.match(r"^DOC-TASK-(\d+)-", finding.clause_id or "") if finding else None
    if not finding or not match:
        raise HTTPException(status_code=400, detail="没有可重新分析的文档问题")
    task = await db.get(TaskInstance, int(match.group(1)))
    if not task:
        raise HTTPException(status_code=400, detail="原文档检查任务不存在")
    from app.services.flow_engine import get_flow_engine
    phase = await get_flow_engine(db).get_phase(task.phase_id)
    assessment = await get_flow_engine(db).get_assessment(phase.assessment_id) if phase else None
    if not assessment or assessment.project_id != project_id:
        raise HTTPException(status_code=400, detail="原文档检查任务不属于当前项目")
    if task.status == "in_progress":
        raise HTTPException(status_code=409, detail="该文档正在分析，请等待完成")
    try:
        verification, run, active_ids, group_size = await queue_document_task_verification(
            db,
            project_id=project_id,
            task=task,
            actor_id=current_user.id,
            notes=request.notes,
            analysis_mode=await _analysis_mode(db, request.analysis_mode),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "queued",
        "message": f"已使用现有材料重新分析 {group_size} 个问题",
        "verification_run_id": verification.id,
        "document_run_id": run.id,
        "document_file_ids": active_ids,
    }


@router.post("/findings/{finding_id}/reopen")
async def reopen_finding_api(
    project_id: int,
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "assessment:manage")
    finding = (await db.execute(select(Finding).where(
        Finding.id == finding_id, Finding.project_id == project_id,
    ))).scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="问题不存在")
    await reopen_finding(db, finding, current_user.id)
    await db.commit()
    return {"status": "open", "finding_id": finding.id}


@router.post("/runs/{run_id}/stop")
async def stop_verification_run(
    project_id: int,
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "assessment:manage")
    run = await db.get(VerificationRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="复测运行不存在")
    if run.status not in {VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING}:
        raise HTTPException(status_code=409, detail="该复测已经结束")
    run.cancel_requested_at = datetime.utcnow()
    await db.commit()
    return {"status": "stopping", "run_id": run.id}


@router.post("/runs/{run_id}/resume")
async def resume_verification_run(
    project_id: int,
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "assessment:manage")
    run = await db.get(VerificationRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="复测运行不存在")
    if run.status not in {VerificationRunStatus.CANCELLED, VerificationRunStatus.FAILED, VerificationRunStatus.PARTIAL}:
        raise HTTPException(status_code=409, detail="该复测当前不能继续")
    items = (await db.execute(select(VerificationItem).where(
        VerificationItem.run_id == run.id,
        VerificationItem.outcome.in_([VerificationOutcome.CANCELLED, VerificationOutcome.UNABLE]),
    ))).scalars().all()
    if not items:
        raise HTTPException(status_code=409, detail="没有可继续的未完成复测项")
    for item in items:
        item.outcome = VerificationOutcome.QUEUED
        item.error_message = None
        item.started_at = None
        item.completed_at = None
    run.status = VerificationRunStatus.QUEUED
    run.cancel_requested_at = None
    run.completed_at = None
    run.lease_owner = None
    run.lease_expires_at = None
    await db.commit()
    return {"status": "queued", "run_id": run.id}


@router.get("/runs/{run_id}")
async def get_verification_run(
    project_id: int,
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "assessment:read")
    run = await db.get(VerificationRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="复测运行不存在")
    items = (await db.execute(select(VerificationItem).where(
        VerificationItem.run_id == run.id
    ).order_by(VerificationItem.id))).scalars().all()
    return _run_payload(run, items)


@router.get("/findings/{finding_id}/events")
async def finding_events(
    project_id: int,
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_project(db, project_id, current_user, "assessment:read")
    finding = await db.get(Finding, finding_id)
    if not finding or finding.project_id != project_id:
        raise HTTPException(status_code=404, detail="问题不存在")
    events = (await db.execute(select(FindingEvent).where(
        FindingEvent.finding_id == finding_id
    ).order_by(FindingEvent.created_at.desc()))).scalars().all()
    return [{
        "id": event.id,
        "event_type": event.event_type,
        "event_data": event.event_data or {},
        "actor_id": event.actor_id,
        "created_at": event.created_at,
    } for event in events]
