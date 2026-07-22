"""HTML/JSON report service for CertiProof self-assessment."""

import ast
from datetime import datetime, timezone
from html import escape
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from app.models.project import Project
from app.models.asset import Asset
from app.models.scan_task import ScanTask, ScanTaskStatus
from app.models.finding import Finding
from app.models.evidence import Evidence
from app.models.assessment import Assessment, PhaseInstance, TaskInstance
from app.models.verification import FindingEvent, VerificationItem, VerificationRun, VerificationRunStatus
from app.models.change_snapshot import ChangeSnapshot
from app.models.document_knowledge import DocumentAnalysisRun, DocumentBlock, DocumentFile
from app.models.report import ReportArtifact
from app.services.assessment_templates import LEVEL_3_TEMPLATE, TASK_TYPES
from app.services.verification_service import controlled_remediation_plan, scrub_sensitive_parameters
from app.services.file_storage import file_storage
from app.services.flow_engine import get_flow_engine, workflow_progress


def _value(value):
    return value.value if hasattr(value, "value") else value


def _dt(value):
    return value.isoformat() if value else None


def _duration_days(start, end):
    if not start or not end:
        return None
    def utc_naive(value):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value

    return max(0, (utc_naive(end) - utc_naive(start)).days)


CAPABILITY_LABELS = {
    "scan_ports": "端口扫描",
    "fast_scan": "高速端口扫描",
    "ping_asset": "主机存活检测",
    "scan_ssl": "SSL/TLS 检测",
    "testssl_scan": "SSL/TLS 检测",
    "scan_vulnerabilities": "漏洞扫描",
    "nuclei_scan": "漏洞扫描",
    "scan_weak_passwords": "弱口令检测",
    "hydra_bruteforce": "弱口令检测",
    "nikto_scan": "Web 深度扫描",
    "directory_scan": "目录扫描",
    "baseline_check": "安全基线检查",
}

ASSESSMENT_PHASE_BY_TASK_TYPE = {
    task["type"]: phase["name"]
    for phase in LEVEL_3_TEMPLATE["phases_config"]
    for task in phase.get("default_tasks", [])
}


def _scan_entries(task: dict) -> list[dict]:
    summary = task.get("result_summary") or {}
    return [
        item for key in ("results", "warnings", "failed")
        for item in summary.get(key) or []
        if isinstance(item, dict)
    ]


def _scan_payloads(task: dict) -> list[dict]:
    summary = task.get("result_summary") or {}
    payloads = [summary.get("data")] if isinstance(summary.get("data"), dict) else []
    payloads.extend(
        item["result"] for item in _scan_entries(task)
        if isinstance(item.get("result"), dict)
    )
    return payloads


def _structured_issue_text(item: dict) -> str:
    item_id = str(item.get("id") or "").strip()
    finding = str(item.get("finding") or "").strip()
    if item_id == "overall_grade" and finding:
        return f"testssl 总体评级：{finding}（工具原始等级）"
    if item_id and finding:
        return f"{item_id}: {finding}"
    return str(item.get("description") or item.get("title") or item.get("name") or finding or item_id or "未命名项")


def _readable_observation(value) -> str:
    text = str(value or "-")
    if "overall_grade:" in text:
        prefix, grade = text.split("overall_grade:", 1)
        return f"{prefix}testssl 总体评级：{grade.strip()}（工具原始等级）"
    marker = text.find("{")
    if marker < 0:
        return text
    try:
        item = ast.literal_eval(text[marker:])
    except (SyntaxError, ValueError):
        return text
    if not isinstance(item, dict):
        return text
    prefix = text[:marker].rstrip(": ")
    detail = _structured_issue_text(item)
    return f"{prefix}: {detail}" if prefix else detail

def _scan_name(task: dict) -> str:
    parameters = task.get("parameters") or {}
    assessment_task_type = parameters.get("task_type") or (task.get("result_summary") or {}).get("task_type")
    task_type_label = (TASK_TYPES.get(assessment_task_type) or {}).get("name")
    capabilities = []
    for item in [parameters.get("capability"), *(parameters.get("capabilities") or [])]:
        if item and item not in capabilities:
            capabilities.append(item)
    for entry in _scan_entries(task):
        capability = entry.get("capability")
        if capability and capability not in capabilities:
            capabilities.append(capability)
    capability_label = " + ".join(CAPABILITY_LABELS.get(item, item) for item in capabilities)
    return parameters.get("report_name") or task_type_label or capability_label or task.get("task_type") or "未命名检测"


def _scan_target(task: dict) -> str:
    parameters = task.get("parameters") or {}
    summary = task.get("result_summary") or {}
    return str(parameters.get("target") or parameters.get("targets") or summary.get("target") or "-")


def _scan_outcome(task: dict) -> dict:
    """Keep execution state separate from the security conclusion in reports."""
    summary = task.get("result_summary") or {}
    payloads = _scan_payloads(task)
    entries = _scan_entries(task)
    execution = _value(task.get("status")) or "pending"
    result_status = _value(summary.get("status"))
    error = task.get("error_message") or summary.get("error")

    if execution in {"failed", "cancelled"} or error or result_status in {"failed", "error", "unable"}:
        return {"execution": execution, "result_status": result_status, "category": "unable", "label": "无法完成", "tone": "danger"}
    if execution in {"pending", "running"}:
        return {"execution": execution, "result_status": result_status, "category": "pending", "label": "尚未完成", "tone": "neutral"}
    if payloads and all(data.get("skipped") is True for data in payloads):
        return {"execution": execution, "result_status": result_status, "category": "skipped", "label": "不适用", "tone": "neutral"}
    incomplete = [
        entry for entry in entries
        if entry.get("status") in {"failed", "warning"}
        or (entry.get("result") or {}).get("scan_completed") is False
        or (entry.get("result") or {}).get("tool_status") == "failed"
    ]
    if incomplete:
        label = "部分完成，存在受限项" if len(incomplete) < len(entries) else "无法完成"
        tone = "warning" if len(incomplete) < len(entries) else "danger"
        return {"execution": execution, "result_status": result_status, "category": "unable", "label": label, "tone": tone}
    if any(data.get("weak_credentials") for data in payloads):
        return {"execution": execution, "result_status": result_status, "category": "risk", "label": "发现弱口令", "tone": "danger"}
    if any(
        data.get(key)
        for data in payloads
        for key in ("issues", "findings", "vulnerabilities", "failed_checks")
    ) or any(
        data.get("unauthorized") is True
        or data.get("empty_password") is True
        or float((data.get("summary") or {}).get("non_compliant") or 0) > 0
        for data in payloads
    ):
        return {"execution": execution, "result_status": result_status, "category": "risk", "label": "发现需关注项", "tone": "warning"}
    if task.get("findings_count") or result_status in {"warning", "fail", "partial", "contradict"}:
        return {"execution": execution, "result_status": result_status, "category": "risk", "label": "发现需关注项", "tone": "warning"}
    if any(data.get("open_ports") for data in payloads):
        return {"execution": execution, "result_status": result_status, "category": "observed", "label": "发现服务，需结合风险判断", "tone": "info"}
    if result_status in {"success", "pass"} or entries or payloads:
        return {"execution": execution, "result_status": result_status, "category": "clean", "label": "本次未发现问题", "tone": "good"}
    return {"execution": execution, "result_status": result_status, "category": "inconclusive", "label": "已执行，结论待确认", "tone": "neutral"}


