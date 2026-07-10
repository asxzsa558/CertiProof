from app.services.task_executor import TaskExecutor


warning = TaskExecutor._risk_items(
    "baseline_check",
    {"status": "warning", "warning": "SSH 连接超时", "result": {"failed_checks": []}},
    "192.0.2.1",
)
assert len(warning) == 1
assert "不代表通过" in warning[0]["description"]
assert warning[0]["remediation"]

finding = TaskExecutor._risk_items(
    "scan_vulnerabilities",
    {"status": "completed", "result": {"findings": [{"title": "CVE test", "severity": "high"}]}},
    "192.0.2.1",
)
assert finding == [{"description": "192.0.2.1: CVE test", "severity": "high"}]

print("task executor finding checks passed")
