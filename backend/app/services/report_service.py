"""HTML/JSON report service for CertiProof self-assessment."""

from datetime import datetime
from html import escape
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.project import Project
from app.models.asset import Asset
from app.models.scan_task import ScanTask
from app.models.finding import Finding
from app.models.evidence import Evidence
from app.models.assessment import Assessment, PhaseInstance, TaskInstance
from app.models.remediation import RemediationTicket
from app.models.change_snapshot import ChangeSnapshot


def _value(value):
    return value.value if hasattr(value, "value") else value


def _dt(value):
    return value.isoformat() if value else None


def _duration_days(start, end):
    if not start or not end:
        return None
    return max(0, (end - start).days)


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

DONE_TICKET_STATUSES = {"resolved", "verified", "closed"}


def _scan_name(task: dict) -> str:
    parameters = task.get("parameters") or {}
    capability = parameters.get("capability")
    return parameters.get("report_name") or CAPABILITY_LABELS.get(capability) or capability or task.get("task_type") or "未命名检测"


def _scan_target(task: dict) -> str:
    parameters = task.get("parameters") or {}
    summary = task.get("result_summary") or {}
    return str(parameters.get("target") or parameters.get("targets") or summary.get("target") or "-")


def _scan_outcome(task: dict) -> dict:
    """Keep execution state separate from the security conclusion in reports."""
    summary = task.get("result_summary") or {}
    data = summary.get("data") or {}
    execution = _value(task.get("status")) or "pending"
    result_status = _value(summary.get("status"))
    error = task.get("error_message") or summary.get("error")

    if execution in {"failed", "cancelled"} or error or result_status in {"failed", "error", "unable"}:
        return {"execution": execution, "result_status": result_status, "category": "unable", "label": "无法完成", "tone": "danger"}
    if execution in {"pending", "running"}:
        return {"execution": execution, "result_status": result_status, "category": "pending", "label": "尚未完成", "tone": "neutral"}
    if data.get("weak_credentials"):
        return {"execution": execution, "result_status": result_status, "category": "risk", "label": "发现弱口令", "tone": "danger"}
    if data.get("issues") or data.get("findings"):
        return {"execution": execution, "result_status": result_status, "category": "risk", "label": "发现需关注项", "tone": "warning"}
    if task.get("findings_count") or result_status in {"warning", "fail", "partial", "contradict"}:
        return {"execution": execution, "result_status": result_status, "category": "risk", "label": "发现需关注项", "tone": "warning"}
    if data.get("open_ports"):
        return {"execution": execution, "result_status": result_status, "category": "observed", "label": "发现服务，需结合风险判断", "tone": "info"}
    if result_status in {"success", "pass"}:
        return {"execution": execution, "result_status": result_status, "category": "clean", "label": "本次未发现问题", "tone": "good"}
    return {"execution": execution, "result_status": result_status, "category": "inconclusive", "label": "已执行，结论待确认", "tone": "neutral"}


def _finding_lifecycle(finding: dict) -> str:
    ticket_status = finding.get("ticket_status")
    if ticket_status == "skipped":
        return "skipped"
    if ticket_status in DONE_TICKET_STATUSES or finding.get("status") in {"resolved", "false_positive"}:
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


