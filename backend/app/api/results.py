from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, delete, or_, select
from typing import List

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.scan_task import ScanTask, ScanTaskStatus
from app.models.finding import Finding
from app.models.evidence import Evidence
from app.models.document_knowledge import DocumentBlock, DocumentFile
from app.models.monitoring import ScanHistory
from app.models.change_snapshot import ChangeSnapshot
from app.services.audit import record_audit_event
from app.services.file_storage import file_storage
from app.services.verification_service import delete_verification_data
from app.services.execution_engine import ExecutionEngine, load_scan_finding_stats
from app.schemas.result import (
    ScanTaskResponse,
    ScanTaskDetail,
    FindingResponse,
    FindingDetail,
    EvidenceResponse,
    ResultSummary,
)

router = APIRouter(prefix="/results", tags=["Results"])


class BulkDeleteScansRequest(BaseModel):
    scan_task_ids: List[int] = Field(default_factory=list, max_length=1000)
    delete_all: bool = False


def _visible_findings(scan_task_id: int):
    return select(Finding).where(
        Finding.scan_task_id == scan_task_id,
        ~and_(
            Finding.clause_name == "自动化技术检测",
            Finding.description.like("%检测未完成（不代表通过）%"),
        ),
    )


def _scan_task_response(scan_task: ScanTask, finding_stats: dict) -> ScanTaskResponse:
    descriptor = ExecutionEngine._scan_task_descriptor(scan_task, finding_stats)
    return ScanTaskResponse.model_validate(scan_task).model_copy(update={
        key: descriptor[key]
        for key in (
            "findings_count", "confirmed_count", "unverified_count", "incomplete_checks_count",
            "conclusion_status", "conclusion_label", "conclusion_summary",
        )
    })


async def _delete_scan_records(db: AsyncSession, scan_task_ids: list[int]) -> tuple[list[str], int]:
    findings = (await db.execute(select(Finding).where(Finding.scan_task_id.in_(scan_task_ids)))).scalars().all()
    finding_ids = [finding.id for finding in findings]
    file_paths = []
    file_bytes = 0
    if finding_ids:
        evidences = (await db.execute(select(Evidence).where(Evidence.finding_id.in_(finding_ids)))).scalars().all()
        file_paths = [evidence.file_path for evidence in evidences if evidence.file_path]
        file_bytes = sum(evidence.file_size or 0 for evidence in evidences if evidence.file_path)
        await delete_verification_data(db, findings[0].project_id, finding_ids)
        await db.execute(delete(Evidence).where(Evidence.finding_id.in_(finding_ids)))
        await db.execute(delete(Finding).where(Finding.id.in_(finding_ids)))
    await db.execute(delete(ScanHistory).where(ScanHistory.scan_task_id.in_(scan_task_ids)))
    await db.execute(delete(ChangeSnapshot).where(ChangeSnapshot.scan_task_id.in_(scan_task_ids)))
    await db.execute(delete(ScanTask).where(ScanTask.id.in_(scan_task_ids)))
    return file_paths, file_bytes


async def _finish_file_cleanup(file_paths: list[str]) -> int:
    deleted = 0
    for file_path in file_paths:
        deleted += bool(await file_storage.delete_file(file_path))
    return deleted


