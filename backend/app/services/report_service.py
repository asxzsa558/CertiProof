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
            "resolution_days": _duration_days(finding.created_at, ticket.resolved_at if ticket else finding.resolved_at),
            "evidence_count": len(related_evidence),
            "evidences": [_evidence_payload(evidence) for evidence in related_evidence],
            "created_at": _dt(finding.created_at),
        })

    score = project.compliance_score or 0
    report = {
        "report_version": "2.1-html",
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
            "closed_tickets": len([t for t in tickets if _value(t.status) in ("verified", "closed")]),
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
    return report


def _badge(text):
    return f'<span class="badge">{escape(str(text or "-"))}</span>'


def _change_text(item):
    changes = item.get("changes") or {}
    if item.get("type") == "asset":
        return f"新增资产 {len(changes.get('added_assets') or [])}；移除资产 {len(changes.get('removed_assets') or [])}"
    return (
        f"新增端口 {len(changes.get('added_ports') or [])}；"
        f"关闭端口 {len(changes.get('removed_ports') or [])}；"
        f"服务变化 {len(changes.get('service_changes') or [])}"
    )


async def generate_html_report(db: AsyncSession, project_id: int) -> str:
    report = await generate_json_report(db, project_id)
    project = report["project"]
    assessment = report["assessment"]
    summary = report["summary"]

    phase_rows = "\n".join(
        f"<tr><td>{escape(p['name'])}</td><td>{_badge(p['status'])}</td><td>{p['completed_tasks']}/{p['total_tasks']}</td><td>{round(p['progress'] or 0)}%</td></tr>"
        for p in assessment["phases"]
    ) or '<tr><td colspan="4">暂无测评阶段</td></tr>'
    finding_rows = "\n".join(
        f"<tr><td>#{f['id']}</td><td>{escape(str(f['clause_id'] or '-'))}</td><td>{_badge(f['severity'])}</td><td>{_badge(f['status'])}</td><td>{_badge(f['ticket_status'])}</td><td>{f['evidence_count']}</td><td>{escape(str(f['description'] or '-'))}</td><td>{escape(str(f['remediation_suggestion'] or '-'))}</td></tr>"
        for f in report["findings"]
    ) or '<tr><td colspan="8">暂无问题</td></tr>'
    timeline_rows = "\n".join(
        f"<tr><td>{escape(t['title'])}</td><td>{_badge(t['status'])}</td><td>{escape(str(t['priority'] or '-'))}</td><td>{escape(str(t['resolution_days'] if t['resolution_days'] is not None else '-'))}</td><td>{escape(str(t['skip_reason'] or '-'))}</td></tr>"
        for t in report["remediation_timeline"]
    ) or '<tr><td colspan="5">暂无整改记录</td></tr>'
    document_gap_rows = "\n".join(
        f"<tr><td>{escape(str(g['document_name'] or g['task_name']))}</td><td>{escape('、'.join(f.get('file_name', '-') for f in g.get('files', [])) or '-')}</td><td>{_badge(g['status'])}</td><td>{_badge(g.get('analysis_mode') or '-')}</td><td>{g.get('page_count') or 0} 页 / 原生 {g.get('native_blocks') or 0} / OCR {g.get('ocr_blocks') or 0} / 视觉 {g.get('vision_blocks') or 0}</td><td>{round((g['coverage'] or 0) * 100)}%</td><td>{escape('；'.join((g['gaps'] or [])[:5]) or '-')}</td></tr>"
        for g in report["document_gaps"]
    ) or '<tr><td colspan="7">暂无文档差距结果</td></tr>'
    asset_rows = "\n".join(
        f"<tr><td>{escape(str(a['name'] or '-'))}</td><td>{escape(a['value'])}</td><td>{_badge(a['asset_type'])}</td><td>{_badge(a['verification_status'])}</td></tr>"
        for a in report["assets"]
    ) or '<tr><td colspan="4">暂无资产</td></tr>'
    scan_rows = "\n".join(
        f"<tr><td>#{s['id']}</td><td>{escape(str((s['parameters'] or {}).get('capability') or s['task_type'] or '-'))}</td><td>{escape(str((s['parameters'] or {}).get('target') or (s['parameters'] or {}).get('targets') or '-'))}</td><td>{_badge(s['status'])}</td><td>{s['findings_count'] or 0}</td><td>{escape(str(s['error_message'] or '-'))}</td></tr>"
        for s in report["scan_tasks"]
    ) or '<tr><td colspan="6">暂无技术检测记录</td></tr>'
    retest_rows = "\n".join(
        f"<tr><td>{escape(str(r['document_name'] or r['task_name']))}</td><td>{round((r.get('previous_coverage') or 0) * 100)}%</td><td>{round((r.get('current_coverage') or 0) * 100)}%</td><td>{_badge(r.get('status'))}</td><td>{escape('；'.join(r.get('fixed_gaps') or []) or '-')}</td><td>{escape('；'.join(r.get('new_gaps') or []) or '-')}</td></tr>"
        for r in report["retest_comparisons"]
    ) or '<tr><td colspan="6">暂无复测对比记录</td></tr>'
    change_rows = "\n".join(
        f"<tr><td>{escape(c['created_at'] or '-')}</td><td>{_badge('资产' if c['type'] == 'asset' else '端口')}</td><td>{escape(c['subject'])}</td><td>{escape(_change_text(c))}</td><td>{_badge('需重新评估' if c['reassessment_required'] else '已知晓')}</td></tr>"
        for c in report["change_history"]
    ) or '<tr><td colspan="5">暂无资产或端口变化</td></tr>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>CertiProof 自查报告 - {escape(project['name'])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #08111f; color: #e5f1ff; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 40px 28px 64px; }}
    h1, h2 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: 30px; }}
    h2 {{ margin-top: 34px; font-size: 18px; color: #7dd3fc; }}
    .muted {{ color: #91a4bd; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 28px 0; }}
    .card {{ border: 1px solid rgba(125,211,252,.22); background: rgba(15,23,42,.84); border-radius: 8px; padding: 18px; }}
    .card strong {{ display: block; font-size: 28px; color: #fff; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: rgba(15,23,42,.72); border: 1px solid rgba(148,163,184,.2); }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid rgba(148,163,184,.16); text-align: left; vertical-align: top; }}
    th {{ color: #93c5fd; font-size: 12px; text-transform: uppercase; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: rgba(56,189,248,.13); color: #bae6fd; border: 1px solid rgba(56,189,248,.25); }}
    @media (max-width: 760px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} main {{ padding: 24px 14px; overflow-x: auto; }} }}
  </style>
</head>
<body>
<main>
  <p class="muted">CertiProof 企业等保自查报告 · HTML</p>
  <h1>{escape(project['name'])}</h1>
  <p class="muted">生成时间：{escape(report['generated_at'])} · 测评进度：{round(assessment['progress'] or 0)}%</p>
  <section class="grid">
    <div class="card"><strong>{summary['total_findings']}</strong><span class="muted">问题数</span></div>
    <div class="card"><strong>{summary['closed_tickets']}/{summary['total_tickets']}</strong><span class="muted">整改进度</span></div>
    <div class="card"><strong>{summary['total_evidences']}</strong><span class="muted">证据数量</span></div>
    <div class="card"><strong>{summary['skipped_tickets']}</strong><span class="muted">跳过项</span></div>
  </section>
  <h2>资产范围</h2>
  <table><thead><tr><th>资产名称</th><th>地址</th><th>类型</th><th>验证状态</th></tr></thead><tbody>{asset_rows}</tbody></table>
  <h2>5 阶段测评进度</h2>
  <table><thead><tr><th>阶段</th><th>状态</th><th>任务</th><th>进度</th></tr></thead><tbody>{phase_rows}</tbody></table>
  <h2>问题清单</h2>
  <table><thead><tr><th>ID</th><th>条款</th><th>级别</th><th>状态</th><th>工单</th><th>证据</th><th>问题</th><th>建议</th></tr></thead><tbody>{finding_rows}</tbody></table>
  <h2>文档差距</h2>
  <table><thead><tr><th>检查项</th><th>证据文件</th><th>结论</th><th>模式</th><th>解析来源</th><th>覆盖率</th><th>缺失项</th></tr></thead><tbody>{document_gap_rows}</tbody></table>
  <h2>技术检测记录</h2>
  <table><thead><tr><th>ID</th><th>检测能力</th><th>资产</th><th>状态</th><th>发现数</th><th>错误</th></tr></thead><tbody>{scan_rows}</tbody></table>
  <h2>复测对比</h2>
  <table><thead><tr><th>文档</th><th>整改前</th><th>整改后</th><th>变化</th><th>已修复</th><th>新增问题</th></tr></thead><tbody>{retest_rows}</tbody></table>
  <h2>整改时间线</h2>
  <table><thead><tr><th>事项</th><th>状态</th><th>优先级</th><th>解决时长/天</th><th>跳过原因</th></tr></thead><tbody>{timeline_rows}</tbody></table>
  <h2>资产与端口变化</h2>
  <table><thead><tr><th>时间</th><th>类型</th><th>资产</th><th>变化</th><th>状态</th></tr></thead><tbody>{change_rows}</tbody></table>
</main>
</body>
</html>"""


# Backward-compatible alias: old callers now receive HTML.
generate_report = generate_html_report
