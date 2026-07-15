"""Small regression check for remediation state and report evidence traceability."""

from types import SimpleNamespace

from app.api.remediation import _apply_finding_status
from app.models.finding import FindingStatus
from app.models.remediation import RemediationStatus
from app.services.report_service import _document_evidence_html


def main() -> None:
    finding = SimpleNamespace(status=FindingStatus.OPEN, resolved_at=None)
    ticket = SimpleNamespace(status=RemediationStatus.IN_PROGRESS)
    _apply_finding_status(ticket, finding)
    assert finding.status == FindingStatus.IN_PROGRESS

    ticket.status = RemediationStatus.SKIPPED
    _apply_finding_status(ticket, finding)
    assert finding.status == FindingStatus.FALSE_POSITIVE
    assert finding.resolved_at is not None

    ticket.status = RemediationStatus.OPEN
    _apply_finding_status(ticket, finding)
    assert finding.status == FindingStatus.OPEN
    assert finding.resolved_at is None

    html = _document_evidence_html({
        "evidence_count": 1,
        "document_evidences": [{
            "file_name": "制度<&>.docx",
            "page": 3,
            "section": ["职责", "审批"],
            "text": "负责人 < 审批人",
        }],
    })
    assert "制度&lt;&amp;&gt;.docx · 第 3 页 · 职责 / 审批" in html
    assert "负责人 &lt; 审批人" in html
    print("remediation lifecycle check passed")


if __name__ == "__main__":
    main()