def _finding_lifecycle(finding: dict) -> str:
    if finding.get("status") in {"fixed", "false_positive"}:
        return "closed"
    return "open"


def _finding_evidence_ids(finding: Finding) -> list[int]:
    ids = []
    for item in finding.evidence_ids or []:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _evidence_payload(evidence: Evidence) -> dict:
    content = evidence.content or {}
    return {
        "id": evidence.id,
        "file_name": evidence.file_name,
        "source": evidence.source,
        "mime_type": evidence.mime_type,
        "file_size": evidence.file_size,
        "page_count": content.get("page_count"),
        "analysis_mode": content.get("analysis_mode"),
        "native_blocks": content.get("native_blocks"),
        "ocr_blocks": content.get("ocr_blocks"),
        "vision_blocks": content.get("vision_blocks"),
        "warnings": content.get("warnings") or [],
    }


def _document_evidence_html(finding: dict) -> str:
    items = finding.get("document_evidences") or []
    if not items:
        return f"<span class=\"muted\">{finding.get('evidence_count', 0)} 条</span>"

    rows = []
    for item in items[:2]:
        section = item.get("section") or []
        if isinstance(section, list):
            section = " / ".join(str(part) for part in section if part)
        location = [item.get("file_name") or "未命名文件"]
        if item.get("page"):
            location.append(f"第 {item['page']} 页")
        if section:
            location.append(str(section))
        excerpt = str(item.get("text") or "").strip().replace("\n", " ")[:180]
        rows.append(
            f"<div class=\"evidence-ref\"><strong>{escape(' · '.join(location))}</strong>"
            f"<span>{escape(excerpt or '已定位结构化证据')}</span></div>"
        )
    remaining = len(items) - len(rows)
    suffix = f"<span class=\"muted\">另有 {remaining} 条</span>" if remaining > 0 else ""
    return "".join(rows) + suffix


