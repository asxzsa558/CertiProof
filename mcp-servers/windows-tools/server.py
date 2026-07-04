"""
Windows Tools MCP Server - Windows/AD 安全检测工具集
使用 impacket 实现 SMB/Windows 安全检测
"""

import asyncio
import time
import re
import json
import os
import tempfile
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


def command_state(returncode: int, stderr: str, has_data: bool) -> tuple[bool, Optional[str]]:
    if returncode == 0 or has_data:
        return True, (stderr or "").strip() or None
    return False, (stderr or "").strip() or f"tool exited with code {returncode}"


# ============== Impacket SAMR Dump (用户枚举) ==============

async def enum4linux_scan(params: Dict[str, Any]) -> Dict[str, Any]:
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
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
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
            stderr_output,
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

async def smb_enum(params: Dict[str, Any]) -> Dict[str, Any]:
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
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
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
        scan_completed, tool_error = command_state(process.returncode, stderr_output, bool(shares))
        
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

async def crackmapexec_scan(params: Dict[str, Any]) -> Dict[str, Any]:
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
        )
        
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
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
            stderr_output,
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
    tools_status = {}
    for tool in ["samrdump.py", "smbclient.py", "lookupsid.py"]:
        try:
            process = await asyncio.create_subprocess_exec(
                tool, "-h",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=5)
            tools_status[tool] = True
        except Exception:
            tools_status[tool] = False
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8014)
