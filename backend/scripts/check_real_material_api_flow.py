"""Run and preserve a real-material four-stage acceptance project through public APIs."""

from __future__ import annotations

import json
import mimetypes
import os
import time
from datetime import datetime
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "artifacts" / "real-compliance-fixtures"
STATE_PATH = FIXTURES / "api-flow-state.json"
REPORT_PATH = ROOT / "artifacts" / "certiproof-real-material-report.html"
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api/v1")
EMAIL = os.getenv("CP_E2E_EMAIL")
PASSWORD = os.getenv("CP_E2E_PASSWORD")
ACCESS_TOKEN = os.getenv("CP_E2E_TOKEN")
ORG_ID = int(os.getenv("CP_E2E_ORG_ID", "1"))
TARGET = os.getenv("CP_E2E_TARGET", "172.23.0.17")
TARGET_USER = os.getenv("CP_E2E_TARGET_USER", "audit")
TARGET_PASSWORD = os.getenv("CP_E2E_TARGET_PASSWORD", "CertiProof-E2E-2026!")
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
            raise RuntimeError("Set CP_E2E_TOKEN or CP_E2E_EMAIL/CP_E2E_PASSWORD for API acceptance.")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "X-Org-Id": str(ORG_ID),
        }

    def request(self, method: str, path: str, **kwargs):
        response = self.client.request(
            method,
            f"{API_BASE}{path}",
            headers=self.headers,
            timeout=kwargs.pop("timeout", 90),
            **kwargs,
        )
        if not response.is_success:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code} {response.text[:1200]}")
        content_type = response.headers.get("content-type", "")
        return response.json() if "application/json" in content_type else response.text


