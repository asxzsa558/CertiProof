"""
Fast Scanner MCP Server - 快速端口扫描工具
使用 masscan 进行超高速全端口扫描（比 nmap 快 10x）
支持异步扫描和实时进度查询
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

MAX_FPING_TARGETS = 1024
MAX_MASSCAN_RATE = 10_000
MAX_MASSCAN_TIMEOUT = 180

app = FastAPI(title="Fast Scanner MCP Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExecuteRequest(BaseModel):
    tool: str
    params: Dict[str, Any]


# 高危端口定义
CRITICAL_PORTS = {
    3306: "MySQL",
    5432: "PostgreSQL",
    1433: "MSSQL",
    1521: "Oracle",
    6379: "Redis",
    27017: "MongoDB",
    9200: "Elasticsearch",
    11211: "Memcached",
    23: "Telnet",
    21: "FTP",
    135: "MSRPC",
    139: "NetBIOS",
    445: "SMB",
    5900: "VNC",
    2375: "Docker",
    2376: "Docker-TLS",
    6443: "Kubernetes",
    8443: "HTTPS-Alt",
}

HIGH_RISK_PORTS = {
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    110: "POP3",
    143: "IMAP",
    3389: "RDP",
    8080: "HTTP-Proxy",
}


def classify_port_risk(port: int) -> str:
    """分类端口风险等级"""
    if port in CRITICAL_PORTS:
        return "critical"
    if port in HIGH_RISK_PORTS:
        return "high"
    if port in [80, 443]:
        return "low"
    return "medium"


def _validate_masscan_params(params: Dict[str, Any]) -> tuple[str, int, int]:
    port_range = str(params.get("port_range", "1-65535"))
    if port_range.lower() in {"high-risk", "high_risk", "critical"}:
        port_range = ",".join(str(port) for port in sorted({*CRITICAL_PORTS, *HIGH_RISK_PORTS, 80, 443}))
    rate = int(params.get("rate", 10_000))
    timeout = int(params.get("timeout", 30))
    ports = set()
    try:
        for part in port_range.split(","):
            start, _, end = part.strip().partition("-")
            first = int(start)
            last = int(end or start)
            if not 1 <= first <= last <= 65535:
                raise ValueError
            ports.update(range(first, last + 1))
    except (TypeError, ValueError):
        raise ValueError("port_range 必须是 1-65535 内的端口或范围")
    if not 1 <= rate <= MAX_MASSCAN_RATE:
        raise ValueError(f"rate 必须介于 1 和 {MAX_MASSCAN_RATE}")
    if not 5 <= timeout <= MAX_MASSCAN_TIMEOUT:
        raise ValueError(f"timeout 必须介于 5 和 {MAX_MASSCAN_TIMEOUT} 秒")
    return port_range, rate, timeout


def parse_masscan_output(output: str, target: str) -> List[Dict]:
    """解析 masscan JSON 输出"""
    open_ports = []
    
    try:
        # masscan 输出是 JSON 数组
        results = json.loads(output)
        
        for result in results:
            port = result.get("ports", [{}])[0].get("port", 0)
            proto = result.get("ports", [{}])[0].get("proto", "tcp")
            status = result.get("ports", [{}])[0].get("status", "open")
            service = result.get("ports", [{}])[0].get("service", {}).get("name", "")
            banner = result.get("ports", [{}])[0].get("service", {}).get("banner", "")
            
            if port > 0 and status == "open":
                open_ports.append({
                    "port": port,
                    "protocol": proto,
                    "state": status,
                    "service": service,
                    "banner": banner,
                    "risk_level": classify_port_risk(port),
                    "risk_description": CRITICAL_PORTS.get(port, HIGH_RISK_PORTS.get(port, "")),
                })
    
    except json.JSONDecodeError:
        # 如果不是 JSON，尝试解析 grepable 格式
        for line in output.split('\n'):
            if line.startswith('open'):
                parts = line.split()
                if len(parts) >= 4:
                    port = int(parts[2])
                    proto = parts[1]
                    open_ports.append({
                        "port": port,
                        "protocol": proto,
                        "state": "open",
                        "service": "",
                        "banner": "",
                        "risk_level": classify_port_risk(port),
                        "risk_description": CRITICAL_PORTS.get(port, HIGH_RISK_PORTS.get(port, "")),
                    })
    
    # 按端口号排序
    open_ports.sort(key=lambda x: x["port"])
    
    return open_ports


async def masscan_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 masscan 全端口扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port_range, rate, timeout = _validate_masscan_params(params)
    banner_grab = params.get("banner_grab", False)
    
    # 构建 masscan 命令
    cmd = [
        "masscan",
        target,
        "-p", port_range,
        "--rate", str(rate),
        "-oJ", "-",  # JSON 输出到 stdout
    ]
    
    if banner_grab:
        cmd.append("--banners")
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析结果
        open_ports = parse_masscan_output(output, target)
        
        # 统计
        critical_count = sum(1 for p in open_ports if p["risk_level"] == "critical")
        high_count = sum(1 for p in open_ports if p["risk_level"] == "high")
        scan_completed = process.returncode == 0
        tool_error = None if scan_completed else (
            stderr_output.strip() or output.strip() or "masscan execution failed"
        )
        
        return {
            "tool": "masscan_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "host_status": "up" if open_ports else "unknown",
                "open_ports": open_ports,
                "total_open": len(open_ports),
                "critical_ports": critical_count,
                "high_risk_ports": high_count,
                "scan_completed": scan_completed,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "port_range": port_range,
                "rate": rate,
                "banner_grab": banner_grab,
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "tool": "masscan_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "host_status": "unknown",
                "open_ports": [],
                "total_open": 0,
                "critical_ports": 0,
                "high_risk_ports": 0,
                "timed_out": True,
                "scan_completed": False,
                "tool_error": f"masscan timed out after {timeout}s",
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "port_range": port_range,
                "rate": rate,
                "banner_grab": banner_grab,
                "error": f"masscan timed out after {timeout}s",
            },
        }
    except FileNotFoundError:
        raise ValueError("masscan not installed")
    except Exception as e:
        raise ValueError(f"masscan error: {e}")


async def fping_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 fping 批量存活检测"""
    targets = params.get("targets", [])
    network = params.get("network")
    
    if not targets and not network:
        raise ValueError("Missing required parameter: targets or network")
    
    if network and not targets:
        import ipaddress
        try:
            network_obj = ipaddress.ip_network(network, strict=False)
            if network_obj.num_addresses > MAX_FPING_TARGETS:
                raise ValueError(f"单次批量存活检测最多支持 {MAX_FPING_TARGETS} 个地址")
            targets = [str(ip) for ip in network_obj.hosts()] or [str(network_obj.network_address)]
        except ValueError:
            if "/" in str(network):
                raise ValueError(f"Invalid CIDR network: {network}")
            targets = [str(network)]
    
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets 必须是非空地址列表")
    if len(targets) > MAX_FPING_TARGETS:
        raise ValueError(f"单次批量存活检测最多支持 {MAX_FPING_TARGETS} 个地址")
    cmd = ["fping", "-a", "-q", "-r", "1"]
    cmd.extend(targets)
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        
        # fping 输出存活的 IP 到 stdout
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = stderr.decode("utf-8", errors="replace").strip()
        duration_ms = int((time.time() - start_time) * 1000)
        
        alive_hosts = [line.strip() for line in output.split('\n') if line.strip()]
        scan_completed = process.returncode in (0, 1)
        tool_error = None if scan_completed else (
            stderr_output or "fping execution failed"
        )
        
        return {
            "tool": "fping_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "network": network,
                "total_scanned": len(targets),
                "alive_hosts": alive_hosts,
                "alive_count": len(alive_hosts),
                "scan_completed": scan_completed,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        raise ValueError("fping scan timeout")
    except FileNotFoundError:
        raise ValueError("fping not installed")
    except Exception as e:
        raise ValueError(f"fping error: {e}")


# ============== API 端点 ==============

# 异步任务存储
SCAN_TASKS = {}


@app.get("/")
async def root():
    return {
        "name": "Fast Scanner MCP Server",
        "version": "1.0.0",
        "tools": ["masscan_scan", "fping_scan"],
    }


@app.get("/health")
async def health():
    # 检查 masscan 是否可用
    try:
        process = await asyncio.create_subprocess_exec(
            "masscan", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        masscan_available = True
    except:
        masscan_available = False
    
    # 检查 fping 是否可用
    try:
        process = await asyncio.create_subprocess_exec(
            "fping", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        fping_available = True
    except:
        fping_available = False
    
    return {
        "status": "healthy" if masscan_available else "degraded",
        "tools": ["masscan_scan", "fping_scan"],
        "masscan_available": masscan_available,
        "fping_available": fping_available,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具（同步模式）"""
    tool_name = request.tool
    params = request.params
    
    try:
        if tool_name == "masscan_scan":
            return await masscan_scan(params)
        elif tool_name == "fping_scan":
            return await fping_scan(params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")


async def run_async_masscan(task_id: str, params: Dict[str, Any]):
    """异步执行 masscan 扫描 - 带真实进度更新"""
    target = params.get("target")
    port_range, rate, timeout = _validate_masscan_params(params)
    banner_grab = params.get("banner_grab", False)
    
    # 解析端口范围估算时长
    def parse_port_count(port_range: str) -> int:
        try:
            if '-' in port_range:
                start, end = map(int, port_range.split('-'))
                return end - start + 1
            return 1
        except:
            return 1000
    
    estimated_ports = parse_port_count(port_range)
    # masscan 在 rate=10000 时约 0.0001 秒/端口，给 3 倍余量
    estimated_duration = max(estimated_ports * 0.0003, 5)
    
    cmd = [
        "masscan",
        target,
        "-p", port_range,
        "--rate", str(rate),
        "-oJ", "-",  # JSON 输出到 stdout
    ]
    
    if banner_grab:
        cmd.append("--banners")
    
    start_time = time.time()
    
    try:
        SCAN_TASKS[task_id]["status"] = "running"
        SCAN_TASKS[task_id]["progress"] = 0
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # 基于时间的进度估算
        async def estimate_progress():
            while SCAN_TASKS[task_id]["status"] == "running":
                elapsed = time.time() - start_time
                progress = min(int((elapsed / estimated_duration) * 90), 89)
                SCAN_TASKS[task_id]["progress"] = progress
                await asyncio.sleep(1)
        
        progress_task = asyncio.create_task(estimate_progress())
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        progress_task.cancel()
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = stderr.decode("utf-8", errors="replace").strip()
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析结果
        open_ports = parse_masscan_output(output, target)
        
        critical_count = sum(1 for p in open_ports if p["risk_level"] == "critical")
        high_count = sum(1 for p in open_ports if p["risk_level"] == "high")
        scan_completed = process.returncode == 0
        tool_error = None if scan_completed else (
            stderr_output or output.strip() or "masscan execution failed"
        )
        
        result = {
            "tool": "masscan_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "host_status": "up" if open_ports else "unknown",
                "open_ports": open_ports,
                "total_open": len(open_ports),
                "critical_ports": critical_count,
                "high_risk_ports": high_count,
                "scan_completed": scan_completed,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "port_range": port_range,
                "rate": rate,
                "banner_grab": banner_grab,
                "returncode": process.returncode,
            },
        }
        
        SCAN_TASKS[task_id]["status"] = "completed"
        SCAN_TASKS[task_id]["progress"] = 100
        SCAN_TASKS[task_id]["result"] = result
        
    except asyncio.TimeoutError:
        SCAN_TASKS[task_id]["status"] = "failed"
        SCAN_TASKS[task_id]["error"] = "masscan scan timeout"
    except Exception as e:
        SCAN_TASKS[task_id]["status"] = "failed"
        SCAN_TASKS[task_id]["error"] = str(e)


@app.post("/scan/start")
async def start_scan(request: ExecuteRequest):
    """启动异步扫描任务"""
    import uuid
    
    tool_name = request.tool
    params = request.params
    
    if tool_name != "masscan_scan":
        raise HTTPException(status_code=400, detail="Only masscan_scan supports async")
    
    task_id = str(uuid.uuid4())
    
    SCAN_TASKS[task_id] = {
        "task_id": task_id,
        "tool": tool_name,
        "params": params,
        "status": "running",
        "progress": 0,
        "start_time": time.time(),
        "result": None,
        "error": None,
    }
    
    asyncio.create_task(run_async_masscan(task_id, params))
    
    return {
        "task_id": task_id,
        "status": "running",
        "message": "Scan started",
    }


@app.get("/scan/{task_id}/progress")
async def get_scan_progress(task_id: str):
    """查询扫描进度"""
    if task_id not in SCAN_TASKS:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    task = SCAN_TASKS[task_id]
    
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "elapsed_ms": int((time.time() - task["start_time"]) * 1000) if task["start_time"] else 0,
        "error": task["error"],
    }


@app.get("/scan/{task_id}/result")
async def get_scan_result(task_id: str):
    """获取扫描结果"""
    if task_id not in SCAN_TASKS:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    task = SCAN_TASKS[task_id]
    
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Task not completed. Status: {task['status']}")
    
    return task["result"]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8011)
