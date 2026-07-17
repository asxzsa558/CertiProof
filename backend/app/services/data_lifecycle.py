"""Scoped business-data cleanup and logical storage telemetry."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.assessment import Assessment, FlowEvent, PhaseInstance, TaskInstance
from app.models.assessment_type import ProjectAssessment
from app.models.asset import Asset
from app.models.audit import AuditEvent
from app.models.change_snapshot import ChangeSnapshot
from app.models.context import (
    ActionHistory,
    ConversationArchive,
    ConversationHistory,
    ConversationSummary,
    ConversationThread,
    ProjectMemory,
    ResultCache,
)
from app.models.document_knowledge import DocumentAnalysisRun, DocumentBlock, DocumentFile
from app.models.evidence import Evidence
from app.models.finding import Finding
from app.models.monitoring import ScanHistory, ScheduledScan
from app.models.organization import Organization, OrganizationMember, OrganizationRole, OrganizationRoleAudit
from app.models.project import Project
from app.models.questionnaire import QuestionnaireRecord
from app.models.report import ReportArtifact
from app.models.scan_task import ScanTask, ScanTaskStatus
from app.services.file_storage import file_storage
from app.services.knowledge_graph import knowledge_graph
from app.services.flow_engine import workflow_progress
from app.services.verification_service import delete_verification_data


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")) if value is not None else 0


async def storage_usage(db: AsyncSession, project_ids: Iterable[int]) -> dict[str, Any]:
    project_ids = list(dict.fromkeys(int(value) for value in project_ids))
    if not project_ids:
        return _storage_payload({})

    document_count, document_bytes = (await db.execute(select(
        func.count(DocumentFile.id),
        func.coalesce(func.sum(DocumentFile.size_bytes), 0),
    ).where(DocumentFile.project_id.in_(project_ids)))).one()
    evidence_count, evidence_bytes = (await db.execute(select(
        func.count(Evidence.id),
        func.coalesce(func.sum(Evidence.file_size), 0),
    ).where(Evidence.project_id.in_(project_ids), Evidence.file_path.is_not(None)))).one()
    block_count = int((await db.execute(select(func.count(DocumentBlock.id)).where(
        DocumentBlock.project_id.in_(project_ids)
    ))).scalar_one())
    vector_count = int((await db.execute(select(func.count(DocumentBlock.id)).where(
        DocumentBlock.project_id.in_(project_ids), DocumentBlock.embedding.is_not(None)
    ))).scalar_one())
    scan_count = int((await db.execute(select(func.count(ScanTask.id)).where(
        ScanTask.project_id.in_(project_ids)
    ))).scalar_one())
    report_count, report_bytes = (await db.execute(select(
        func.count(ReportArtifact.id),
        func.coalesce(func.sum(ReportArtifact.html_size), 0),
    ).where(ReportArtifact.project_id.in_(project_ids)))).one()

    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        parsed_bytes = int((await db.execute(select(func.coalesce(func.sum(
            func.octet_length(DocumentBlock.text)
            + func.coalesce(func.pg_column_size(DocumentBlock.table_data), 0)
            + func.coalesce(func.pg_column_size(DocumentBlock.bbox), 0)
            + func.coalesce(func.pg_column_size(DocumentBlock.metadata_json), 0)
        ), 0)).where(DocumentBlock.project_id.in_(project_ids)))).scalar_one())
        vector_bytes = int((await db.execute(select(func.coalesce(func.sum(
            func.pg_column_size(DocumentBlock.embedding)
        ), 0)).where(
            DocumentBlock.project_id.in_(project_ids), DocumentBlock.embedding.is_not(None)
        ))).scalar_one())
        scan_bytes = int((await db.execute(select(func.coalesce(func.sum(
            func.coalesce(func.pg_column_size(ScanTask.parameters), 0)
            + func.coalesce(func.pg_column_size(ScanTask.progress), 0)
            + func.coalesce(func.pg_column_size(ScanTask.result_summary), 0)
        ), 0)).where(ScanTask.project_id.in_(project_ids)))).scalar_one())
    else:
        blocks = (await db.execute(select(
            DocumentBlock.text,
            DocumentBlock.table_data,
            DocumentBlock.bbox,
            DocumentBlock.metadata_json,
        ).where(DocumentBlock.project_id.in_(project_ids)))).all()
        parsed_bytes = sum(
            len((row.text or "").encode("utf-8"))
            + _json_bytes(row.table_data)
            + _json_bytes(row.bbox)
            + _json_bytes(row.metadata_json)
            for row in blocks
        )
        vector_bytes = vector_count * settings.DOCUMENT_EMBEDDING_DIMENSION * 4
        scans = (await db.execute(select(
            ScanTask.parameters, ScanTask.progress, ScanTask.result_summary
        ).where(ScanTask.project_id.in_(project_ids)))).all()
        scan_bytes = sum(_json_bytes(row.parameters) + _json_bytes(row.progress) + _json_bytes(row.result_summary) for row in scans)

    return _storage_payload({
        "original_files": {"bytes": int(document_bytes or 0) + int(evidence_bytes or 0), "count": int(document_count) + int(evidence_count)},
        "parsed_content": {"bytes": parsed_bytes, "count": block_count},
        "vectors": {"bytes": vector_bytes, "count": vector_count},
        "scan_results": {"bytes": scan_bytes, "count": scan_count},
        "reports": {"bytes": int(report_bytes or 0), "count": int(report_count or 0)},
    })


def _storage_payload(values: dict[str, dict[str, int]]) -> dict[str, Any]:
    categories = {
        "original_files": {"bytes": 0, "count": 0, "label": "原文件与证据附件"},
        "parsed_content": {"bytes": 0, "count": 0, "label": "解析内容块"},
        "vectors": {"bytes": 0, "count": 0, "label": "语义向量"},
        "ocr_cache": {"bytes": 0, "count": 0, "label": "OCR 临时缓存", "transient": True},
        "scan_results": {"bytes": 0, "count": 0, "label": "检测结果"},
        "reports": {"bytes": 0, "count": 0, "label": "HTML 报告"},
    }
    for key, value in values.items():
        categories[key].update(value)
    return {
        "categories": categories,
        "total_bytes": sum(int(item["bytes"]) for item in categories.values()),
        "notes": {
            "ocr_cache": "OCR 临时文件随请求自动释放，不形成长期存储。",
            "reports": "HTML 报告按版本保存；新检测或整改材料会将当前版本标记为过期。",
            "vectors": "向量容量为数据库逻辑占用，不含共享索引页。",
        },
    }


async def delete_storage_files(paths: Iterable[str]) -> dict[str, Any]:
    unique_paths = [path for path in dict.fromkeys(paths) if path]
    failed = []
    deleted = 0
    for path in unique_paths:
        for attempt in range(3):
            if await file_storage.delete_file(path):
                deleted += 1
                break
            if attempt < 2:
                await asyncio.sleep(0.2 * (attempt + 1))
        else:
            failed.append(path)
    return {"deleted_file_count": deleted, "failed_file_paths": failed}


async def clear_project_documents(db: AsyncSession, project_id: int) -> dict[str, Any]:
    active = int((await db.execute(select(func.count(DocumentAnalysisRun.id)).where(
        DocumentAnalysisRun.project_id == project_id,
        DocumentAnalysisRun.status.in_(["queued", "running"]),
    ))).scalar_one())
    if active:
        raise ValueError(f"仍有 {active} 个文档分析任务运行中，请等待完成后再清理")

    documents = (await db.execute(select(
        DocumentFile.id, DocumentFile.storage_path, DocumentFile.size_bytes
    ).where(DocumentFile.project_id == project_id))).all()
    run_ids = list((await db.execute(select(DocumentAnalysisRun.id).where(
        DocumentAnalysisRun.project_id == project_id
    ))).scalars().all())
    task_rows = (await db.execute(select(TaskInstance, PhaseInstance, Assessment)
        .join(PhaseInstance, PhaseInstance.id == TaskInstance.phase_id)
        .join(Assessment, Assessment.id == PhaseInstance.assessment_id)
        .where(Assessment.project_id == project_id, TaskInstance.task_type == "doc_review")
    )).all()
    task_ids = [task.id for task, _, _ in task_rows]

    finding_filter = Finding.project_id == project_id
    scopes = []
    if run_ids:
        scopes.append(Finding.document_run_id.in_(run_ids))
    if task_ids:
        scopes.extend(Finding.clause_id.like(f"DOC-TASK-{task_id}-%") for task_id in task_ids)
    finding_ids = list((await db.execute(select(Finding.id).where(
        finding_filter, or_(*scopes)
    ))).scalars().all()) if scopes else []
    evidence_paths = []
    if finding_ids:
        evidence_paths = list((await db.execute(select(Evidence.file_path).where(
            Evidence.finding_id.in_(finding_ids), Evidence.file_path.is_not(None)
        ))).scalars().all())
        await delete_verification_data(db, project_id, finding_ids)
        await db.execute(delete(Evidence).where(Evidence.finding_id.in_(finding_ids)))
        await db.execute(delete(Finding).where(Finding.id.in_(finding_ids)))

    await db.execute(delete(DocumentAnalysisRun).where(DocumentAnalysisRun.project_id == project_id))
    await db.execute(delete(DocumentFile).where(DocumentFile.project_id == project_id))
    await knowledge_graph.purge_project(db, project_id)

    phases: dict[int, tuple[PhaseInstance, Assessment]] = {}
    for task, phase, assessment in task_rows:
        task.status = "todo"
        task.started_at = None
        task.completed_at = None
        task.result = None
        task.evidence_ids = None
        phases[phase.id] = (phase, assessment)
    for phase, assessment in phases.values():
        tasks = (await db.execute(select(TaskInstance).where(TaskInstance.phase_id == phase.id))).scalars().all()
        phase.completed_tasks = sum(task.status in {"completed", "cancelled"} for task in tasks)
        phase.progress = phase.completed_tasks / phase.total_tasks * 100 if phase.total_tasks else 0
        if phase.status in {"completed", "failed"}:
            phase.status = "pending"
            phase.completed_at = None
        assessment_phases = list((await db.execute(select(PhaseInstance).where(
            PhaseInstance.assessment_id == assessment.id,
        ))).scalars().all())
        assessment.completed_phases = sum(item.status == "completed" for item in assessment_phases)
        assessment.progress = workflow_progress(assessment_phases)
        if assessment.status == "completed":
            assessment.status = "in_progress"
            assessment.completed_at = None

    project = await db.get(Project, project_id)
    if project:
        project.compliance_score = None
    return {
        "deleted_documents": len(documents),
        "deleted_runs": len(run_ids),
        "deleted_findings": len(finding_ids),
        "released_file_bytes": sum(int(row.size_bytes or 0) for row in documents),
        "file_paths": [row.storage_path for row in documents] + evidence_paths,
    }


async def delete_project_records(db: AsyncSession, project: Project) -> dict[str, Any]:
    project_id = project.id
    active_scans = int((await db.execute(select(func.count(ScanTask.id)).where(
        ScanTask.project_id == project_id,
        ScanTask.status.in_([ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING]),
    ))).scalar_one())
    active_documents = int((await db.execute(select(func.count(DocumentAnalysisRun.id)).where(
        DocumentAnalysisRun.project_id == project_id,
        DocumentAnalysisRun.status.in_(["queued", "running"]),
    ))).scalar_one())
    if active_scans or active_documents:
        raise ValueError(f"项目仍有运行任务：检测 {active_scans} 个，文档分析 {active_documents} 个")

    documents = (await db.execute(select(DocumentFile.storage_path, DocumentFile.size_bytes).where(
        DocumentFile.project_id == project_id
    ))).all()
    evidence_files = (await db.execute(select(Evidence.file_path, Evidence.file_size).where(
        Evidence.project_id == project_id, Evidence.file_path.is_not(None)
    ))).all()
    report_files = (await db.execute(select(ReportArtifact.html_path, ReportArtifact.html_size).where(
        ReportArtifact.project_id == project_id
    ))).all()
    await knowledge_graph.purge_project(db, project_id)

    assessment_ids = list((await db.execute(select(Assessment.id).where(Assessment.project_id == project_id))).scalars().all())
    phase_ids = list((await db.execute(select(PhaseInstance.id).where(
        PhaseInstance.assessment_id.in_(assessment_ids)
    ))).scalars().all()) if assessment_ids else []
    scheduled_ids = list((await db.execute(select(ScheduledScan.id).where(
        ScheduledScan.project_id == project_id
    ))).scalars().all())
    finding_ids = select(Finding.id).where(Finding.project_id == project_id)
    questionnaire_ids = select(QuestionnaireRecord.id).where(QuestionnaireRecord.project_id == project_id)

    await delete_verification_data(db, project_id)
    await db.execute(delete(Evidence).where(Evidence.project_id == project_id))
    await db.execute(delete(Evidence).where(Evidence.finding_id.in_(finding_ids)))
    await db.execute(delete(Evidence).where(Evidence.questionnaire_record_id.in_(questionnaire_ids)))
    await db.execute(delete(QuestionnaireRecord).where(QuestionnaireRecord.project_id == project_id))
    await db.execute(delete(Finding).where(Finding.project_id == project_id))
    await db.execute(delete(ProjectAssessment).where(ProjectAssessment.project_id == project_id))
    await db.execute(delete(ReportArtifact).where(ReportArtifact.project_id == project_id))
    await db.execute(delete(DocumentAnalysisRun).where(DocumentAnalysisRun.project_id == project_id))
    await db.execute(delete(DocumentFile).where(DocumentFile.project_id == project_id))
    if assessment_ids:
        await db.execute(delete(FlowEvent).where(FlowEvent.assessment_id.in_(assessment_ids)))
    if phase_ids:
        await db.execute(delete(TaskInstance).where(TaskInstance.phase_id.in_(phase_ids)))
        await db.execute(delete(PhaseInstance).where(PhaseInstance.id.in_(phase_ids)))
    await db.execute(delete(Assessment).where(Assessment.project_id == project_id))
    if scheduled_ids:
        await db.execute(delete(ScanHistory).where(ScanHistory.scheduled_scan_id.in_(scheduled_ids)))
    await db.execute(delete(ScheduledScan).where(ScheduledScan.project_id == project_id))
    await db.execute(delete(ChangeSnapshot).where(ChangeSnapshot.project_id == project_id))
    await db.execute(delete(ScanTask).where(ScanTask.project_id == project_id))
    await db.execute(delete(Asset).where(Asset.project_id == project_id))
    await db.execute(delete(ProjectMemory).where(ProjectMemory.project_id == project_id))
    await db.execute(delete(ResultCache).where(ResultCache.project_id == project_id))
    await db.execute(delete(ActionHistory).where(ActionHistory.project_id == project_id))
    await db.execute(delete(ConversationHistory).where(ConversationHistory.project_id == project_id))
    await db.execute(delete(ConversationSummary).where(ConversationSummary.project_id == project_id))
    await db.execute(update(ConversationThread).where(ConversationThread.project_id == project_id).values(
        source_archive_id=None, parent_thread_id=None
    ))
    await db.execute(delete(ConversationArchive).where(ConversationArchive.project_id == project_id))
    await db.execute(delete(ConversationThread).where(ConversationThread.project_id == project_id))
    await db.execute(update(AuditEvent).where(AuditEvent.project_id == project_id).values(project_id=None))
    await db.delete(project)
    return {
        "project_id": project_id,
        "file_paths": [row.storage_path for row in documents] + [row.file_path for row in evidence_files] + [row.html_path for row in report_files],
        "released_file_bytes": (
            sum(int(row.size_bytes or 0) for row in documents)
            + sum(int(row.file_size or 0) for row in evidence_files)
            + sum(int(row.html_size or 0) for row in report_files)
        ),
    }


async def delete_organization_records(db: AsyncSession, organization: Organization) -> dict[str, Any]:
    """Delete an organization and all owned business data without FK leaks."""
    organization_id = organization.id
    projects = list((await db.execute(select(Project).where(
        Project.organization_id == organization_id
    ))).scalars().all())
    cleanups = [await delete_project_records(db, project) for project in projects]

    await db.execute(update(AuditEvent).where(
        AuditEvent.organization_id == organization_id
    ).values(organization_id=None))
    await db.execute(delete(OrganizationRoleAudit).where(
        OrganizationRoleAudit.organization_id == organization_id
    ))
    await db.execute(delete(OrganizationMember).where(
        OrganizationMember.organization_id == organization_id
    ))
    await db.execute(delete(OrganizationRole).where(
        OrganizationRole.organization_id == organization_id
    ))
    await db.delete(organization)
    return {
        "organization_id": organization_id,
        "deleted_projects": len(cleanups),
        "file_paths": [path for item in cleanups for path in item["file_paths"]],
        "released_file_bytes": sum(item["released_file_bytes"] for item in cleanups),
    }