async def generate_json_report(
    db: AsyncSession,
    project_id: int,
    assessment_id: int | None = None,
) -> dict:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise ValueError("Project not found")

    result = await db.execute(
        select(Assessment)
        .where(
            Assessment.project_id == project_id,
            *( [Assessment.id == assessment_id] if assessment_id is not None else [] ),
        )
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .limit(1)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise ValueError("当前项目尚未创建可生成报告的测评")

    phases_data = []
    if assessment:
        result = await db.execute(
            select(PhaseInstance)
            .where(PhaseInstance.assessment_id == assessment.id)
            .order_by(PhaseInstance.order)
        )
        phases = result.scalars().all()
        for phase in phases:
            result = await db.execute(select(TaskInstance).where(TaskInstance.phase_id == phase.id))
            tasks = result.scalars().all()
            phases_data.append({
                "id": phase.id,
                "phase_id": phase.phase_id,
                "name": phase.name,
                "order": phase.order,
                "status": phase.status,
                "total_tasks": phase.total_tasks,
                "completed_tasks": phase.completed_tasks,
                "progress": phase.progress,
                "started_at": _dt(phase.started_at),
                "completed_at": _dt(phase.completed_at),
                "tasks": [
                    {
                        "id": task.id,
                        "task_type": task.task_type,
                        "name": task.name,
                        "status": task.status,
                        "result": task.result,
                        "started_at": _dt(task.started_at),
                        "completed_at": _dt(task.completed_at),
                    }
                    for task in tasks
                ],
            })

    result = await db.execute(
        select(ScanTask).where(
            ScanTask.project_id == project_id,
            ScanTask.assessment_id == assessment.id,
        ).order_by(ScanTask.created_at.desc())
    )
    scan_tasks = [
        task for task in result.scalars().all()
        if (task.parameters or {}).get("source") == "assessment_task"
    ]

    result = await db.execute(
        select(Asset).where(Asset.project_id == project_id).order_by(Asset.id)
    )
    assets = result.scalars().all()

    result = await db.execute(
        select(Finding).where(
            Finding.project_id == project_id,
            Finding.assessment_id == assessment.id,
        ).order_by(Finding.severity)
    )
    findings = result.scalars().all()

    verification_runs = (await db.execute(
        select(VerificationRun).where(
            VerificationRun.project_id == project_id,
            VerificationRun.assessment_id == assessment.id,
        ).order_by(VerificationRun.created_at)
    )).scalars().all()
    verification_run_ids = [run.id for run in verification_runs]
    verification_items = (await db.execute(
        select(VerificationItem)
        .where(VerificationItem.run_id.in_(verification_run_ids))
        .order_by(VerificationItem.created_at)
    )).scalars().all() if verification_run_ids else []
    finding_events = (await db.execute(
        select(FindingEvent)
        .where(FindingEvent.finding_id.in_([finding.id for finding in findings]))
        .order_by(FindingEvent.created_at)
    )).scalars().all() if findings else []
    result = await db.execute(
        select(ChangeSnapshot)
        .where(ChangeSnapshot.project_id == project_id, ChangeSnapshot.changes_detected.is_(True))
        .order_by(ChangeSnapshot.id.desc())
        .limit(100)
    )
    change_snapshots = result.scalars().all()

    finding_ids = [finding.id for finding in findings]
    document_block_ids = sorted({
        evidence_id
        for finding in findings
        if finding.document_run_id
        for evidence_id in _finding_evidence_ids(finding)
    })
    technical_evidence_ids = sorted({
        evidence_id
        for finding in findings
        if not finding.document_run_id
        for evidence_id in _finding_evidence_ids(finding)
    })
    evidence_by_id = {}
    if finding_ids:
        result = await db.execute(select(Evidence).where(Evidence.finding_id.in_(finding_ids)))
        evidence_by_id.update({evidence.id: evidence for evidence in result.scalars().all()})
    if technical_evidence_ids:
        result = await db.execute(select(Evidence).where(Evidence.id.in_(technical_evidence_ids)))
        evidence_by_id.update({evidence.id: evidence for evidence in result.scalars().all()})
    evidences = list(evidence_by_id.values())
    document_blocks = {}
    if document_block_ids:
        rows = (await db.execute(
            select(DocumentBlock, DocumentFile)
            .join(DocumentFile, DocumentFile.id == DocumentBlock.document_file_id)
            .where(DocumentBlock.id.in_(document_block_ids))
        )).all()
        document_blocks = {block.id: (block, document) for block, document in rows}
    project_evidence_count = len(evidences)
    project_document_count = (await db.execute(
        select(func.count()).select_from(DocumentFile).where(
            DocumentFile.assessment_id == assessment.id,
            DocumentFile.is_active.is_(True),
        )
    )).scalar() or 0
    project_evidence_count += project_document_count

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    judgment_counts = {"pass": 0, "fail": 0, "partial": 0, "not_tested": 0, "paper_compliant": 0}
    findings_data = []
    for finding in findings:
        severity = _value(finding.severity)
        judgment = _value(finding.judgment)
        status = _value(finding.status)
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        judgment_counts[judgment] = judgment_counts.get(judgment, 0) + 1
        related_ids = set(_finding_evidence_ids(finding))
        related_evidence = [
            evidence for evidence in evidences
            if evidence.finding_id == finding.id or (not finding.document_run_id and evidence.id in related_ids)
        ]
        related_document_evidence = []
        if finding.document_run_id:
            for block_id in related_ids:
                item = document_blocks.get(block_id)
                if not item:
                    continue
                block, document = item
                if block.analysis_run_id != finding.document_run_id:
                    continue
                related_document_evidence.append({
                    "block_id": block.id,
                    "document_file_id": document.id,
                    "file_name": document.original_name,
                    "page": block.page_number,
                    "section": block.section_path,
                    "type": block.block_type,
                    "source": block.source,
                    "confidence": block.source_confidence,
                    "text": block.text,
                })
        findings_data.append({
            "id": finding.id,
            "clause_id": finding.clause_id,
            "clause_name": finding.clause_name,
            "severity": severity,
            "judgment": judgment,
            "judgment_engine": _value(finding.judgment_engine),
            "description": finding.description,
            "remediation_suggestion": finding.remediation_suggestion,
            "remediation_plan": controlled_remediation_plan(finding),
            "status": status,
            "fingerprint": finding.fingerprint,
            "source_type": finding.source_type,
            "source_key": finding.source_key,
            "scope_key": finding.scope_key,
            "resolution_days": _duration_days(finding.created_at, finding.resolved_at),
            "source": finding.source_type or ("document" if finding.document_run_id else "technical"),
            "scan_task_id": finding.scan_task_id,
            "document_run_id": finding.document_run_id,
            "evidence_count": len(related_evidence) + len(related_document_evidence),
            "evidences": [_evidence_payload(evidence) for evidence in related_evidence],
            "document_evidences": related_document_evidence,
            "created_at": _dt(finding.created_at),
        })

    score_metrics = await get_flow_engine(db)._calculate_compliance_metrics(assessment)
    score = score_metrics["score"]
    report = {
        "report_version": "3.0-html",
        "generated_at": datetime.utcnow().isoformat(),
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "compliance_level": _value(project.compliance_level),
            "compliance_score": score,
            "status": _value(project.status),
            "created_at": _dt(project.created_at),
        },
        "assessment": {
            "id": assessment.id if assessment else None,
            "type": assessment.assessment_type_code if assessment else None,
            "name": assessment.name if assessment else None,
            "level": assessment.assessment_level if assessment else None,
            "status": assessment.status if assessment else None,
            "progress": assessment.progress if assessment else 0,
            "total_phases": assessment.total_phases if assessment else 0,
            "completed_phases": assessment.completed_phases if assessment else 0,
            "started_at": _dt(assessment.started_at) if assessment else None,
            "completed_at": _dt(assessment.completed_at) if assessment else None,
            "phases": phases_data,
        },
        "summary": {
            "total_assets": len(assets),
            "total_findings": len(findings),
            "severity_counts": severity_counts,
            "judgment_counts": judgment_counts,
            "total_scan_tasks": len(scan_tasks),
            "total_evidences": project_evidence_count,
            "verification_runs": len(verification_runs),
            "verified_findings": len([f for f in findings if _value(f.status) == "fixed"]),
        },
        "assets": [
            {
                "id": asset.id,
                "name": asset.name,
                "value": asset.value,
                "asset_type": _value(asset.asset_type),
                "verification_status": _value(asset.verification_status),
                "is_active": asset.is_active,
            }
            for asset in assets
        ],
        "scan_tasks": [
            {
                "id": task.id,
                "task_type": _value(task.task_type),
                "status": _value(task.status),
                "parameters": scrub_sensitive_parameters(task.parameters or {}),
                "result_summary": task.result_summary,
                "error_message": task.error_message,
                "findings_count": task.findings_count,
                "created_at": _dt(task.created_at),
                "completed_at": _dt(task.completed_at),
            }
            for task in scan_tasks
        ],
        "findings": findings_data,
        "verification_runs": [
            {
                "id": run.id,
                "source_type": run.source_type,
                "status": _value(run.status),
                "notes": run.notes,
                "summary": run.summary or {},
                "created_at": _dt(run.created_at),
                "started_at": _dt(run.started_at),
                "completed_at": _dt(run.completed_at),
            }
            for run in verification_runs
        ],
        "finding_events": [
            {
                "id": item.id,
                "finding_id": item.finding_id,
                "verification_item_id": item.verification_item_id,
                "type": item.event_type,
                "data": item.event_data or {},
                "created_at": _dt(item.created_at),
            }
            for item in finding_events
        ],
        "verification_items": [
            {
                "id": item.id,
                "run_id": item.run_id,
                "finding_id": item.finding_id,
                "source_type": item.source_type,
                "target": item.target,
                "capability": item.capability,
                "outcome": _value(item.outcome),
                "baseline": item.baseline_observation or {},
                "current": item.current_observation or {},
                "comparison": item.comparison or {},
                "error": item.error_message,
                "created_at": _dt(item.created_at),
                "completed_at": _dt(item.completed_at),
            }
            for item in verification_items
        ],
        "change_history": [
            {
                "id": item.id,
                "type": item.snapshot_type,
                "subject": item.subject,
                "changes": item.changes or {},
                "changes_detected": item.changes_detected,
                "reliable": item.reliable,
                "reassessment_required": item.reassessment_required,
                "created_at": _dt(item.created_at),
            }
            for item in change_snapshots
        ],
    }
    report["document_gaps"] = [
        {
            "task_id": task["id"],
            "task_name": task["name"],
            "document_name": (task.get("result") or {}).get("analysis", {}).get("document_name"),
            "status": (task.get("result") or {}).get("analysis", {}).get("status"),
            "coverage": (task.get("result") or {}).get("analysis", {}).get("coverage"),
            "confidence": (task.get("result") or {}).get("analysis", {}).get("confidence"),
            "gaps": (task.get("result") or {}).get("analysis", {}).get("gaps", []),
            "files": (task.get("result") or {}).get("analysis", {}).get("files", []),
            "analysis_mode": (task.get("result") or {}).get("analysis", {}).get("analysis_mode"),
            "page_count": sum((file.get("page_count") or 0) for file in (task.get("result") or {}).get("analysis", {}).get("files", [])),
            "native_blocks": sum((file.get("native_blocks") or 0) for file in (task.get("result") or {}).get("analysis", {}).get("files", [])),
            "ocr_blocks": sum((file.get("ocr_blocks") or 0) for file in (task.get("result") or {}).get("analysis", {}).get("files", [])),
            "vision_blocks": sum((file.get("vision_blocks") or 0) for file in (task.get("result") or {}).get("analysis", {}).get("files", [])),
        }
        for phase in phases_data
        for task in phase["tasks"]
        if (task.get("result") or {}).get("analysis", {}).get("type") == "document_control_analysis"
    ]
    report["retest_comparisons"] = report["verification_items"]
    technical_scans = [
        {
            **task,
            "name": _scan_name(task),
            "target": _scan_target(task),
            "phase": (task.get("parameters") or {}).get("report_phase")
            or ASSESSMENT_PHASE_BY_TASK_TYPE.get((task.get("parameters") or {}).get("task_type"))
            or "独立检测",
            "outcome": _scan_outcome(task),
        }
        for task in report["scan_tasks"]
        if (task.get("result_summary") or {}).get("type") != "document_control_analysis"
    ]
    for finding in report["findings"]:
        finding["lifecycle"] = _finding_lifecycle(finding)
        finding["priority"] = finding.get("severity") or "medium"

    open_findings = [finding for finding in report["findings"] if finding["lifecycle"] == "open"]
    closed_findings = [finding for finding in report["findings"] if finding["lifecycle"] == "closed"]
    high_risk_open = sum(1 for finding in open_findings if finding.get("severity") in {"critical", "high"})
    unable_scans = [scan for scan in technical_scans if scan["outcome"]["category"] == "unable"]
    risk_scans = [scan for scan in technical_scans if scan["outcome"]["category"] == "risk"]
    clean_scans = [scan for scan in technical_scans if scan["outcome"]["category"] == "clean"]
    document_unable = sum(1 for item in report["document_gaps"] if item.get("status") == "unable")
    document_attention = sum(1 for item in report["document_gaps"] if item.get("status") in {"fail", "partial", "unable"})
    report["summary"].update({
        "open_findings": len(open_findings),
        "closed_findings": len(closed_findings),
        "high_risk_open": high_risk_open,
        "technical_scans": len(technical_scans),
        "risk_scans": len(risk_scans),
        "clean_scans": len(clean_scans),
        "unable_scans": len(unable_scans),
        "document_checks": len(report["document_gaps"]),
        "document_attention": document_attention,
        "document_unable": document_unable,
    })
    if high_risk_open:
        conclusion = ("attention", "存在高风险待整改项，当前不应将项目视为已完成自查。")
    elif unable_scans or document_unable:
        conclusion = ("attention", "存在无法完成的检查，报告结论仅覆盖已成功取得结果的范围。")
    elif open_findings or document_attention:
        conclusion = ("attention", "仍有待整改或待补充证据的事项，建议完成整改后重新复测。")
    elif (assessment.progress if assessment else 0) < 100:
        conclusion = ("progress", "测评流程尚未完成，当前报告仅反映已执行检查的阶段性结果。")
    else:
        conclusion = ("ready", "当前已无待处理问题；结论仅覆盖本报告列出的资产、文档与已执行检查。")

    report["technical_scans"] = technical_scans
    report["score_metrics"] = score_metrics
    if assessment.assessment_type_code == "miping":
        from app.services.miping_matrix import build_miping_domain_matrix
        report["miping_matrix"] = await build_miping_domain_matrix(db, assessment)
    report["finding_lifecycle"] = {"open": open_findings, "closed": closed_findings}
    report["report_conclusion"] = {
        "state": conclusion[0],
        "message": conclusion[1],
        "basis": f"基于 {len(technical_scans)} 次技术检测、{len(report['document_gaps'])} 项文档核查和 {len(report['findings'])} 个问题记录生成。",
    }
    return report


