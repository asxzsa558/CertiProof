import asyncio

from app.orchestrator.orchestrator import Orchestrator
from app.services.flow_engine import FlowEngine


def test_current_command_target_removes_target_copied_from_history():
    plan, response = Orchestrator()._keep_current_command_targets(
        [
            {"capability": "nikto_scan", "parameters": {"target": "139.224.104.187"}},
            {"capability": "nikto_scan", "parameters": {"target": "172.23.0.17"}},
        ],
        "对 172.23.0.17 进行Web 扫描",
        "扫描两个目标",
    )

    assert plan == [{"capability": "nikto_scan", "parameters": {"target": "172.23.0.17"}}]
    assert "172.23.0.17" in response
    assert "139.224.104.187" not in response


def test_explicit_project_asset_web_scan_recovers_from_invalid_ai_plan():
    plan, response = Orchestrator()._normalize_explicit_asset_plan(
        [{"capability": "chat", "parameters": {"message": "缺少必要参数：url"}}],
        {
            "project_assets": [
                {"value": "139.224.104.187"},
                {"value": "121.40.95.31"},
            ],
        },
        "对 139.224.104.187 进行Web 扫描",
        "参数不完整或不合法：缺少必要参数：url。请补充后重试。",
    )

    assert plan == [{"capability": "nikto_scan", "parameters": {"target": "139.224.104.187"}}]
    assert "Web 安全扫描" in response
    assert "139.224.104.187" in response
    assert "121.40.95.31" not in response


def test_web_vulnerability_wording_uses_nikto_not_generic_nuclei():
    assert Orchestrator()._requested_scan_capability("重新进行 Web 漏洞扫描") == "nikto_scan"


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
