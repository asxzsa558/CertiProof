from types import SimpleNamespace

from app.api.dashboard import (
    _actionable_risk_summary,
    _asset_topology_status,
    _topology_services,
)


def finding(severity, status="open", clause_name="检查项", description="问题"):
    return SimpleNamespace(
        severity=severity,
        status=status,
        clause_name=clause_name,
        description=description,
    )


def test_actionable_risk_summary_uses_one_pending_risk_contract():
    result = _actionable_risk_summary([
        finding("critical"),
        finding("high"),
        finding("medium"),
        finding("high", status="fixed"),
        finding("low"),
        finding("high", clause_name="自动化技术检测", description="检测未完成（不代表通过）"),
    ])

    assert result == {
        "risk_count": 3,
        "critical_count": 1,
        "high_count": 1,
        "medium_count": 1,
    }


def test_asset_topology_status_separates_risk_clear_and_unverified_assets():
    assert _asset_topology_status({"critical_count": 1}, "pending", False) == "critical"
    assert _asset_topology_status({"high_count": 1}, "verified", True) == "high"
    assert _asset_topology_status({"risk_count": 1}, "verified", True) == "warning"
    assert _asset_topology_status({}, "pending", True) == "unverified"
    assert _asset_topology_status({}, "verified", False) == "unverified"
    assert _asset_topology_status({}, "verified", True) == "normal"


def test_topology_service_keeps_port_protocol_and_service_details():
    services = _topology_services({
        "data": {"open_ports": [{"port": 443, "protocol": "tcp", "service": "https", "state": "open"}]},
    })

    assert services == [{
        "id": "443/tcp",
        "label": "443/tcp",
        "port": 443,
        "protocol": "tcp",
        "service": "https",
    }]
