import asyncio

from app.orchestrator.orchestrator import Orchestrator
from app.services.flow_engine import FlowEngine


def test_explicit_asset_retargets_selected_skill_plan_without_keyword_tool_override():
    plan, response = Orchestrator()._normalize_explicit_asset_plan(
        [{"capability": "nikto_scan", "parameters": {"target": "项目资产"}}],
        {
            "project_assets": [
                {"value": "139.224.104.187"},
                {"value": "121.40.95.31"},
            ],
        },
        "对 139.224.104.187 进行Web 扫描",
        "开始 Web 扫描",
    )

    assert plan == [{"capability": "nikto_scan", "parameters": {"target": "139.224.104.187"}}]
    assert "Web 安全扫描" in response
    assert "139.224.104.187" in response
    assert "121.40.95.31" not in response


def test_project_asset_scope_preserves_skill_selected_capability_and_parameters():
    plan, _response = Orchestrator()._normalize_project_asset_plan(
        [{"capability": "scan_ports", "parameters": {"target": "old", "port_range": "30-3000"}}],
        {"project_assets": [{"value": "192.0.2.10"}]},
        "对当前项目所有资产执行检测",
        "开始检测",
    )

    assert plan == [{
        "capability": "scan_ports",
        "parameters": {"target": "项目资产", "port_range": "30-3000"},
    }]


def test_scan_score_recalculation_delegates_to_flow_engine(monkeypatch):
    assessment = object()
    synced = []

    class Result:
        def scalar_one_or_none(self):
            return assessment

    class DB:
        committed = False

        async def execute(self, _query):
            return Result()

        async def commit(self):
            self.committed = True

        async def rollback(self):
            raise AssertionError("score recalculation should not roll back")

    async def sync(_engine, value):
        synced.append(value)

    monkeypatch.setattr(FlowEngine, "_sync_project_assessment", sync)
    db = DB()
    asyncio.run(Orchestrator()._calculate_and_update_score(db, 70))

    assert synced == [assessment]
    assert db.committed is True