@router.get("/projects/{project_id}/scans", response_model=List[ScanTaskResponse])
async def list_scan_tasks(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目的所有扫描任务"""
    # 验证项目存在且用户有权限访问
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "scan:read")
    
    # 获取扫描任务列表
    result = await db.execute(
        select(ScanTask)
        .where(ScanTask.project_id == project_id)
        .order_by(ScanTask.created_at.desc())
    )
    scan_tasks = result.scalars().all()
    finding_stats = await load_scan_finding_stats(db, scan_tasks)
    return [_scan_task_response(task, finding_stats[task.id]) for task in scan_tasks]


@router.get("/scans/{scan_task_id}", response_model=ScanTaskDetail)
async def get_scan_task(
    scan_task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取扫描任务详情"""
    result = await db.execute(
        select(ScanTask).where(ScanTask.id == scan_task_id)
    )
    scan_task = result.scalar_one_or_none()
    
    if not scan_task:
        raise HTTPException(status_code=404, detail="Scan task not found")
    
    # 验证项目属于当前用户
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, scan_task.project_id, current_user.id, "scan:read")
    
    # 获取 findings
    result = await db.execute(_visible_findings(scan_task_id))
    findings = result.scalars().all()
    
    # 构建响应
    finding_stats = await load_scan_finding_stats(db, [scan_task])
    response = _scan_task_response(scan_task, finding_stats[scan_task.id])
    return ScanTaskDetail(
        **response.model_dump(),
        findings=[FindingResponse.model_validate(f) for f in findings],
    )


@router.get("/scans/{scan_task_id}/summary", response_model=ResultSummary)
async def get_scan_summary(
    scan_task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取扫描结果摘要"""
    result = await db.execute(
        select(ScanTask).where(ScanTask.id == scan_task_id)
    )
    scan_task = result.scalar_one_or_none()
    
    if not scan_task:
        raise HTTPException(status_code=404, detail="Scan task not found")
    
    # 验证项目属于当前用户
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, scan_task.project_id, current_user.id, "scan:read")
    
    # 获取 findings
    result = await db.execute(_visible_findings(scan_task_id))
    findings = result.scalars().all()
    
    # 统计
    passed = sum(1 for f in findings if f.judgment.value == "pass")
    failed = sum(1 for f in findings if f.judgment.value == "fail")
    partial = sum(1 for f in findings if f.judgment.value == "partial")
    
    return ResultSummary(
        scan_task=_scan_task_response(scan_task, (await load_scan_finding_stats(db, [scan_task]))[scan_task.id]),
        findings=[FindingResponse.model_validate(f) for f in findings],
        total_findings=len(findings),
        passed=passed,
        failed=failed,
        partial=partial,
        compliance_score=project.compliance_score,
    )


@router.get("/findings/{finding_id}", response_model=FindingDetail)
async def get_finding(
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 Finding 详情"""
    result = await db.execute(
        select(Finding).where(Finding.id == finding_id)
    )
    finding = result.scalar_one_or_none()
    
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    
    # 验证项目属于当前用户
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, finding.project_id, current_user.id, "scan:read")
    
    # 获取 evidences
    evidence_ids = [value for value in (finding.evidence_ids or []) if isinstance(value, int)]
    evidence_filter = Evidence.finding_id == finding_id
    if evidence_ids and not finding.document_run_id:
        evidence_filter = or_(evidence_filter, Evidence.id.in_(evidence_ids))
    result = await db.execute(select(Evidence).where(evidence_filter))
    evidences = result.scalars().all()

    document_evidences = []
    if finding.document_run_id and evidence_ids:
        rows = (await db.execute(
            select(DocumentBlock, DocumentFile)
            .join(DocumentFile, DocumentFile.id == DocumentBlock.document_file_id)
            .where(
                DocumentBlock.analysis_run_id == finding.document_run_id,
                DocumentBlock.id.in_(evidence_ids),
            )
            .order_by(DocumentFile.original_name, DocumentBlock.page_number, DocumentBlock.ordinal)
        )).all()
        document_evidences = [{
            "block_id": block.id,
            "document_file_id": document.id,
            "file_name": document.original_name,
            "page": block.page_number,
            "section": block.section_path,
            "type": block.block_type,
            "source": block.source,
            "confidence": block.source_confidence,
            "bbox": block.bbox,
            "text": block.text,
            "table": block.table_data,
        } for block, document in rows]
    
    # 构建响应
    response = FindingResponse.model_validate(finding)
    return FindingDetail(
        **response.model_dump(),
        evidences=[EvidenceResponse.model_validate(e) for e in evidences],
        document_evidences=document_evidences,
    )


