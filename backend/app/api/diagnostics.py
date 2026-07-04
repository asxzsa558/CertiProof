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
    services = {
        "mcp_gateway": "http://mcp-gateway:9000",
        "security_tools": "http://security-tools:8010",
        "fast_scanner": "http://fast-scanner:8011",
        "web_tools": "http://web-tools:8012",
        "network_tools": "http://network-tools:8013",
        "windows_tools": "http://windows-tools:8014",
        "db_tools": "http://db-tools:8015",
        "ssh_checker": "http://ssh-checker:8016",
        "ocr_server": "http://ocr-server:8005",
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, base_url in services.items():
            try:
                response = await client.get(f"{base_url}/health")
                if response.status_code == 200:
                    results[name] = {"status": "healthy", "details": response.json()}
                else:
                    results[name] = {"status": "unhealthy", "error": f"HTTP {response.status_code}"}
            except Exception as e:
                results[name] = {"status": "unhealthy", "error": str(e)}

        try:
            response = await client.get("http://mcp-gateway:9000/tools")
            if response.status_code == 200:
                results["gateway_routes"] = {
                    "status": "healthy",
                    "details": response.json(),
                }
            else:
                results["gateway_routes"] = {
                    "status": "unhealthy",
                    "error": f"HTTP {response.status_code}",
                }
        except Exception as e:
            results["gateway_routes"] = {"status": "unhealthy", "error": str(e)}
    
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
        "ping_host": {"target": "127.0.0.1", "count": 1},
        "ping_asset": {"target": "127.0.0.1", "count": 1},
        "nmap_scan": {"target": "127.0.0.1", "port_range": "high-risk"},
        "scan_ports": {"target": "127.0.0.1", "port_range": "high-risk"},
        "masscan_scan": {"target": "127.0.0.1", "port_range": "1-100", "rate": 100},
        "fping_scan": {"targets": ["127.0.0.1"]},
        "testssl_scan": {"target": "127.0.0.1", "port": 443},
        "scan_ssl": {"target": "127.0.0.1", "port": 443},
        "nuclei_scan": {"target": "http://127.0.0.1", "severity": "low,medium,high,critical"},
        "scan_vulnerabilities": {"target": "http://127.0.0.1"},
        "hydra_bruteforce": {"target": "127.0.0.1", "service": "ssh", "port": 22},
        "scan_weak_passwords": {"target": "127.0.0.1", "service": "ssh", "port": 22},
        "nikto_scan": {"target": "127.0.0.1"},
        "sqlmap_scan": {"url": "http://127.0.0.1/?id=1"},
        "gobuster_scan": {"url": "http://127.0.0.1"},
        "ffuf_scan": {"url": "http://127.0.0.1/FUZZ"},
        "redis_check": {"target": "127.0.0.1"},
        "mysql_check": {"target": "127.0.0.1"},
        "mongodb_check": {"target": "127.0.0.1"},
        "memcached_check": {"target": "127.0.0.1"},
        "oracle_check": {"target": "127.0.0.1"},
        "snmp_walk": {"target": "127.0.0.1"},
        "snmp_bruteforce": {"target": "127.0.0.1"},
        "snmp_get": {"target": "127.0.0.1", "oid": "1.3.6.1.2.1.1.1.0"},
        "enum4linux_scan": {"target": "127.0.0.1"},
        "crackmapexec_scan": {"target": "127.0.0.1"},
        "smb_enum": {"target": "127.0.0.1"},
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
