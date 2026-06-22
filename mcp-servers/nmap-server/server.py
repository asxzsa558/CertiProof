"""
Nmap MCP Server - 端口扫描工具
使用 nmap 进行端口扫描，返回标准化 JSON 格式
支持异步扫描和实时进度查询
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
import time
import asyncio
import uuid
import re

app = FastAPI(title="Nmap MCP Server", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
}

HIGH_RISK_PORTS = {
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    110: "POP3",
    143: "IMAP",
    3389: "RDP",
    8080: "HTTP-Proxy",
    8443: "HTTPS-Alt",
}

# 异步任务存储
SCAN_TASKS: Dict[str, Dict[str, Any]] = {}


class ExecuteRequest(BaseModel):
    """执行请求"""
    tool: str
    params: Dict[str, Any]


class PortInfo(BaseModel):
    """端口信息"""
    port: int
    protocol: str
    state: str
    service: Optional[str] = None
    version: Optional[str] = None
    risk_level: str = "info"


class NmapScanResult(BaseModel):
    """nmap 扫描结果"""
    target: str
    host_status: str
    open_ports: List[PortInfo] = []
    os_guess: Optional[str] = None


def classify_port_risk(port: int) -> str:
    """分类端口风险等级"""
    if port in CRITICAL_PORTS:
        return "critical"
    if port in HIGH_RISK_PORTS:
        return "high"
    if port in [80, 443]:
        return "low"
    return "medium"


def parse_nmap_xml(xml_content: str, target: str) -> NmapScanResult:
    """解析 nmap XML 输出"""
    result = NmapScanResult(
        target=target,
        host_status="unknown",
        open_ports=[],
    )
    
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse nmap XML: {e}")
    
    for host in root.findall(".//host"):
        # 主机状态
        status_elem = host.find("status")
        if status_elem is not None:
            result.host_status = status_elem.get("state", "unknown")
        
        # 端口信息
        for port_elem in host.findall(".//port"):
            port_id = int(port_elem.get("portid", 0))
            protocol = port_elem.get("protocol", "tcp")
            
            state_elem = port_elem.find("state")
            state = state_elem.get("state", "unknown") if state_elem is not None else "unknown"
            
            if state != "open":
                continue
            
            # 服务信息
            service = None
            version = None
            service_elem = port_elem.find("service")
            if service_elem is not None:
                service = service_elem.get("name")
                product = service_elem.get("product", "")
                ver = service_elem.get("version", "")
                if product or ver:
                    version = f"{product} {ver}".strip()
            
            # 风险等级
            risk_level = classify_port_risk(port_id)
            
            result.open_ports.append(PortInfo(
                port=port_id,
                protocol=protocol,
                state=state,
                service=service,
                version=version,
                risk_level=risk_level,
            ))
        
        # OS 识别
        for os_elem in host.findall(".//osmatch"):
            result.os_guess = os_elem.get("name")
            break
    
    return result


def parse_port_range(port_range: str) -> int:
    """解析端口范围，返回总端口数"""
    total = 0
    for part in port_range.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            total += int(end) - int(start) + 1
        else:
            total += 1
    return total


async def run_async_scan(task_id: str, params: Dict[str, Any]):
    """异步执行 nmap 扫描"""
    target = params.get("target")
    if not target:
        SCAN_TASKS[task_id]["status"] = "failed"
        SCAN_TASKS[task_id]["error"] = "Missing required parameter: target"
        return
    
    port_range = params.get("port_range", "1-1000")
    service_detection = params.get("service_detection", True)
    os_detection = params.get("os_detection", False)
    
    # 计算总端口数
    total_ports = parse_port_range(port_range)
    SCAN_TASKS[task_id]["total_ports"] = total_ports
    
    # 构建 nmap 命令 - 使用 grepable 输出以便实时解析
    cmd = ["nmap", "-sT", "-oG", "-"]
    
    if service_detection:
        cmd.append("-sV")
    
    if os_detection:
        cmd.append("-O")
    
    cmd.extend(["-p", port_range, target])
    
    start_time = time.time()
    SCAN_TASKS[task_id]["start_time"] = start_time
    
    try:
        # 使用 Popen 异步执行
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # 实时读取输出
        scanned_ports = 0
        open_ports = []
        
        # 读取 stdout (grepable 格式)
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            
            line_str = line.decode("utf-8", errors="replace").strip()
            
            # 解析 grepable 输出
            # 格式: Host: 127.0.0.1 (localhost)  Ports: 22/open/tcp//ssh//OpenSSH 8.9p1 Ubuntu 3ubuntu0.1 (Ubuntu 22.04; Linux; 2023-05-05)/, 80/open/tcp//http//nginx 1.18.0/
            if line_str.startswith("Host:") and "Ports:" in line_str:
                ports_part = line_str.split("Ports:", 1)[1]
                for port_entry in ports_part.split(","):
                    port_entry = port_entry.strip()
                    if "/open/" in port_entry:
                        parts = port_entry.split("/")
                        if len(parts) >= 5:
                            port_num = int(parts[0])
                            state = parts[1]
                            protocol = parts[2]
                            service = parts[4] if len(parts) > 4 else None
                            version = parts[6] if len(parts) > 6 else None
                            
                            risk_level = classify_port_risk(port_num)
                            open_ports.append({
                                "port": port_num,
                                "protocol": protocol,
                                "state": state,
                                "service": service,
                                "version": version,
                                "risk_level": risk_level,
                            })
                            scanned_ports += 1
            
            # 更新进度
            SCAN_TASKS[task_id]["scanned_ports"] = scanned_ports
            SCAN_TASKS[task_id]["open_ports"] = open_ports
            if total_ports > 0:
                SCAN_TASKS[task_id]["progress"] = min(95, int((scanned_ports / total_ports) * 100))
        
        # 等待进程结束
        await process.wait()
        
        # 获取 stderr
        stderr = await process.stderr.read()
        stderr_str = stderr.decode("utf-8", errors="replace")
        
        if process.returncode != 0:
            SCAN_TASKS[task_id]["status"] = "failed"
            SCAN_TASKS[task_id]["error"] = f"nmap error: {stderr_str}"
            return
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 完成
        SCAN_TASKS[task_id]["status"] = "completed"
        SCAN_TASKS[task_id]["progress"] = 100
        SCAN_TASKS[task_id]["duration_ms"] = duration_ms
        SCAN_TASKS[task_id]["result"] = {
            "tool": "nmap_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "host_status": "up",
                "open_ports": open_ports,
                "os_guess": None,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "port_range": port_range,
                "total_ports": total_ports,
            },
        }
    
    except asyncio.TimeoutError:
        SCAN_TASKS[task_id]["status"] = "failed"
        SCAN_TASKS[task_id]["error"] = "nmap scan timeout"
    except Exception as e:
        SCAN_TASKS[task_id]["status"] = "failed"
        SCAN_TASKS[task_id]["error"] = f"nmap scan error: {e}"


async def nmap_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 nmap 扫描（同步兼容模式）"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port_range = params.get("port_range", "1-1000")
    service_detection = params.get("service_detection", True)
    os_detection = params.get("os_detection", False)
    
    # 构建 nmap 命令
    cmd = ["nmap", "-oX", "-", "-sT"]  # TCP connect scan, XML output
    
    if service_detection:
        cmd.append("-sV")
    
    if os_detection:
        cmd.append("-O")
    
    cmd.extend(["-p", port_range, target])
    
    # 执行 nmap
    start_time = time.time()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        if result.returncode != 0:
            raise ValueError(f"nmap error: {result.stderr}")
        
        # 解析 XML
        parsed = parse_nmap_xml(result.stdout, target)
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 返回标准格式
        return {
            "tool": "nmap_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": parsed.target,
                "host_status": parsed.host_status,
                "open_ports": [p.model_dump() for p in parsed.open_ports],
                "os_guess": parsed.os_guess,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "port_range": port_range,
            },
        }
    
    except subprocess.TimeoutExpired:
        raise ValueError("nmap scan timeout")
    except Exception as e:
        raise ValueError(f"nmap scan error: {e}")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "Nmap MCP Server",
        "version": "1.0.0",
        "tools": ["nmap_scan", "port_scan"],
    }


@app.get("/health")
async def health():
    """健康检查"""
    # 检查 nmap 是否可用
    try:
        result = subprocess.run(
            ["nmap", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        nmap_available = result.returncode == 0
    except:
        nmap_available = False
    
    return {
        "status": "healthy" if nmap_available else "degraded",
        "tools": ["nmap_scan", "port_scan"],
        "nmap_available": nmap_available,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具（同步模式）"""
    tool_name = request.tool
    params = request.params
    
    if tool_name in ["nmap_scan", "port_scan"]:
        return await nmap_scan(params)
    
    raise HTTPException(
        status_code=404,
        detail=f"Unknown tool: {tool_name}"
    )


