from pathlib import Path

import yaml

from app.services.ai_engine import AIEngine
from app.services.assessment_templates import MIPING_DOMAINS, MIPING_LEVEL_3_TEMPLATE
from app.services.document_control_engine import DocumentControlEngine


ROOT = Path(__file__).resolve().parents[1]


def test_miping_library_covers_all_materials_and_required_points():
    data = yaml.safe_load((ROOT / "reference/compliance/miping_document_controls.yaml").read_text())
    documents = data["documents"]
    assert len(documents) == 13
    controls = [control for document in documents.values() for control in document["controls"]]
    assert len(controls) == 56
    assert sum(len(control["required_points"]) for control in controls) == 112
    assert all(document.get("basis") and document.get("automation_boundary") for document in documents.values())
    assert all(point.get("evidence_keywords") and point.get("missing_judgement") for control in controls for point in control["required_points"])
    assert data["requirement_defaults"]["severity"] == "medium"
    high_risk = next(control for control in controls if control["id"] == "MIP-ALG-003")
    assert high_risk["severity"] == "high"
    assert high_risk["required_points"][0]["negative_conditions"]
    engine = DocumentControlEngine(data)
    inherited = engine.documents["network_communication_evidence"]["controls"][0]["required_points"][0]
    assert inherited["basis"] and inherited["automation_boundary"]
    assert inherited["severity"] == "medium"


def test_miping_template_maps_to_eight_domains():
    phases = MIPING_LEVEL_3_TEMPLATE["phases_config"]
    assert [phase["id"] for phase in phases] == [
        "gap_analysis", "field_assessment", "remediation_verification", "report",
    ]
    assert len(MIPING_DOMAINS) == 8
    assert len(phases[0]["default_tasks"]) == 9
    assert len(phases[1]["default_tasks"]) == 5


def test_help_distinguishes_dengbao_and_miping_tools():
    engine = AIEngine()
    miping = engine._help_response("哪些工具是进行密评检测的？", {"current_project": {}})
    dengbao = engine._help_response("等保有哪些检测工具？", {"current_project": {}})
    assert "密码协议与套件" in miping and "数字证书" in miping
    assert "八个层面" in miping
    assert "端口" in dengbao and "漏洞" in dengbao and "基线" in dengbao
