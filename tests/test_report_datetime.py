from datetime import datetime, timezone

from app.services.report_service import _duration_days, _readable_observation, _scan_brief, _scan_name, _scan_outcome


def test_report_duration_accepts_mixed_database_datetime_awareness():
    created_at = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    resolved_at = datetime(2026, 7, 3, 8, 0)

    assert _duration_days(created_at, resolved_at) == 2
    assert _duration_days(resolved_at, created_at) == 0


def test_assessment_scan_report_uses_business_name_and_nested_result():
    task = {
        "task_type": "targeted",
        "status": "completed",
        "parameters": {"task_type": "ssh_baseline_assessment", "target": "192.0.2.10"},
        "result_summary": {
            "results": [{
                "capability": "baseline_check",
                "status": "completed",
                "result": {
                    "summary": {"total_checks": 26, "non_compliant": 3, "compliance_rate": 87.5},
                    "tool_status": "success",
                },
            }],
        },
        "findings_count": 3,
    }

    assert _scan_name(task) == "SSH/主机基线核查"
    assert _scan_outcome(task)["category"] == "risk"
    assert _scan_brief(task) == "基线 26 项，不符合 3 项，符合率 87.5%"


def test_assessment_scan_report_marks_all_skipped_tools_not_applicable():
    task = {
        "task_type": "targeted",
        "status": "completed",
        "parameters": {"task_type": "windows_ad_smb_assessment"},
        "result_summary": {
            "results": [{
                "capability": "windows_security_scan",
                "status": "completed",
                "result": {"skipped": True, "skip_reason": "目标未开放 SMB 服务"},
            }],
        },
    }

    assert _scan_name(task) == "Windows/AD/SMB 检测"
    assert _scan_outcome(task)["category"] == "skipped"
    assert _scan_brief(task) == "目标未开放 SMB 服务"


def test_report_formats_structured_historical_observation_as_readable_text():
    raw = "192.0.2.10: {'id': 'overall_grade', 'severity': 'CRITICAL', 'finding': 'T'}"

    assert _readable_observation(raw) == "192.0.2.10: testssl 总体评级：T（工具原始等级）"
    assert _readable_observation("192.0.2.10: overall_grade: T") == "192.0.2.10: testssl 总体评级：T（工具原始等级）"
