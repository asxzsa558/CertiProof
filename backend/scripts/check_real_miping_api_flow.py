"""Run a preserved, real-document Miping self-assessment through public APIs."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "artifacts" / "real-miping-fixtures"
STATE_PATH = FIXTURES / "api-flow-state.json"
REPORT_PATH = ROOT / "artifacts" / "certiproof-real-miping-report.html"
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api/v1")
EMAIL = os.getenv("CP_E2E_EMAIL")
PASSWORD = os.getenv("CP_E2E_PASSWORD")
ACCESS_TOKEN = os.getenv("CP_E2E_TOKEN")
ORG_ID = int(os.getenv("CP_E2E_ORG_ID", "1"))
TARGET = os.getenv("CP_E2E_TARGET", "e2e-target")
TERMINAL_TASKS = {"completed", "failed", "cancelled"}
TERMINAL_RUNS = {"completed", "failed", "cancelled", "partial"}


class API:
    def __init__(self) -> None:
        self.client = httpx.Client(trust_env=False)
        if ACCESS_TOKEN:
            token = ACCESS_TOKEN
        elif EMAIL and PASSWORD:
            response = self.client.post(
                f"{API_BASE}/auth/login",
                json={"email": EMAIL, "password": PASSWORD},
                timeout=30,
            )
            response.raise_for_status()
            token = response.json()["access_token"]
        else:
            raise RuntimeError("Set CP_E2E_TOKEN or CP_E2E_EMAIL/CP_E2E_PASSWORD.")
        self.headers = {"Authorization": f"Bearer {token}", "X-Org-Id": str(ORG_ID)}

    def request(self, method: str, path: str, **kwargs):
        response = self.client.request(
            method,
            f"{API_BASE}{path}",
            headers=self.headers,
            timeout=kwargs.pop("timeout", 120),
            **kwargs,
        )
        if not response.is_success:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code} {response.text[:1600]}")
        return response.json() if "application/json" in response.headers.get("content-type", "") else response.text


def save_state(**values) -> None:
    current = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    current.update(values)
    current["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STATE_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def upload_batch(api: API, phase_id: int, archive: Path) -> int:
    with archive.open("rb") as stream:
        response = api.client.post(
            f"{API_BASE}/assessments/phases/{phase_id}/documents/batch",
            headers=api.headers,
            data={"analysis_mode": "standard"},
            files={"files": (archive.name, stream, "application/zip")},
            timeout=180,
        )
    if not response.is_success:
        raise RuntimeError(f"batch upload {archive.name}: HTTP {response.status_code} {response.text[:1600]}")
    return response.json()["run_id"]


def wait_document_run(api: API, run_id: int, label: str, timeout: int = 3600) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        run = api.request("GET", f"/assessments/document-runs/{run_id}")
        progress = run.get("progress") or {}
        marker = run.get("status"), progress.get("percent"), progress.get("message")
        if marker != last:
            print(f"[{label}] {marker}", flush=True)
            last = marker
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(3)
    raise TimeoutError(f"{label} timed out after {timeout}s")


def wait_tasks(api: API, phase_id: int, label: str, timeout: int = 3600) -> list[dict]:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        tasks = api.request("GET", f"/assessments/phases/{phase_id}/tasks")
        summary = {status: sum(item["status"] == status for item in tasks) for status in {item["status"] for item in tasks}}
        if summary != last:
            print(f"[{label}] {summary}", flush=True)
            last = summary
        if tasks and all(item["status"] in TERMINAL_TASKS for item in tasks):
            return tasks
        time.sleep(4)
    raise TimeoutError(f"{label} timed out after {timeout}s")


def workspace(api: API, project_id: int, assessment_id: int) -> dict:
    return api.request("GET", f"/projects/{project_id}/verification/workspace?assessment_id={assessment_id}")


def wait_verification_runs(
    api: API,
    project_id: int,
    assessment_id: int,
    run_ids: set[int],
    timeout: int = 3600,
) -> dict:
    if not run_ids:
        return workspace(api, project_id, assessment_id)
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        current = workspace(api, project_id, assessment_id)
        selected = [run for run in current.get("runs", []) if run["id"] in run_ids]
        states = tuple(sorted((run["id"], run["status"], (run.get("summary") or {}).get("completed", 0)) for run in selected))
        if states != last:
            print(f"[整改复测] {states}", flush=True)
            last = states
        if len(selected) == len(run_ids) and all(run["status"] in TERMINAL_RUNS for run in selected):
            return current
        time.sleep(3)
    raise TimeoutError(f"verification runs timed out: {sorted(run_ids)}")


def require_completed_documents(tasks: list[dict], expected: int, label: str) -> None:
    documents = [task for task in tasks if task["task_type"] == "doc_review"]
    assert len(documents) == expected, f"{label}: expected {expected} document tasks, got {len(documents)}"
    failed = [task for task in documents if task["status"] != "completed"]
    assert not failed, json.dumps([{"name": item["name"], "status": item["status"], "result": item.get("result")} for item in failed], ensure_ascii=False)


def nested_dicts(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from nested_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from nested_dicts(item)


def finish_existing(api: API, project_id: int, assessment_id: int) -> None:
    """Resume the durable verification/report tail without recreating expensive document work."""
    current_workspace = workspace(api, project_id, assessment_id)

    active_ids = {
        run["id"] for run in current_workspace.get("runs", [])
        if run["status"] not in TERMINAL_RUNS
    }
    current_workspace = wait_verification_runs(api, project_id, assessment_id, active_ids)

    technical_run_ids: set[int] = set()
    for group in current_workspace.get("technical_groups", []):
        finding_ids = [
            item["id"] for item in group["findings"]
            if item["status"] == "open" and not item.get("latest_verification")
        ]
        if not finding_ids:
            continue
        payload = api.request("POST", f"/projects/{project_id}/verification/technical", json={
            "finding_ids": finding_ids,
            "notes": "真实密评闭环验收：整改后重新执行同一密码协议与证书检测并保留对比结果。",
            "credentials": {},
        })
        technical_run_ids.add(payload["run_id"])
    current_workspace = wait_verification_runs(api, project_id, assessment_id, technical_run_ids)
    assert current_workspace["summary"]["fixed"] > 0, current_workspace["summary"]

    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    phase = {item["phase_id"]: item for item in phases}
    if phase["remediation_verification"]["status"] != "completed":
        api.request("POST", f"/assessments/phases/{phase['remediation_verification']['id']}/complete", json={
            "outputs": {"acceptance": "真实整改材料和技术复测均已执行"},
        })

    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    phase = {item["phase_id"]: item for item in phases}
    assert phase["report"]["status"] in {"active", "completed"}, phases
    report_tasks = api.request("GET", f"/assessments/phases/{phase['report']['id']}/tasks")
    report_task = next(item for item in report_tasks if item["task_type"] == "html_report")
    if report_task["status"] != "completed":
        api.request("POST", f"/assessments/tasks/{report_task['id']}/start")
    html = api.request("GET", f"/assessments/{assessment_id}/report", timeout=180)
    for text in (
        "企业密码应用自查报告",
        "密码应用八个层面结论",
        "密评准备与差距分析",
        "密码应用现场评估",
        "整改与复测记录",
    ):
        assert text in html, text
    REPORT_PATH.write_text(html, encoding="utf-8")

    final_assessment = api.request("GET", f"/assessments/{assessment_id}")
    assert final_assessment["status"] == "completed", final_assessment
    assert round(final_assessment["progress"]) == 100, final_assessment
    final_matrix = api.request("GET", f"/assessments/{assessment_id}/miping-matrix")
    current = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    save_state(
        status="completed",
        report=str(REPORT_PATH),
        final_summary=current_workspace["summary"],
        final_matrix=final_matrix["counts"],
        technical_verification_run_ids=sorted({*current.get("technical_verification_run_ids", []), *active_ids, *technical_run_ids}),
    )
    print(json.dumps({
        "status": "real Miping API flow completed",
        "project_id": project_id,
        "assessment_id": assessment_id,
        "initial_summary": current.get("initial_summary"),
        "final_summary": current_workspace["summary"],
        "initial_matrix": current.get("initial_matrix"),
        "final_matrix": final_matrix["counts"],
        "report": str(REPORT_PATH),
    }, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    if not (FIXTURES / "manifest.json").exists():
        raise RuntimeError("Run backend/scripts/build_real_miping_documents.py first.")
    api = API()
    resume_project_id = int(os.getenv("CP_E2E_RESUME_PROJECT_ID", "0"))
    if resume_project_id:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if state.get("project_id") != resume_project_id:
            raise RuntimeError(f"state project {state.get('project_id')} does not match resume project {resume_project_id}")
        print(f"[恢复项目] {resume_project_id}，继续持久化整改复测与报告生成", flush=True)
        finish_existing(api, resume_project_id, state["assessment_id"])
        return
    api.request("POST", "/assessments/templates/init")
    templates = api.request("GET", "/assessments/templates?assessment_code=miping")
    template = next(item for item in templates if item["assessment_type_code"] == "miping" and item["compliance_level"] == 3)

    marker = datetime.now().strftime("%m%d-%H%M")
    project = api.request("POST", "/projects/", json={
        "organization_id": ORG_ID,
        "name": f"CertiProof 密评真实材料闭环验收 {marker}",
        "system_name": "受控密码应用业务系统",
        "description": "保留项目：13 类真实 DOCX 材料、初检缺口、八层面矩阵、整改复测和密评 HTML 报告验收。",
        "compliance_level": "三级",
        "assessment_configs": [
            {"code": "dengbao", "level": "三级"},
            {"code": "miping", "level": "三级"},
        ],
    })
    project_id = project["id"]
    print(f"[项目] {project_id} {project['name']}", flush=True)

    asset = api.request("POST", f"/projects/{project_id}/assets/", json={
        "asset_type": "domain",
        "value": TARGET,
        "name": "Docker 内网密码协议验收靶机",
    })
    api.request("POST", f"/projects/{project_id}/assets/{asset['id']}/confirm-scope", json={"confirmed": True})
    assessment = api.request("POST", f"/assessments/projects/{project_id}", json={
        "template_id": template["id"],
        "name": "密评真实材料四阶段闭环验收",
    })
    assessment_id = assessment["id"]
    save_state(project_id=project_id, project_name=project["name"], assessment_id=assessment_id, status="created")
    api.request("POST", f"/assessments/{assessment_id}/start")

    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    expected_phases = ["密评准备与差距分析", "密码应用现场评估", "整改与复测", "生成密评自查报告"]
    assert [phase["name"] for phase in phases] == expected_phases, phases
    phase = {item["phase_id"]: item for item in phases}

    gap_run_id = upload_batch(api, phase["gap_analysis"]["id"], FIXTURES / "密评初检-准备与差距分析材料.zip")
    gap_batch = wait_document_run(api, gap_run_id, "准备材料归类")
    assert gap_batch["status"] == "completed", gap_batch
    assert len((gap_batch.get("result") or {}).get("classified") or []) == 9, gap_batch.get("result")
    gap_tasks = wait_tasks(api, phase["gap_analysis"]["id"], "准备与差距分析")
    require_completed_documents(gap_tasks, 9, "准备与差距分析")
    save_state(status="gap_documents_completed", gap_document_run_id=gap_run_id)

    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    phase = {item["phase_id"]: item for item in phases}
    assert phase["field_assessment"]["status"] == "active", phases
    field_run_id = upload_batch(api, phase["field_assessment"]["id"], FIXTURES / "密评初检-现场证据材料.zip")
    api.request("POST", f"/assessments/phases/{phase['field_assessment']['id']}/technical/execute", json={
        "asset_ids": [asset["id"]],
        "credentials": {},
    })
    field_batch = wait_document_run(api, field_run_id, "现场证据归类")
    assert field_batch["status"] == "completed", field_batch
    assert len((field_batch.get("result") or {}).get("classified") or []) == 4, field_batch.get("result")
    field_tasks = wait_tasks(api, phase["field_assessment"]["id"], "密码应用现场评估")
    require_completed_documents(field_tasks, 4, "密码应用现场评估")
    crypto_task = next(item for item in field_tasks if item["task_type"] == "crypto_network_communication_assessment")
    assert crypto_task["status"] == "completed", crypto_task
    transport_results = [
        item for item in nested_dicts(crypto_task.get("result"))
        if item.get("capability") == "crypto_transport_scan"
    ]
    assert transport_results, "crypto transport subtool did not return a result"
    assert any((item.get("data") or {}).get("scan_completed") is True for item in transport_results), transport_results
    assert "does not support async mode" not in json.dumps(crypto_task.get("result"), ensure_ascii=False)

    initial_workspace = workspace(api, project_id, assessment_id)
    assert initial_workspace["summary"]["open"] > 0, "deliberately incomplete materials produced no findings"
    matrix = api.request("GET", f"/assessments/{assessment_id}/miping-matrix")
    assert len(matrix["domains"]) == 8, matrix
    assert matrix["counts"].get("pass", 0) < 8, "initial gaps were incorrectly reported as all-pass"
    save_state(status="initial_assessment_completed", initial_summary=initial_workspace["summary"], initial_matrix=matrix["counts"])
    print(f"[初检] findings={initial_workspace['summary']} matrix={matrix['counts']}", flush=True)

    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    phase = {item["phase_id"]: item for item in phases}
    assert phase["remediation_verification"]["status"] == "active", phases
    remediation_run_id = upload_batch(
        api,
        phase["remediation_verification"]["id"],
        FIXTURES / "密评整改复测-全量材料.zip",
    )
    remediation_batch = wait_document_run(api, remediation_run_id, "整改材料归类")
    assert remediation_batch["status"] == "completed", remediation_batch
    result = remediation_batch.get("result") or {}
    assert len(result.get("classified") or []) == 13, result
    document_verification_ids = {
        item["verification_run_id"] for item in result.get("verification_runs") or []
    }
    wait_verification_runs(api, project_id, assessment_id, document_verification_ids)
    save_state(
        status="document_verification_completed",
        gap_document_run_id=gap_run_id,
        field_document_run_id=field_run_id,
        remediation_document_run_id=remediation_run_id,
        document_verification_run_ids=sorted(document_verification_ids),
    )
    finish_existing(api, project_id, assessment_id)


if __name__ == "__main__":
    main()
