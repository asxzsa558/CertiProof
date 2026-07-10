import importlib.util
from pathlib import Path

module_path = Path(__file__).resolve().parents[1] / "app" / "services" / "assessment_templates.py"
spec = importlib.util.spec_from_file_location("assessment_templates", module_path)
assessment_templates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assessment_templates)

LEVEL_2_TEMPLATE = assessment_templates.LEVEL_2_TEMPLATE
LEVEL_3_TEMPLATE = assessment_templates.LEVEL_3_TEMPLATE
FIVE_STAGE_PHASE_NAMES = assessment_templates.FIVE_STAGE_PHASE_NAMES


def check(template):
    phases = template["phases_config"]
    assert [phase["name"] for phase in phases] == FIVE_STAGE_PHASE_NAMES
    assert len(phases) == 5
    assert not {"系统定级", "备案", "测评报告"} & {phase["name"] for phase in phases}
    phase_map = {phase["id"]: phase for phase in phases}
    gap_tasks = phase_map["gap_analysis"]["default_tasks"]
    field_task_types = {task["type"] for task in phase_map["field_assessment"]["default_tasks"]}
    assert len([task for task in gap_tasks if task["type"] == "doc_review"]) == 10
    assert {
        "high_risk_port_scan",
        "basic_vulnerability_scan",
        "basic_baseline_check",
        "basic_weak_password_scan",
        "basic_ssl_tls_scan",
    } <= {task["type"] for task in gap_tasks}
    assert {
        "full_asset_assessment",
        "web_vulnerability_assessment",
        "directory_discovery_assessment",
        "web_fuzz_assessment",
        "sql_injection_assessment",
        "database_security_assessment",
        "ssh_baseline_assessment",
    } <= field_task_types


if __name__ == "__main__":
    check(LEVEL_2_TEMPLATE)
    check(LEVEL_3_TEMPLATE)
    print("five-stage templates ok")