@router.get("/evidences/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 Evidence 详情"""
    result = await db.execute(
        select(Evidence).where(Evidence.id == evidence_id)
    )
    evidence = result.scalar_one_or_none()
    
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    
    # 验证项目属于当前用户
    result = await db.execute(
        select(Finding).where(Finding.id == evidence.finding_id)
    )
    finding = result.scalar_one_or_none()
    
    from app.api.projects import get_project_for_user
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    await get_project_for_user(db, finding.project_id, current_user.id, "scan:read")
    
    return evidence


@router.post("/projects/{project_id}/scans/bulk-delete")
async def bulk_delete_scan_tasks(
    project_id: int,
    payload: BulkDeleteScansRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, project_id, current_user.id, "scan:cancel")

    query = select(ScanTask).where(ScanTask.project_id == project_id)
    if not payload.delete_all:
        requested_ids = sorted(set(payload.scan_task_ids))
        if not requested_ids:
            raise HTTPException(status_code=400, detail="请选择要删除的检测记录")
        query = query.where(ScanTask.id.in_(requested_ids))
    tasks = (await db.execute(query)).scalars().all()
    if not payload.delete_all and len(tasks) != len(set(payload.scan_task_ids)):
        raise HTTPException(status_code=404, detail="部分检测记录不存在或不属于当前项目")

    active = [task for task in tasks if task.status in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING)]
    active_ids = {task.id for task in active}
    if active and not payload.delete_all:
        raise HTTPException(status_code=409, detail="运行中或等待中的检测不能删除，请先停止任务")
    task_ids = [task.id for task in tasks if task.id not in active_ids]
    if not task_ids:
        return {"deleted_count": 0, "deleted_ids": [], "skipped_active_count": len(active), "deleted_file_count": 0, "released_file_bytes": 0}

    file_paths, file_bytes = await _delete_scan_records(db, task_ids)
    await record_audit_event(
        db,
        event_type="scan_results.bulk_deleted",
        resource_type="project",
        resource_id=project_id,
        actor_user_id=current_user.id,
        organization_id=project.organization_id,
        project_id=project_id,
        details={
            "deleted_count": len(task_ids),
            "delete_all": payload.delete_all,
            "skipped_active_count": len(active),
            "attachment_file_count": len(file_paths),
            "attachment_bytes": file_bytes,
        },
    )
    await db.commit()
    deleted_file_count = await _finish_file_cleanup(file_paths)
    return {
        "deleted_count": len(task_ids),
        "deleted_ids": task_ids,
        "skipped_active_count": len(active),
        "deleted_file_count": deleted_file_count,
        "released_file_bytes": file_bytes,
    }


@router.delete("/scans/{scan_task_id}")
async def delete_scan_task(
    scan_task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除扫描任务及其关联数据"""
    # 获取扫描任务
    result = await db.execute(
        select(ScanTask).where(ScanTask.id == scan_task_id)
    )
    scan_task = result.scalar_one_or_none()
    
    if not scan_task:
        raise HTTPException(status_code=404, detail="Scan task not found")
    
    # 验证项目属于当前用户
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, scan_task.project_id, current_user.id, "scan:cancel")
    
    if scan_task.status in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING):
        raise HTTPException(status_code=409, detail="运行中或等待中的检测不能删除，请先停止任务")
    file_paths, file_bytes = await _delete_scan_records(db, [scan_task_id])
    await record_audit_event(
        db,
        event_type="scan_result.deleted",
        resource_type="scan_task",
        resource_id=scan_task_id,
        actor_user_id=current_user.id,
        organization_id=project.organization_id,
        project_id=scan_task.project_id,
        details={"attachment_file_count": len(file_paths), "attachment_bytes": file_bytes},
    )
    await db.commit()
    deleted_file_count = await _finish_file_cleanup(file_paths)
    
    return {"message": "检测记录已删除", "deleted_file_count": deleted_file_count, "released_file_bytes": file_bytes}
