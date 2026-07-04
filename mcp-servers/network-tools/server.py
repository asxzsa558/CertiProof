"""
Network Tools MCP Server - 网络设备检测工具集
包含 snmpwalk、onesixtyone 等网络设备检测工具
"""

import asyncio
import time
import re
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


class ExecuteRequest(BaseModel):
    tool: str
    params: Dict[str, Any]


# ============== SNMP Walk ==============

async def snmp_walk(params: Dict[str, Any]) -> Dict[str, Any]:
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
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = stderr.decode("utf-8", errors="replace")
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

async def snmp_bruteforce(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 SNMP 团体字爆破"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    wordlist = params.get("wordlist", "/usr/share/wordlists/snmp-common.txt")
    timeout = params.get("timeout", 120)
    
    cmd = [
        "onesixtyone",
        "-c", wordlist,
        target,
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
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析 onesixtyone 输出
        found = []
        for line in output.split('\n'):
            if line.strip():
                # 格式: 192.168.1.1 [public] Linux...
                match = re.match(r'([\d\.]+)\s+\[(\w+)\]\s+(.*)', line)
                if match:
                    found.append({
                        "target": match.group(1),
                        "community": match.group(2),
                        "description": match.group(3),
                    })
        
        return {
            "tool": "snmp_bruteforce",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "found": found,
                "total_found": len(found),
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "wordlist": wordlist,
            },
        }
    
    except asyncio.TimeoutError:
        raise ValueError("snmp bruteforce timeout")
    except FileNotFoundError:
        raise ValueError("onesixtyone not installed")
    except Exception as e:
        raise ValueError(f"snmp bruteforce error: {e}")


# ============== SNMP Get ==============

async def snmp_get(params: Dict[str, Any]) -> Dict[str, Any]:
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
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        output = stdout.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析输出
        value = None
        if '=' in output:
            parts = output.split('=', 1)
            if len(parts) == 2:
                value = parts[1].strip()
        
        return {
            "tool": "snmp_get",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "oid": oid,
                "community": community,
                "value": value,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8013)
