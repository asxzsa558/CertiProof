"""
Security Tools MCP Server - 统一安全工具服务
合并 nmap、testssl、nuclei、hydra 到一个容器
"""

import asyncio
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Security Tools MCP Server", version="1.0.0")

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


# ============== Nmap 工具 ==============

async def nmap_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 nmap 端口扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port_range = params.get("port_range", "1-65535")
    # 全端口扫描时禁用服务检测以提高速度
    service_detection = params.get("service_detection", True)
    if port_range == "1-65535":
        service_detection = False
    
    cmd = ["nmap", "-sS", "-T5", "-oG", "-", "--min-rate", "10000"]
    if service_detection:
        cmd.append("-sV")
    cmd.extend(["-p", port_range, target])
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        
        output = stdout.decode("utf-8", errors="replace")
        open_ports = []
        host_status = "unknown"
        
        for line in output.split("\n"):
            if line.startswith("Host:") and "Status:" in line:
                if "Up" in line:
                    host_status = "up"
                elif "Down" in line:
                    host_status = "down"
            if line.startswith("Host:") and "Ports:" in line:
                ports_part = line.split("Ports:", 1)[1]
                for port_entry in ports_part.split(","):
                    port_entry = port_entry.strip()
                    if "/open/" in port_entry:
                        parts = port_entry.split("/")
                        if len(parts) >= 5:
                            open_ports.append({
                                "port": int(parts[0]),
                                "protocol": parts[2],
                                "state": parts[1],
                                "service": parts[4] if len(parts) > 4 else None,
                            })
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "tool": "nmap_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "host_status": host_status,
                "open_ports": open_ports,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "port_range": port_range,
            },
        }
    except asyncio.TimeoutError:
        raise ValueError("nmap scan timeout")
    except Exception as e:
        raise ValueError(f"nmap scan error: {e}")


# ============== Ping 工具 ==============

async def ping_host(params: Dict[str, Any]) -> Dict[str, Any]:
    """Ping 主机检测可达性"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    count = params.get("count", 3)
    timeout = params.get("timeout", 2)
    
    cmd = ["ping", "-c", str(count), "-W", str(timeout), target]
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        
        output = stdout.decode("utf-8", errors="replace")
        
        # 解析 ping 结果
        reachable = process.returncode == 0
        packet_loss = 100
        avg_latency = None
        
        # 解析 packet loss
        for line in output.split("\n"):
            if "packet loss" in line:
                # 格式: "3 packets transmitted, 3 received, 0% packet loss"
                parts = line.split(",")
                for part in parts:
                    if "packet loss" in part:
                        loss_str = part.strip().split()[0]
                        packet_loss = int(loss_str.replace("%", ""))
            
            # 解析 avg latency
            if "min/avg/max" in line:
                # 格式: "rtt min/avg/max/mdev = 10.5/10.8/11.2/0.3 ms"
                parts = line.split("=")
                if len(parts) > 1:
                    values = parts[1].strip().split("/")
                    if len(values) >= 2:
                        avg_latency = float(values[1])
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "tool": "ping_host",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "reachable": reachable,
                "packet_loss": packet_loss,
                "avg_latency_ms": avg_latency,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "ping_time": datetime.utcnow().isoformat(),
                "count": count,
            },
        }
    except asyncio.TimeoutError:
        raise ValueError("ping timeout")
    except Exception as e:
        raise ValueError(f"ping error: {e}")


# ============== TestSSL 工具 ==============

async def testssl_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 testssl.sh SSL/TLS 检测"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 443)
    
    cmd = [
        "/testssl/testssl.sh",
        "--json",
        "--warnings", "off",
        f"{target}:{port}",
    ]
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        
        output = stdout.decode("utf-8", errors="replace")
        
        # 解析 JSON 输出 - testssl.sh 输出多行 JSON
        tls_version = None
        certificate = {}
        issues = []
        vulnerabilities = []
        
        # 尝试解析每一行 JSON
        for line in output.strip().split('\n'):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    item_id = data.get("id", "")
                    finding = data.get("finding", "")
                    severity = data.get("severity", "")
                    
                    # 提取 TLS 版本
                    if "protocol" in item_id.lower() or "tls" in item_id.lower():
                        if finding and not tls_version:
                            tls_version = finding
                    
                    # 提取证书信息
                    elif "cert" in item_id.lower():
                        if "subject" in item_id.lower():
                            certificate["subject"] = finding
                        elif "issuer" in item_id.lower():
                            certificate["issuer"] = finding
                        elif "expiration" in item_id.lower() or "valid" in item_id.lower():
                            certificate["validity"] = finding
                    
                    # 提取问题
                    elif severity in ["WARN", "MEDIUM"]:
                        if finding:
                            issues.append(f"{item_id}: {finding}")
                    
                    # 提取漏洞
                    elif severity in ["HIGH", "CRITICAL"]:
                        vulnerabilities.append({
                            "id": item_id,
                            "severity": severity,
                            "finding": finding,
                        })
            except json.JSONDecodeError:
                continue
        
        # 如果没有解析到任何信息，添加提示
        if not tls_version and not certificate and not issues:
            issues.append("Unable to parse detailed results, but scan completed successfully")
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "tool": "testssl_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "tls_version": tls_version,
                "certificate": certificate if certificate else None,
                "issues": issues,
                "vulnerabilities": vulnerabilities,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
            },
        }
    except asyncio.TimeoutError:
        raise ValueError("testssl scan timeout")
    except Exception as e:
        raise ValueError(f"testssl scan error: {e}")


# ============== Nuclei 工具 ==============

async def nuclei_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 nuclei 漏洞扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    templates = params.get("templates")
    severity = params.get("severity")
    
    cmd = ["nuclei", "-target", target, "-jsonl", "-silent"]
    
    if templates:
        cmd.extend(["-tags", templates])
    if severity:
        cmd.extend(["-severity", severity])
    
    cmd.extend(["-timeout", "30", "-retries", "2"])
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        
        output = stdout.decode("utf-8", errors="replace")
        findings = []
        
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "template":
                    findings.append({
                        "template_id": data.get("template-id"),
                        "name": data.get("info", {}).get("name"),
                        "severity": data.get("info", {}).get("severity"),
                        "host": data.get("host"),
                    })
            except json.JSONDecodeError:
                continue
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "tool": "nuclei_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "findings": findings,
                "total_findings": len(findings),
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
            },
        }
    except asyncio.TimeoutError:
        raise ValueError("nuclei scan timeout")
    except Exception as e:
        raise ValueError(f"nuclei scan error: {e}")


# ============== Hydra 工具 ==============

async def hydra_bruteforce(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 hydra 暴力破解"""
    target = params.get("target")
    service = params.get("service", "ssh")
    port = params.get("port", 22)
    
    cmd = [
        "hydra",
        "-l", "admin",
        "-p", "admin",
        "-s", str(port),
        target,
        service,
    ]
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        
        output = stdout.decode("utf-8", errors="replace")
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "tool": "hydra_bruteforce",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "service": service,
                "port": port,
                "found": [],
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
            },
        }
    except asyncio.TimeoutError:
        raise ValueError("hydra scan timeout")
    except Exception as e:
        raise ValueError(f"hydra scan error: {e}")


