from app.services.ai_engine import AIEngine


def test_invalid_sqlmap_step_does_not_cancel_valid_web_scan():
    result = AIEngine()._validate_plan({
        "plan": [
            {"capability": "nikto_scan", "parameters": {"target": "139.224.104.187"}},
            {"capability": "sqlmap_scan", "parameters": {"target": "139.224.104.187"}},
        ],
        "response": "开始 Web 扫描",
    })

    assert result["plan"] == [{
        "capability": "nikto_scan",
        "parameters": {"target": "139.224.104.187"},
    }]
    assert "SQL 注入检测需要带查询参数的 URL" in result["response"]


def test_sqlmap_target_alias_is_normalized_for_parameterized_url():
    result = AIEngine()._validate_plan({
        "plan": [{
            "capability": "sqlmap_scan",
            "parameters": {"target": "example.com/page?id=1"},
        }],
        "response": "开始 SQL 注入检测",
    })

    assert result["plan"] == [{
        "capability": "sqlmap_scan",
        "parameters": {"url": "http://example.com/page?id=1"},
    }]
