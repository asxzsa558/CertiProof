from app.services.task_executor import CAPABILITY_NAMES, TaskExecutor


warning = TaskExecutor._risk_items(
    "baseline_check",
    {"status": "warning", "warning": "SSH 连接超时", "result": {"failed_checks": []}},
    "192.0.2.1",
)
assert warning == [{
    "description": "192.0.2.1: SSH 连接超时",
    "severity": "medium",
    "judgment": "not_tested",
    "risk_key": "execution:unable",
    "remediation": "确认目标服务是否适用并恢复网络、凭据或工具条件后重新检测；未完成前不得视为通过。",
}]
assert CAPABILITY_NAMES["baseline_check"] == "安全基线核查"

finding = TaskExecutor._risk_items(
    "scan_vulnerabilities",
    {"status": "completed", "result": {"findings": [{"title": "CVE test", "severity": "high"}]}},
    "192.0.2.1",
)
assert finding == [{
    "description": "192.0.2.1: CVE test",
    "severity": "high",
    "risk_key": "CVE test",
    "raw": {"title": "CVE test", "severity": "high"},
}]

print("task executor finding checks passed")
