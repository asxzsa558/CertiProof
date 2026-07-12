"""End-to-end MVP flow check with a generated HTML/JSON report.

Creates a temporary project, runs the five-stage assessment core path,
generates findings/remediation/change evidence, writes reports, then cleans up.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine as db_engine
from app.models.asset import Asset, AssetType, VerificationStatus
from app.models.assessment import Assessment, TaskInstance
from app.models.assessment_type import ProjectAssessment
from app.models.change_snapshot import ChangeSnapshot
from app.models.evidence import Evidence, EvidenceType
from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.organization import OrganizationMember
from app.models.project import ComplianceLevel, Project, ProjectStatus
from app.models.remediation import RemediationStatus, RemediationTicket
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy
from app.models.user import User
from app.services.change_detection import record_asset_snapshot, record_port_snapshots
from app.services.document_pipeline import create_document_run, process_document_run
from app.services.file_storage import file_storage
from app.services.flow_engine import get_flow_engine
from app.services.report_service import generate_html_report, generate_json_report


STAGE_NAMES = ["差距分析", "现场测评", "整改加固", "复测验证", "生成报告"]


def _enum_value(value):
    return getattr(value, "value", value)


async def _first_user_and_org(db):
    user = (await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.id).limit(1))).scalar_one_or_none()
    if not user:
        raise RuntimeError("No active user exists; cannot run full flow check.")
    member = (await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.user_id == user.id)
        .order_by(OrganizationMember.id)
        .limit(1)
    )).scalar_one_or_none()
    return user, member.organization_id if member else None


async def _save_document_evidence(db, project_id: int, task: TaskInstance, file_name: str, content: str, user_id: int):
    file_path, digest, file_size = await file_storage.save_file(project_id, file_name, content.encode("utf-8"))
    evidence = Evidence(
        project_id=project_id,
        evidence_type=EvidenceType.DOCUMENT,
        source="full_flow_e2e",
        file_name=file_name,
        file_path=file_path,
        file_size=file_size,
        mime_type="text/plain",
        clause_id=f"DOC-TASK-{task.id}",
        hash_sha256=digest,
        uploaded_by=user_id,
        description=f"自动化验收：{task.name}",
    )
    db.add(evidence)
    await db.commit()
    return evidence


async def _replace_document_evidence(db, project_id: int, task: TaskInstance, file_name: str, content: str, user_id: int):
    clause_id = f"DOC-TASK-{task.id}"
    evidences = (await db.execute(
        select(Evidence).where(Evidence.project_id == project_id, Evidence.clause_id == clause_id)
    )).scalars().all()
    for evidence in evidences:
        if evidence.file_path:
            await file_storage.delete_file(evidence.file_path)
        await db.delete(evidence)
    await db.commit()
    return await _save_document_evidence(db, project_id, task, file_name, content, user_id)


async def _run_document_analysis(db, task: TaskInstance, project_id: int, user_id: int):
    run = await create_document_run(db, task, project_id, user_id, "standard")
    await process_document_run(db, run)
    await db.refresh(run)
    task = await db.get(TaskInstance, task.id)
    analysis = (task.result or {}).get("analysis") if task and task.result else None
    if not analysis or run.status != ScanTaskStatus.COMPLETED:
        raise AssertionError(f"document run failed: run={run.id}, status={run.status}, analysis={analysis}")
    return run, task, analysis


async def _complete_remaining_tasks(db, assessment_id: int):
    engine = get_flow_engine(db)
    phases = await engine.get_phases(assessment_id)
    for phase in phases:
        tasks = await engine.get_tasks(phase.id, official_only=True)
        for task in tasks:
            if task.status == "completed":
                continue
            if task.status == "todo":
                await engine.start_task(task.id)
            if task.status == "in_progress":
                await engine.complete_task(task.id, {
                    "type": task.task_type,
                    "status": "completed",
                    "simulated_for_e2e": True,
                    "message": "自动化验收模拟完成，技术检测详情由独立 Finding/ScanTask 覆盖。",
                })


async def _add_scan_task(
    db,
    project_id: int,
    *,
    capability: str,
    target: str,
    report_phase: str,
    report_name: str,
    data: dict,
    findings_count: int = 0,
    high_count: int = 0,
    medium_count: int = 0,
    low_count: int = 0,
    status: str = "success",
):
    scan_task = ScanTask(
        project_id=project_id,
        task_type=ScanTaskType.TARGETED,
        status=ScanTaskStatus.COMPLETED,
        triggered_by=TriggeredBy.MANUAL,
        parameters={
            "capability": capability,
            "target": target,
            "report_phase": report_phase,
            "report_name": report_name,
            "source": "full_flow_e2e",
        },
        progress={"stage": "completed", "percent": 100, "message": f"{report_name}完成"},
        result_summary={
            "status": status,
            "target": target,
            "capability": capability,
            "data": data,
        },
        findings_count=findings_count,
        high_severity_count=high_count,
        medium_severity_count=medium_count,
        low_severity_count=low_count,
        completed_at=datetime.utcnow(),
    )
    db.add(scan_task)
    await db.flush()
    return scan_task


async def _add_finding_with_ticket(
    db,
    scan_task: ScanTask,
    project_id: int,
    user_id: int,
    *,
    clause_id: str,
    clause_name: str,
    severity: Severity,
    description: str,
    remediation: str,
    ticket_status: RemediationStatus,
    finding_status: FindingStatus = FindingStatus.OPEN,
    priority: str = "medium",
):
    resolved_at = datetime.utcnow() if finding_status == FindingStatus.RESOLVED else None
    finding = Finding(
        project_id=project_id,
        scan_task_id=scan_task.id,
        clause_id=clause_id,
        clause_name=clause_name,
        severity=severity,
        judgment=Judgment.FAIL,
        judgment_engine=JudgmentEngine.RULE,
        confidence=0.96,
        description=description,
        remediation_suggestion=remediation,
        status=finding_status,
        resolved_at=resolved_at,
    )
    db.add(finding)
    await db.flush()

    evidence = Evidence(
        finding_id=finding.id,
        project_id=project_id,
        evidence_type=EvidenceType.TOOL_OUTPUT,
        source=(scan_task.parameters or {}).get("capability"),
        content=scan_task.result_summary,
        raw_output=json.dumps(scan_task.result_summary, ensure_ascii=False),
        clause_id=finding.clause_id,
        uploaded_by=user_id,
        description=f"自动化验收：{clause_name}",
    )
    db.add(evidence)
    await db.flush()
    finding.evidence_ids = [evidence.id]

    db.add(RemediationTicket(
        finding_id=finding.id,
        project_id=project_id,
        title=description,
        description=description,
        remediation_plan=remediation,
        priority=priority,
        assigned_by=user_id,
        status=ticket_status,
        resolution_notes="自动化验收：已完成整改并进入复测验证。" if ticket_status in {RemediationStatus.VERIFIED, RemediationStatus.CLOSED} else "自动化验收：已创建整改项。",
        resolved_at=resolved_at,
        verified_at=datetime.utcnow() if ticket_status in {RemediationStatus.VERIFIED, RemediationStatus.CLOSED} else None,
    ))
    return finding


async def _add_technical_finding(db, project_id: int, user_id: int):
    port_scan = await _add_scan_task(
        db,
        project_id,
        capability="scan_ports",
        target="203.0.113.10",
        report_phase="差距分析",
        report_name="基础技术检测：高危端口扫描",
        findings_count=1,
        high_count=1,
        status="warning",
        data={
            "reachable": True,
            "scan_completed": True,
            "open_ports": [
                {"port": 22, "protocol": "tcp", "service": "ssh"},
                {"port": 3306, "protocol": "tcp", "service": "mysql"},
            ],
        },
    )
    await _add_finding_with_ticket(
        db,
        port_scan,
        project_id,
        user_id,
        clause_id="TECH-E2E-HIGH-RISK-PORT",
        clause_name="高危端口暴露",
        severity=Severity.HIGH,
        description="自动化验收发现 MySQL 3306 端口对测试资产暴露。",
        remediation="限制数据库端口访问源，启用防火墙策略并复测端口暴露面。",
        finding_status=FindingStatus.RESOLVED,
        ticket_status=RemediationStatus.VERIFIED,
        priority="high",
    )

    await _add_scan_task(
        db,
        project_id,
        capability="scan_weak_passwords",
        target="203.0.113.10:22",
        report_phase="差距分析",
        report_name="基础技术检测：弱口令检测",
        status="success",
        data={
            "service": "ssh",
            "attempted": True,
            "credential_sets": 12,
            "weak_credentials": [],
            "conclusion": "未发现弱口令，但已记录认证尝试范围。",
        },
    )

    ssl_scan = await _add_scan_task(
        db,
        project_id,
        capability="scan_ssl",
        target="https://e2e-added.example.test",
        report_phase="差距分析",
        report_name="基础技术检测：SSL/TLS 检测",
        findings_count=1,
        medium_count=1,
        status="warning",
        data={
            "certificate_valid": True,
            "issues": ["TLS 1.0/1.1 未明确禁用", "缺少 HSTS 响应头"],
        },
    )
    await _add_finding_with_ticket(
        db,
        ssl_scan,
        project_id,
        user_id,
        clause_id="TECH-E2E-SSL-HARDENING",
        clause_name="SSL/TLS 加固不足",
        severity=Severity.MEDIUM,
        description="基础技术检测发现 TLS 加固项不完整。",
        remediation="禁用旧协议版本，补充 HSTS 等安全响应头后复测。",
        finding_status=FindingStatus.OPEN,
        ticket_status=RemediationStatus.IN_PROGRESS,
    )

    web_scan = await _add_scan_task(
        db,
        project_id,
        capability="nikto_scan",
        target="http://e2e-added.example.test",
        report_phase="现场测评",
        report_name="现场测评：Web 深度扫描",
        findings_count=1,
        medium_count=1,
        status="warning",
        data={
            "paths_checked": 42,
            "findings": [
                {"severity": "medium", "title": "缺少 X-Frame-Options 响应头"},
            ],
        },
    )
    await _add_finding_with_ticket(
        db,
        web_scan,
        project_id,
        user_id,
        clause_id="FIELD-E2E-WEB-HEADER",
        clause_name="Web 安全响应头缺失",
        severity=Severity.MEDIUM,
        description="现场测评发现 Web 服务缺少 X-Frame-Options 响应头。",
        remediation="在反向代理或应用网关补充安全响应头并复测。",
        finding_status=FindingStatus.RESOLVED,
        ticket_status=RemediationStatus.VERIFIED,
    )

    await _add_scan_task(
        db,
        project_id,
        capability="nuclei_scan",
        target="http://e2e-added.example.test",
        report_phase="现场测评",
        report_name="现场测评：漏洞扫描",
        status="success",
        data={
            "templates": 128,
            "findings": [],
            "conclusion": "未发现高危漏洞模板命中。",
        },
    )

    await _add_scan_task(
        db,
        project_id,
        capability="scan_ports",
        target="203.0.113.10",
        report_phase="复测验证",
        report_name="复测验证：端口整改复测",
        status="success",
        data={
            "reachable": True,
            "scan_completed": True,
            "open_ports": [{"port": 22, "protocol": "tcp", "service": "ssh"}],
            "fixed_ports": [{"port": 3306, "protocol": "tcp", "service": "mysql"}],
            "conclusion": "复测未再发现 MySQL 3306 对外暴露。",
        },
    )
    await db.commit()
    return port_scan


async def _add_change_history(db, project_id: int, scan_task_id: int):
    await record_asset_snapshot(db, project_id)
    db.add(Asset(
        project_id=project_id,
        asset_type=AssetType.DOMAIN,
        value="e2e-added.example.test",
        name="自动化新增资产",
        verification_status=VerificationStatus.VERIFIED,
        is_active=True,
    ))
    await db.flush()
    await record_asset_snapshot(db, project_id)
    await record_port_snapshots(db, project_id, scan_task_id, {
        "203.0.113.10": {
            "status": "success",
            "capability": "scan_ports",
            "parameters": {"scan_mode": "high-risk"},
            "data": {
                "reachable": True,
                "scan_completed": True,
                "open_ports": [{"port": 22, "protocol": "tcp", "service": "ssh"}],
            },
        }
    })
    await record_port_snapshots(db, project_id, scan_task_id, {
        "203.0.113.10": {
            "status": "success",
            "capability": "scan_ports",
            "parameters": {"scan_mode": "high-risk"},
            "data": {
                "reachable": True,
                "scan_completed": True,
                "open_ports": [
                    {"port": 22, "protocol": "tcp", "service": "ssh"},
                    {"port": 3306, "protocol": "tcp", "service": "mysql"},
                ],
            },
        }
    })
    await db.commit()


async def _cleanup_project(db, project_id: int):
    evidences = (await db.execute(select(Evidence).where(Evidence.project_id == project_id))).scalars().all()
    for evidence in evidences:
        if evidence.file_path:
            await file_storage.delete_file(evidence.file_path)
    assessment_ids = (await db.execute(select(Assessment.id).where(Assessment.project_id == project_id))).scalars().all()
    for assessment_id in assessment_ids:
        assessment = await db.get(Assessment, assessment_id)
        if assessment:
            await db.delete(assessment)
    await db.execute(delete(ProjectAssessment).where(ProjectAssessment.project_id == project_id))
    await db.execute(delete(ChangeSnapshot).where(ChangeSnapshot.project_id == project_id))
    await db.execute(delete(RemediationTicket).where(RemediationTicket.project_id == project_id))
    await db.execute(delete(Evidence).where(Evidence.project_id == project_id))
    await db.execute(delete(Finding).where(Finding.project_id == project_id))
    await db.execute(delete(ScanTask).where(ScanTask.project_id == project_id))
    await db.execute(delete(Asset).where(Asset.project_id == project_id))
    project = await db.get(Project, project_id)
    if project:
        await db.delete(project)
    await db.commit()


async def run_full_flow():
    db_engine.echo = False
    for logger_name in ("sqlalchemy.engine", "sqlalchemy.engine.Engine"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    html_output = Path(os.getenv("REPORT_OUTPUT", "/tmp/certiproof-full-flow-report.html"))
    json_output = Path(os.getenv("REPORT_JSON_OUTPUT", "/tmp/certiproof-full-flow-report.json"))
    keep_project = os.getenv("KEEP_E2E_PROJECT", "").lower() in {"1", "true", "yes"}
    project_id = None

    async with AsyncSessionLocal() as db:
        user, org_id = await _first_user_and_org(db)
        marker = uuid.uuid4().hex[:8]
        project = Project(
            user_id=user.id,
            owner_id=user.id,
            organization_id=org_id,
            name=f"CertiProof 自动化验收 {marker}",
            system_name="自动化等保自查系统",
            description="临时项目：验证 5 阶段流程、文档合规、整改、变化检测和 HTML 报告。",
            compliance_level=ComplianceLevel.LEVEL_3,
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.flush()
        project_id = project.id
        db.add(Asset(
            project_id=project.id,
            asset_type=AssetType.IP,
            value="203.0.113.10",
            name="自动化测试资产",
            verification_status=VerificationStatus.VERIFIED,
            is_active=True,
        ))
        await db.commit()

        engine = get_flow_engine(db)
        templates = await engine.upsert_default_templates()
        template = next(item for item in templates if item.compliance_level == 3)
        assessment = await engine.create_assessment(project.id, template.id, "自动化 5 阶段等保自查", user.id)
        await engine.start_assessment(assessment.id)
        phases = await engine.get_phases(assessment.id)
        assert [phase.name for phase in phases] == STAGE_NAMES

        gap_phase = next(phase for phase in phases if phase.name == "差距分析")
        gap_tasks = await engine.get_tasks(gap_phase.id, official_only=True)
        doc_tasks = [task for task in gap_tasks if task.task_type == "doc_review"]
        assert len(doc_tasks) == 10
        doc_task = next(task for task in doc_tasks if "安全事件管理制度" in task.name)

        incomplete_doc = "\n".join([
            "安全事件管理制度",
            "本制度明确事件发现后应由值班人员进行事件报告。",
            "安全事件应上报安全负责人。",
        ])
        await _save_document_evidence(db, project.id, doc_task, "e2e-security-event-v1.txt", incomplete_doc, user.id)
        first_run, doc_task, first_analysis = await _run_document_analysis(db, doc_task, project.id, user.id)
        assert first_analysis["status"] in {"fail", "partial"}
        assert first_analysis["gaps"], "first document analysis should generate gaps"

        improved_doc = "\n".join([
            "安全事件管理制度",
            "一、事件发现与事件报告：监控、日志审计和人员上报发现异常后，应在 30 分钟内上报并通报。",
            "二、事件处置与处理记录：安全事件处置必须形成处置记录和闭环记录。",
            "三、分析复盘：事件关闭前应开展原因分析、复盘和总结。",
            "四、整改预防：制定整改、预防、改进措施并跟踪负责人。",
            "五、事件分类与事件分级：按影响范围、严重程度划分级别。",
            "六、升级通报和报告时限：重大事件按升级流程通报，明确报告时限。",
            "七、证据留存：日志、截图、取证材料和记录保存不少于六个月。",
            "八、关闭验证：整改完成后进行验证、确认和关闭。",
        ])
        await _replace_document_evidence(db, project.id, doc_task, "e2e-security-event-v2.txt", improved_doc, user.id)
        second_run, doc_task, second_analysis = await _run_document_analysis(db, doc_task, project.id, user.id)
        comparison = second_analysis.get("retest_comparison")
        assert comparison and comparison["delta"] >= 0
        assert comparison["fixed_gaps"], "retest comparison should list fixed gaps"

        technical_scan = await _add_technical_finding(db, project.id, user.id)
        await _add_change_history(db, project.id, technical_scan.id)
        await _complete_remaining_tasks(db, assessment.id)
        assessment = await engine.get_assessment(assessment.id)
        assert assessment.status == "completed"
        assert round(assessment.progress or 0) == 100

        report = await generate_json_report(db, project.id)
        html = await generate_html_report(db, project.id)

        assert report["report_version"] == "3.0-html"
        assert [phase["name"] for phase in report["assessment"]["phases"]] == STAGE_NAMES
        assert report["summary"]["total_findings"] >= 2
        assert report["summary"]["total_evidences"] >= 2
        assert report["summary"]["total_scan_tasks"] >= 8
        assert report["summary"]["closed_tickets"] >= 2
        assert report["document_gaps"], "report should include document gap analysis"
        assert report["retest_comparisons"], "report should include retest comparisons"
        assert report["technical_scans"], "report should distinguish technical scan conclusions"
        assert report["summary"]["open_findings"] >= 1
        assert report["report_conclusion"]["state"] == "attention"
        assert any(item["changes_detected"] for item in report["change_history"])
        assert any(finding["evidence_count"] > 0 for finding in report["findings"])

        required_html = [
            "自查结论",
            "当前待整改事项",
            "复测验证",
            "检测覆盖与执行结果",
            "执行状态",
            "检测结论",
            "文档合规核查",
            "问题闭环明细",
            "测评范围与变更",
            "基础技术检测：高危端口扫描",
            "现场测评：Web 深度扫描",
            "复测验证：端口整改复测",
        ]
        missing = [section for section in required_html if section not in html]
        assert not missing, f"HTML report missing sections: {missing}"
        assert "e2e-security-event-v2.txt" in html
        assert "TECH-E2E-HIGH-RISK-PORT" in html

        html_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.parent.mkdir(parents=True, exist_ok=True)
        html_output.write_text(html, encoding="utf-8")
        json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = {
            "project_id": project.id,
            "assessment_id": assessment.id,
            "first_document_run": first_run.id,
            "second_document_run": second_run.id,
            "findings": report["summary"]["total_findings"],
            "evidences": report["summary"]["total_evidences"],
            "retest_delta": comparison["delta"],
            "html_report": str(html_output),
            "json_report": str(json_output),
            "html_bytes": len(html.encode("utf-8")),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        if not keep_project:
            await _cleanup_project(db, project.id)


if __name__ == "__main__":
    asyncio.run(run_full_flow())
