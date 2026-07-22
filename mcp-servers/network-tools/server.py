"""
Network Tools MCP Server - 网络设备检测工具集
包含 snmpwalk、onesixtyone 等网络设备检测工具
"""

import asyncio
import contextlib
import socket
import time
import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Network Tools MCP Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def clean_snmp_error(value: str) -> str:
    return "\n".join(
        line for line in (value or "").splitlines()
        if line.strip() and not line.lower().startswith("created directory:")
    ).strip()


class ExecuteRequest(BaseModel):
    tool: str
    params: Dict[str, Any]


SCAN_TASKS: Dict[str, Dict[str, Any]] = {}


async def _communicate(process, timeout: int, continuous: bool):
    if continuous:
        return await process.communicate()
    return await asyncio.wait_for(process.communicate(), timeout=timeout)


async def _terminate_process(process) -> None:
    if not process or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=3)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


# ============== SNMP Walk ==============

async def snmp_walk(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """执行 SNMP walk 获取网络设备信息"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    community = params.get("community", "public")
    version = params.get("version", "2c")
    oid = params.get("oid", "1.3.6.1.2.1")  # 默认 MIB-2
    timeout = params.get("timeout", 60)
    
    cmd = [
        "snmpwalk",
        "-v", version,
        "-c", community,
        target,
        oid,
    ]
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process_callback:
            process_callback(process)
        stdout, stderr = await _communicate(process, timeout, continuous and "timeout" not in params)
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = clean_snmp_error(stderr.decode("utf-8", errors="replace"))
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析 SNMP 输出
        results = []
        for line in output.split('\n'):
            if '=' in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    oid_path = parts[0].strip()
                    value = parts[1].strip()
                    results.append({
                        "oid": oid_path,
                        "value": value,
                    })
        
        # 检查是否成功
        success = len(results) > 0 and "Timeout" not in stderr_output
        
        return {
            "tool": "snmp_walk",
            "version": "1.0",
            "status": "success" if success else "failed",
            "data": {
                "target": target,
                "community": community,
                "version": version,
                "oid": oid,
                "results": results[:100],  # 限制返回数量
                "total_results": len(results),
                "success": success,
                "scan_completed": success,
                "tool_error": None if success else (
                    stderr_output.strip() or "未收到 SNMP 响应，无法完成 SNMP 信息枚举"
                ),
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "error": stderr_output if not success else None,
            },
        }
    
    except asyncio.TimeoutError:
        raise ValueError("snmpwalk timeout")
    except FileNotFoundError:
        raise ValueError("snmpwalk not installed")
    except Exception as e:
        raise ValueError(f"snmpwalk error: {e}")


# ============== SNMP Brute Force ==============

async def snmp_bruteforce(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """执行 SNMP 团体字爆破"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    wordlist = params.get("wordlist", "/usr/share/wordlists/snmp-common.txt")
    timeout = params.get("timeout", 120)
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(target, None, family=socket.AF_INET)
        resolved_target = addresses[0][4][0]
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve SNMP target {target}: {exc}") from exc
    
    cmd = [
        "onesixtyone",
        "-c", wordlist,
        resolved_target,
    ]
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process_callback:
            process_callback(process)
        stdout, stderr = await _communicate(process, timeout, continuous and "timeout" not in params)
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = clean_snmp_error(stderr.decode("utf-8", errors="replace"))
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析 onesixtyone 输出
        found = []
        for line in output.split('\n'):
            if line.strip():
                # 格式: 192.168.1.1 [public] Linux...
                match = re.match(r'([^\s]+)\s+\[([^\]]+)\]\s*(.*)', line)
                if match:
                    found.append({
                        "target": match.group(1),
                        "community": match.group(2),
                        "description": match.group(3),
                    })

        scan_completed = bool(found)
        tool_error = None if scan_completed else (
            stderr_output or "未收到 SNMP 响应，无法确认未使用弱团体字"
        )
        
        return {
            "tool": "snmp_bruteforce",
            "version": "1.0",
            "status": "success" if scan_completed else "failed",
            "data": {
                "target": target,
                "resolved_target": resolved_target,
                "found": found,
                "total_found": len(found),
                "scan_completed": scan_completed,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "wordlist": wordlist,
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        raise ValueError("snmp bruteforce timeout")
    except FileNotFoundError:
        raise ValueError("onesixtyone not installed")
    except Exception as e:
        raise ValueError(f"snmp bruteforce error: {e}")


# ============== SNMP Get ==============

async def snmp_get(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """执行 SNMP get 获取单个 OID 值"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    oid = params.get("oid")
    if not oid:
        raise ValueError("Missing required parameter: oid")
    
    community = params.get("community", "public")
    version = params.get("version", "2c")
    timeout = params.get("timeout", 30)
    
    cmd = [
        "snmpget",
        "-v", version,
        "-c", community,
        target,
        oid,
    ]
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process_callback:
            process_callback(process)
        stdout, stderr = await _communicate(process, timeout, continuous and "timeout" not in params)
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = clean_snmp_error(stderr.decode("utf-8", errors="replace"))
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析输出
        value = None
        if '=' in output:
            parts = output.split('=', 1)
            if len(parts) == 2:
                value = parts[1].strip()

        scan_completed = value is not None and "timeout" not in stderr_output.lower()
        tool_error = None if scan_completed else (
            stderr_output or "未收到 SNMP 响应，无法读取指定 OID"
        )
        
        return {
            "tool": "snmp_get",
            "version": "1.0",
            "status": "success" if scan_completed else "failed",
            "data": {
                "target": target,
                "oid": oid,
                "community": community,
                "value": value,
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
        raise ValueError("snmpget timeout")
    except FileNotFoundError:
        raise ValueError("snmpget not installed")
    except Exception as e:
        raise ValueError(f"snmpget error: {e}")


# ============== API 端点 ==============

@app.get("/")
async def root():
    return {
        "name": "Network Tools MCP Server",
        "version": "1.0.0",
        "tools": ["snmp_walk", "snmp_bruteforce", "snmp_get"],
    }


@app.get("/health")
async def health():
    tools_status = {}
    
    for tool in ["snmpwalk", "onesixtyone", "snmpget"]:
        try:
            process = await asyncio.create_subprocess_exec(
                tool, "--version" if tool != "onesixtyone" else "-h",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=5)
            tools_status[tool] = True
        except:
            tools_status[tool] = False
    
    return {
        "status": "healthy" if any(tools_status.values()) else "degraded",
        "tools": ["snmp_walk", "snmp_bruteforce", "snmp_get"],
        "tools_available": tools_status,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params
    
    tool_map = {
        "snmp_walk": snmp_walk,
        "snmp_bruteforce": snmp_bruteforce,
        "snmp_get": snmp_get,
    }
    
    if tool_name not in tool_map:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    
    try:
        return await tool_map[tool_name](params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_async_network_tool(task_id: str, tool_name: str, params: Dict[str, Any]) -> None:
    labels = {
        "snmp_walk": "SNMP 信息枚举",
        "snmp_bruteforce": "SNMP 团体字检测",
        "snmp_get": "SNMP OID 检测",
    }
    runners = {"snmp_walk": snmp_walk, "snmp_bruteforce": snmp_bruteforce, "snmp_get": snmp_get}
    task = SCAN_TASKS[task_id]
    label = labels[tool_name]
    task.update(status="running", progress=0, heartbeat_at=datetime.utcnow().isoformat(), elapsed_seconds=0)

    async def heartbeat():
        started = time.time()
        while task["status"] == "running":
            elapsed = int(time.time() - started)
            task.update(
                progress=min(95, 5 + elapsed // 2),
                elapsed_seconds=elapsed,
                heartbeat_at=datetime.utcnow().isoformat(),
                message=f"{label}正在执行，已运行 {elapsed} 秒",
            )
            await asyncio.sleep(2)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        task["result"] = await runners[tool_name](
            params,
            process_callback=lambda process: task.update(process=process),
            continuous=True,
        )
        task.update(status="completed", progress=100, message=f"{label}执行完成")
    except asyncio.CancelledError:
        task.update(status="cancelled", error="用户已停止检测", message=f"{label}已停止")
        raise
    except Exception as exc:
        task.update(status="failed", error=str(exc), message=f"{label}执行失败")
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


@app.post("/scan/start")
async def start_scan(request: ExecuteRequest):
    if request.tool not in {"snmp_walk", "snmp_bruteforce", "snmp_get"}:
        raise HTTPException(status_code=400, detail=f"Tool {request.tool} does not support async mode")
    task_id = str(uuid.uuid4())
    SCAN_TASKS[task_id] = {
        "task_id": task_id, "tool": request.tool, "status": "pending",
        "progress": 0, "result": None, "error": None,
    }
    SCAN_TASKS[task_id]["handle"] = asyncio.create_task(
        _run_async_network_tool(task_id, request.tool, request.params)
    )
    return {"task_id": task_id, "status": "running", "message": "Scan started"}


@app.get("/scan/{task_id}/progress")
async def get_scan_progress(task_id: str):
    task = SCAN_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {
        "task_id": task_id, "status": task["status"], "progress": task.get("progress", 0),
        "message": task.get("message"), "elapsed_seconds": task.get("elapsed_seconds", 0),
        "heartbeat_at": task.get("heartbeat_at"),
        "alive": task["status"] == "running" and (
            task.get("process") is None or task["process"].returncode is None
        ),
        "error": task.get("error"),
    }


@app.get("/scan/{task_id}/result")
async def get_scan_result(task_id: str):
    task = SCAN_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Task not completed. Status: {task['status']}")
    return task["result"]


@app.post("/scan/{task_id}/cancel")
async def cancel_scan(task_id: str):
    task = SCAN_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    if task["status"] in {"completed", "failed", "cancelled"}:
        return {"task_id": task_id, "status": task["status"]}
    task.update(status="cancelled", error="用户已停止检测")
    handle = task.get("handle")
    if handle:
        handle.cancel()
    await _terminate_process(task.get("process"))
    if handle:
        with contextlib.suppress(asyncio.CancelledError):
            await handle
    return {"task_id": task_id, "status": "cancelled"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8013)
