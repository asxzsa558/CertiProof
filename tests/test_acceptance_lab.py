import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_target_ports_are_health_checked():
    source = (ROOT / "scripts/e2e_target_service.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == "LAB_SERVICES" for target in node.targets)
    )
    services = ast.literal_eval(assignment.value)
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for name, port in services.items():
        if name != "snmp":
            assert str(port) in compose


def test_acceptance_matrix_documents_external_limits():
    source = (ROOT / "backend/scripts/check_security_tools_acceptance.py").read_text(encoding="utf-8")
    assert "Windows/AD/SMB" in source
    assert "需要 Windows VM" in source
    assert "交换机、密码机、国密硬件" in source