# ============== API 端点 ==============

# 异步任务存储
SCAN_TASKS = {}

@app.get("/")
async def root():
    return {
        "name": "Security Tools MCP Server",
        "version": "1.0.0",
        "tools": ["nmap_scan", "testssl_scan", "nuclei_scan", "hydra_bruteforce", "ping_host"],
    }


@app.get("/health")
async def health():
    """健康检查"""
    tools_status = {}
    
    # 检查 nmap
    try:
        result = subprocess.run(["nmap", "--version"], capture_output=True, timeout=5)
        tools_status["nmap"] = result.returncode == 0
    except:
        tools_status["nmap"] = False
    
    # 检查 testssl
    try:
        result = subprocess.run(["/testssl/testssl.sh", "--version"], capture_output=True, timeout=5)
        tools_status["testssl"] = result.returncode == 0
    except:
        tools_status["testssl"] = False
    
    # 检查 nuclei
    try:
        result = subprocess.run(["nuclei", "-version"], capture_output=True, timeout=5)
        tools_status["nuclei"] = result.returncode == 0
    except:
        tools_status["nuclei"] = False
    
    # 检查 hydra
    try:
        result = subprocess.run(["hydra", "-h"], capture_output=True, timeout=5)
        tools_status["hydra"] = True  # hydra 返回非 0 但可用
    except:
        tools_status["hydra"] = False
    
    all_available = all(tools_status.values())
    
    return {
        "status": "healthy" if all_available else "degraded",
        "tools": ["nmap_scan", "testssl_scan", "nuclei_scan", "hydra_bruteforce"],
        "tools_status": tools_status,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params
    
    if tool_name == "nmap_scan":
        return await nmap_scan(params)
    elif tool_name == "testssl_scan":
        return await testssl_scan(params)
    elif tool_name == "nuclei_scan":
        return await nuclei_scan(params)
    elif tool_name == "hydra_bruteforce":
        return await hydra_bruteforce(params)
    elif tool_name == "ping_host":
        return await ping_host(params)
    else:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")


# ============== 异步扫描支持 ==============

import uuid

async def run_async_nmap(task_id: str, params: Dict[str, Any]):
    """异步执行 nmap 扫描"""
    try:
        SCAN_TASKS[task_id]["status"] = "running"
        result = await nmap_scan(params)
        SCAN_TASKS[task_id]["status"] = "completed"
        SCAN_TASKS[task_id]["result"] = result
    except Exception as e:
        SCAN_TASKS[task_id]["status"] = "failed"
        SCAN_TASKS[task_id]["error"] = str(e)


@app.post("/scan/start")
async def start_scan(request: ExecuteRequest):
    """启动异步扫描"""
    tool_name = request.tool
    params = request.params
    
    if tool_name != "nmap_scan":
        raise HTTPException(status_code=400, detail="Only nmap_scan supports async mode")
    
    task_id = str(uuid.uuid4())
    SCAN_TASKS[task_id] = {
        "task_id": task_id,
        "tool": tool_name,
        "params": params,
        "status": "pending",
        "result": None,
        "error": None,
    }
    
    # 启动异步任务
    asyncio.create_task(run_async_nmap(task_id, params))
    
    return {
        "task_id": task_id,
        "status": "started",
        "message": "Scan started",
    }


@app.get("/scan/{task_id}/progress")
async def get_scan_progress(task_id: str):
    """获取扫描进度"""
    if task_id not in SCAN_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = SCAN_TASKS[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": 100 if task["status"] == "completed" else 0,
    }


@app.get("/scan/{task_id}/result")
async def get_scan_result(task_id: str):
    """获取扫描结果"""
    if task_id not in SCAN_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = SCAN_TASKS[task_id]
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not completed yet")
    
    return task["result"]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
