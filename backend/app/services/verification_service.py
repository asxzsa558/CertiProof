"""Direct Finding remediation and verification lifecycle."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_box import encrypt_json
from app.models.assessment import Assessment, PhaseInstance, TaskInstance
from app.models.finding import Finding, FindingStatus
from app.models.verification import (
    FindingEvent,
    VerificationItem,
    VerificationOutcome,
    VerificationRun,
    VerificationRunStatus,
)


SENSITIVE_PARAMETER_KEYS = {
    "password", "passphrase", "private_key", "key_file", "token", "secret", "credential_envelope",
}


def controlled_remediation_plan(finding: Finding) -> dict:
    """Build deterministic, evidence-bound guidance; verification remains authoritative."""
    description = (finding.description or "").strip()
    source_key = (finding.source_key or "").strip()
    target = (finding.scope_key or "").strip()
    base = {
        "evidence": description or "当前问题未附带可读证据，应先补充证据再实施变更。",
        "target": target or "尚未明确对象",
        "applicability": "执行前确认实际技术栈、业务窗口和配置归属；本建议不会自动修改生产环境。",
        "prerequisites": ["备份当前配置或文档版本", "在测试环境验证并安排可回滚的变更窗口"],
        "steps": [],
        "verification": "重新执行产生该 Finding 的同一检查，只有真实复测不再出现该问题才可关闭。",
        "rollback": "恢复变更前版本，重载服务并执行健康检查。",
        "requires_context": True,
    }
    lower = description.lower()
    if finding.source_type == "document":
        base.update({
            "applicability": "适用于当前文档检查点；修改对象以证据中标明的制度或方案为准。",
            "prerequisites": ["保留现行文件和版本号", "确认文档责任部门、审批人和生效范围"],
            "steps": [
                f"定位“{finding.clause_name or finding.clause_id}”对应章节，并逐项补足问题描述指出的缺失内容。",
                "明确适用对象、责任主体、执行步骤、频率或时限、记录留存和例外处理，避免只罗列关键词。",
                "完成审批、生效日期和版本记录后，上传整改后的完整文件替换或补充原材料。",
            ],
            "verification": "由文档合规检查重新解析全部有效材料，并对该文档类别所有检查点重新取证；证据完整且无矛盾才关闭问题。",
            "rollback": "恢复上一已批准文档版本，并保留本次修改、审批和复测记录。",
            "requires_context": False,
        })
        return base

    if source_key == "scan_ssl":
        if "hsts" in lower:
            steps = [
                "确认所有 HTTP 请求均可靠跳转 HTTPS，且子域是否都支持 HTTPS。",
                "在实际入口组件中配置 Strict-Transport-Security；先使用较短 max-age 验证，再按策略提高，确认后才考虑 includeSubDomains。",
                "重载入口服务并检查业务、回调和旧客户端兼容性。",
            ]
        elif any(word in lower for word in ("cbc", "obsolete", "cipher", "lucky13")):
            steps = [
                "盘点客户端兼容范围，确认可以停用旧 TLS 协议和 CBC/弱密码套件。",
                "在实际 TLS 终止组件中仅保留组织批准的 TLS 1.2/1.3 套件，并优先启用 TLS 1.3。",
                "重载服务，在测试客户端和关键业务链路验证握手后再发布。",
            ]
        else:
            steps = ["核对证书链、协议版本、密码套件和安全响应头配置。", "在测试环境修正对应 TLS 项并完成兼容性验证后发布。"]
        base.update({
            "steps": steps,
            "verification": f"对 {target or '目标 HTTPS 服务'} 重新执行 SSL/TLS 检测，确认原证据项消失且证书链与业务握手正常。",
            "rollback": "恢复入口服务配置备份并重载；若 HSTS 已被客户端缓存，需评估其不可即时回滚特性。",
        })
        return base

    if source_key in {"nikto_scan", "web_discovery_scan"}:
        base["steps"] = [
            "确认问题由反向代理、Web 服务器还是应用代码产生，并定位负责配置。",
            "在测试环境限制非业务 HTTP 方法，补齐证据指出的安全响应头；根据应用实际需要设定值，避免照搬模板。",
            "执行功能、登录、跨域、下载和回调回归测试后再发布。",
        ]
        base["verification"] = f"重新执行 Web 安全扫描并使用 curl 检查 {target or '目标站点'} 的状态码、允许方法和响应头，同时完成业务回归。"
        return base

    if source_key == "scan_weak_passwords":
        base.update({
            "steps": ["立即停用已命中的弱口令并轮换为唯一强凭据。", "检查同凭据复用、异常登录和权限范围，必要时吊销会话。", "启用登录限速、锁定策略和多因素认证。"],
            "verification": "使用授权账号验证新凭据可用，再按相同账号和协议重新执行弱口令检测，确认旧凭据不可登录。",
            "rollback": "不得恢复已泄露弱口令；若业务失败，使用受控应急账号并再次轮换。",
            "requires_context": False,
        })
        return base

    if source_key in {"scan_vulnerabilities", "baseline_check", "network_device_scan"} and any(word in lower for word in ("timeout", "超时", "必须提供", "无法", "no response", "未完成")):
        base.update({
            "applicability": "这是检测链路未完成，不是“未发现风险”的结论。",
            "prerequisites": ["确认资产授权范围", "确认网络可达、目标端口、白名单和有效凭据"],
            "steps": ["按错误详情修复连通性、凭据或超时配置。", "缩小目标范围或降低并发后重试；仍失败时检查目标日志和云安全组。"],
            "verification": "原工具完整执行并返回可靠结果后，才能形成风险结论。",
            "rollback": "本项通常不修改业务配置；临时白名单或调试策略应在检测后撤销。",
            "requires_context": False,
        })
        return base

    templates = {
        "scan_ports": ["确认暴露端口是否为业务必需。", "非必需服务应停用；必需服务通过安全组、防火墙或访问控制仅允许授权来源。"],
        "database_security_scan": ["确认数据库类型、监听地址和认证模式。", "关闭未授权访问，启用身份认证并将管理端口限制到应用或运维网段。"],
        "windows_security_scan": ["确认域、主机和 SMB 业务依赖。", "按最小权限修正共享、匿名访问和协议配置，并审计高权限账号。"],
        "baseline_check": ["依据失败检查项定位主机配置。", "在测试主机按最小权限和审计要求修正，验证服务后分批发布。"],
    }
    base["steps"] = templates.get(source_key) or [finding.remediation_suggestion or "由系统负责人确认风险成因并制定最小变更方案。", "在测试环境验证后发布并保留变更记录。"]
    return base


def scrub_sensitive_parameters(value):
    if isinstance(value, dict):
        return {
            key: scrub_sensitive_parameters(item)
            for key, item in value.items()
            if key.lower() not in SENSITIVE_PARAMETER_KEYS and not key.startswith("_")
        }
    if isinstance(value, list):
        return [scrub_sensitive_parameters(item) for item in value]
    return value


def make_finding_fingerprint(source_type: str, scope_key: str, source_key: str, risk_key: str) -> str:
    canonical = json.dumps(
        [source_type.strip().lower(), scope_key.strip().lower(), source_key.strip().lower(), risk_key.strip().lower()],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def add_finding_event(
    db: AsyncSession,
    finding: Finding,
    event_type: str,
    *,
    verification_item: VerificationItem | None = None,
    actor_id: int | None = None,
    data: dict | None = None,
) -> FindingEvent:
    event = FindingEvent(
        project_id=finding.project_id,
        finding_id=finding.id,
        verification_item_id=verification_item.id if verification_item else None,
        event_type=event_type,
        event_data=data or {},
        actor_id=actor_id,
    )
    db.add(event)
    return event


async def delete_verification_data(
    db: AsyncSession,
    project_id: int,
    finding_ids: Iterable[int] | None = None,
) -> None:
    scoped_ids = list(dict.fromkeys(int(value) for value in finding_ids or []))
    if finding_ids is not None and not scoped_ids:
        return
    if finding_ids is None:
        await db.execute(delete(FindingEvent).where(FindingEvent.project_id == project_id))
        await db.execute(delete(VerificationItem).where(VerificationItem.project_id == project_id))
        await db.execute(delete(VerificationRun).where(VerificationRun.project_id == project_id))
        return

    run_ids = list((await db.execute(
        select(VerificationItem.run_id).where(VerificationItem.finding_id.in_(scoped_ids)).distinct()
    )).scalars().all())
    await db.execute(delete(FindingEvent).where(FindingEvent.finding_id.in_(scoped_ids)))
    await db.execute(delete(VerificationItem).where(VerificationItem.finding_id.in_(scoped_ids)))
    for run_id in run_ids:
        remaining = (await db.execute(
            select(VerificationItem.id).where(VerificationItem.run_id == run_id).limit(1)
        )).scalar_one_or_none()
        if remaining is None:
            await db.execute(delete(VerificationRun).where(VerificationRun.id == run_id))


async def reset_verification_data(db: AsyncSession, project_id: int) -> None:
    await delete_verification_data(db, project_id)
    findings = (await db.execute(select(Finding).where(
        Finding.project_id == project_id,
        Finding.status.not_in([FindingStatus.FALSE_POSITIVE]),
    ))).scalars().all()
    for finding in findings:
        finding.status = FindingStatus.OPEN
        finding.resolved_at = None


async def latest_assessment_and_phase(db: AsyncSession, project_id: int) -> tuple[Assessment, PhaseInstance]:
    assessment = (await db.execute(
        select(Assessment).where(Assessment.project_id == project_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1)
    )).scalar_one_or_none()
    if not assessment:
        raise ValueError("当前项目尚未创建等保测评")
    phase = (await db.execute(select(PhaseInstance).where(
        PhaseInstance.assessment_id == assessment.id,
        PhaseInstance.phase_id == "remediation_verification",
    ))).scalar_one_or_none()
    if not phase:
        raise ValueError("当前测评缺少整改与复测阶段")
    return assessment, phase


async def create_verification_run(
    db: AsyncSession,
    *,
    project_id: int,
    findings: Iterable[Finding],
    source_type: str,
    actor_id: int,
    notes: str = "",
    credentials: dict | None = None,
    document_file_ids: list[int] | None = None,
) -> VerificationRun:
    findings = list(findings)
    if not findings:
        raise ValueError("没有可复测的问题")
    if any(finding.project_id != project_id for finding in findings):
        raise ValueError("复测问题不属于当前项目")
    if any((finding.source_type or "") != source_type for finding in findings):
        raise ValueError("一次复测只能处理同一种问题来源")
    active = (await db.execute(select(VerificationItem.finding_id).join(VerificationRun).where(
        VerificationItem.finding_id.in_([finding.id for finding in findings]),
        VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
    ))).scalars().all()
    if active:
        raise ValueError(f"所选问题已有复测在执行：{sorted(set(active))}")

    assessment, phase = await latest_assessment_and_phase(db, project_id)
    from app.services.report_service import invalidate_report_artifacts
    await invalidate_report_artifacts(db, project_id, "已发起新的整改复测")
    run = VerificationRun(
        project_id=project_id,
        assessment_id=assessment.id,
        phase_id=phase.id,
        source_type=source_type,
        requested_by=actor_id,
        notes=notes.strip() or None,
        document_file_ids=document_file_ids or [],
        credential_envelope=encrypt_json(credentials) if credentials else None,
        summary={"total": len(findings), "completed": 0},
    )
    db.add(run)
    await db.flush()
    for finding in findings:
        item = VerificationItem(
            run_id=run.id,
            project_id=project_id,
            finding_id=finding.id,
            source_type=source_type,
            target=finding.scope_key,
            capability=finding.source_key,
            fingerprint=finding.fingerprint or make_finding_fingerprint(
                source_type, finding.scope_key or "", finding.source_key or finding.clause_id, finding.clause_id,
            ),
            baseline_scan_task_id=finding.scan_task_id,
            baseline_document_run_id=finding.document_run_id,
            baseline_observation={
                "description": finding.description,
                "judgment": getattr(finding.judgment, "value", finding.judgment),
                "severity": getattr(finding.severity, "value", finding.severity),
            },
        )
        db.add(item)
        await db.flush()
        await add_finding_event(db, finding, "verification_queued", verification_item=item, actor_id=actor_id)
    await reconcile_verification_phase(db, project_id)
    return run


async def queue_document_task_verification(
    db: AsyncSession,
    *,
    project_id: int,
    task: TaskInstance,
    actor_id: int,
    analysis_mode: str,
    notes: str = "",
) -> tuple[VerificationRun, object, list[int], int]:
    """Queue one full document-category recheck against its open findings."""
    phase = await db.get(PhaseInstance, task.phase_id)
    assessment = await db.get(Assessment, phase.assessment_id) if phase else None
    if not assessment or assessment.project_id != project_id:
        raise ValueError("原文档检查任务不属于当前项目")
    findings = list((await db.execute(select(Finding).where(
        Finding.project_id == project_id,
        Finding.source_type == "document",
        Finding.scope_key == f"task:{task.id}",
        Finding.status == FindingStatus.OPEN,
    ))).scalars().all())
    if not findings:
        raise ValueError("该类文档当前没有待复测问题")

    from app.models.document_knowledge import DocumentFile
    active_ids = list((await db.execute(select(DocumentFile.id).where(
        DocumentFile.assessment_id == assessment.id,
        DocumentFile.task_id == task.id,
        DocumentFile.is_active.is_(True),
    ))).scalars().all())
    if not active_ids:
        raise ValueError("该类文档没有可重新分析的有效材料")

    verification = await create_verification_run(
        db,
        project_id=project_id,
        findings=findings,
        source_type="document",
        actor_id=actor_id,
        notes=notes,
        document_file_ids=active_ids,
    )
    from app.services.document_pipeline import create_document_run
    document_run = await create_document_run(
        db,
        task,
        project_id,
        actor_id,
        analysis_mode,
        run_parameters={"verification_run_id": verification.id},
    )
    items = (await db.execute(select(VerificationItem).where(
        VerificationItem.run_id == verification.id
    ))).scalars().all()
    for item in items:
        item.current_document_run_id = document_run.id
    await db.commit()
    return verification, document_run, active_ids, len(findings)


async def apply_verification_outcome(
    db: AsyncSession,
    item: VerificationItem,
    outcome: VerificationOutcome,
    *,
    observation: dict | None = None,
    comparison: dict | None = None,
    error: str | None = None,
) -> None:
    finding = await db.get(Finding, item.finding_id)
    if not finding:
        raise ValueError("复测项关联的问题不存在")
    item.outcome = outcome
    item.current_observation = observation or {}
    item.comparison = comparison or {}
    item.error_message = error
    item.completed_at = datetime.utcnow()
    if outcome == VerificationOutcome.FIXED:
        finding.status = FindingStatus.FIXED
        finding.resolved_at = datetime.utcnow()
        event_type = "verification_fixed"
    elif outcome in {VerificationOutcome.STILL_PRESENT, VerificationOutcome.UNABLE, VerificationOutcome.CANCELLED}:
        finding.status = FindingStatus.OPEN
        finding.resolved_at = None
        event_type = f"verification_{outcome.value}"
    else:
        event_type = "verification_new"
    await add_finding_event(
        db, finding, event_type, verification_item=item,
        data={"error": error, "comparison": comparison or {}},
    )


async def finish_verification_run(db: AsyncSession, run: VerificationRun) -> None:
    items = (await db.execute(select(VerificationItem).where(VerificationItem.run_id == run.id))).scalars().all()
    counts = {outcome.value: 0 for outcome in VerificationOutcome}
    for item in items:
        key = getattr(item.outcome, "value", item.outcome)
        counts[key] = counts.get(key, 0) + 1
    terminal = {
        VerificationOutcome.FIXED, VerificationOutcome.STILL_PRESENT, VerificationOutcome.NEW,
        VerificationOutcome.UNABLE, VerificationOutcome.CANCELLED,
    }
    if items and all(item.outcome in terminal for item in items):
        run.status = (
            VerificationRunStatus.COMPLETED
            if not counts["unable"] and not counts["cancelled"]
            else VerificationRunStatus.PARTIAL
        )
        run.completed_at = datetime.utcnow()
        run.lease_owner = None
        run.lease_expires_at = None
        run.credential_envelope = None
    run.summary = {"total": len(items), "completed": sum(counts[item.value] for item in terminal), **counts}
    await reconcile_verification_phase(db, run.project_id)


async def reopen_finding(db: AsyncSession, finding: Finding, actor_id: int) -> None:
    finding.status = FindingStatus.OPEN
    finding.resolved_at = None
    await add_finding_event(db, finding, "finding_reopened", actor_id=actor_id)
    await reconcile_verification_phase(db, finding.project_id)


async def reconcile_verification_phase(db: AsyncSession, project_id: int) -> None:
    assessment = (await db.execute(
        select(Assessment).where(Assessment.project_id == project_id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1)
    )).scalar_one_or_none()
    if not assessment:
        return
    phases = (await db.execute(
        select(PhaseInstance).where(PhaseInstance.assessment_id == assessment.id).order_by(PhaseInstance.order)
    )).scalars().all()
    by_key = {phase.phase_id: phase for phase in phases}
    gap = by_key.get("gap_analysis")
    field = by_key.get("field_assessment")
    verification = by_key.get("remediation_verification")
    report = by_key.get("report")
    if not field or not verification:
        return

    findings = (await db.execute(select(Finding).where(
        Finding.project_id == project_id,
        Finding.status != FindingStatus.FALSE_POSITIVE,
    ))).scalars().all()
    reviewed_ids = set((await db.execute(select(VerificationItem.finding_id).where(
        VerificationItem.project_id == project_id,
        VerificationItem.outcome.in_([
            VerificationOutcome.FIXED,
            VerificationOutcome.STILL_PRESENT,
            VerificationOutcome.UNABLE,
            VerificationOutcome.NEW,
        ]),
    ))).scalars().all())
    reviewed = sum(finding.status == FindingStatus.FIXED or finding.id in reviewed_ids for finding in findings)
    active_runs = int((await db.execute(select(VerificationRun.id).where(
        VerificationRun.project_id == project_id,
        VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
    ))).scalars().first() is not None)
    explicitly_finalized = bool((verification.outputs or {}).get("continued_to_report"))
    if active_runs and explicitly_finalized:
        verification.outputs = None
        explicitly_finalized = False
    upstream_done = bool(gap and gap.status == "completed" and field.status == "completed")
    failed_tasks = (await db.execute(
        select(TaskInstance).join(PhaseInstance, PhaseInstance.id == TaskInstance.phase_id).where(
            PhaseInstance.assessment_id == assessment.id,
            PhaseInstance.phase_id.in_(["gap_analysis", "field_assessment"]),
            TaskInstance.status == "failed",
        )
    )).scalars().all()
    from app.services.task_executor import TASK_CAPABILITY_MAP
    execution_blockers = []
    for task in failed_tasks:
        capabilities = set((TASK_CAPABILITY_MAP.get(task.task_type) or {}).get("capabilities") or [])
        represented = any(
            (finding.source_type == "document" and finding.scope_key == f"task:{task.id}")
            or (finding.source_type == "technical" and finding.source_key in capabilities)
            for finding in findings
        )
        if not represented:
            execution_blockers.append(task.id)
    total_work = len(findings) + len(execution_blockers)
    review_progress = (reviewed / total_work * 100) if total_work else (100 if upstream_done else 0)
    verification.total_tasks = total_work
    verification.completed_tasks = reviewed
    verification.progress = 100 if explicitly_finalized and not active_runs else review_progress
    if explicitly_finalized:
        verification.outputs = {
            **(verification.outputs or {}),
            "review_progress": round(review_progress, 1),
            "finding_summary": {
                "total": len(findings),
                "open": sum(finding.status == FindingStatus.OPEN for finding in findings),
                "fixed": sum(finding.status == FindingStatus.FIXED for finding in findings),
            },
        }
    report_must_wait = False
    if not upstream_done:
        verification.progress = review_progress
        if explicitly_finalized:
            verification.outputs = None
        verification.status = "pending"
        verification.started_at = None
        verification.completed_at = None
        report_must_wait = True
    elif explicitly_finalized and not active_runs:
        verification.status = "completed"
        verification.started_at = verification.started_at or datetime.utcnow()
        verification.completed_at = verification.completed_at or datetime.utcnow()
        if report and report.status == "pending":
            report.status = "active"
            report.started_at = report.started_at or datetime.utcnow()
    elif reviewed == len(findings) and not execution_blockers and not active_runs:
        verification.status = "completed"
        verification.started_at = verification.started_at or datetime.utcnow()
        verification.completed_at = verification.completed_at or datetime.utcnow()
        if report and report.status == "pending":
            report.status = "active"
            report.started_at = report.started_at or datetime.utcnow()
    else:
        verification.status = "active"
        verification.started_at = verification.started_at or datetime.utcnow()
        verification.completed_at = None
        report_must_wait = True

    if report and report_must_wait:
        from app.services.report_service import invalidate_report_artifacts
        await invalidate_report_artifacts(db, project_id, "测评或复测状态已变化")
        report.status = "pending"
        report.progress = 0
        report.completed_tasks = 0
        report.started_at = None
        report.completed_at = None
        report.outputs = None
        report_tasks = (await db.execute(
            select(TaskInstance).where(TaskInstance.phase_id == report.id)
        )).scalars().all()
        for task in report_tasks:
            task.status = "todo"
            task.result = None
            task.evidence_ids = None
            task.started_at = None
            task.completed_at = None
            task.lease_owner = None
            task.lease_expires_at = None
            task.heartbeat_at = None
            task.cancel_requested_at = None

    from app.services.flow_engine import workflow_progress

    assessment.completed_phases = sum(phase.status == "completed" for phase in phases)
    assessment.total_phases = len(phases)
    assessment.progress = workflow_progress(phases)
    if assessment.completed_phases < assessment.total_phases:
        assessment.status = "in_progress" if any(phase.status != "pending" for phase in phases) else "not_started"
        assessment.completed_at = None
