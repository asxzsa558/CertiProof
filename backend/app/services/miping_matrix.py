"""Build the persisted eight-domain Miping result matrix."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import Assessment
from app.models.finding import Finding, FindingStatus, Judgment
from app.services.assessment_templates import MIPING_DOMAINS
from app.services.flow_engine import get_flow_engine
from app.services.task_executor import TASK_CAPABILITY_MAP


def _document_name(task):
    return task.name.removeprefix("文档检查：") if task.task_type == "doc_review" else None


def _value(value):
    return value.value if hasattr(value, "value") else value


def _task_outcome(task, findings: list[Finding]) -> tuple[str, str]:
    if task.status == "in_progress":
        return "running", "正在提取或执行检查"
    if task.status == "todo":
        return "pending", "尚未提交所需材料或执行检测"
    if task.status in {"failed", "cancelled"}:
        return "unable", (task.result or {}).get("error") or "检查未可靠完成"
    if task.task_type == "doc_review":
        analysis = (task.result or {}).get("analysis") or {}
        outcome = analysis.get("status") or "unable"
        return outcome, analysis.get("message") or {
            "pass": "必检证据完整",
            "partial": "已找到证据，但完整性不足",
            "fail": "可靠分析后仍缺少必需证据",
        }.get(outcome, "文档结论不可用")

    capabilities = set((TASK_CAPABILITY_MAP.get(task.task_type) or {}).get("capabilities") or [])
    related = [item for item in findings if item.source_type == "technical" and item.source_key in capabilities]
    if any(_value(item.judgment) == _value(Judgment.NOT_TESTED) and _value(item.status) == _value(FindingStatus.OPEN) for item in related):
        return "unable", "自动检测存在未完成或无法验证项"
    if any(_value(item.status) == _value(FindingStatus.OPEN) for item in related):
        return "fail", "自动检测发现密码应用风险"
    return "pass", "自动检测完成，未发现工具覆盖范围内的问题"


async def build_miping_domain_matrix(db: AsyncSession, assessment: Assessment) -> dict:
    if assessment.assessment_type_code != "miping":
        raise ValueError("八层面矩阵仅适用于密评自查")

    engine = get_flow_engine(db)
    phases = await engine.get_phases(assessment.id)
    tasks = [task for phase in phases for task in await engine.get_tasks(phase.id, official_only=True)]
    findings = list((await db.execute(select(Finding).where(
        Finding.assessment_id == assessment.id,
        Finding.status != FindingStatus.FALSE_POSITIVE,
    ))).scalars().all())

    rows = []
    for domain in MIPING_DOMAINS:
        document_names = set(domain.get("documents") or [])
        task_types = set(domain.get("task_types") or [])
        related_tasks = [task for task in tasks if _document_name(task) in document_names or task.task_type in task_types]
        outcomes = [_task_outcome(task, findings) for task in related_tasks]
        statuses = [item[0] for item in outcomes]
        domain_status = next((status for status in ("running", "fail", "unable", "pending", "partial") if status in statuses), "pass")
        if not statuses:
            domain_status = "pending"
        rows.append({
            "id": domain["id"],
            "name": domain["name"],
            "method": domain["method"],
            "status": domain_status,
            "tasks": [
                {"id": task.id, "name": task.name, "task_type": task.task_type, "status": outcome[0], "detail": outcome[1]}
                for task, outcome in zip(related_tasks, outcomes)
            ],
        })

    keys = ("pass", "partial", "fail", "unable", "pending", "running")
    return {
        "assessment_id": assessment.id,
        "domains": rows,
        "counts": {key: sum(row["status"] == key for row in rows) for key in keys},
    }