def save_state(**values) -> None:
    current = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    current.update(values)
    current["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STATE_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def wait_document_run(api: API, run_id: int, label: str, timeout: int = 1800) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        run = api.request("GET", f"/assessments/document-runs/{run_id}")
        marker = (run.get("status"), (run.get("progress") or {}).get("percent"), (run.get("progress") or {}).get("message"))
        if marker != last:
            print(f"[{label}] {marker}", flush=True)
            last = marker
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(3)
    raise TimeoutError(f"{label} timed out after {timeout}s")


def wait_tasks(
    api: API,
    phase_id: int,
    label: str,
    timeout: int = 2700,
    task_types: set[str] | None = None,
) -> list[dict]:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        all_tasks = api.request("GET", f"/assessments/phases/{phase_id}/tasks")
        tasks = [task for task in all_tasks if not task_types or task["task_type"] in task_types]
        states = tuple((task["name"], task["status"]) for task in tasks)
        summary = {
            status: sum(task["status"] == status for task in tasks)
            for status in {task["status"] for task in tasks}
        }
        if summary != last:
            print(f"[{label}] {summary}", flush=True)
            last = summary
        if tasks and all(task["status"] in TERMINAL_TASKS for task in tasks):
            return tasks
        time.sleep(4)
    raise TimeoutError(f"{label} timed out after {timeout}s")


def wait_verification_runs(api: API, project_id: int, run_ids: set[int], timeout: int = 1800) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        workspace = api.request("GET", f"/projects/{project_id}/verification/workspace")
        selected = [run for run in workspace.get("runs", []) if run["id"] in run_ids]
        states = tuple(sorted((run["id"], run["status"], (run.get("summary") or {}).get("completed", 0)) for run in selected))
        if states != last:
            print(f"[整改复测] {states}", flush=True)
            last = states
        if len(selected) == len(run_ids) and all(run["status"] in TERMINAL_RUNS for run in selected):
            return workspace
        time.sleep(3)
    raise TimeoutError(f"verification runs timed out: {sorted(run_ids)}")


def upload_verification_document(api: API, project_id: int, group: dict, path: Path) -> int:
    open_finding = next(item for item in group["findings"] if item["status"] == "open")
    with path.open("rb") as stream:
        response = api.client.post(
            f"{API_BASE}/projects/{project_id}/verification/document",
            headers=api.headers,
            data={
                "finding_id": str(open_finding["id"]),
                "notes": f"真实材料验收：用 {path.name} 替换初版并重新判断全部检查点。",
                "replace_file_ids": json.dumps([item["id"] for item in group.get("files", [])]),
                "analysis_mode": "standard",
            },
            files={"files": (path.name, stream, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
            timeout=120,
        )
    if not response.is_success:
        raise RuntimeError(f"document verification {path.name}: HTTP {response.status_code} {response.text[:1200]}")
    payload = response.json()
    print(f"[提交整改文档] {group['title']} -> run {payload['verification_run_id']}", flush=True)
    return payload["verification_run_id"]


def continue_flow(api: API, project_id: int, assessment_id: int, asset: dict) -> None:
    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    phase_by_name = {phase["name"]: phase for phase in phases}
    credentials = {TARGET: {"username": TARGET_USER, "password": TARGET_PASSWORD}}
    api.request("POST", f"/assessments/phases/{phase_by_name['差距分析']['id']}/technical/execute", json={
        "asset_ids": [asset["id"]], "credentials": credentials,
    })
    gap_tasks = wait_tasks(api, phase_by_name["差距分析"]["id"], "正确凭据基础技术检测")
    assert next(task for task in gap_tasks if task["task_type"] == "basic_baseline_check")["status"] == "completed"
    save_state(status="gap_analysis_completed")

    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    phase_by_name = {phase["name"]: phase for phase in phases}
    api.request("POST", f"/assessments/phases/{phase_by_name['现场测评']['id']}/technical/execute", json={
        "asset_ids": [asset["id"]], "credentials": credentials,
    })
    field_tasks = wait_tasks(api, phase_by_name["现场测评"]["id"], "现场技术检测")
    save_state(status="field_assessment_finished", field_task_states={task["name"]: task["status"] for task in field_tasks})

    workspace = api.request("GET", f"/projects/{project_id}/verification/workspace")
    initial_document_findings = sum(
        item["status"] == "open"
        for group in workspace.get("document_groups", [])
        for item in group["findings"]
    )
    assert initial_document_findings > 0, "deliberately incomplete documents produced no findings"
    print(f"[初检问题] document={initial_document_findings} total={workspace['summary']['total']}", flush=True)

    remediation_files = {
        "人员安全管理制度": FIXTURES / "remediated" / "人员安全管理制度V1.0-整改版.docx",
        "安全事件管理制度": FIXTURES / "remediated" / "安全事件管理制度V1.0-整改版.docx",
        "信息安全事件应急预案": FIXTURES / "remediated" / "信息安全事件应急预案-可解析版.docx",
    }
    verification_run_ids: set[int] = set()
    for group in workspace.get("document_groups", []):
        if group["title"] in remediation_files and any(item["status"] == "open" for item in group["findings"]):
            verification_run_ids.add(upload_verification_document(api, project_id, group, remediation_files[group["title"]]))
    assert verification_run_ids, "no remediable document group matched the real replacement files"
    workspace = wait_verification_runs(api, project_id, verification_run_ids)
    assert workspace["summary"]["fixed"] > 0, workspace["summary"]

    for attempt in range(2):
        analysis_groups = [
            group for group in workspace.get("document_groups", [])
            if any(item["status"] == "open" and item.get("judgment") == "not_tested" for item in group["findings"])
        ]
        if not analysis_groups:
            break
        retry_ids = set()
        for group in analysis_groups:
            finding = next(item for item in group["findings"] if item["status"] == "open" and item.get("judgment") == "not_tested")
            payload = api.request("POST", f"/projects/{project_id}/verification/document/reanalyze", json={
                "finding_id": finding["id"],
                "notes": f"真实材料验收：判证依赖临时不可用，第 {attempt + 1} 次使用现有材料重试。",
            })
            retry_ids.add(payload["verification_run_id"])
        workspace = wait_verification_runs(api, project_id, retry_ids)

    untouched_document_groups = [
        group for group in workspace.get("document_groups", [])
        if any(
            item["status"] == "open" and not item.get("latest_verification")
            for item in group["findings"]
        )
    ]
    review_run_ids = set()
    for group in untouched_document_groups:
        finding = next(
            item for item in group["findings"]
            if item["status"] == "open" and not item.get("latest_verification")
        )
        payload = api.request("POST", f"/projects/{project_id}/verification/document/reanalyze", json={
            "finding_id": finding["id"],
            "notes": "真实材料验收：重新检查当前材料并如实保留仍未解决的问题。",
        })
        review_run_ids.add(payload["verification_run_id"])
    if review_run_ids:
        workspace = wait_verification_runs(api, project_id, review_run_ids)

    technical_run_ids: set[int] = set()
    for group in workspace.get("technical_groups", []):
        finding_ids = [item["id"] for item in group["findings"] if item["status"] == "open"]
        if not finding_ids:
            continue
        payload = api.request("POST", f"/projects/{project_id}/verification/technical", json={
            "finding_ids": finding_ids,
            "notes": "真实材料验收：整改后重新执行同一工具并比较结果。",
            "credentials": credentials,
        })
        technical_run_ids.add(payload["run_id"])
    if technical_run_ids:
        workspace = wait_verification_runs(api, project_id, technical_run_ids)

    workspace = api.request("GET", f"/projects/{project_id}/verification/workspace")
    unreviewed = [
        item
        for group in [*workspace.get("document_groups", []), *workspace.get("technical_groups", [])]
        for item in group["findings"]
        if item["status"] == "open" and not item.get("latest_verification")
    ]
    assert not unreviewed, unreviewed
    assert workspace["summary"]["open"] > 0, "acceptance target should retain real unresolved findings"

    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    phase_by_name = {phase["name"]: phase for phase in phases}
    assert phase_by_name["生成报告"]["status"] == "active", phases
    report_tasks = api.request("GET", f"/assessments/phases/{phase_by_name['生成报告']['id']}/tasks")
    report_task = next(task for task in report_tasks if task["task_type"] == "html_report")
    api.request("POST", f"/assessments/tasks/{report_task['id']}/start")
    report_tasks = wait_tasks(api, phase_by_name["生成报告"]["id"], "HTML 报告生成", timeout=600)
    assert next(task for task in report_tasks if task["id"] == report_task["id"])["status"] == "completed"
    html = api.request("GET", f"/projects/{project_id}/report", timeout=120)
    for text in ("差距分析", "现场测评", "整改与复测记录", "文档合规核查", "检测覆盖与执行结果"):
        assert text in html, text
    REPORT_PATH.write_text(html, encoding="utf-8")

    final_assessment = api.request("GET", f"/assessments/{assessment_id}")
    assert final_assessment["status"] == "completed" and round(final_assessment["progress"]) == 100
    save_state(
        status="completed",
        report=str(REPORT_PATH),
        summary=workspace["summary"],
        document_verification_run_ids=sorted(verification_run_ids),
        document_review_run_ids=sorted(review_run_ids),
        technical_verification_run_ids=sorted(technical_run_ids),
    )
    print(json.dumps({
        "status": "real material api flow completed",
        "project_id": project_id,
        "assessment_id": assessment_id,
        "report": str(REPORT_PATH),
        "summary": workspace["summary"],
    }, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    api = API()
    resume_project_id = int(os.getenv("CP_E2E_RESUME_PROJECT_ID", "0"))
    if resume_project_id:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if state.get("project_id") != resume_project_id:
            raise RuntimeError(f"state project {state.get('project_id')} does not match resume project {resume_project_id}")
        assets = api.request("GET", f"/projects/{resume_project_id}/assets/")
        asset = next(item for item in assets if item["value"] == TARGET)
        print(f"[恢复项目] {resume_project_id}，从正确凭据技术检测继续", flush=True)
        continue_flow(api, resume_project_id, state["assessment_id"], asset)
        return
    api.request("POST", "/assessments/templates/init")
    templates = api.request("GET", "/assessments/templates")
    template = next(item for item in templates if item["compliance_level"] == 3)
    marker = datetime.now().strftime("%m%d-%H%M")
    project = api.request("POST", "/projects/", json={
        "organization_id": ORG_ID,
        "name": f"CertiProof 真实材料全流程验收 {marker}",
        "system_name": "受控内网业务系统",
        "description": "保留项目：真实 DOCX/PDF/扫描件、受控 SSH/Web 靶机、错误凭据重试、整改文档复测与 HTML 报告验收。",
        "compliance_level": "三级",
        "assessment_type_ids": [],
    })
    project_id = project["id"]
    save_state(project_id=project_id, project_name=project["name"], status="project_created", target=TARGET)
    print(f"[项目] {project_id} {project['name']}", flush=True)

    asset = api.request("POST", f"/projects/{project_id}/assets/", json={
        "asset_type": "ip", "value": TARGET, "name": "Docker 内网受控验收靶机",
    })
    api.request("POST", f"/projects/{project_id}/assets/{asset['id']}/confirm-scope", json={"confirmed": True})
    assessment = api.request("POST", f"/assessments/projects/{project_id}", json={
        "template_id": template["id"], "name": "真实材料四阶段验收",
    })
    assessment_id = assessment["id"]
    api.request("POST", f"/assessments/{assessment_id}/start")
    phases = api.request("GET", f"/assessments/{assessment_id}/phases")
    assert [phase["name"] for phase in phases] == ["差距分析", "现场测评", "整改与复测", "生成报告"]
    phase_by_name = {phase["name"]: phase for phase in phases}
    save_state(assessment_id=assessment_id, status="assessment_started")

    archive_path = FIXTURES / "初次差距分析材料包.zip"
    with archive_path.open("rb") as stream:
        response = api.client.post(
            f"{API_BASE}/assessments/phases/{phase_by_name['差距分析']['id']}/documents/batch",
            headers=api.headers,
            data={"analysis_mode": "standard"},
            files={"files": (archive_path.name, stream, "application/zip")},
            timeout=180,
        )
    if not response.is_success:
        raise RuntimeError(f"batch upload: HTTP {response.status_code} {response.text[:1200]}")
    batch_id = response.json()["run_id"]
    save_state(batch_document_run_id=batch_id, status="documents_queued")
    batch = wait_document_run(api, batch_id, "批量文档归类")
    assert batch["status"] == "completed", batch
    batch_result = batch.get("result") or {}
    classified = batch_result.get("classified") or []
    unmatched = batch_result.get("unmatched") or batch_result.get("unclassified") or []
    assert len(classified) >= 10, batch_result
    print(f"[文档归类] classified={len(classified)} unmatched={len(unmatched)}", flush=True)

    gap_tasks = wait_tasks(
        api,
        phase_by_name["差距分析"]["id"],
        "十类文档检查",
        task_types={"doc_review"},
    )
    document_tasks = [task for task in gap_tasks if task["task_type"] == "doc_review"]
    assert len(document_tasks) == 10, document_tasks
    failed_documents = [task for task in document_tasks if task["status"] == "failed"]
    assert all((task.get("result") or {}).get("status") == "unable" for task in failed_documents), failed_documents
    if failed_documents:
        reasons = [
            (task.get("result") or {}).get("error")
            or (task.get("result") or {}).get("message")
            or "分析依赖不可用"
            for task in failed_documents
        ]
        print(f"[降级路径] 文档任务明确标记 unable：{reasons}", flush=True)

    wrong_credentials = {TARGET: {"username": TARGET_USER, "password": "intentionally-wrong-password"}}
    api.request("POST", f"/assessments/phases/{phase_by_name['差距分析']['id']}/technical/execute", json={
        "asset_ids": [asset["id"]], "credentials": wrong_credentials,
    })
    wrong_tasks = wait_tasks(api, phase_by_name["差距分析"]["id"], "错误凭据技术检测")
    baseline_wrong = next(task for task in wrong_tasks if task["task_type"] == "basic_baseline_check")
    assert baseline_wrong["status"] == "failed", baseline_wrong
    wrong_text = json.dumps(baseline_wrong.get("result") or {}, ensure_ascii=False)
    assert any(word in wrong_text.lower() for word in ("auth", "password", "凭据", "认证")), wrong_text
    print("[错误凭据] 基线任务明确失败且保留认证原因", flush=True)

    continue_flow(api, project_id, assessment_id, asset)


if __name__ == "__main__":
    main()
