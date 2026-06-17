"""
Hydra MCP Server - 弱口令检测工具
使用 hydra 进行弱口令检测，返回标准化 JSON 格式
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import subprocess
import json
from datetime import datetime
import time
import re

app = FastAPI(title="Hydra MCP Server", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExecuteRequest(BaseModel):
    """执行请求"""
    tool: str
    params: Dict[str, Any]


class BruteforceResult(BaseModel):
    """暴力破解结果"""
    target: str
    service: str
    port: int
    found: List[Dict[str, str]] = []
    attempts: int = 0
    duration_ms: int = 0


def parse_hydra_output(output: str, target: str, service: str, port: int) -> BruteforceResult:
    """解析 hydra 输出"""
    result = BruteforceResult(
        target=target,
        service=service,
        port=port,
    )
    
    # 解析找到的凭据
    # 格式: [DATA] login: "root" pass: "123456"
    pattern = r'login:\s*"([^"]+)"\s+pass:\s*"([^"]+)"'
    matches = re.findall(pattern, output)
    
    for login, password in matches:
        result.found.append({
            "username": login,
            "password": password,
        })
    
    # 解析尝试次数
    # 格式: 1 of 1 target successfully completed, 0 left (0 errors)
    attempts_pattern = r'(\d+)\s+of\s+\d+\s+target'
    match = re.search(attempts_pattern, output)
    if match:
        result.attempts = int(match.group(1))
    
    return result


async def hydra_bruteforce(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 hydra 暴力破解"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    service = params.get("service", "ssh")
    port = params.get("port", 22)
    max_attempts = params.get("max_attempts", 3)
    
    # 构建 hydra 命令
    # 注意：这里使用简单的字典，实际应该使用更完整的字典
    cmd = [
        "hydra",
        "-l", "root",  # 默认用户名
        "-p", "123456",  # 简单测试密码
        "-t", "1",  # 单线程
        "-w", "3",  # 超时 3 秒
        "-F",  # 找到第一个就停止
        "-o", "-",  # 输出到 stdout
        "-s", str(port),
        target,
        service,
    ]
    
    # 执行 hydra
    start_time = time.time()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        # 解析输出
        parsed = parse_hydra_output(result.stdout + result.stderr, target, service, port)
        
        duration_ms = int((time.time() - start_time) * 1000)
        parsed.duration_ms = duration_ms
        
        # 返回标准格式
        return {
            "tool": "hydra_bruteforce",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": parsed.target,
                "service": parsed.service,
                "port": parsed.port,
                "found": parsed.found,
                "attempts": parsed.attempts,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "max_attempts": max_attempts,
            },
        }
    
    except subprocess.TimeoutExpired:
        raise ValueError("hydra bruteforce timeout")
    except Exception as e:
        raise ValueError(f"hydra bruteforce error: {e}")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "Hydra MCP Server",
        "version": "1.0.0",
        "tools": ["hydra_bruteforce", "password_test"],
    }


@app.get("/health")
async def health():
    """健康检查"""
    # 检查 hydra 是否可用
    try:
        result = subprocess.run(
            ["hydra", "-h"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        hydra_available = True  # hydra -h 会返回非 0，但说明已安装
    except:
        hydra_available = False
    
    return {
        "status": "healthy" if hydra_available else "degraded",
        "tools": ["hydra_bruteforce", "password_test"],
        "hydra_available": hydra_available,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params
    
    if tool_name in ["hydra_bruteforce", "password_test"]:
        return await hydra_bruteforce(params)
    
    raise HTTPException(
        status_code=404,
        detail=f"Unknown tool: {tool_name}"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
