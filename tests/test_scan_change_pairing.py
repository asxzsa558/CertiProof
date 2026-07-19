from types import SimpleNamespace

from app.services.execution_engine import ExecutionEngine


def _task(task_id, capability, target):
    return SimpleNamespace(
        id=task_id,
        parameters={"plan": [{"capability": capability, "parameters": {"target": target}}]},
        status="completed",
        result_summary={},
        findings_count=0,
        created_at=None,
        completed_at=None,
    )


def test_change_comparison_skips_latest_unmatched_scan_and_uses_newest_pair():
    tasks = [
        _task(30, "tech_assessment", "10.0.0.1"),
        _task(29, "scan_ports", "10.0.0.1"),
        _task(28, "scan_vulnerabilities", "10.0.0.1"),
        _task(27, "scan_ports", "10.0.0.1"),
    ]

    current, previous = ExecutionEngine._latest_comparable_scan_pair(tasks)

    assert (current.id, previous.id) == (29, 27)
