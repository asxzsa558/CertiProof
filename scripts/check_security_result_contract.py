"""Assert the security result contract survives composite tools.

Run from repo root:
    python3 scripts/check_security_result_contract.py
"""

import importlib.util
import sys
import types
from pathlib import Path


class Dummy:
    def __init__(self, *args, **kwargs):
        pass


class ScanTaskTypeDummy:
    FULL = "full"


class ScanTaskStatusDummy:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriggeredByDummy:
    MANUAL = "manual"


def module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def load_orchestrator_class():
    module(
        "sqlalchemy",
        select=lambda *args, **kwargs: None,
        update=lambda *args, **kwargs: None,
        or_=lambda *args, **kwargs: None,
    )
    module("sqlalchemy.ext")
    module("sqlalchemy.ext.asyncio", AsyncSession=Dummy)
    module("app")
    module("app.orchestrator")
    module("app.orchestrator.agent", Agent=Dummy)
    module("app.orchestrator.skill_loader", SkillLoader=Dummy)
    module("app.mcp")
    module("app.mcp.gateway_client", MCPGatewayClient=Dummy)
    module("app.services")
    module("app.services.asset_scope", target_identity=lambda value: value)
    module("app.services.ai_engine", ai_engine=Dummy())
    module("app.services.audit", record_audit_event=lambda *args, **kwargs: None)
    module("app.services.execution_engine", execution_engine=Dummy())
    module("app.services.context_manager", ContextManager=Dummy)
    module("app.services.llm_service", llm_service=Dummy())
    module(
        "app.models.scan_task",
        ScanTask=Dummy,
        ScanTaskType=ScanTaskTypeDummy,
        ScanTaskStatus=ScanTaskStatusDummy,
        TriggeredBy=TriggeredByDummy,
    )
    module("app.models.finding", Finding=Dummy)
    module("app.models.project", Project=Dummy)
    module("app.core")
    module("app.core.database", AsyncSessionLocal=Dummy)
    module("app.core.config", settings=types.SimpleNamespace(TASK_EXECUTION_MODE="inline", TASK_LEASE_MINUTES=10))
    module("app.core.redaction", redact_sensitive=lambda value: value)

    path = Path(__file__).resolve().parents[1] / "backend/app/orchestrator/orchestrator.py"
    spec = importlib.util.spec_from_file_location("contract_orchestrator", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Orchestrator


def main():
    Orchestrator = load_orchestrator_class()
    orchestrator = Orchestrator()
    execution_result = {
        "results": [
            {
                "capability": "full_compliance_scan",
                "target": "example.test",
                "status": "success",
                "result": {
                    "target": "example.test",
                    "summary": {"total": 4, "success": 3, "failed": 1, "skipped": 0},
                    "sub_results": [
                        {
                            "status": "success",
                            "target": "example.test",
                            "capability": "scan_ports",
                            "label": "端口扫描",
                            "data": {
                                "host_status": "up",
                                "open_ports": [{"port": 443, "protocol": "tcp", "service": "https"}],
                                "filtered_ports": [{"port": 22, "protocol": "tcp", "state": "filtered"}],
                            },
                            "metadata": {},
                            "error": None,
                        },
                        {
                            "status": "success",
                            "target": "example.test",
                            "capability": "gobuster_scan",
                            "label": "目录爆破",
                            "data": {"discovered": [{"path": "/admin", "status": 200}]},
                            "metadata": {},
                            "error": None,
                        },
                        {
                            "status": "success",
                            "target": "example.test",
                            "capability": "redis_check",
                            "label": "Redis 检测",
                            "data": {"unauthorized": True, "port": 6379},
                            "metadata": {},
                            "error": None,
                        },
                        {
                            "status": "failed",
                            "target": "example.test",
                            "capability": "scan_ssl",
                            "label": "SSL/TLS 检测",
                            "data": {},
                            "metadata": {},
                            "error": "connection refused",
                        },
                    ],
                },
            }
        ],
        "success_count": 1,
        "failed_count": 0,
    }

    summary = orchestrator._summarize_execution_result(execution_result)
    scan_results = orchestrator._extract_scan_results_from_execution(execution_result)

    assert "开放端口" in summary
    assert "失败 - connection refused" in summary
    assert len(scan_results["open_ports"]) == 1
    assert len(scan_results["filtered_ports"]) == 1
    assert len(scan_results["web_discoveries"]) == 1
    assert len(scan_results["database_issues"]) == 1
    assert len(scan_results["composite_results"]) == 1


if __name__ == "__main__":
    main()