def report_artifact_payload(artifact: ReportArtifact | None) -> dict:
    if not artifact:
        return {"available": False}
    snapshot = artifact.snapshot or {}
    project = snapshot.get("project") or {}
    summary = snapshot.get("summary") or {}
    score_metrics = snapshot.get("score_metrics") or {}
    return {
        "available": True,
        "id": artifact.id,
        "project_id": artifact.project_id,
        "assessment_id": artifact.assessment_id,
        "task_id": artifact.task_id,
        "version": artifact.version,
        "status": artifact.status,
        "stale": artifact.status == "stale",
        "stale_reason": artifact.stale_reason,
        "html_sha256": artifact.html_sha256,
        "html_size": artifact.html_size,
        "generated_at": _dt(artifact.created_at),
        "invalidated_at": _dt(artifact.invalidated_at),
        "score": project.get("compliance_score") if project.get("compliance_score") is not None else score_metrics.get("score"),
        "coverage": score_metrics.get("coverage"),
        "reliable": score_metrics.get("reliable"),
        "unable": score_metrics.get("unable", summary.get("unable_scans", 0)),
        "not_applicable": score_metrics.get("not_applicable"),
        "open_findings": summary.get("open_findings", 0),
        "total_findings": summary.get("total_findings", 0),
    }


async def get_latest_report_artifact(
    db: AsyncSession,
    project_id: int,
    *,
    assessment_id: int | None = None,
) -> ReportArtifact | None:
    query = select(ReportArtifact).where(ReportArtifact.project_id == project_id)
    if assessment_id is not None:
        query = query.where(ReportArtifact.assessment_id == assessment_id)
    return (await db.execute(query.order_by(ReportArtifact.version.desc()).limit(1))).scalar_one_or_none()


async def list_report_artifacts(
    db: AsyncSession,
    project_id: int,
    assessment_id: int | None = None,
) -> list[ReportArtifact]:
    query = select(ReportArtifact).where(ReportArtifact.project_id == project_id)
    if assessment_id is not None:
        query = query.where(ReportArtifact.assessment_id == assessment_id)
    return list((await db.execute(
        query.order_by(ReportArtifact.version.desc())
    )).scalars().all())


async def get_report_artifact_version(
    db: AsyncSession,
    project_id: int,
    version: int,
) -> ReportArtifact | None:
    return (await db.execute(select(ReportArtifact).where(
        ReportArtifact.project_id == project_id,
        ReportArtifact.version == version,
    ))).scalar_one_or_none()


async def invalidate_report_artifacts(
    db: AsyncSession,
    project_id: int,
    reason: str,
    *,
    reopen_phase: bool = True,
    assessment_id: int | None = None,
) -> int:
    """Mark the current report stale while preserving its immutable snapshot."""
    filters = [ReportArtifact.project_id == project_id, ReportArtifact.status == "current"]
    if assessment_id is not None:
        filters.append(ReportArtifact.assessment_id == assessment_id)
    result = await db.execute(
        update(ReportArtifact)
        .where(*filters)
        .values(status="stale", stale_reason=reason, invalidated_at=datetime.utcnow())
    )
    changed = result.rowcount or 0
    if not changed or not reopen_phase:
        return changed

    assessment = await db.get(Assessment, assessment_id) if assessment_id is not None else (await db.execute(
        select(Assessment).where(Assessment.project_id == project_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1)
    )).scalar_one_or_none()
    if assessment:
        phase = (await db.execute(select(PhaseInstance).where(
            PhaseInstance.assessment_id == assessment.id,
            PhaseInstance.phase_id == "report",
        ))).scalar_one_or_none()
        if phase:
            phase.status = "active"
            phase.progress = 0
            phase.completed_tasks = 0
            phase.completed_at = None
            phase.outputs = None
            phase.started_at = phase.started_at or datetime.utcnow()
            for task in (await db.execute(select(TaskInstance).where(TaskInstance.phase_id == phase.id))).scalars().all():
                task.status = "todo"
                task.result = None
                task.started_at = None
                task.completed_at = None
            phases = list((await db.execute(select(PhaseInstance).where(
                PhaseInstance.assessment_id == assessment.id
            ))).scalars().all())
            assessment.completed_phases = sum(item.status == "completed" for item in phases)
            assessment.progress = workflow_progress(phases)
            assessment.status = "in_progress"
            assessment.completed_at = None
    project = await db.get(Project, project_id)
    if project:
        project.compliance_score = None
    return changed


def _final_report_snapshot(report: dict, task_id: int, version: int) -> dict:
    """Render the snapshot as it will look after the report task commits."""
    assessment = report["assessment"]
    for phase in assessment.get("phases") or []:
        if phase.get("phase_id") != "report":
            continue
        phase["status"] = "completed"
        phase["progress"] = 100
        phase["completed_tasks"] = phase["total_tasks"]
        for task in phase.get("tasks") or []:
            if task.get("id") == task_id:
                task["status"] = "completed"
    completed_phases = sum(
        phase.get("status") == "completed" for phase in assessment.get("phases") or []
    )
    total_phases = int(assessment.get("total_phases") or len(assessment.get("phases") or []))
    assessment["completed_phases"] = completed_phases
    phase_progress = [
        100.0 if phase.get("status") == "completed" else float(phase.get("progress") or 0)
        for phase in assessment.get("phases") or []
    ]
    assessment["progress"] = sum(phase_progress) / max(1, len(phase_progress))
    assessment["status"] = "completed" if completed_phases == total_phases else "in_progress"
    summary = report["summary"]
    if (
        report["report_conclusion"]["state"] == "progress"
        and not summary.get("open_findings")
        and not summary.get("unable_scans")
        and not summary.get("document_attention")
    ):
        report["report_conclusion"] = {
            "state": "ready",
            "message": "当前已无待处理问题；结论仅覆盖本报告列出的资产、文档与已执行检查。",
            "basis": report["report_conclusion"]["basis"],
        }
    report["artifact"] = {"version": version, "status": "current"}
    return report


