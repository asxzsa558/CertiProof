"""
Web Tools MCP Server - Web 安全检测工具集
包含 nikto、sqlmap、gobuster、ffuf 等 Web 安全检测工具
"""

import asyncio
import json
import time
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
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


def completed_or_error(returncode: int, stderr: str, discovered_count: int) -> tuple[bool, Optional[str]]:
    if returncode == 0:
        return True, None
    err = (stderr or "").strip()
    if discovered_count > 0:
        return True, err or None
    return False, err or f"tool exited with code {returncode}"


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

async def nikto_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 nikto Web 服务器扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 80)
    ssl = params.get("ssl", False)
    timeout = params.get("timeout", 600)
    
    # 构建 URL
    scheme = "https" if ssl else "http"
    url = f"{scheme}://{target}:{port}"
    
    cmd = [
        "nikto",
        "-h", url,
        "-Format", "json",
        "-output", "-",
    ]
    
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
        stderr_output = stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析 nikto JSON 输出
        findings = []
        try:
            nikto_data = json.loads(output)
            for vuln in nikto_data.get("vulnerabilities", []):
                findings.append({
                    "id": vuln.get("id", ""),
                    "osvdb": vuln.get("osvdb", ""),
                    "method": vuln.get("method", ""),
                    "uri": vuln.get("uri", ""),
                    "description": vuln.get("description", ""),
                    "severity": "high" if "OSVDB" in vuln.get("osvdb", "") else "medium",
                })
        except json.JSONDecodeError:
            # 如果不是 JSON，尝试解析文本格式
            for line in output.split('\n'):
                if '+' in line and ('OSVDB' in line or 'CGI' in line):
                    findings.append({
                        "description": line.strip(),
                        "severity": "medium",
                    })
        
        return {
            "tool": "nikto_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": url,
                "findings": findings,
                "total_findings": len(findings),
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
            },
        }
    
    except asyncio.TimeoutError:
        raise ValueError("nikto scan timeout")
    except FileNotFoundError:
        raise ValueError("nikto not installed")
    except Exception as e:
        raise ValueError(f"nikto error: {e}")


# ============== SQLMap ==============

async def sqlmap_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 sqlmap SQL 注入检测"""
    url = params.get("url")
    if not url:
        raise ValueError("Missing required parameter: url")
    
    data = params.get("data")
    level = params.get("level", 1)
    risk = params.get("risk", 1)
    timeout = params.get("timeout", 300)
    
    cmd = [
        "sqlmap",
        "-u", url,
        "--batch",
        "--level", str(level),
        "--risk", str(risk),
        "--output-format", "json",
    ]
    
    if data:
        cmd.extend(["-d", data])
    
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
        
        # 解析 sqlmap 输出
        vulnerable = False
        injection_points = []
        
        # 检查是否发现注入点
        if "is vulnerable" in output.lower() or "parameter" in output.lower():
            vulnerable = True
            
            # 提取注入点信息
            for line in output.split('\n'):
                if 'parameter' in line.lower() and ('GET' in line or 'POST' in line):
                    injection_points.append({
                        "description": line.strip(),
                        "type": "sql_injection",
                    })
        
        return {
            "tool": "sqlmap_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": url,
                "vulnerable": vulnerable,
                "injection_points": injection_points,
                "total_injections": len(injection_points),
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "level": level,
                "risk": risk,
            },
        }
    
    except asyncio.TimeoutError:
        raise ValueError("sqlmap scan timeout")
    except FileNotFoundError:
        raise ValueError("sqlmap not installed")
    except Exception as e:
        raise ValueError(f"sqlmap error: {e}")


# ============== Gobuster ==============

async def gobuster_scan(params: Dict[str, Any]) -> Dict[str, Any]:
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
    timeout = params.get("timeout", 300)
    
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
        )
        return process, await asyncio.wait_for(process.communicate(), timeout=timeout)

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
            if line.startswith('/') or line.startswith('http'):
                parts = line.split()
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
        raise ValueError("gobuster scan timeout")
    except FileNotFoundError:
        raise ValueError("gobuster not installed")
    except Exception as e:
        raise ValueError(f"gobuster error: {e}")


# ============== FFuf ==============

async def ffuf_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 ffuf Web 模糊测试"""
    url = params.get("url")
    if not url:
        raise ValueError("Missing required parameter: url")
    
    wordlist = params.get("wordlist", "/usr/share/wordlists/dirb/common.txt")
    method = params.get("method", "GET")
    timeout = params.get("timeout", 300)
    
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
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
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
                discovered.append({
                    "input": result.get("input", {}).get("FUZZ", ""),
                    "status": result.get("status", 0),
                    "length": result.get("length", 0),
                    "words": result.get("words", 0),
                    "lines": result.get("lines", 0),
                    "url": result.get("url", ""),
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
        raise ValueError("ffuf scan timeout")
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8012)
