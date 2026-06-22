"""
Diagnostics API - 诊断和连通性测试
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.mcp.gateway_client import MCPGatewayClient
import httpx

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])


@router.get("/mcp/health")
async def test_mcp_health(
    current_user: User = Depends(get_current_user),
):
    """测试 MCP Gateway 健康状态"""
    results = {}
    
    # 测试 Gateway
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("http://mcp-gateway:9000/health")
            if response.status_code == 200:
                data = response.json()
                results["gateway"] = {
                    "status": "healthy",
                    "details": data,
                }
            else:
                results["gateway"] = {
                    "status": "unhealthy",
                    "error": f"HTTP {response.status_code}",
                }
    except Exception as e:
        results["gateway"] = {
            "status": "unhealthy",
            "error": str(e),
        }
    
    # 测试 Security Tools
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("http://security-tools:8010/health")
            if response.status_code == 200:
                data = response.json()
                results["security_tools"] = {
                    "status": "healthy",
                    "details": data,
                }
            else:
                results["security_tools"] = {
                    "status": "unhealthy",
                    "error": f"HTTP {response.status_code}",
                }
    except Exception as e:
        results["security_tools"] = {
            "status": "unhealthy",
            "error": str(e),
        }
    
    # 测试 OCR Server
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("http://ocr-server:8005/health")
            if response.status_code == 200:
                results["ocr_server"] = {
                    "status": "healthy",
                }
            else:
                results["ocr_server"] = {
                    "status": "unhealthy",
                    "error": f"HTTP {response.status_code}",
                }
    except Exception as e:
        results["ocr_server"] = {
            "status": "unhealthy",
            "error": str(e),
        }
    
    # 判断整体状态
    all_healthy = all(r.get("status") == "healthy" for r in results.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": results,
    }


@router.post("/mcp/test-tool")
async def test_mcp_tool(
    tool_name: str = "ping_host",
    current_user: User = Depends(get_current_user),
):
    """测试具体工具是否可用"""
    client = MCPGatewayClient()
    
    # 根据工具类型使用不同的测试参数
    test_params = {
        "ping_host": {"target": "localhost", "count": 1},
        "nmap_scan": {"target": "localhost", "port_range": "1-100"},
        "testssl_scan": {"target": "localhost", "port": 443},
    }
    
    params = test_params.get(tool_name, {"target": "localhost"})
    
    try:
        result = await client.call(tool_name, params)
        return {
            "tool": tool_name,
            "status": "available",
            "result": result,
        }
    except Exception as e:
        return {
            "tool": tool_name,
            "status": "unavailable",
            "error": str(e),
        }
