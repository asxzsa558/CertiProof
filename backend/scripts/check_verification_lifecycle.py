"""Small dependency-free checks for report traceability and finding identity."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report_service import _document_evidence_html
from app.services.verification_service import make_finding_fingerprint, scrub_sensitive_parameters


def main() -> None:
    fingerprint = make_finding_fingerprint("technical", "192.0.2.10", "scan_ports", "port:22/tcp")
    assert fingerprint == make_finding_fingerprint("technical", "192.0.2.10", "scan_ports", "port:22/tcp")
    assert scrub_sensitive_parameters({"target": "192.0.2.10", "password": "hidden"}) == {"target": "192.0.2.10"}

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
    print("verification lifecycle check passed")


if __name__ == "__main__":
    main()