async def ensure_report_generation_ready(
    db: AsyncSession,
    project_id: int,
    assessment_id: int | None = None,
) -> None:
    assessment_query = select(Assessment).where(Assessment.project_id == project_id)
    if assessment_id is not None:
        assessment_query = assessment_query.where(Assessment.id == assessment_id)
    assessment = (await db.execute(
        assessment_query.order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1)
    )).scalar_one_or_none()
    if not assessment:
        raise ValueError("当前项目尚未创建可生成报告的测评")

    phases = list((await db.execute(select(PhaseInstance).where(
        PhaseInstance.assessment_id == assessment.id,
    ).order_by(PhaseInstance.order))).scalars().all())
    report_phase = next((phase for phase in phases if phase.phase_id == "report"), None)
    if not report_phase:
        raise ValueError("当前测评缺少生成报告阶段")
    incomplete_phases = [
        phase for phase in phases
        if phase.order < report_phase.order and phase.status != "completed"
    ]
    if incomplete_phases:
        names = "、".join(phase.name for phase in incomplete_phases)
        raise ValueError(f"报告生成前必须完成全部前置阶段：{names}")

    from app.services.flow_engine import get_flow_engine
    engine = get_flow_engine(db)
    unfinished_tasks = []
    for phase in phases:
        if phase.phase_id not in {"gap_analysis", "field_assessment"}:
            continue
        unfinished_tasks.extend(
            (phase, task)
            for task in await engine.get_tasks(phase.id, official_only=True)
            if task.status in {"todo", "in_progress"}
        )
    if unfinished_tasks:
        labels = "、".join(f"{phase.name}/{task.name}" for phase, task in unfinished_tasks[:3])
        suffix = f"等 {len(unfinished_tasks)} 项" if len(unfinished_tasks) > 3 else ""
        raise ValueError(f"仍有正式检查未形成结论：{labels}{suffix}")

    running_scan_parameters = (await db.execute(select(ScanTask.parameters).where(
        ScanTask.project_id == project_id,
        ScanTask.assessment_id == assessment.id,
        ScanTask.status.in_([ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING]),
    ))).scalars().all()
    active_scans = sum(
        1 for parameters in running_scan_parameters
        if (parameters or {}).get("source") == "assessment_task"
    )
    active_documents = int((await db.execute(select(func.count(DocumentAnalysisRun.id)).where(
        DocumentAnalysisRun.project_id == project_id,
        DocumentAnalysisRun.assessment_id == assessment.id,
        DocumentAnalysisRun.status.in_(["queued", "running"]),
    ))).scalar() or 0)
    active_verifications = int((await db.execute(select(func.count(VerificationRun.id)).where(
        VerificationRun.project_id == project_id,
        VerificationRun.assessment_id == assessment.id,
        VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
    ))).scalar() or 0)
    if active_scans or active_documents or active_verifications:
        raise ValueError(
            f"仍有任务执行中：技术检测 {active_scans} 个，文档分析 {active_documents} 个，整改复测 {active_verifications} 个"
        )


async def create_report_artifact(
    db: AsyncSession,
    *,
    project_id: int,
    assessment_id: int,
    task_id: int,
    generated_by: int | None,
) -> ReportArtifact:
    await ensure_report_generation_ready(db, project_id, assessment_id)
    project = (await db.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    )).scalar_one()
    existing_max = int((await db.execute(select(func.max(ReportArtifact.version)).where(
        ReportArtifact.project_id == project_id
    ))).scalar() or 0)
    version = max(existing_max, int(project.report_version_counter or 0)) + 1
    project.report_version_counter = version
    report = await generate_json_report(db, project_id, assessment_id)
    assessment = await db.get(Assessment, assessment_id)
    if assessment:
        from app.services.flow_engine import get_flow_engine
        score_metrics = await get_flow_engine(db)._calculate_compliance_metrics(assessment)
        report["score_metrics"] = score_metrics
        report["project"]["compliance_score"] = score_metrics["score"]
    report = _final_report_snapshot(report, task_id, version)
    html = await generate_html_report(db, project_id, report=report)
    path, digest, size = await file_storage.save_file(
        project_id,
        f"certiproof-report-v{version}.html",
        html.encode("utf-8"),
    )
    await invalidate_report_artifacts(
        db,
        project_id,
        "已生成更新版本",
        reopen_phase=False,
        assessment_id=assessment_id,
    )
    artifact = ReportArtifact(
        project_id=project_id,
        assessment_id=assessment_id,
        task_id=task_id,
        version=version,
        status="current",
        html_path=path,
        html_sha256=digest,
        html_size=size,
        snapshot=report,
        generated_by=generated_by,
    )
    db.add(artifact)
    await db.flush()
    return artifact


async def read_report_artifact_html(artifact: ReportArtifact) -> bytes:
    content = await file_storage.read_file(artifact.html_path)
    if content is None:
        raise FileNotFoundError("报告文件不存在，请重新生成报告")
    return content


LABELS = {
    "critical": "严重", "high": "高", "medium": "中", "low": "低", "info": "提示",
    "open": "待整改", "closed": "已关闭", "skipped": "不适用",
    "pending": "未开始", "running": "执行中", "completed": "已执行", "failed": "执行失败", "cancelled": "已取消",
    "pass": "符合", "success": "成功", "fail": "不符合", "partial": "部分符合", "unable": "无法判断", "warning": "需关注", "improved": "已改善",
    "fixed": "已修复", "still_present": "仍存在", "new": "新增问题",
    "attention": "需要处理", "progress": "测评进行中", "ready": "结论可用",
    "ip": "IP 主机", "domain": "域名", "cloud_resource": "云资源", "unverified": "未验证",
}

ASSET_VERIFICATION_LABELS = {
    "verified": "已验证",
    "pending": "待验证",
    "unverified": "未验证",
    "failed": "验证失败",
}


def _tone(value) -> str:
    value = _value(value)
    if value in {"critical", "high", "failed", "fail", "unable", "open"}:
        return "danger"
    if value in {"medium", "warning", "partial", "in_progress", "attention"}:
        return "warning"
    if value in {"pass", "success", "fixed", "verified", "closed", "completed", "ready", "improved"}:
        return "good"
    return "neutral"


def _label(value) -> str:
    raw = _value(value)
    return LABELS.get(raw, str(raw or "-"))


def _badge(value, tone: str | None = None) -> str:
    return f'<span class="badge {escape(tone or _tone(value))}">{escape(_label(value))}</span>'


def _asset_verification_badge(value) -> str:
    raw = _value(value)
    label = ASSET_VERIFICATION_LABELS.get(raw, str(raw or "-"))
    return f'<span class="badge {escape(_tone(raw))}">{escape(label)}</span>'


