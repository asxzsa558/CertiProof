"""HTTP smoke test for the five-stage assessment API.

Creates a temporary project through the public API, uploads one document,
polls the queued document analysis, checks restart/reset behavior, downloads
the HTML report, then deletes the project.
"""

import asyncio
import json
import os
import time
import uuid
from urllib import error, request

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine as db_engine
from app.core.security import create_access_token
from app.models.organization import OrganizationMember
from app.models.user import User


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api/v1")
HEALTH_URL = os.getenv("HEALTH_URL", API_BASE.removesuffix("/api/v1") + "/health")


async def _auth_context() -> tuple[str, int]:
    db_engine.echo = False
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.id).limit(1))).scalar_one_or_none()
        if not user:
            raise RuntimeError("No active user available for API smoke test.")
        member = (await db.execute(
            select(OrganizationMember)
            .where(OrganizationMember.user_id == user.id)
            .order_by(OrganizationMember.id)
            .limit(1)
        )).scalar_one_or_none()
        if not member:
            raise RuntimeError("The test user has no organization membership.")
        return create_access_token(data={"sub": str(user.id)}), member.organization_id


def _request(method: str, path: str, token: str, org_id: int, body=None, *, content_type="application/json"):
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}", "X-Org-Id": str(org_id)}
    data = None
    if body is not None:
        if content_type == "application/json":
            data = json.dumps(body).encode("utf-8")
        else:
            data = body
        headers["Content-Type"] = content_type
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=20) as resp:
            payload = resp.read()
            if not payload:
                return resp.status, None
            if resp.headers.get_content_type() == "application/json":
                return resp.status, json.loads(payload.decode("utf-8"))
            return resp.status, payload.decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc


def _multipart(files: list[tuple[str, str, bytes]], fields: dict[str, str] | None = None) -> tuple[bytes, str]:
    boundary = f"----certiproof-smoke-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in (fields or {}).items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode(),
            b"\r\n",
        ])
    for field_name, file_name, content in files:
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field_name}"; filename="{file_name}"\r\n'.encode(),
            b"Content-Type: text/plain\r\n\r\n",
            content,
            b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _wait_for_api() -> None:
    last_error = None
    for _ in range(30):
        try:
            with request.urlopen(HEALTH_URL, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - smoke test reports the final connection error.
            last_error = exc
            time.sleep(1)
    raise AssertionError(f"API did not become healthy: {last_error}")


def main() -> None:
    _wait_for_api()
    token, org_id = asyncio.run(_auth_context())
    project_id = None
    marker = uuid.uuid4().hex[:8]

    try:
        status, _ = _request("POST", "/assessments/templates/init", token, org_id)
        assert status == 200
        status, templates = _request("GET", "/assessments/templates", token, org_id)
        assert status == 200 and templates
        template = next(item for item in templates if item["compliance_level"] == 3)

        status, project = _request("POST", "/projects/", token, org_id, {
            "organization_id": org_id,
            "name": f"CertiProof API 烟测 {marker}",
            "system_name": "API 烟测系统",
            "description": "临时项目：验证等保测评 API 不报错。",
            "compliance_level": "三级",
            "assessment_type_ids": [],
        })
        assert status == 201
        project_id = project["id"]

        status, asset = _request("POST", f"/projects/{project_id}/assets/", token, org_id, {
            "asset_type": "ip",
            "value": "203.0.113.30",
            "name": "API 烟测资产",
        })
        assert status == 201
        status, verified_asset = _request("POST", f"/projects/{project_id}/assets/{asset['id']}/verify", token, org_id, {
            "verification_method": "port_response",
        })
        assert status == 200 and verified_asset["verification_status"] == "verified"

        status, assessment = _request("POST", f"/assessments/projects/{project_id}", token, org_id, {
            "template_id": template["id"],
            "name": "API 5 阶段烟测",
        })
        assert status == 200
        assessment_id = assessment["id"]

        status, started = _request("POST", f"/assessments/{assessment_id}/start", token, org_id)
        assert status == 200 and started["status"] == "in_progress"

        status, phases = _request("GET", f"/assessments/{assessment_id}/phases", token, org_id)
        names = [phase["name"] for phase in phases]
        assert names == ["差距分析", "现场测评", "整改加固", "复测验证", "生成报告"], names
        gap_phase = next(phase for phase in phases if phase["name"] == "差距分析")

        status, tasks = _request("GET", f"/assessments/phases/{gap_phase['id']}/tasks", token, org_id)
        assert status == 200 and len(tasks) == 15
        doc_task = next(task for task in tasks if task["task_type"] == "doc_review" and "安全事件管理制度" in task["name"])

        document = "\n".join([
            "安全事件管理制度",
            "事件发现后应报告安全负责人。",
            "事件处置应记录处理过程。",
        ]).encode("utf-8")
        body, content_type = _multipart(
            [("files", "api-smoke-security-event.txt", document)],
            {"analysis_mode": "standard"},
        )
        status, upload = _request("POST", f"/assessments/tasks/{doc_task['id']}/documents", token, org_id, body, content_type=content_type)
        assert status == 202 and upload["status"] == "queued"
        run_id = upload["run_id"]

        terminal = None
        for _ in range(30):
            status, run = _request("GET", f"/assessments/document-runs/{run_id}", token, org_id)
            assert status == 200
            if run["status"] in {"completed", "failed", "cancelled"}:
                terminal = run
                break
            time.sleep(1)
        assert terminal and terminal["status"] == "completed", terminal

        status, report_html = _request("GET", f"/projects/{project_id}/report", token, org_id)
        assert status == 200 and "5 阶段测评进度" in report_html and "文档差距" in report_html

        status, restart = _request("POST", f"/assessments/{assessment_id}/restart", token, org_id, {"mode": "reset"})
        assert status == 200 and restart["status"] == "reset"
        status, after_reset = _request("GET", f"/assessments/{assessment_id}", token, org_id)
        assert status == 200 and after_reset["status"] == "not_started" and round(after_reset["progress"] or 0) == 0

        print(json.dumps({
            "status": "assessment api smoke ok",
            "project_id": project_id,
            "assessment_id": assessment_id,
            "document_run_id": run_id,
            "phases": names,
        }, ensure_ascii=False))
    finally:
        if project_id:
            _request("DELETE", f"/projects/{project_id}", token, org_id)


if __name__ == "__main__":
    main()
