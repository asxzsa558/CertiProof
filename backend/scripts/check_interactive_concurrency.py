"""Exercise independent interactive queues and multi-asset result attribution."""

import asyncio
import json
import time
import uuid

from check_assessment_api_smoke import _auth_context, _request, _wait_for_api


def _wait_for_result(task_id: str, token: str, org_id: int, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, result = _request("GET", f"/chat/result/{task_id}", token, org_id)
        assert status == 200
        if result["status"] in {"completed", "failed"}:
            return result
        time.sleep(1)
    raise AssertionError(f"交互任务超时：{task_id}")


def _start_scan(project_id: int, token: str, org_id: int, payload: dict) -> tuple[dict, float]:
    started_at = time.monotonic()
    status, response = _request("POST", "/chat/", token, org_id, {
        "project_id": project_id,
        "message": json.dumps(payload, ensure_ascii=False),
    })
    elapsed = time.monotonic() - started_at
    assert status == 200 and response.get("task_id") and response.get("scan_task_id"), response
    assert elapsed < 10, f"创建交互任务耗时 {elapsed:.1f}s，疑似被前一任务阻塞"
    return response, elapsed


def main() -> None:
    _wait_for_api()
    token, org_id = asyncio.run(_auth_context())
    project_id = None
    try:
        marker = uuid.uuid4().hex[:8]
        status, project = _request("POST", "/projects/", token, org_id, {
            "organization_id": org_id,
            "name": f"CertiProof 交互并发烟测 {marker}",
            "system_name": "交互并发烟测",
            "description": "临时项目：验证独立交互队列和多资产归属。",
            "compliance_level": "三级",
            "assessment_type_ids": [],
        })
        assert status == 201
        project_id = project["id"]

        assets = []
        for value in ("e2e-target", "redis"):
            status, asset = _request("POST", f"/projects/{project_id}/assets/", token, org_id, {
                "asset_type": "domain",
                "value": value,
                "name": f"内部验收资产 {value}",
            })
            assert status == 201
            status, confirmed = _request(
                "POST",
                f"/projects/{project_id}/assets/{asset['id']}/confirm-scope",
                token,
                org_id,
                {"confirmed": True},
            )
            assert status == 200 and confirmed.get("scope_confirmed_at")
            assets.append({"id": asset["id"], "value": value})

        web, web_latency = _start_scan(project_id, token, org_id, {
            "type": "multi_asset_scan",
            "capability": "nikto_scan",
            "assets": [assets[0]],
            "parameters": {"port": 80, "timeout": 30},
        })
        ports, port_latency = _start_scan(project_id, token, org_id, {
            "type": "multi_asset_scan",
            "capability": "scan_ports",
            "assets": [assets[0], assets[1], assets[0]],
            "parameters": {"port_range": "22,80,443,6379", "host_timeout": 30},
        })
        assert web["task_id"] != ports["task_id"]

        port_result = _wait_for_result(ports["task_id"], token, org_id)
        web_result = _wait_for_result(web["task_id"], token, org_id)
        assert port_result["status"] == "completed", port_result
        assert web_result["status"] in {"completed", "failed"}, web_result

        status, web_scan = _request(
            "GET", f"/projects/{project_id}/scans/{web['scan_task_id']}", token, org_id
        )
        assert status == 200
        status, port_scan = _request(
            "GET", f"/projects/{project_id}/scans/{ports['scan_task_id']}", token, org_id
        )
        assert status == 200
        port_plan = port_scan["parameters"]["plan"]
        assert [step["parameters"]["target"] for step in port_plan] == ["e2e-target", "redis"]
        assert web_scan["status"] in {"completed", "failed"}
        assert port_scan["status"] == "completed"

        scan_results = (port_scan.get("result_summary") or {}).get("scan_results") or {}
        result_targets = set((scan_results.get("asset_results") or {}).keys())
        assert {"e2e-target", "redis"}.issubset(result_targets), scan_results

        print(json.dumps({
            "status": "interactive concurrency ok",
            "project_id": project_id,
            "task_ids": [web["task_id"], ports["task_id"]],
            "enqueue_latency_seconds": [round(web_latency, 3), round(port_latency, 3)],
            "multi_asset_targets": sorted(result_targets),
        }, ensure_ascii=False))
    finally:
        if project_id:
            _request("DELETE", f"/projects/{project_id}", token, org_id)


if __name__ == "__main__":
    main()