@app.post("/scan/start")
async def start_scan(request: ExecuteRequest):
    """
    启动异步扫描任务
    返回 task_id 用于查询进度
    """
    tool_name = request.tool
    params = request.params
    
    if tool_name not in ["nmap_scan", "port_scan"]:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown tool: {tool_name}"
        )
    
    task_id = str(uuid.uuid4())
    
    # 初始化任务状态
    SCAN_TASKS[task_id] = {
        "task_id": task_id,
        "tool": tool_name,
        "params": params,
        "status": "running",
        "progress": 0,
        "total_ports": 0,
        "scanned_ports": 0,
        "open_ports": [],
        "start_time": time.time(),
        "duration_ms": None,
        "result": None,
        "error": None,
    }
    
    # 启动异步任务
    asyncio.create_task(run_async_scan(task_id, params))
    
    return {
        "task_id": task_id,
        "status": "running",
        "message": "Scan started",
    }


@app.get("/scan/{task_id}/progress")
async def get_scan_progress(task_id: str):
    """
    查询扫描进度
    """
    if task_id not in SCAN_TASKS:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found: {task_id}"
        )
    
    task = SCAN_TASKS[task_id]
    
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "total_ports": task["total_ports"],
        "scanned_ports": task["scanned_ports"],
        "open_ports_found": len(task["open_ports"]),
        "open_ports": task["open_ports"],
        "elapsed_ms": int((time.time() - task["start_time"]) * 1000) if task["start_time"] else 0,
        "duration_ms": task["duration_ms"],
        "error": task["error"],
    }


@app.get("/scan/{task_id}/result")
async def get_scan_result(task_id: str):
    """
    获取扫描结果
    """
    if task_id not in SCAN_TASKS:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found: {task_id}"
        )
    
    task = SCAN_TASKS[task_id]
    
    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed. Status: {task['status']}"
        )
    
    return task["result"]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
