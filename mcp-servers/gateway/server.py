"""
MCP Gateway - 路由 + 鉴权 + Schema 验证
统一入口，将请求路由到对应的 Tool Server
支持同步和异步调用模式
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
import asyncio
import httpx
import os

app = FastAPI(title="MCP Gateway", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 工具路由表：工具名 -> Tool Server URL
TOOL_ROUTES = {
    # 安全工具（统一服务）
    "nmap_scan": "http://security-tools:8010",
    "port_scan": "http://security-tools:8010",
    "scan_ports": "http://security-tools:8010",  # 别名
    "testssl_scan": "http://security-tools:8010",
    "ssl_check": "http://security-tools:8010",
    "scan_ssl": "http://security-tools:8010",  # 别名
    "nuclei_scan": "http://security-tools:8010",
    "vuln_scan": "http://security-tools:8010",
    "scan_vulnerabilities": "http://security-tools:8010",  # 别名
    "hydra_bruteforce": "http://security-tools:8010",
    "password_test": "http://security-tools:8010",
    "scan_weak_passwords": "http://security-tools:8010",  # 别名
    "ping_host": "http://security-tools:8010",
    "ping_asset": "http://security-tools:8010",
    
    # SSH 白盒配置核查
    "linux_baseline": "http://ssh-checker:8016",
    "password_policy_check": "http://ssh-checker:8016",
    "ssh_config_check": "http://ssh-checker:8016",
    "audit_config_check": "http://ssh-checker:8016",
    "service_port_check": "http://ssh-checker:8016",
    "file_permission_check": "http://ssh-checker:8016",
    "mac_check": "http://ssh-checker:8016",
    
    # 快速端口扫描
    "masscan_scan": "http://fast-scanner:8011",
    "fping_scan": "http://fast-scanner:8011",
    
    # Web 安全检测
    "nikto_scan": "http://web-tools:8012",
    "sqlmap_scan": "http://web-tools:8012",
    "gobuster_scan": "http://web-tools:8012",
    "ffuf_scan": "http://web-tools:8012",
    
    # 网络设备检测
    "snmp_walk": "http://network-tools:8013",
    "snmp_bruteforce": "http://network-tools:8013",
    "snmp_get": "http://network-tools:8013",
    
    # Windows/AD 安全检测
    "enum4linux_scan": "http://windows-tools:8014",
    "crackmapexec_scan": "http://windows-tools:8014",
    "smb_enum": "http://windows-tools:8014",
    
    # 数据库安全检测
    "redis_check": "http://db-tools:8015",
    "oracle_check": "http://db-tools:8015",
    "mongodb_check": "http://db-tools:8015",
    "memcached_check": "http://db-tools:8015",
    "mysql_check": "http://db-tools:8015",
    
    # OCR 相关
    "ocr_analyze": "http://ocr-server:8005",
    "screenshot_analyze": "http://ocr-server:8005",
}

TOOL_ALIASES = {
    "ping_asset": "ping_host",
    "nmap_scan": "nmap_scan",
    "port_scan": "nmap_scan",
    "scan_ports": "nmap_scan",
    "testssl_scan": "testssl_scan",
    "ssl_check": "testssl_scan",
    "scan_ssl": "testssl_scan",
    "nuclei_scan": "nuclei_scan",
    "vuln_scan": "nuclei_scan",
    "scan_vulnerabilities": "nuclei_scan",
    "hydra_bruteforce": "hydra_bruteforce",
    "password_test": "hydra_bruteforce",
    "scan_weak_passwords": "hydra_bruteforce",
    "nikto": "nikto_scan",
    "gobuster": "gobuster_scan",
    "dirbust": "gobuster_scan",
    "sqlmap": "sqlmap_scan",
    "ffuf": "ffuf_scan",
    "redis": "redis_check",
    "mysql": "mysql_check",
    "mongo": "mongodb_check",
    "mongodb": "mongodb_check",
    "oracle": "oracle_check",
    "memcached": "memcached_check",
    "snmp": "snmp_walk",
    "snmpget": "snmp_get",
    "windows": "enum4linux_scan",
    "smb": "smb_enum",
    "cme": "crackmapexec_scan",
}


def canonical_tool_name(tool_name: str) -> str:
    return TOOL_ALIASES.get(tool_name, tool_name)

# 工具到 Tool Server 的映射（用于健康检查）
SERVER_ROUTES = {
    "security-tools": "http://security-tools:8010",
    "ssh-checker": "http://ssh-checker:8016",
    "fast-scanner": "http://fast-scanner:8011",
    "web-tools": "http://web-tools:8012",
    "network-tools": "http://network-tools:8013",
    "windows-tools": "http://windows-tools:8014",
    "db-tools": "http://db-tools:8015",
    "ocr-server": "http://ocr-server:8005",
}

# 支持异步扫描的工具
ASYNC_TOOLS = ["nmap_scan", "port_scan", "scan_ports", "masscan_scan", "nuclei_scan", "hydra_bruteforce", "testssl_scan"]


class ToolCallRequest(BaseModel):
    """工具调用请求"""
    tool: str
    params: Dict[str, Any]


class ToolCallResponse(BaseModel):
    """工具调用响应"""
    tool: str
    version: str = "1.0"
    status: str
    data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "MCP Gateway",
        "version": "1.0.0",
        "status": "running",
        "tools": list(TOOL_ROUTES.keys()),
    }


@app.get("/health")
async def health():
    """
    健康检查 - 聚合所有 Tool Server 的状态
    """
    async def check_server(server_name: str, server_url: str):
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{server_url}/health")
            if response.status_code == 200:
                details = response.json()
                status = details.get("status", "healthy") if isinstance(details, dict) else "healthy"
                return server_name, {
                    "status": "healthy" if status in {"healthy", "running"} else "degraded",
                    "details": details,
                }
            return server_name, {"status": "unhealthy", "error": f"HTTP {response.status_code}"}
        except Exception as exc:
            return server_name, {"status": "unhealthy", "error": str(exc)}

    checked = await asyncio.gather(
        *(check_server(server_name, server_url) for server_name, server_url in SERVER_ROUTES.items())
    )
    results = dict(checked)
    
    # 判断整体状态
    all_healthy = all(r["status"] == "healthy" for r in results.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "servers": results,
    }


@app.get("/tools")
async def list_tools():
    """
    列出所有可用的工具
    """
    tools = []
    
    for tool_name, server_url in TOOL_ROUTES.items():
        canonical_name = canonical_tool_name(tool_name)
        tools.append({
            "name": tool_name,
            "server": server_url,
            "supports_async": canonical_name in ASYNC_TOOLS,
            "canonical_name": canonical_name,
        })
    
    return {
        "tools": tools,
        "count": len(tools),
    }


@app.post("/call", response_model=ToolCallResponse)
async def call_tool(request: ToolCallRequest):
    """
    调用工具（同步模式）
    """
    tool_name = canonical_tool_name(request.tool)
    params = request.params
    
    # 1. 路由
    server_url = TOOL_ROUTES.get(tool_name)
    if not server_url:
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}. Available tools: {list(TOOL_ROUTES.keys())}"
        )
    
    # 2. 转发
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(
                f"{server_url}/execute",
                json={
                    "tool": tool_name,
                    "params": params,
                }
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as e:
        # 解析工具服务器返回的错误信息
        error_detail = e.response.text
        try:
            error_json = e.response.json()
            if isinstance(error_json, dict) and "detail" in error_json:
                error_detail = error_json["detail"]
        except:
            pass
        
        # 根据错误类型返回友好的错误信息
        if "timeout" in error_detail.lower():
            friendly_error = f"工具执行超时，目标可能不可达或响应过慢"
        elif "not installed" in error_detail.lower():
            friendly_error = f"工具未安装，请联系管理员"
        elif "missing required parameter" in error_detail.lower():
            friendly_error = f"缺少必要参数，请检查输入"
        elif "connection" in error_detail.lower() or "unreachable" in error_detail.lower():
            friendly_error = f"无法连接到目标，请检查目标地址是否正确"
        elif "permission" in error_detail.lower() or "auth" in error_detail.lower():
            friendly_error = f"认证失败，请检查用户名和密码"
        else:
            friendly_error = f"工具执行失败: {error_detail}"
        
        raise HTTPException(
            status_code=e.response.status_code,
            detail=friendly_error
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"工具服务不可用: {e}"
        )
    
    # 3. 返回
    return ToolCallResponse(
        tool=tool_name,
        version=result.get("version", "1.0"),
        status=result.get("status", "success"),
        data=result.get("data"),
        metadata=result.get("metadata"),
        error=result.get("error"),
    )


@app.post("/call/async")
async def call_tool_async(request: ToolCallRequest):
    """
    异步调用工具
    返回 task_id 用于查询进度
    """
    tool_name = canonical_tool_name(request.tool)
    params = request.params
    
    # 检查是否支持异步
    if tool_name not in ASYNC_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Tool {tool_name} does not support async mode. Use /call instead."
        )
    
    # 路由
    server_url = TOOL_ROUTES.get(tool_name)
    if not server_url:
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}"
        )
    
    # 转发到异步接口
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{server_url}/scan/start",
                json={
                    "tool": tool_name,
                    "params": params,
                }
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Tool server error: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Tool server unavailable: {e}"
        )
    
    return {
        "tool": tool_name,
        "task_id": result.get("task_id"),
        "status": "running",
        "message": result.get("message", "Scan started"),
    }


@app.get("/progress/{tool_name}/{task_id}")
async def get_progress(tool_name: str, task_id: str):
    """
    查询异步任务进度
    """
    tool_name = canonical_tool_name(tool_name)
    # 路由
    server_url = TOOL_ROUTES.get(tool_name)
    if not server_url:
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}"
        )
    
    # 查询进度
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{server_url}/scan/{task_id}/progress"
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Tool server error: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Tool server unavailable: {e}"
        )


@app.get("/result/{tool_name}/{task_id}")
async def get_result(tool_name: str, task_id: str):
    """
    获取异步任务结果
    """
    tool_name = canonical_tool_name(tool_name)
    # 路由
    server_url = TOOL_ROUTES.get(tool_name)
    if not server_url:
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}"
        )
    
    # 获取结果
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{server_url}/scan/{task_id}/result"
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Tool server error: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Tool server unavailable: {e}"
        )


@app.post("/call/{tool_name}")
async def call_tool_by_name(tool_name: str, params: Dict[str, Any]):
    """
    通过 URL 路径调用工具（备用接口）
    """
    request = ToolCallRequest(tool=tool_name, params=params)
    return await call_tool(request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
