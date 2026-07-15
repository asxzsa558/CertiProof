from app.services.task_executor import CAPABILITY_NAMES, TaskExecutor


warning = TaskExecutor._risk_items(
    "baseline_check",
    {"status": "warning", "warning": "SSH 连接超时", "result": {"failed_checks": []}},
    "192.0.2.1",
)
assert warning == []
assert CAPABILITY_NAMES["baseline_check"] == "安全基线核查"

finding = TaskExecutor._risk_items(
    "scan_vulnerabilities",
    {"status": "completed", "result": {"findings": [{"title": "CVE test", "severity": "high"}]}},
    "192.0.2.1",
)
assert finding == [{"description": "192.0.2.1: CVE test", "severity": "high"}]

print("task executor finding checks passed")
