"""
Web Tools MCP Server - Web 安全检测工具集
包含 nikto、sqlmap、gobuster、ffuf 等 Web 安全检测工具
"""

import asyncio
import contextlib
import json
import time
import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import unquote, urlsplit
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Web Tools MCP Server", version="1.0.0")

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


def completed_or_error(returncode: int, stderr: str, discovered_count: int) -> tuple[bool, Optional[str]]:
    if returncode == 0:
        return True, None
    err = (stderr or "").strip()
    if discovered_count > 0:
        return True, err or None
    return False, err or f"tool exited with code {returncode}"


def timeout_result(tool: str, target: str, duration_ms: int, error: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "tool": tool,
        "version": "1.0",
        "status": "warning",
        "data": {
            "target": target,
            "scan_completed": False,
            "tool_error": error,
            **(data or {}),
        },
        "metadata": {
            "duration_ms": duration_ms,
            "scan_time": datetime.utcnow().isoformat(),
            "timed_out": True,
        },
    }


def parse_gobuster_soft_404(stderr: str) -> Optional[Dict[str, str]]:
    """Detect gobuster wildcard/soft-404 guard and extract retry filters."""
    match = re.search(
        r"non existing urls\.\s+\S+\s+=>\s+(\d+)\s+\(Length:\s*(\d+)\)",
        stderr or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return {"status_code": match.group(1), "length": match.group(2)}


# ============== Nikto ==============

def parse_nikto_findings(output: str) -> List[Dict[str, str]]:
    findings = []
    for line in (output or "").splitlines():
        value = line.strip()
        if not value.startswith("+"):
            continue
        issue = bool(re.match(r"^\+\s+\[\d+\]", value)) or bool(re.search(
            r"\b(?:OSVDB|CVE-\d+|vulnerable|outdated|dangerous|exposed|misconfiguration)\b",
            value,
            re.IGNORECASE,
        ))
        if issue:
            findings.append({"description": value, "severity": "medium"})
    return findings

async def nikto_scan(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """执行 nikto Web 服务器扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 80)
    ssl = params.get("ssl", False)
    timeout = params.get("timeout", 120)
    
    # 构建 URL
    scheme = "https" if ssl else "http"
    url = f"{scheme}://{target}:{port}"
    
    cmd = [
        "nikto",
        "-h", url,
        "-nointeractive",
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
        stderr_output = stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Nikto standard output avoids optional Perl JSON/XML modules.
        findings = parse_nikto_findings(output)

        scan_completed, tool_error = completed_or_error(
            process.returncode, stderr_output, len(findings)
        )
        
        return {
            "tool": "nikto_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": url,
                "findings": findings,
                "total_findings": len(findings),
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
        if process.returncode is None:
            process.kill()
            await process.communicate()
        return timeout_result(
            "nikto_scan", url, int((time.time() - start_time) * 1000),
            f"Web 漏洞扫描在 {timeout} 秒后超时，目标可能响应过慢、限速或被过滤",
            {"findings": [], "total_findings": 0},
        )
    except FileNotFoundError:
        raise ValueError("nikto not installed")
    except Exception as e:
        raise ValueError(f"nikto error: {e}")


# ============== SQLMap ==============

async def sqlmap_scan(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """执行 sqlmap SQL 注入检测"""
    url = params.get("url")
    if not url:
        raise ValueError("Missing required parameter: url")
    
    data = params.get("data")
    level = params.get("level", 1)
    risk = params.get("risk", 1)
    timeout = params.get("timeout", 120)
    
    cmd = [
        "sqlmap",
        "-u", url,
        "--batch",
        "--flush-session",
        "--level", str(level),
        "--risk", str(risk),
    ]
    
    if data:
        cmd.extend(["--data", data])
    
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
        
        # 解析 sqlmap 输出
        vulnerable = False
        injection_points = []
        
        lowered_output = output.lower()
        # SQLMap CLI has no stable JSON output; only its explicit finding markers count.
        if any(marker in lowered_output for marker in (
            "is vulnerable",
            "appears to be injectable",
            "sqlmap identified the following injection point",
        )):
            vulnerable = True
            
            # 提取注入点信息
            for line in output.split('\n'):
                lowered_line = line.lower()
                if ('parameter' in lowered_line or 'payload:' in lowered_line) and (
                    'get' in lowered_line or 'post' in lowered_line or 'payload:' in lowered_line
                ):
                    injection_points.append({
                        "description": line.strip(),
                        "type": "sql_injection",
                    })

        scan_completed, tool_error = completed_or_error(
            process.returncode, stderr_output, len(injection_points)
        )
        
        return {
            "tool": "sqlmap_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": url,
                "vulnerable": vulnerable,
                "injection_points": injection_points,
                "total_injections": len(injection_points),
                "scan_completed": scan_completed,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "level": level,
                "risk": risk,
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        return timeout_result(
            "sqlmap_scan", url, int((time.time() - start_time) * 1000),
            f"SQL 注入检测在 {timeout} 秒后超时，目标可能响应过慢、限速或被过滤",
            {"vulnerable": False, "injection_points": [], "total_injections": 0},
        )
    except FileNotFoundError:
        raise ValueError("sqlmap not installed")
    except Exception as e:
        raise ValueError(f"sqlmap error: {e}")


# ============== Gobuster ==============

async def gobuster_scan(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """执行 gobuster 目录/文件爆破"""
    url = params.get("url") or params.get("target")
    if not url:
        raise ValueError("Missing required parameter: url or target")
    
    # 自动添加 http:// 前缀
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    
    wordlist = params.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
    extensions = params.get("extensions", "php,asp,aspx,jsp,html,txt")
    threads = params.get("threads", 10)
    timeout = params.get("timeout", 120)
    
    def build_cmd(exclude_length: Optional[str] = None) -> List[str]:
        cmd = [
            "gobuster", "dir",
            "-u", url,
            "-w", wordlist,
            "-x", extensions,
            "-t", str(threads),
            "-q",  # 安静模式
            "--no-color",
        ]
        if exclude_length:
            cmd.extend(["--exclude-length", exclude_length])
        return cmd

    cmd = build_cmd(params.get("exclude_length"))
    
    async def run_command(current_cmd: List[str]):
        process = await asyncio.create_subprocess_exec(
            *current_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process_callback:
            process_callback(process)
        return process, await _communicate(process, timeout, continuous and "timeout" not in params)

    start_time = time.time()
    retried_with = None
    
    try:
        process, (stdout, stderr) = await run_command(cmd)
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = stderr.decode("utf-8", errors="replace")
        soft_404 = parse_gobuster_soft_404(stderr_output)
        if process.returncode != 0 and soft_404 and not params.get("exclude_length"):
            retried_with = {"exclude_length": soft_404["length"], "reason": "soft_404_wildcard"}
            process, (stdout, stderr) = await run_command(build_cmd(soft_404["length"]))
            output = stdout.decode("utf-8", errors="replace")
            retry_stderr = stderr.decode("utf-8", errors="replace")
            stderr_output = retry_stderr or (
                f"目标对不存在路径返回统一响应，已自动排除长度 {soft_404['length']} 后重试"
            )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析 gobuster 输出
        discovered = []
        for line in output.split('\n'):
            clean_line = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line).strip()
            if clean_line.startswith('/') or clean_line.startswith('http'):
                parts = clean_line.split()
                if len(parts) >= 2:
                    path = parts[0]
                    status = parts[1] if len(parts) > 1 else ""
                    size = parts[2] if len(parts) > 2 else ""
                    
                    discovered.append({
                        "path": path,
                        "status": status,
                        "size": size,
                    })
        scan_completed, tool_error = completed_or_error(process.returncode, stderr_output, len(discovered))
        
        return {
            "tool": "gobuster_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": url,
                "discovered": discovered,
                "total_discovered": len(discovered),
                "scan_completed": scan_completed,
                "tool_error": tool_error,
                "auto_calibration": retried_with,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "wordlist": wordlist,
                "extensions": extensions,
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        return timeout_result(
            "gobuster_scan", url, int((time.time() - start_time) * 1000),
            f"目录扫描在 {timeout} 秒后超时，目标可能响应过慢、限速或被过滤",
            {"discovered": [], "total_discovered": 0, "auto_calibration": None},
        )
    except FileNotFoundError:
        raise ValueError("gobuster not installed")
    except Exception as e:
        raise ValueError(f"gobuster error: {e}")


# ============== FFuf ==============

async def ffuf_scan(params: Dict[str, Any], process_callback=None, continuous: bool = False) -> Dict[str, Any]:
    """执行 ffuf Web 模糊测试"""
    url = params.get("url")
    if not url:
        raise ValueError("Missing required parameter: url")
    
    wordlist = params.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
    method = params.get("method", "GET")
    timeout = params.get("timeout", 120)
    
    # 确保 URL 包含 FUZZ 占位符
    if "FUZZ" not in url:
        url = url.rstrip('/') + "/FUZZ"
    
    cmd = [
        "ffuf",
        "-u", url,
        "-w", wordlist,
        "-X", method,
        "-mc", "200,201,301,302,403",  # 匹配的状态码
        "-ac",
        "-s",
        "-json",
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
        stderr_output = stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析 ffuf JSON 输出
        discovered = []
        for line in output.splitlines():
            if not line.strip():
                continue
            try:
                result = json.loads(line)
                result_url = result.get("url", "")
                input_value = result.get("input", {}).get("FUZZ", "")
                if result_url:
                    input_value = unquote(urlsplit(result_url).path.rstrip('/').rsplit('/', 1)[-1])
                discovered.append({
                    "input": input_value,
                    "status": result.get("status", 0),
                    "length": result.get("length", 0),
                    "words": result.get("words", 0),
                    "lines": result.get("lines", 0),
                    "url": result_url,
                })
            except json.JSONDecodeError:
                continue
        scan_completed, tool_error = completed_or_error(process.returncode, stderr_output, len(discovered))
        
        return {
            "tool": "ffuf_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": url.replace("FUZZ", ""),
                "discovered": discovered,
                "total_discovered": len(discovered),
                "scan_completed": scan_completed,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "wordlist": wordlist,
                "method": method,
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        return timeout_result(
            "ffuf_scan", url, int((time.time() - start_time) * 1000),
            f"Web 模糊测试在 {timeout} 秒后超时，目标可能响应过慢、限速或被过滤",
            {"discovered": [], "total_discovered": 0},
        )
    except FileNotFoundError:
        raise ValueError("ffuf not installed")
    except Exception as e:
        raise ValueError(f"ffuf error: {e}")


# ============== API 端点 ==============

@app.get("/")
async def root():
    return {
        "name": "Web Tools MCP Server",
        "version": "1.0.0",
        "tools": ["nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan"],
    }


@app.get("/health")
async def health():
    tools_status = {}
    
    for tool in ["nikto", "sqlmap", "gobuster", "ffuf"]:
        try:
            process = await asyncio.create_subprocess_exec(
                tool, "--version" if tool != "nikto" else "-V",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=5)
            tools_status[tool] = True
        except:
            tools_status[tool] = False
    
    return {
        "status": "healthy" if any(tools_status.values()) else "degraded",
        "tools": ["nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan"],
        "tools_available": tools_status,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params
    
    tool_map = {
        "nikto_scan": nikto_scan,
        "sqlmap_scan": sqlmap_scan,
        "gobuster_scan": gobuster_scan,
        "ffuf_scan": ffuf_scan,
    }
    
    if tool_name not in tool_map:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    
    try:
        return await tool_map[tool_name](params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_async_web_tool(task_id: str, tool_name: str, params: Dict[str, Any]) -> None:
    labels = {
        "nikto_scan": "Nikto Web 漏洞扫描",
        "sqlmap_scan": "SQLMap 注入检测",
        "gobuster_scan": "Gobuster 目录扫描",
        "ffuf_scan": "FFUF 模糊测试",
    }
    runners = {
        "nikto_scan": nikto_scan,
        "sqlmap_scan": sqlmap_scan,
        "gobuster_scan": gobuster_scan,
        "ffuf_scan": ffuf_scan,
    }
    task = SCAN_TASKS[task_id]
    label = labels[tool_name]
    task.update(
        status="running",
        progress=0,
        started_at=datetime.utcnow().isoformat(),
        heartbeat_at=datetime.utcnow().isoformat(),
        elapsed_seconds=0,
        message=f"{label}已启动",
    )

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
        task.update(status="cancelled", error="用户已停止扫描", message=f"{label}已停止")
        raise
    except Exception as exc:
        task.update(status="failed", error=str(exc), message=f"{label}执行失败")
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


@app.post("/scan/start")
async def start_scan(request: ExecuteRequest):
    if request.tool not in {"nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan"}:
        raise HTTPException(status_code=400, detail=f"Tool {request.tool} does not support async mode")
    task_id = str(uuid.uuid4())
    SCAN_TASKS[task_id] = {
        "task_id": task_id,
        "tool": request.tool,
        "status": "pending",
        "progress": 0,
        "result": None,
        "error": None,
    }
    SCAN_TASKS[task_id]["handle"] = asyncio.create_task(
        _run_async_web_tool(task_id, request.tool, request.params)
    )
    return {"task_id": task_id, "status": "running", "message": "Scan started"}


@app.get("/scan/{task_id}/progress")
async def get_scan_progress(task_id: str):
    task = SCAN_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task.get("progress", 0),
        "message": task.get("message"),
        "elapsed_seconds": task.get("elapsed_seconds", 0),
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
    task.update(status="cancelled", error="用户已停止扫描")
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
    uvicorn.run(app, host="0.0.0.0", port=8012)