def _change_text(item):
    changes = item.get("changes") or {}
    if item.get("type") == "asset":
        return f"新增资产 {len(changes.get('added_assets') or [])}；移除资产 {len(changes.get('removed_assets') or [])}"
    return (
        f"新增端口 {len(changes.get('added_ports') or [])}；"
        f"关闭端口 {len(changes.get('removed_ports') or [])}；"
        f"服务变化 {len(changes.get('service_changes') or [])}"
    )


def _scan_brief(task: dict) -> str:
    summary = task.get("result_summary") or {}
    parts = []
    for data in _scan_payloads(task):
        if data.get("skipped") is True:
            parts.append(data.get("skip_reason") or "目标不适用，本项已跳过")
        if data.get("open_ports") is not None:
            ports = ", ".join(f"{item.get('port')}/{item.get('protocol', 'tcp')} {item.get('service') or ''}".strip() for item in data.get("open_ports") or [])
            parts.append(f"开放端口：{ports or '无'}")
        if data.get("weak_credentials") is not None:
            parts.append(f"弱口令命中：{len(data.get('weak_credentials') or [])}")
        baseline = data.get("summary") or {}
        if baseline.get("total_checks") is not None:
            parts.append(f"基线 {baseline.get('total_checks')} 项，不符合 {baseline.get('non_compliant') or 0} 项，符合率 {baseline.get('compliance_rate') or 0}%")
        for key, label in (("issues", "配置问题"), ("vulnerabilities", "漏洞"), ("findings", "发现项"), ("failed_checks", "未通过项")):
            values = data.get(key) or []
            if values:
                samples = []
                for item in values[:2]:
                    if isinstance(item, dict):
                        samples.append(_structured_issue_text(item))
                    else:
                        samples.append(str(item))
                parts.append(f"{label} {len(values)} 项：{'；'.join(samples)}")
        if data.get("conclusion"):
            parts.append(str(data["conclusion"]))
    unique = list(dict.fromkeys(part for part in parts if part))
    if unique:
        return "；".join(unique[:4])
    errors = [str(entry.get("warning") or entry.get("error")) for entry in _scan_entries(task) if entry.get("warning") or entry.get("error")]
    return "；".join(errors[:3]) or summary.get("status") or "-"


def _percent(value) -> str:
    return f"{round((value or 0) * 100)}%"


def _timestamp(value) -> str:
    if not value:
        return "-"
    return str(value).replace("T", " ").split("+")[0].split(".")[0]


def _remediation_plan_html(finding: dict) -> str:
    plan = finding.get("remediation_plan") or {}
    steps = "".join(f"<li>{escape(str(step))}</li>" for step in plan.get("steps") or [])
    if not steps:
        return f'<p class="recommendation">{escape(str(finding.get("remediation_suggestion") or "请补充整改措施并重新验证。"))}</p>'
    return (
        '<div class="recommendation"><strong>受控整改步骤</strong>'
        f'<ol>{steps}</ol><p><b>验证：</b>{escape(str(plan.get("verification") or "重新执行原检查。"))}</p>'
        f'<p><b>回滚：</b>{escape(str(plan.get("rollback") or "恢复变更前版本。"))}</p></div>'
    )


