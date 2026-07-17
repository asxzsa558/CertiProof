"""
DB Tools MCP Server - 数据库安全检测工具集
包含 redis-cli、tnscmd10g、nc 等数据库安全检测工具
"""

import asyncio
import time
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="DB Tools MCP Server", version="1.0.0")

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


def no_response_result(tool: str, target: str, port: int, duration_ms: int, fields: Dict[str, Any], error: str) -> Dict[str, Any]:
    return {
        "tool": tool,
        "version": "1.0",
        "status": "success",
        "data": {
            "target": target,
            "port": port,
            "reachable": False,
            "scan_completed": False,
            "tool_error": error,
            **fields,
        },
        "metadata": {
            "duration_ms": duration_ms,
            "scan_time": datetime.utcnow().isoformat(),
            "error": error,
        },
    }


async def tcp_open(target: str, port: int, timeout: float) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(target, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


# ============== Redis Check ==============

async def redis_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """检查 Redis 未授权访问"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 6379)
    timeout = params.get("timeout", 5)
    
    # 尝试无密码连接
    cmd = [
        "redis-cli",
        "-h", target,
        "-p", str(port),
        "INFO", "server",
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
        stderr_output = stderr.decode("utf-8", errors="replace").strip()
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 检查是否成功连接
        unauthorized = "redis_version" in output
        reachable = process.returncode == 0 or unauthorized
        tool_error = None if reachable else (stderr_output or output.strip() or "redis connection failed")
        
        return {
            "tool": "redis_check",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "unauthorized": unauthorized,
                "info": output[:2000] if unauthorized else None,
                "reachable": reachable,
                "scan_completed": reachable,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        duration_ms = int((time.time() - start_time) * 1000)
        return no_response_result(
            "redis_check",
            target,
            port,
            duration_ms,
            {"unauthorized": False, "info": None},
            "redis connection timeout",
        )
    except FileNotFoundError:
        raise ValueError("redis-cli not installed")
    except Exception as e:
        raise ValueError(f"redis check error: {e}")


# ============== Oracle Check ==============

async def oracle_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """检查 Oracle TNS 版本信息泄露（使用 Python 原生实现）"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    port = params.get("port", 1521)
    timeout = params.get("timeout", 5)

    cmd = [
        "python3",
        "/app/tools/oracle_tns_check.py",
        target,
        str(port),
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
        stderr_output = stderr.decode("utf-8", errors="replace").strip()
        duration_ms = int((time.time() - start_time) * 1000)

        # 解析 JSON 输出
        result_data = {}
        try:
            import json as json_module
            parsed = json_module.loads(output)
            result_data = parsed
            version_info = parsed
        except Exception:
            version_info = {}
            for line in output.split('\n'):
                if ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        version_info[parts[0].strip()] = parts[1].strip()

        oracle_status = str(result_data.get("status", "")).lower()
        reachable = (
            process.returncode == 0
            and bool(output.strip())
            and oracle_status not in {"closed", "error", "failed", "timeout", "unreachable"}
        )
        tool_error = None if reachable else (
            result_data.get("error")
            or stderr_output
            or f"oracle connection {oracle_status or 'failed'}"
        )

        return {
            "tool": "oracle_check",
            "version": "2.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "version_info": version_info,
                "raw_output": output[:2000],
                "reachable": reachable,
                "scan_completed": reachable,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }

    except asyncio.TimeoutError:
        duration_ms = int((time.time() - start_time) * 1000)
        return no_response_result(
            "oracle_check",
            target,
            port,
            duration_ms,
            {"version_info": {}, "raw_output": ""},
            "oracle connection timeout",
        )
    except FileNotFoundError:
        raise ValueError("oracle_tns_check.py not found")
    except Exception as e:
        raise ValueError(f"oracle check error: {e}")


# ============== MongoDB Check ==============

async def mongodb_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """检查 MongoDB 未授权访问"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 27017)
    timeout = params.get("timeout", 5)
    
    # 使用 nc 发送 MongoDB 命令
    cmd = [
        "nc",
        "-w", str(timeout),
        target,
        str(port),
    ]
    
    start_time = time.time()
    if not await tcp_open(target, port, min(timeout, 2)):
        return no_response_result(
            "mongodb_check", target, port, int((time.time() - start_time) * 1000),
            {"unauthorized": False, "raw_output": None},
            "Connection refused or service not listening",
        )
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # 发送 MongoDB 命令获取版本
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=b'db.version()\nexit\n'),
            timeout=timeout,
        )
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = stderr.decode("utf-8", errors="replace").strip()
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 检查是否返回版本信息
        unauthorized = "version" in output.lower() or "ok" in output.lower()
        reachable = process.returncode == 0 and bool(output.strip())
        tool_error = None if reachable else (stderr_output or output.strip() or "mongodb connection failed")
        
        return {
            "tool": "mongodb_check",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "unauthorized": unauthorized,
                "raw_output": output[:2000] if unauthorized else None,
                "reachable": reachable,
                "scan_completed": reachable,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        duration_ms = int((time.time() - start_time) * 1000)
        return no_response_result(
            "mongodb_check",
            target,
            port,
            duration_ms,
            {"unauthorized": False, "raw_output": None},
            "mongodb connection timeout",
        )
    except FileNotFoundError:
        raise ValueError("nc not installed")
    except Exception as e:
        raise ValueError(f"mongodb check error: {e}")


# ============== Memcached Check ==============

async def memcached_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """检查 Memcached 未授权访问"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 11211)
    timeout = params.get("timeout", 5)
    
    cmd = [
        "nc",
        "-w", str(timeout),
        target,
        str(port),
    ]
    
    start_time = time.time()
    if not await tcp_open(target, port, min(timeout, 2)):
        return no_response_result(
            "memcached_check", target, port, int((time.time() - start_time) * 1000),
            {"unauthorized": False, "raw_output": None},
            "Connection refused or service not listening",
        )
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # 发送 stats 命令
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=b'stats\nquit\n'),
            timeout=timeout,
        )
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = stderr.decode("utf-8", errors="replace").strip()
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 检查是否返回统计信息
        unauthorized = "STAT" in output
        reachable = process.returncode == 0 and bool(output.strip())
        tool_error = None if reachable else (stderr_output or output.strip() or "memcached connection failed")
        
        return {
            "tool": "memcached_check",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "unauthorized": unauthorized,
                "raw_output": output[:2000] if unauthorized else None,
                "reachable": reachable,
                "scan_completed": reachable,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        duration_ms = int((time.time() - start_time) * 1000)
        return no_response_result(
            "memcached_check",
            target,
            port,
            duration_ms,
            {"unauthorized": False, "raw_output": None},
            "memcached connection timeout",
        )
    except FileNotFoundError:
        raise ValueError("nc not installed")
    except Exception as e:
        raise ValueError(f"memcached check error: {e}")


# ============== MySQL Check ==============

async def mysql_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """检查 MySQL 空口令"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 3306)
    username = params.get("username", "root")
    timeout = params.get("timeout", 5)
    
    cmd = [
        "mysql",
        "-h", target,
        "-P", str(port),
        "-u", username,
        "-e", "SELECT VERSION();",
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
        
        # 检查是否成功连接
        empty_password = "VERSION()" in output or "version" in output.lower()
        reachable = process.returncode == 0 and bool(output.strip())
        tool_error = None if reachable else (stderr_output.strip() or output.strip() or "mysql connection failed")
        
        return {
            "tool": "mysql_check",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "username": username,
                "empty_password": empty_password,
                "version": output.strip() if empty_password else None,
                "reachable": reachable,
                "scan_completed": reachable,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }
    
    except asyncio.TimeoutError:
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "tool": "mysql_check",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "username": username,
                "empty_password": False,
                "version": None,
                "reachable": False,
                "scan_completed": False,
                "tool_error": "mysql connection timeout",
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "error": "mysql connection timeout",
            },
        }
    except FileNotFoundError:
        raise ValueError("mysql not installed")
    except Exception as e:
        raise ValueError(f"mysql check error: {e}")


# ============== API 端点 ==============

@app.get("/")
async def root():
    return {
        "name": "DB Tools MCP Server",
        "version": "1.0.0",
        "tools": ["redis_check", "mongodb_check", "memcached_check", "mysql_check", "oracle_check"],
    }


@app.get("/health")
async def health():
    tools_status = {}
    
    for tool in ["redis-cli", "nc", "mysql"]:
        try:
            process = await asyncio.create_subprocess_exec(
                tool, "--version" if tool != "nc" else "-h",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=5)
            tools_status[tool] = True
        except:
            tools_status[tool] = False
    
    return {
        "status": "healthy" if any(tools_status.values()) else "degraded",
        "tools": ["redis_check", "mongodb_check", "memcached_check", "mysql_check", "oracle_check"],
        "tools_available": tools_status,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params
    
    tool_map = {
        "redis_check": redis_check,
        "oracle_check": oracle_check,
        "mongodb_check": mongodb_check,
        "memcached_check": memcached_check,
        "mysql_check": mysql_check,
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
    uvicorn.run(app, host="0.0.0.0", port=8015)
