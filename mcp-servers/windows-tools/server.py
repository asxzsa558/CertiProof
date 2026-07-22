"""
Windows Tools MCP Server - Windows/AD 安全检测工具集
使用 impacket 实现 SMB/Windows 安全检测
"""

import asyncio
import contextlib
import time
import re
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Windows Tools MCP Server", version="3.0.0")

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


def command_state(returncode: int, output: str, has_data: bool) -> tuple[bool, Optional[str]]:
    message = (output or "").strip()
    connection_error = any(token in message.lower() for token in (
        "connection refused", "connection error", "timed out", "no route to host",
    ))
    if has_data:
        return True, message or None
    if returncode == 0 and not connection_error:
        return True, None
    return False, message or f"tool exited with code {returncode}"


# ============== Impacket SAMR Dump (用户枚举) ==============

async def enum4linux_scan(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """使用 impacket samrdump 进行 Windows 用户/组枚举"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    username = params.get("username", "")
    password = params.get("password", "")
    timeout = params.get("timeout", 120)
    
    # 构建 impacket samrdump 命令
    if username and password:
        cred = f"{username}:{password}@{target}"
        cmd = ["samrdump.py", cred]
    else:
        cred = f"guest@{target}"
        cmd = ["samrdump.py", "-no-pass", cred]
    
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
        stderr_output = stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析 samrdump 输出
        result = {
            "users": [],
            "groups": [],
        }
        
        for line in output.split('\n'):
            # 解析用户信息
            if "Found user:" in line:
                match = re.search(r'Found user:\s*(\S+)', line)
                if match:
                    result["users"].append({"name": match.group(1)})
            
            # 解析用户账户信息
            if "|" in line and not line.startswith("Found"):
                parts = line.split("|")
                if len(parts) >= 2:
                    user_info = {
                        "name": parts[0].strip(),
                        "rid": parts[1].strip() if len(parts) > 1 else "",
                    }
                    if user_info["name"] and user_info["name"] not in [u.get("name") for u in result["users"]]:
                        result["users"].append(user_info)
        scan_completed, tool_error = command_state(
            process.returncode,
            f"{stderr_output}\n{output}",
            bool(result["users"] or result["groups"]),
        )
        
        return {
            "tool": "enum4linux_scan",
            "version": "3.0",
            "status": "success",
            "data": {
                "target": target,
                "scan_type": "users",
                "result": result,
                "raw_output": output[:5000],
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
        raise ValueError("enum4linux timeout")
    except Exception as e:
        raise ValueError(f"enum4linux error: {e}")


# ============== Impacket SMB Client (共享枚举) ==============

async def smb_enum(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """使用 impacket smbclient 进行 SMB 共享枚举"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    username = params.get("username", "guest")
    password = params.get("password", "")
    timeout = params.get("timeout", 60)
    
    # 构建 impacket smbclient 命令
    if username and password:
        cred = f"{username}:{password}@{target}"
        auth_args = []
    else:
        cred = f"guest@{target}"
        auth_args = ["-no-pass"]
    input_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt")
    input_file.write("shares\nexit\n")
    input_file.close()
    cmd = ["smbclient.py", *auth_args, cred, "-inputfile", input_file.name]
    
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
        stderr_output = stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析共享列表
        shares = []
        in_shares = False
        for line in output.split('\n'):
            if "share" in line.lower() and "type" in line.lower():
                in_shares = True
                continue
            if in_shares and line.strip():
                parts = line.split()
                if len(parts) >= 2:
                    shares.append({
                        "name": parts[0],
                        "type": parts[1] if len(parts) > 1 else "Unknown",
                        "comment": " ".join(parts[2:]) if len(parts) > 2 else "",
                    })
        scan_completed, tool_error = command_state(
            process.returncode, f"{stderr_output}\n{output}", bool(shares)
        )
        
        return {
            "tool": "smb_enum",
            "version": "3.0",
            "status": "success",
            "data": {
                "target": target,
                "shares": shares,
                "total_shares": len(shares),
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
        raise ValueError("smbclient timeout")
    except Exception as e:
        raise ValueError(f"smbclient error: {e}")
    finally:
        if os.path.exists(input_file.name):
            os.remove(input_file.name)


# ============== Impacket Lookupsid (SID 枚举) ==============

async def crackmapexec_scan(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """使用 impacket lookupsid 进行 SID/用户枚举"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    username = params.get("username", "")
    password = params.get("password", "")
    timeout = params.get("timeout", 120)
    
    # 构建 impacket lookupsid 命令
    if username and password:
        cred = f"{username}:{password}@{target}"
        cmd = ["lookupsid.py", cred]
    else:
        cred = f"guest@{target}"
        cmd = ["lookupsid.py", "-no-pass", cred]
    
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
        stderr_output = stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析 SID 输出
        result = {
            "users": [],
            "groups": [],
            "sids": [],
        }
        
        for line in output.split('\n'):
            if "SID" in line or "User" in line or "Group" in line:
                # 解析 SID 信息
                sid_match = re.search(r'(S-\d-\d+-[\d-]+)', line)
                name_match = re.search(r'(\w+\\\w+)', line)
                
                if sid_match:
                    sid_info = {
                        "sid": sid_match.group(1),
                        "name": name_match.group(1) if name_match else "",
                        "type": "User" if "User" in line else "Group" if "Group" in line else "Unknown",
                    }
                    result["sids"].append(sid_info)
                    
                    # 分类到 users 或 groups
                    if sid_info["type"] == "User" and sid_info["name"]:
                        result["users"].append({"name": sid_info["name"].split("\\")[-1]})
                    elif sid_info["type"] == "Group" and sid_info["name"]:
                        result["groups"].append({"name": sid_info["name"].split("\\")[-1]})
        scan_completed, tool_error = command_state(
            process.returncode,
            f"{stderr_output}\n{output}",
            bool(result["users"] or result["groups"] or result["sids"]),
        )
        
        return {
            "tool": "crackmapexec_scan",
            "version": "3.0",
            "status": "success",
            "data": {
                "target": target,
                "scan_type": "sid_enum",
                "result": result,
                "raw_output": output[:5000],
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
        raise ValueError("lookupsid timeout")
    except Exception as e:
        raise ValueError(f"lookupsid error: {e}")


# ============== API 端点 ==============

@app.get("/")
async def root():
    return {
        "name": "Windows Tools MCP Server",
        "version": "3.0.0",
        "tools": ["enum4linux_scan", "crackmapexec_scan", "smb_enum"],
    }


@app.get("/health")
async def health():
    tools_status = {
        tool: shutil.which(tool) is not None
        for tool in ("samrdump.py", "smbclient.py", "lookupsid.py")
    }
    impacket_available = all(tools_status.values())
    
    return {
        "status": "healthy" if impacket_available else "degraded",
        "tools": ["enum4linux_scan", "crackmapexec_scan", "smb_enum"],
        "impacket_available": impacket_available,
        "tools_available": tools_status,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params
    
    tool_map = {
        "enum4linux_scan": enum4linux_scan,
        "crackmapexec_scan": crackmapexec_scan,
        "smb_enum": smb_enum,
    }
    
    if tool_name not in tool_map:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    
    try:
        return await tool_map[tool_name](params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_async_windows_tool(task_id: str, tool_name: str, params: Dict[str, Any]) -> None:
    labels = {
        "enum4linux_scan": "Windows 用户与组枚举",
        "crackmapexec_scan": "Windows SID 枚举",
        "smb_enum": "SMB 共享枚举",
    }
    runners = {
        "enum4linux_scan": enum4linux_scan,
        "crackmapexec_scan": crackmapexec_scan,
        "smb_enum": smb_enum,
    }
    task = SCAN_TASKS[task_id]
    label = labels[tool_name]
    task.update(status="running", progress=0, heartbeat_at=datetime.utcnow().isoformat(), elapsed_seconds=0)

    async def heartbeat():
        started = time.time()
        while task["status"] == "running":
            elapsed = int(time.time() - started)
            task.update(
                progress=min(95, 5 + elapsed // 3),
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
    if request.tool not in {"enum4linux_scan", "crackmapexec_scan", "smb_enum"}:
        raise HTTPException(status_code=400, detail=f"Tool {request.tool} does not support async mode")
    task_id = str(uuid.uuid4())
    SCAN_TASKS[task_id] = {
        "task_id": task_id, "tool": request.tool, "status": "pending",
        "progress": 0, "result": None, "error": None,
    }
    SCAN_TASKS[task_id]["handle"] = asyncio.create_task(
        _run_async_windows_tool(task_id, request.tool, request.params)
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
    uvicorn.run(app, host="0.0.0.0", port=8014)
