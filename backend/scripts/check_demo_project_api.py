"""Smoke test for the one-click demo project API."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_assessment_api_smoke import _auth_context, _request, _wait_for_api


def main() -> None:
    _wait_for_api()
    token, org_id = asyncio.run(_auth_context())
    status, demo = _request("POST", "/projects/demo", token, org_id, {"organization_id": org_id})
    assert status == 201 and demo.get("project_id"), demo
    project_id = demo["project_id"]

    status, assets = _request("GET", f"/projects/{project_id}/assets/", token, org_id)
    assert status == 200 and len(assets) == 3, assets
    status, assessments = _request("GET", f"/assessments/projects/{project_id}", token, org_id)
    assert status == 200 and assessments and assessments[0]["total_phases"] == 4, assessments
    status, verification = _request("GET", f"/projects/{project_id}/verification/workspace", token, org_id)
    assert status == 200 and verification.get("summary", {}).get("total", 0) >= 2, verification
    status, dashboard = _request("GET", "/dashboard/organization-command", token, org_id)
    nodes = dashboard.get("exposure_topology", {}).get("nodes", [])
    assert status == 200 and any(node.get("id") == f"asset-{assets[0]['id']}" for node in nodes), nodes

    print(json.dumps({"status": "demo project api ok", "project_id": project_id, "topology_nodes": len(nodes)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