async def generate_json_report(db: AsyncSession, project_id: int) -> dict:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise ValueError("Project not found")

    result = await db.execute(
        select(Assessment)
        .where(Assessment.project_id == project_id)
        .order_by(Assessment.created_at.desc())
        .limit(1)
    )
    assessment = result.scalar_one_or_none()

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
        select(ScanTask).where(ScanTask.project_id == project_id).order_by(ScanTask.created_at.desc())
    )
    scan_tasks = result.scalars().all()

    result = await db.execute(
        select(Asset).where(Asset.project_id == project_id).order_by(Asset.id)
    )
    assets = result.scalars().all()

    result = await db.execute(
        select(Finding).where(Finding.project_id == project_id).order_by(Finding.severity)
    )
    findings = result.scalars().all()

    result = await db.execute(
        select(RemediationTicket).where(RemediationTicket.project_id == project_id).order_by(RemediationTicket.created_at.desc())
    )
    tickets = result.scalars().all()
    result = await db.execute(
        select(ChangeSnapshot)
        .where(ChangeSnapshot.project_id == project_id, ChangeSnapshot.changes_detected.is_(True))
        .order_by(ChangeSnapshot.id.desc())
        .limit(100)
    )
    change_snapshots = result.scalars().all()
    ticket_by_finding = {ticket.finding_id: ticket for ticket in tickets}

    finding_ids = [finding.id for finding in findings]
    explicit_evidence_ids = sorted({evidence_id for finding in findings for evidence_id in _finding_evidence_ids(finding)})
    evidence_by_id = {}
    if finding_ids:
        result = await db.execute(select(Evidence).where(Evidence.finding_id.in_(finding_ids)))
        evidence_by_id.update({evidence.id: evidence for evidence in result.scalars().all()})
    if explicit_evidence_ids:
        result = await db.execute(select(Evidence).where(Evidence.id.in_(explicit_evidence_ids)))
        evidence_by_id.update({evidence.id: evidence for evidence in result.scalars().all()})
    evidences = list(evidence_by_id.values())
    project_evidence_count = (await db.execute(
        select(func.count()).select_from(Evidence).where(Evidence.project_id == project_id)
    )).scalar() or len(evidences)

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
        related_evidence = [e for e in evidences if e.finding_id == finding.id or e.id in related_ids]
        ticket = ticket_by_finding.get(finding.id)
        findings_data.append({
            "id": finding.id,
            "clause_id": finding.clause_id,
            "clause_name": finding.clause_name,
            "severity": severity,
            "judgment": judgment,
            "judgment_engine": _value(finding.judgment_engine),
            "description": finding.description,
            "remediation_suggestion": finding.remediation_suggestion,
            "status": status,
            "ticket_status": _value(ticket.status) if ticket else None,
            "ticket_priority": ticket.priority if ticket else None,
            "ticket_title": ticket.title if ticket else None,
            "resolution_days": _duration_days(finding.created_at, ticket.resolved_at if ticket else finding.resolved_at),
            "evidence_count": len(related_evidence),
            "evidences": [_evidence_payload(evidence) for evidence in related_evidence],
            "created_at": _dt(finding.created_at),
        })

    score = project.compliance_score or 0
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
            "name": assessment.name if assessment else None,
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
            "total_tickets": len(tickets),
            "closed_tickets": len([t for t in tickets if _value(t.status) in ("resolved", "verified", "closed")]),
            "skipped_tickets": len([t for t in tickets if _value(t.status) == "skipped"]),
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
                "parameters": task.parameters,
                "result_summary": task.result_summary,
                "error_message": task.error_message,
                "findings_count": task.findings_count,
                "created_at": _dt(task.created_at),
                "completed_at": _dt(task.completed_at),
            }
            for task in scan_tasks
        ],
        "findings": findings_data,
        "remediation_timeline": [
            {
                "id": ticket.id,
                "finding_id": ticket.finding_id,
                "title": ticket.title,
                "status": _value(ticket.status),
                "priority": ticket.priority,
                "created_at": _dt(ticket.created_at),
                "resolved_at": _dt(ticket.resolved_at),
                "verified_at": _dt(ticket.verified_at),
                "resolution_days": _duration_days(ticket.created_at, ticket.resolved_at or ticket.verified_at),
                "skip_reason": getattr(ticket, "skip_reason", None),
            }
            for ticket in tickets
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
    report["retest_comparisons"] = [
        {
            "task_name": task["name"],
            "document_name": analysis.get("document_name"),
            **analysis["retest_comparison"],
        }
        for phase in phases_data
        for task in phase["tasks"]
        if (analysis := (task.get("result") or {}).get("analysis", {})).get("retest_comparison")
    ]
    technical_scans = [
        {
            **task,
            "name": _scan_name(task),
            "target": _scan_target(task),
            "phase": (task.get("parameters") or {}).get("report_phase") or "独立检测",
            "outcome": _scan_outcome(task),
        }
        for task in report["scan_tasks"]
        if (task.get("result_summary") or {}).get("type") != "document_control_analysis"
    ]
    for finding in report["findings"]:
        finding["lifecycle"] = _finding_lifecycle(finding)
        finding["priority"] = finding.get("ticket_priority") or finding.get("severity") or "medium"

    open_findings = [finding for finding in report["findings"] if finding["lifecycle"] == "open"]
    closed_findings = [finding for finding in report["findings"] if finding["lifecycle"] == "closed"]
    skipped_findings = [finding for finding in report["findings"] if finding["lifecycle"] == "skipped"]
    high_risk_open = sum(1 for finding in open_findings if finding.get("severity") in {"critical", "high"})
    unable_scans = [scan for scan in technical_scans if scan["outcome"]["category"] == "unable"]
    risk_scans = [scan for scan in technical_scans if scan["outcome"]["category"] == "risk"]
    clean_scans = [scan for scan in technical_scans if scan["outcome"]["category"] == "clean"]
    document_unable = sum(1 for item in report["document_gaps"] if item.get("status") == "unable")
    document_attention = sum(1 for item in report["document_gaps"] if item.get("status") in {"fail", "partial", "unable"})
    report["summary"].update({
        "open_findings": len(open_findings),
        "closed_findings": len(closed_findings),
        "skipped_findings": len(skipped_findings),
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
    report["finding_lifecycle"] = {"open": open_findings, "closed": closed_findings, "skipped": skipped_findings}
    report["report_conclusion"] = {
        "state": conclusion[0],
        "message": conclusion[1],
        "basis": f"基于 {len(technical_scans)} 次技术检测、{len(report['document_gaps'])} 项文档核查和 {len(report['findings'])} 个问题记录生成。",
    }
    return report


LABELS = {
    "critical": "严重", "high": "高", "medium": "中", "low": "低", "info": "提示",
    "open": "待整改", "in_progress": "整改中", "resolved": "已解决", "verified": "复测通过", "closed": "已关闭", "skipped": "已跳过",
    "pending": "未开始", "running": "执行中", "completed": "已执行", "failed": "执行失败", "cancelled": "已取消",
    "pass": "符合", "success": "成功", "fail": "不符合", "partial": "部分符合", "unable": "无法判断", "warning": "需关注", "improved": "已改善",
    "attention": "需要处理", "progress": "测评进行中", "ready": "结论可用",
    "ip": "IP 主机", "domain": "域名", "cloud_resource": "云资源", "unverified": "未验证",
}

ASSET_VERIFICATION_LABELS = {"verified": "已验证", "unverified": "未验证"}


def _tone(value) -> str:
    value = _value(value)
    if value in {"critical", "high", "failed", "fail", "unable", "open"}:
        return "danger"
    if value in {"medium", "warning", "partial", "in_progress", "attention"}:
        return "warning"
    if value in {"pass", "success", "resolved", "verified", "closed", "completed", "ready", "improved"}:
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
    data = summary.get("data") or {}
    if data.get("open_ports") is not None:
        ports = ", ".join(f"{item.get('port')}/{item.get('protocol', 'tcp')} {item.get('service') or ''}".strip() for item in data.get("open_ports") or [])
        fixed = ", ".join(str(item.get("port")) for item in data.get("fixed_ports") or [])
        parts = [f"开放端口：{ports or '无'}"]
        if fixed:
            parts.append(f"已修复端口：{fixed}")
        return "；".join(parts)
    if data.get("weak_credentials") is not None:
        return f"弱口令命中：{len(data.get('weak_credentials') or [])}；字典组：{data.get('credential_sets') or 0}"
    if data.get("issues") is not None:
        return "；".join(data.get("issues") or []) or "未发现 SSL/TLS 问题"
    if data.get("findings") is not None:
        return f"发现项：{len(data.get('findings') or [])}；{data.get('conclusion') or ''}".strip("；")
    return data.get("conclusion") or summary.get("status") or "-"


def _percent(value) -> str:
    return f"{round((value or 0) * 100)}%"


def _timestamp(value) -> str:
    if not value:
        return "-"
    return str(value).replace("T", " ").split("+")[0].split(".")[0]


async def generate_html_report(db: AsyncSession, project_id: int) -> str:
    report = await generate_json_report(db, project_id)
    project = report["project"]
    assessment = report["assessment"]
    summary = report["summary"]
    conclusion = report["report_conclusion"]
    lifecycle = report["finding_lifecycle"]

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    open_findings = sorted(lifecycle["open"], key=lambda item: priority_order.get(item.get("priority"), 9))

    phase_rows = "\n".join(
        f"<tr><td><strong>{escape(p['name'])}</strong></td><td>{_badge(p['status'])}</td><td>{p['completed_tasks']}/{p['total_tasks']}</td><td><div class=\"progress\"><i style=\"width:{max(0, min(100, round(p['progress'] or 0)))}%\"></i></div><em>{round(p['progress'] or 0)}%</em></td></tr>"
        for p in assessment["phases"]
    ) or '<tr><td colspan="4">暂无测评阶段</td></tr>'
    priority_rows = "\n".join(
        f"<article class=\"action-item\"><div>{_badge(f['priority'])}<strong>{escape(str(f.get('ticket_title') or f.get('clause_name') or f['clause_id'] or '待整改事项'))}</strong></div><p>{escape(str(f['description'] or '-'))}</p><footer><span>当前：{_badge(f.get('ticket_status') or f['status'])}</span><span>证据 {f['evidence_count']} 条</span></footer><p class=\"recommendation\">{escape(str(f['remediation_suggestion'] or '请补充整改措施并重新验证。'))}</p></article>"
        for f in open_findings[:12]
    ) or '<p class="empty">当前没有待整改问题。</p>'
    document_retest_rows = "\n".join(
        f"<tr><td>文档复测</td><td><strong>{escape(str(r['document_name'] or r['task_name']))}</strong></td><td>{_badge(r.get('previous_status'))} {_percent(r.get('previous_coverage'))}</td><td>{_badge(r.get('current_status'))} {_percent(r.get('current_coverage'))}</td><td>已修复 {len(r.get('fixed_gaps') or [])} 项；新增 {len(r.get('new_gaps') or [])} 项</td></tr>"
        for r in report["retest_comparisons"]
    )
    technical_retest_rows = "\n".join(
        f"<tr><td>技术复测</td><td><strong>{escape(scan['name'])}</strong><br><span class=\"muted\">{escape(scan['target'])}</span></td><td>单次复测记录</td><td>{_badge(scan['outcome']['label'], scan['outcome']['tone'])}</td><td>{escape(_scan_brief(scan))}</td></tr>"
        for scan in report["technical_scans"]
        if scan["phase"] == "复测验证"
    )
    retest_rows = document_retest_rows + technical_retest_rows or '<tr><td colspan="5">尚未产生可追溯的复测结果。</td></tr>'
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
        f"<tr><td>#{f['id']}</td><td>{escape(str(f['clause_id'] or '-'))}</td><td>{_badge(f['priority'])}</td><td>{_badge(f['lifecycle'])}</td><td>{_badge(f.get('ticket_status') or f['status'])}</td><td>{f['evidence_count']}</td><td>{escape(str(f['description'] or '-'))}</td><td>{escape(str(f['remediation_suggestion'] or '-'))}</td></tr>"
        for f in sorted(report["findings"], key=lambda item: (item["lifecycle"] != "open", priority_order.get(item.get("priority"), 9)))
    ) or '<tr><td colspan="8">未产生问题记录。</td></tr>'
    change_rows = "\n".join(
        f"<tr><td>{escape(_timestamp(c['created_at']))}</td><td>{_badge('资产' if c['type'] == 'asset' else '端口', 'info')}</td><td>{escape(c['subject'])}</td><td>{escape(_change_text(c))}</td><td>{_badge('需重新评估' if c['reassessment_required'] else '已知晓', 'warning' if c['reassessment_required'] else 'good')}</td></tr>"
        for c in report["change_history"]
    ) or '<tr><td colspan="5">暂无资产或端口变化</td></tr>'

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
    .action-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }} .action-item {{ min-width:0; padding:15px; border:1px solid #31445a; background:#0a1928; }} .action-item > div {{ display:flex; align-items:center; gap:8px; }} .action-item strong {{ min-width:0; overflow-wrap:anywhere; font-size:14px; }} .action-item p {{ margin-top:10px; color:#c9d8e6; }} .action-item footer {{ display:flex; justify-content:space-between; gap:8px; margin-top:12px; color:var(--muted); font-size:11px; }} .action-item .recommendation {{ padding-top:10px; border-top:1px solid var(--line); color:#9fddeb; }} .empty {{ color:var(--muted); padding:14px 0; }}
    .table-wrap {{ overflow:auto; border:1px solid var(--line); background:#091827; }} table {{ width:100%; min-width:680px; border-collapse:collapse; }} th,td {{ padding:11px 12px; border-bottom:1px solid #183247; text-align:left; vertical-align:top; }} th {{ color:#9ec9df; background:#0c2032; font-size:11px; font-weight:600; }} td {{ color:#d7e5ef; font-size:12px; }} tr:last-child td {{ border-bottom:0; }} td em {{ display:inline-block; margin-left:8px; color:var(--muted); font-size:11px; font-style:normal; }} .progress {{ display:inline-block; width:92px; height:6px; margin-right:6px; overflow:hidden; vertical-align:middle; background:#10283a; }} .progress i {{ display:block; height:100%; background:var(--cyan); }}
    details {{ border:1px solid var(--line); background:#091827; }} summary {{ padding:12px 14px; color:#c8e9f3; cursor:pointer; }} details .table-wrap {{ border-width:1px 0 0; }}
    @media (max-width:900px) {{ .shell {{ padding:20px 14px 44px; }} .metrics,.action-list {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .layout {{ display:block; }} .toc {{ position:static; grid-template-columns:repeat(2,minmax(0,1fr)); margin-bottom:24px; padding:0 0 12px; border-right:0; border-bottom:1px solid var(--line); }} }} @media (max-width:560px) {{ h1 {{ font-size:26px; }} .hero-line {{ align-items:flex-start; flex-direction:column; }} .metrics,.action-list {{ grid-template-columns:1fr; }} .toc {{ grid-template-columns:1fr; }} }}
    @media print {{ body {{ background:#fff; color:#172231; }} .shell {{ max-width:none; padding:16mm; }} .hero,section {{ border-color:#d7e0e8; }} .metric,.conclusion,.action-item,.table-wrap,details {{ background:#fff; border-color:#d7e0e8; }} .toc {{ display:none; }} .layout {{ display:block; }} .badge {{ color:#172231; background:#fff; border-color:#8495a6; }} th {{ color:#172231; background:#eef4f8; }} td {{ color:#263747; border-color:#d7e0e8; }} .muted,.meta,.section-head p {{ color:#52697d; }} }}
  </style>
</head>
<body>
<main class="shell">
  <header class="hero"><p class="eyebrow">CERTIPROOF / 企业等保自查报告 / HTML</p><h1>{escape(project['name'])}</h1><div class="hero-line"><p class="meta">等保等级：{escape(str(project['compliance_level'] or '未定级'))} · 生成时间：{escape(_timestamp(report['generated_at']))}</p><p class="meta">流程进度：{round(assessment['progress'] or 0)}% · 已完成阶段：{assessment['completed_phases']}/{assessment['total_phases']}</p></div></header>
  <section class="conclusion"><div>{_badge('attention' if conclusion['state'] == 'attention' else conclusion['state'], 'warning' if conclusion['state'] == 'attention' else ('good' if conclusion['state'] == 'ready' else 'neutral'))}</div><div><h2>自查结论</h2><p>{escape(conclusion['message'])}</p><small>{escape(conclusion['basis'])}</small></div></section>
  <section class="metrics" aria-label="报告摘要"><div class="metric"><strong>{summary['open_findings']}</strong><span>当前待整改问题</span></div><div class="metric"><strong>{summary['high_risk_open']}</strong><span>其中高风险问题</span></div><div class="metric"><strong>{summary['closed_findings']}/{summary['total_findings']}</strong><span>已闭环 / 累计发现</span></div><div class="metric"><strong>{summary['clean_scans']}/{summary['technical_scans']}</strong><span>本次未发现问题的技术检测</span></div></section>
  <div class="layout"><nav class="toc"><span>报告目录</span><a href="#actions">待整改事项</a><a href="#retest">复测验证</a><a href="#coverage">检测覆盖</a><a href="#documents">文档合规</a><a href="#findings">问题闭环</a><a href="#scope">范围与变化</a></nav><div class="content">
    <section id="actions"><div class="section-head"><div><h2>当前待整改事项</h2><p>只列出尚未关闭或跳过的问题，按优先级排序。</p></div><span class="muted">{summary['open_findings']} 项</span></div><div class="action-list">{priority_rows}</div></section>
    <section id="retest"><div class="section-head"><div><h2>复测验证</h2><p>仅展示具有真实前后对比的文档复测，以及明确标为“复测验证”的技术检查。</p></div><span class="muted">文档 {len(report['retest_comparisons'])} 项</span></div><div class="table-wrap"><table><thead><tr><th>类型</th><th>对象</th><th>整改前</th><th>当前结果</th><th>变化说明</th></tr></thead><tbody>{retest_rows}</tbody></table></div></section>
    <section id="coverage"><div class="section-head"><div><h2>检测覆盖与执行结果</h2><p>“执行状态”只表示工具是否运行；“检测结论”才表示本次发现。</p></div><span class="muted">无法完成 {summary['unable_scans']} 项 · 需关注 {summary['risk_scans']} 项</span></div><div class="table-wrap"><table><thead><tr><th>阶段</th><th>检测内容</th><th>资产</th><th>执行状态</th><th>检测结论</th><th>结果摘要</th><th>错误详情</th></tr></thead><tbody>{scan_rows}</tbody></table></div><div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>测评阶段</th><th>阶段状态</th><th>完成任务</th><th>进度</th></tr></thead><tbody>{phase_rows}</tbody></table></div></section>
    <section id="documents"><div class="section-head"><div><h2>文档合规核查</h2><p>结论来自已提取的正文、OCR 或视觉解析内容；“无法判断”不会计为符合。</p></div><span class="muted">待关注 {summary['document_attention']} 项</span></div><div class="table-wrap"><table><thead><tr><th>检查项</th><th>当前结论</th><th>覆盖率</th><th>证据文件</th><th>解析来源</th><th>仍缺少的内容</th></tr></thead><tbody>{document_gap_rows}</tbody></table></div></section>
    <section id="findings"><div class="section-head"><div><h2>问题闭环明细</h2><p>累计问题保留可追溯记录；已关闭项目不会混入当前待整改清单。</p></div><span class="muted">已关闭 {summary['closed_findings']} · 已跳过 {summary['skipped_findings']}</span></div><details><summary>展开全部 {summary['total_findings']} 个问题的状态、证据与整改建议</summary><div class="table-wrap"><table><thead><tr><th>ID</th><th>条款 / 编号</th><th>优先级</th><th>生命周期</th><th>整改状态</th><th>证据</th><th>问题描述</th><th>整改建议</th></tr></thead><tbody>{finding_rows}</tbody></table></div></details></section>
    <section id="scope"><div class="section-head"><div><h2>测评范围与变更</h2><p>资产和端口发生变化后，应以最新结果重新执行受影响检查。</p></div><span class="muted">{summary['total_assets']} 个资产 · {summary['total_evidences']} 条证据</span></div><div class="table-wrap"><table><thead><tr><th>资产名称</th><th>地址</th><th>类型</th><th>验证状态</th></tr></thead><tbody>{asset_rows}</tbody></table></div><div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>发现时间</th><th>类型</th><th>对象</th><th>变化</th><th>处理建议</th></tr></thead><tbody>{change_rows}</tbody></table></div></section>
  </div></div>
</main>
</body>
</html>"""


# Backward-compatible alias: old callers now receive HTML.
generate_report = generate_html_report
