from app.orchestrator.orchestrator import Orchestrator


def main():
    orchestrator = Orchestrator()
    context = {
        "project_assets": [
            {"value": "121.40.95.31"},
            {"value": "139.224.104.187"},
        ]
    }
    stale_plan = [
        {
            "capability": "scan_weak_passwords",
            "parameters": {"target": "139.224.104.107"},
        }
    ]

    normalized, response = orchestrator._normalize_project_asset_plan(
        stale_plan,
        context,
        "给我做一个全资产的端口扫描",
        "139.224.104.107 不在当前项目资产中",
    )
    expanded = orchestrator._expand_project_asset_targets(normalized, context)

    assert [step["parameters"]["target"] for step in expanded] == [
        "121.40.95.31",
        "139.224.104.187",
    ]
    assert all(step["capability"] == "scan_ports" for step in expanded)
    assert all(step["parameters"]["port_range"] == "high-risk" for step in expanded)
    assert "139.224.104.107" not in response
    assert "端口扫描" in response

    chat_plan, chat_response = orchestrator._normalize_project_asset_plan(
        [{"capability": "chat", "parameters": {"message": "旧目标不在项目中"}}],
        context,
        "给我做一个全资产的端口扫描",
        "旧目标不在项目中",
    )
    chat_expanded = orchestrator._expand_project_asset_targets(chat_plan, context)
    assert all(step["capability"] == "scan_ports" for step in chat_expanded)
    assert [step["parameters"]["target"] for step in chat_expanded] == [
        "121.40.95.31",
        "139.224.104.187",
    ]
    assert "端口扫描" in chat_response


if __name__ == "__main__":
    main()
