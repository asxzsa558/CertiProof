"""Outbound-only runtime for a CertiProof remote scan node."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import platform
import socket
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.services.execution_engine import ExecutionEngine
from app.services.execution_policy import NETWORK_CAPABILITIES
from app.services.scan_node_service import execution_targets, target_host


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("certiproof.remote_node")

CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "").rstrip("/")
if CONTROL_PLANE_URL and not CONTROL_PLANE_URL.endswith("/api/v1"):
    CONTROL_PLANE_URL += "/api/v1"
STATE_FILE = Path(os.getenv("NODE_STATE_FILE", "/var/lib/certiproof-node/identity.json"))
ENROLL_TOKEN = os.getenv("ENROLL_TOKEN", "")
ALLOW_INSECURE = os.getenv("ALLOW_INSECURE_CONTROL_PLANE", "false").lower() == "true"


def runtime_info() -> dict:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "version": os.getenv("CERTIPROOF_VERSION", "source"),
    }


def validate_control_plane_url() -> None:
    parsed = urlsplit(CONTROL_PLANE_URL)
    if not parsed.scheme or not parsed.hostname:
        raise RuntimeError("CONTROL_PLANE_URL 必须是可访问的 CertiProof 地址")
    local = parsed.hostname in {"localhost", "127.0.0.1", "backend"}
    if parsed.scheme != "https" and not local and not ALLOW_INSECURE:
        raise RuntimeError("远端节点只允许 HTTPS 控制平面；测试环境需显式设置 ALLOW_INSECURE_CONTROL_PLANE=true")


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("节点身份文件损坏，请删除后使用新注册令牌重新注册") from exc
    if not value.get("node_id") or not value.get("node_token"):
        raise RuntimeError("节点身份文件缺少 node_id 或 node_token")
    return value


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(STATE_FILE)
    STATE_FILE.chmod(0o600)


def job_allowed(config: dict, job: dict) -> bool:
    capability = job.get("capability")
    if capability not in NETWORK_CAPABILITIES or capability not in (config.get("capabilities") or []):
        return False
    project_id = job.get("project_id")
    if project_id and project_id in (config.get("project_ids") or []):
        return True
    targets = execution_targets(job.get("parameters") or {})
    if not targets or not config.get("allowed_cidrs"):
        return False
    networks = [ipaddress.ip_network(value, strict=False) for value in config["allowed_cidrs"]]
    for target in targets:
        try:
            address = ipaddress.ip_address(target_host(target) or "")
        except ValueError:
            return False
        if not any(address in network for network in networks):
            return False
    return True


class RemoteNode:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30, read=45))
        self.state: dict = {}
        self.config: dict = {}
        self.running: dict[str, asyncio.Task] = {}

    def headers(self) -> dict:
        return {
            "X-Node-ID": str(self.state["node_id"]),
            "Authorization": f"Bearer {self.state['node_token']}",
        }

    async def request(self, method: str, path: str, **kwargs) -> dict:
        response = await self.client.request(method, f"{CONTROL_PLANE_URL}/scan-nodes{path}", **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    async def enroll(self) -> None:
        existing = load_state()
        if existing:
            self.state = existing
            return
        if not ENROLL_TOKEN:
            raise RuntimeError("首次启动必须提供 ENROLL_TOKEN")
        response = await self.request("POST", "/runtime/enroll", json={
            "enrollment_token": ENROLL_TOKEN,
            "runtime_info": runtime_info(),
        })
        self.state = {"node_id": response["node_id"], "node_token": response["node_token"]}
        self.config = response["config"]
        save_state(self.state)
        logger.info("节点注册完成，node_id=%s", self.state["node_id"])

    async def heartbeat(self) -> None:
        response = await self.request("POST", "/runtime/heartbeat", headers=self.headers(), json={
            "runtime_info": runtime_info(),
            "active_jobs": len(self.running),
            "config_version": self.config.get("config_version", 0),
        })
        self.config = response["config"]

    async def monitor_job(self, job_id: str, task: asyncio.Task) -> None:
        while not task.done():
            await asyncio.sleep(max(2, int(self.config.get("heartbeat_seconds", 10))))
            response = await self.request(
                "POST",
                f"/runtime/jobs/{job_id}/heartbeat",
                headers=self.headers(),
                json={"progress": {"stage": "远端工具执行中", "percent": 50}},
            )
            if response.get("control_state") == "cancel_requested":
                task.cancel()
                return
            self.config = response.get("config") or self.config

    async def execute_job(self, job: dict) -> None:
        job_id = job["id"]
        if not job_allowed(self.config, job):
            await self.request(
                "POST",
                f"/runtime/jobs/{job_id}/fail",
                headers=self.headers(),
                json={"error": "节点拒绝执行：任务不在节点配置的项目、网段或能力范围内"},
            )
            return
        execution = asyncio.create_task(ExecutionEngine()._execute_capability(
            job["capability"],
            job.get("parameters") or {},
            int(job.get("user_id") or 0),
            project_id=None,
            db=None,
        ))
        monitor = asyncio.create_task(self.monitor_job(job_id, execution))
        try:
            result = await execution
            await self.request(
                "POST",
                f"/runtime/jobs/{job_id}/complete",
                headers=self.headers(),
                json={"result": result},
            )
        except asyncio.CancelledError:
            await self.request(
                "POST",
                f"/runtime/jobs/{job_id}/fail",
                headers=self.headers(),
                json={"error": "任务已由控制平面取消"},
            )
        except Exception as exc:
            logger.exception("远端任务 %s 执行失败", job_id)
            await self.request(
                "POST",
                f"/runtime/jobs/{job_id}/fail",
                headers=self.headers(),
                json={"error": f"{type(exc).__name__}: {str(exc)[:3500]}"},
            )
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)

    async def claim(self) -> None:
        response = await self.request("POST", "/runtime/jobs/claim", headers=self.headers())
        self.config = response.get("config") or self.config
        job = response.get("job")
        if not job:
            return
        task = asyncio.create_task(self.execute_job(job))
        self.running[job["id"]] = task
        task.add_done_callback(lambda _task, job_id=job["id"]: self.running.pop(job_id, None))

    async def run(self) -> None:
        validate_control_plane_url()
        await self.enroll()
        while True:
            try:
                await self.heartbeat()
                capacity = max(0, int(self.config.get("max_concurrency", 1)) - len(self.running))
                for _ in range(capacity):
                    await self.claim()
                await asyncio.sleep(max(2, int(self.config.get("heartbeat_seconds", 10))))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    raise RuntimeError("节点凭证已失效，请在控制平面轮换注册令牌并清除身份卷后重新注册") from exc
                logger.warning("控制平面返回 HTTP %s，稍后重试", exc.response.status_code)
                await asyncio.sleep(10)
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("暂时无法连接控制平面：%s", exc)
                await asyncio.sleep(10)


async def main() -> None:
    node = RemoteNode()
    try:
        await node.run()
    finally:
        await node.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