async def generate_html_report(db: AsyncSession, project_id: int, report: dict | None = None) -> str:
    report = report or await generate_json_report(db, project_id)
    project = report["project"]
    assessment = report["assessment"]
    summary = report["summary"]
    conclusion = report["report_conclusion"]
    lifecycle = report["finding_lifecycle"]
    is_miping = assessment.get("type") == "miping"
    report_title = "企业密码应用自查报告" if is_miping else "企业等保自查报告"
    level_label = "密码应用级别" if is_miping else "等保等级"
    level_value = f"第{assessment.get('level')}级" if assessment.get("level") else "未设置"

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    open_findings = sorted(lifecycle["open"], key=lambda item: priority_order.get(item.get("priority"), 9))

    phase_rows = "\n".join(
        f"<tr><td><strong>{escape(p['name'])}</strong></td><td>{_badge(p['status'])}</td><td>{p['completed_tasks']}/{p['total_tasks']}</td><td><div class=\"progress\"><i style=\"width:{max(0, min(100, round(p['progress'] or 0)))}%\"></i></div><em>{round(p['progress'] or 0)}%</em></td></tr>"
        for p in assessment["phases"]
    ) or '<tr><td colspan="4">暂无测评阶段</td></tr>'
    priority_rows = "\n".join(
        f"<article class=\"action-item\"><div>{_badge(f['priority'])}<strong>{escape(str(f.get('clause_name') or f['clause_id'] or '待整改事项'))}</strong></div><p>{escape(str(f['description'] or '-'))}</p>{_document_evidence_html(f)}<footer><span>当前：{_badge(f['status'])}</span><span>证据 {f['evidence_count']} 条</span></footer>{_remediation_plan_html(f)}</article>"
        for f in open_findings[:12]
    ) or '<p class="empty">当前没有待整改问题。</p>'
    finding_map = {finding["id"]: finding for finding in report["findings"]}
    retest_rows = "\n".join(
        f"<tr><td>{'文档复测' if item['source_type'] == 'document' else '技术复测'}</td>"
        f"<td><strong>{escape(str((finding_map.get(item['finding_id']) or {}).get('clause_name') or item.get('capability') or '检查项'))}</strong>"
        f"<br><span class=\"muted\">{escape(str(item.get('target') or '-'))}</span></td>"
        f"<td>{escape(_readable_observation((item.get('baseline') or {}).get('description') or '初检存在问题'))}</td>"
        f"<td>{_badge(item.get('outcome'))}</td>"
        f"<td>{escape(str(item.get('error') or (item.get('current') or {}).get('description') or (item.get('comparison') or {}).get('after') or '-'))}</td></tr>"
        for item in report["verification_items"]
    ) or '<tr><td colspan="5">尚未产生可追溯的复测结果。</td></tr>'
    document_gap_rows = "\n".join(
        f"<tr><td><strong>{escape(str(g['document_name'] or g['task_name']))}</strong></td><td>{_badge(g['status'])}</td><td>{round((g['coverage'] or 0) * 100)}%</td><td>{escape('、'.join(f.get('file_name', '-') for f in g.get('files', [])) or '-')}</td><td>{g.get('page_count') or 0} 页 · 原生 {g.get('native_blocks') or 0} · OCR {g.get('ocr_blocks') or 0} · 视觉 {g.get('vision_blocks') or 0}</td><td>{escape('；'.join((g['gaps'] or [])[:5]) or '未发现缺失项')}</td></tr>"
        for g in report["document_gaps"]
    ) or '<tr><td colspan="6">尚未执行文档合规核查。</td></tr>'
    asset_rows = "\n".join(
        f"<tr><td>{escape(str(a['name'] or '-'))}</td><td>{escape(a['value'])}</td><td>{_badge(a['asset_type'])}</td><td>{_asset_verification_badge(a['verification_status'])}</td></tr>"
        for a in report["assets"]
    ) or '<tr><td colspan="4">暂无资产</td></tr>'
    scan_rows = "\n".join(
        f"<tr><td>{escape(scan['phase'])}</td><td><strong>{escape(scan['name'])}</strong></td><td>{escape(scan['target'])}</td><td>{_badge(scan['outcome']['execution'])}</td><td>{_badge(scan['outcome']['label'], scan['outcome']['tone'])}</td><td>{escape(_scan_brief(scan))}</td><td>{escape(str(scan.get('error_message') or '-'))}</td></tr>"
        for scan in report["technical_scans"]
    ) or '<tr><td colspan="7">尚未执行技术检测。</td></tr>'
    finding_rows = "\n".join(
        f"<tr><td>#{f['id']}</td><td>{escape(str(f['clause_id'] or '-'))}</td><td>{_badge(f['priority'])}</td><td>{_badge(f['lifecycle'])}</td><td>{_badge(f['status'])}</td><td>{_document_evidence_html(f)}</td><td>{escape(_readable_observation(f['description']))}</td><td>{escape(str(f['remediation_suggestion'] or '-'))}</td></tr>"
        for f in sorted(report["findings"], key=lambda item: (item["lifecycle"] != "open", priority_order.get(item.get("priority"), 9)))
    ) or '<tr><td colspan="8">未产生问题记录。</td></tr>'
    change_rows = "\n".join(
        f"<tr><td>{escape(_timestamp(c['created_at']))}</td><td>{_badge('资产' if c['type'] == 'asset' else '端口', 'info')}</td><td>{escape(c['subject'])}</td><td>{escape(_change_text(c))}</td><td>{_badge('需重新评估' if c['reassessment_required'] else '已知晓', 'warning' if c['reassessment_required'] else 'good')}</td></tr>"
        for c in report["change_history"]
    ) or '<tr><td colspan="5">暂无资产或端口变化</td></tr>'
    def matrix_detail(domain):
        return "；".join(f"{task['name']}：{task['detail']}" for task in domain.get("tasks", [])) or "尚未形成检查项"

    matrix_rows = "\n".join(
        f"<tr><td><strong>{escape(domain['name'])}</strong></td><td>{_badge(domain['status'])}</td>"
        f"<td>{escape({'hybrid': '自动检测 + 材料证据', 'document': '制度材料检查', 'evidence': '现场证据检查'}.get(domain['method'], domain['method']))}</td>"
        f"<td>{escape(matrix_detail(domain))}</td></tr>"
        for domain in (report.get("miping_matrix") or {}).get("domains", [])
    )
    matrix_toc = '<a href="#miping-matrix">八层面结论</a>' if is_miping else ""
    matrix_rows_html = matrix_rows or '<tr><td colspan="4">尚未形成八层面结论。</td></tr>'
    matrix_section = (
        '<section id="miping-matrix"><div class="section-head"><div><h2>密码应用八个层面结论</h2>'
        '<p>自动检测只覆盖可远程验证的网络通信项；其他层面依据材料和现场证据判断，无法取证不会判为通过。</p></div>'
        f'<span class="muted">通过 {(report.get("miping_matrix") or {}).get("counts", {}).get("pass", 0)} / 8</span></div>'
        '<div class="table-wrap"><table><thead><tr><th>评估层面</th><th>结论</th><th>检查方式</th><th>依据与说明</th></tr></thead>'
        f'<tbody>{matrix_rows_html}</tbody></table></div></section>'
    ) if is_miping else ""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>CertiProof 自查报告 - {escape(project['name'])}</title>
  <style>
    :root {{ color-scheme: dark; --canvas:#07111d; --panel:#0b1a2a; --line:#19334b; --text:#edf6ff; --muted:#91a8bd; --cyan:#54dff1; --green:#66dca4; --amber:#f2c969; --red:#f47683; }}
    * {{ box-sizing: border-box; }} body {{ margin:0; background:var(--canvas); color:var(--text); font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }}
    .shell {{ max-width:1440px; margin:0 auto; padding:26px 28px 64px; }} .eyebrow,.meta,.muted {{ color:var(--muted); }} .eyebrow {{ margin:0 0 8px; color:var(--cyan); font:600 11px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:0; }}
    .hero {{ padding:22px 0 26px; border-bottom:1px solid var(--line); }} h1,h2,h3,p {{ margin:0; }} h1 {{ max-width:800px; font-size:32px; line-height:1.2; letter-spacing:0; }} .hero-line {{ display:flex; align-items:center; justify-content:space-between; gap:18px; margin-top:13px; }} .meta {{ font-size:12px; }}
    .conclusion {{ display:grid; grid-template-columns:auto minmax(0,1fr); gap:14px; margin:22px 0; padding:18px; border:1px solid var(--line); background:#0a1928; }} .conclusion h2 {{ font-size:17px; }} .conclusion p {{ margin-top:4px; color:#c5d6e6; }} .conclusion small {{ display:block; margin-top:8px; color:var(--muted); }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:20px 0 30px; }} .metric {{ min-width:0; padding:15px; border:1px solid var(--line); background:#091827; }} .metric strong {{ display:block; color:#fff; font:600 27px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace; }} .metric span {{ display:block; margin-top:7px; color:var(--muted); font-size:12px; }}
    .layout {{ display:grid; grid-template-columns:186px minmax(0,1fr); gap:28px; }} .toc {{ align-self:start; position:sticky; top:20px; display:grid; gap:3px; padding-right:16px; border-right:1px solid var(--line); }} .toc span {{ margin-bottom:7px; color:var(--muted); font-size:11px; }} .toc a {{ padding:6px 0; color:#a9c4d7; text-decoration:none; font-size:12px; }} .toc a:hover {{ color:var(--cyan); }} .content {{ min-width:0; }} section {{ padding:0 0 30px; margin:0 0 30px; border-bottom:1px solid var(--line); }} section:last-child {{ border:0; }} .section-head {{ display:flex; align-items:baseline; justify-content:space-between; gap:16px; margin-bottom:13px; }} h2 {{ font-size:19px; }} .section-head p {{ color:var(--muted); font-size:12px; }}
    .badge {{ display:inline-flex; align-items:center; min-height:22px; padding:2px 8px; color:#bfeefa; border:1px solid #275168; background:#0b2635; border-radius:999px; font-size:11px; white-space:nowrap; }} .badge.good {{ color:#a9f0c8; border-color:#246447; background:#0b2b21; }} .badge.warning {{ color:#ffe099; border-color:#705826; background:#30270e; }} .badge.danger {{ color:#ffb0b8; border-color:#71343f; background:#32151d; }} .badge.info {{ color:#bfeefa; border-color:#275168; background:#0b2635; }} .badge.neutral {{ color:#becbd6; border-color:#3b4c5b; background:#14202c; }}
    .action-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }} .action-item {{ min-width:0; padding:15px; border:1px solid #31445a; background:#0a1928; }} .action-item > div {{ display:flex; align-items:center; gap:8px; }} .action-item strong {{ min-width:0; overflow-wrap:anywhere; font-size:14px; }} .action-item p {{ margin-top:10px; color:#c9d8e6; }} .action-item footer {{ display:flex; justify-content:space-between; gap:8px; margin-top:12px; color:var(--muted); font-size:11px; }} .action-item .recommendation {{ display:block; padding-top:10px; border-top:1px solid var(--line); color:#9fddeb; }} .action-item .recommendation ol {{ margin:8px 0; padding-left:20px; color:#c9d8e6; }} .action-item .recommendation li {{ margin:5px 0; }} .empty {{ color:var(--muted); padding:14px 0; }}
    .evidence-ref {{ display:grid!important; gap:3px!important; margin-top:9px; padding:8px 10px; border-left:2px solid #2e7084; background:#081522; }} .evidence-ref strong {{ color:#9fddeb; font-size:11px; }} .evidence-ref span {{ color:#aebfce; font-size:11px; overflow-wrap:anywhere; }}
    .table-wrap {{ overflow:auto; border:1px solid var(--line); background:#091827; }} table {{ width:100%; min-width:680px; border-collapse:collapse; }} th,td {{ padding:11px 12px; border-bottom:1px solid #183247; text-align:left; vertical-align:top; }} th {{ color:#9ec9df; background:#0c2032; font-size:11px; font-weight:600; }} td {{ color:#d7e5ef; font-size:12px; }} tr:last-child td {{ border-bottom:0; }} td em {{ display:inline-block; margin-left:8px; color:var(--muted); font-size:11px; font-style:normal; }} .progress {{ display:inline-block; width:92px; height:6px; margin-right:6px; overflow:hidden; vertical-align:middle; background:#10283a; }} .progress i {{ display:block; height:100%; background:var(--cyan); }}
    details {{ border:1px solid var(--line); background:#091827; }} summary {{ padding:12px 14px; color:#c8e9f3; cursor:pointer; }} details .table-wrap {{ border-width:1px 0 0; }}
    @media (max-width:900px) {{ .shell {{ padding:20px 14px 44px; }} .metrics,.action-list {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .layout {{ display:block; }} .toc {{ position:static; grid-template-columns:repeat(2,minmax(0,1fr)); margin-bottom:24px; padding:0 0 12px; border-right:0; border-bottom:1px solid var(--line); }} }} @media (max-width:560px) {{ h1 {{ font-size:26px; }} .hero-line {{ align-items:flex-start; flex-direction:column; }} .metrics,.action-list {{ grid-template-columns:1fr; }} .toc {{ grid-template-columns:1fr; }} }}
    @media print {{ body {{ background:#fff; color:#172231; }} .shell {{ max-width:none; padding:16mm; }} .hero,section {{ border-color:#d7e0e8; }} .metric,.conclusion,.action-item,.table-wrap,details {{ background:#fff; border-color:#d7e0e8; }} .toc {{ display:none; }} .layout {{ display:block; }} .badge {{ color:#172231; background:#fff; border-color:#8495a6; }} th {{ color:#172231; background:#eef4f8; }} td {{ color:#263747; border-color:#d7e0e8; }} .muted,.meta,.section-head p {{ color:#52697d; }} }}
  </style>
</head>
<body>
<main class="shell">
  <header class="hero"><p class="eyebrow">CERTIPROOF / {report_title} / HTML / V{escape(str((report.get('artifact') or {}).get('version') or '-'))}</p><h1>{escape(project['name'])}</h1><div class="hero-line"><p class="meta">{level_label}：{escape(level_value)} · 生成时间：{escape(_timestamp(report['generated_at']))}</p><p class="meta">流程进度：{round(assessment['progress'] or 0)}% · 已完成阶段：{assessment['completed_phases']}/{assessment['total_phases']}</p></div></header>
  <section class="conclusion"><div>{_badge('attention' if conclusion['state'] == 'attention' else conclusion['state'], 'warning' if conclusion['state'] == 'attention' else ('good' if conclusion['state'] == 'ready' else 'neutral'))}</div><div><h2>自查结论</h2><p>{escape(conclusion['message'])}</p><small>{escape(conclusion['basis'])}</small></div></section>
  <section class="metrics" aria-label="报告摘要"><div class="metric"><strong>{summary['open_findings']}</strong><span>当前待整改问题</span></div><div class="metric"><strong>{summary['high_risk_open']}</strong><span>其中高风险问题</span></div><div class="metric"><strong>{summary['closed_findings']}/{summary['total_findings']}</strong><span>已闭环 / 累计发现</span></div><div class="metric"><strong>{summary['clean_scans']}/{summary['technical_scans']}</strong><span>本次未发现问题的技术检测</span></div></section>
  <div class="layout"><nav class="toc"><span>报告目录</span><a href="#actions">待整改事项</a><a href="#retest">整改与复测</a>{matrix_toc}<a href="#coverage">检测覆盖</a><a href="#documents">文档合规</a><a href="#findings">问题闭环</a><a href="#scope">范围与变化</a></nav><div class="content">
    <section id="actions"><div class="section-head"><div><h2>当前待整改事项</h2><p>只列出尚未通过真实复测的问题，按优先级排序。</p></div><span class="muted">{summary['open_findings']} 项</span></div><div class="action-list">{priority_rows}</div></section>
    <section id="retest"><div class="section-head"><div><h2>整改与复测记录</h2><p>逐问题展示改进文档或技术复测的初检依据、当前结论和无法完成原因。</p></div><span class="muted">共 {len(report['retest_comparisons'])} 项</span></div><div class="table-wrap"><table><thead><tr><th>类型</th><th>对象</th><th>整改前</th><th>当前结果</th><th>变化说明</th></tr></thead><tbody>{retest_rows}</tbody></table></div></section>
    {matrix_section}
    <section id="coverage"><div class="section-head"><div><h2>检测覆盖与执行结果</h2><p>“执行状态”只表示工具是否运行；“检测结论”才表示本次发现。</p></div><span class="muted">无法完成 {summary['unable_scans']} 项 · 需关注 {summary['risk_scans']} 项</span></div><div class="table-wrap"><table><thead><tr><th>阶段</th><th>检测内容</th><th>资产</th><th>执行状态</th><th>检测结论</th><th>结果摘要</th><th>错误详情</th></tr></thead><tbody>{scan_rows}</tbody></table></div><div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>测评阶段</th><th>阶段状态</th><th>完成任务</th><th>进度</th></tr></thead><tbody>{phase_rows}</tbody></table></div></section>
    <section id="documents"><div class="section-head"><div><h2>文档合规核查</h2><p>结论来自已提取的正文、OCR 或视觉解析内容；“无法判断”不会计为符合。</p></div><span class="muted">待关注 {summary['document_attention']} 项</span></div><div class="table-wrap"><table><thead><tr><th>检查项</th><th>当前结论</th><th>覆盖率</th><th>证据文件</th><th>解析来源</th><th>仍缺少的内容</th></tr></thead><tbody>{document_gap_rows}</tbody></table></div></section>
    <section id="findings"><div class="section-head"><div><h2>问题闭环明细</h2><p>累计问题保留可追溯记录；只有真实复测通过的问题才计为已关闭。</p></div><span class="muted">已关闭 {summary['closed_findings']}</span></div><details><summary>展开全部 {summary['total_findings']} 个问题的状态、证据与整改建议</summary><div class="table-wrap"><table><thead><tr><th>ID</th><th>条款 / 编号</th><th>优先级</th><th>生命周期</th><th>整改状态</th><th>证据</th><th>问题描述</th><th>整改建议</th></tr></thead><tbody>{finding_rows}</tbody></table></div></details></section>
    <section id="scope"><div class="section-head"><div><h2>测评范围与变更</h2><p>资产和端口发生变化后，应以最新结果重新执行受影响检查。</p></div><span class="muted">{summary['total_assets']} 个资产 · {summary['total_evidences']} 条证据</span></div><div class="table-wrap"><table><thead><tr><th>资产名称</th><th>地址</th><th>类型</th><th>验证状态</th></tr></thead><tbody>{asset_rows}</tbody></table></div><div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>发现时间</th><th>类型</th><th>对象</th><th>变化</th><th>处理建议</th></tr></thead><tbody>{change_rows}</tbody></table></div></section>
  </div></div>
</main>
</body>
</html>"""
