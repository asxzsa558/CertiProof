import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.verification import _finding_payload, _run_payload
from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.verification import VerificationItem, VerificationOutcome, VerificationRun, VerificationRunStatus


def main():
    finding = Finding(
        id=1,
        project_id=1,
        source_type="document",
        source_key="DOC-CONTROL",
        scope_key="task:1",
        clause_id="DOC-TASK-1-CONTROL-P1",
        clause_name="测试条款",
        severity=Severity.MEDIUM,
        judgment=Judgment.FAIL,
        judgment_engine=JudgmentEngine.RULE,
        description="缺少必要制度要求",
        status=FindingStatus.OPEN,
    )
    item = VerificationItem(
        id=2,
        run_id=3,
        project_id=1,
        finding_id=1,
        source_type="document",
        target="task:1",
        capability="DOC-CONTROL",
        fingerprint="a" * 64,
        outcome=VerificationOutcome.UNABLE,
        error_message="本次分析没有覆盖原检查点",
    )
    payload = _finding_payload(finding, item)
    assert payload["source_type"] == "document"
    assert payload["status"] == "open"
    assert payload["latest_verification"]["outcome"] == "unable"

    run = VerificationRun(
        id=3,
        project_id=1,
        assessment_id=1,
        phase_id=1,
        source_type="document",
        requested_by=1,
        status=VerificationRunStatus.PARTIAL,
    )
    run_payload = _run_payload(run, [item])
    assert run_payload["status"] == "partial"
    assert run_payload["items"][0]["error"]
    print("verification contract check passed")


if __name__ == "__main__":
    main()
