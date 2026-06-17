"""
MCP Gateway Client - MCP Gateway 客户端
通过 Gateway 统一调用各种 MCP 工具
"""

import httpx
from typing import Dict, Any, Optional
from app.core.config import settings


class MCPGatewayClient:
    """MCP Gateway 客户端"""
    
    def __init__(self, gateway_url: Optional[str] = None):
        if gateway_url is None:
            self.gateway_url = settings.MCP_GATEWAY_URL
        else:
            self.gateway_url = gateway_url
        
        self.timeout = 600.0  # 10 分钟超时
    
    async def call(self, tool_name: str, params: dict) -> dict:
        """
        通过 Gateway 调用工具
        
        Args:
            tool_name: 工具名称
            params: 工具参数
        
        Returns:
            工具返回结果
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.gateway_url}/call",
                    json={
                        "tool": tool_name,
                        "params": params,
                    }
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                raise Exception(f"MCP Gateway error: {e.response.status_code} - {e.response.text}")
            except httpx.RequestError as e:
                raise Exception(f"MCP Gateway request error: {e}")
    
    async def health(self) -> dict:
        """
        检查 Gateway 和所有 Tool Server 的健康状态
        
        Returns:
            健康状态字典
        """
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.get(f"{self.gateway_url}/health")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                return {
                    "status": "unhealthy",
                    "error": str(e),
                }
    
    async def list_tools(self) -> dict:
        """
        列出所有可用的工具
        
        Returns:
            工具列表
        """
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.get(f"{self.gateway_url}/tools")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "tools": [],
                }


# 全局单例
mcp_gateway_client = MCPGatewayClient()
