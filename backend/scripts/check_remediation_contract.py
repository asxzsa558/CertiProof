import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.remediation import _apply_finding_status, _ticket_payload
from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.remediation import RemediationStatus, RemediationTicket


def _finding(clause_id="DOC-TASK-1-control-point"):
    return Finding(
        id=1,
        project_id=1,
        scan_task_id=10,
        clause_id=clause_id,
        clause_name="测试条款",
        severity=Severity.MEDIUM,
        judgment=Judgment.FAIL,
        judgment_engine=JudgmentEngine.RULE,
        confidence=0.75,
        description="缺少必要制度要求",
        remediation_suggestion="补充制度内容",
        status=FindingStatus.OPEN,
        evidence_ids=[],
    )


def _ticket(status=RemediationStatus.OPEN):
    return RemediationTicket(
        id=1,
        finding_id=1,
        project_id=1,
        title="整改测试",
        priority="medium",
        status=status,
    )


def main():
    finding = _finding()
    payload = _ticket_payload(_ticket(), finding)
    assert payload["source"] == "document"
    assert payload["source_label"] == "文档差距"
    assert payload["finding_status"] == "open"
    assert payload["judgment"] == "fail"

    technical_payload = _ticket_payload(_ticket(), _finding("TECH-1"))
    assert technical_payload["source"] == "technical"

    ticket = _ticket(RemediationStatus.IN_PROGRESS)
    _apply_finding_status(ticket, finding)
    assert finding.status == FindingStatus.IN_PROGRESS

    ticket.status = RemediationStatus.RESOLVED
    _apply_finding_status(ticket, finding)
    assert finding.status == FindingStatus.RESOLVED
    assert finding.resolved_at is not None

    skipped = _finding()
    _apply_finding_status(_ticket(RemediationStatus.SKIPPED), skipped)
    assert skipped.status == FindingStatus.OPEN

    print("remediation contract check passed")


if __name__ == "__main__":
    main()
