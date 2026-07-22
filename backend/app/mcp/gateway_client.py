"""
MCP Gateway Client - MCP Gateway 客户端
通过 Gateway 统一调用各种 MCP 工具
支持同步和异步调用模式
"""

import httpx
import asyncio
import logging
from typing import Dict, Any, Optional, Callable
from app.core.config import settings

logger = logging.getLogger(__name__)


class MCPGatewayClient:
    """MCP Gateway 客户端"""
    
    def __init__(self, gateway_url: Optional[str] = None):
        if gateway_url is None:
            self.gateway_url = settings.MCP_GATEWAY_URL
        else:
            self.gateway_url = gateway_url
        
        # 同步通道只承载有界探测；长任务由 Gateway 409 升级到心跳轮询。
        self.timeout = 120.0
        self.max_retries = 2  # 最大重试次数
        self.retry_delay = 2.0  # 重试延迟（秒）
        self.progress_stale_seconds = float(settings.MCP_PROGRESS_STALE_SECONDS)
    
    async def call(self, tool_name: str, params: dict) -> dict:
        """
        通过 Gateway 调用工具（同步模式，带重试机制）
        
        Args:
            tool_name: 工具名称
            params: 工具参数
        
        Returns:
            工具返回结果
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                logger.info(f"MCP Gateway call attempt {attempt + 1}/{self.max_retries + 1}: {tool_name}")
                
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
                ) as client:
                    response = await client.post(
                        f"{self.gateway_url}/call",
                        json={
                            "tool": tool_name,
                            "params": params,
                        }
                    )
                    response.raise_for_status()
                    result = response.json()
                    logger.info(f"MCP Gateway call success: {tool_name}")
                    return result
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 409:
                    logger.info("MCP Gateway routed long-running tool to async mode: %s", tool_name)
                    return await self.call_with_progress(tool_name, params)
                last_error = Exception(f"MCP Gateway error: {e.response.status_code} - {e.response.text}")
                logger.error(f"MCP Gateway HTTP error (attempt {attempt + 1}): {e.response.status_code} - {e.response.text}")
                
                # 如果是 4xx 错误，不重试
                if 400 <= e.response.status_code < 500:
                    raise last_error
                    
            except httpx.RequestError as e:
                last_error = Exception(f"MCP Gateway request error: {type(e).__name__}: {str(e)}")
                logger.error(f"MCP Gateway request error (attempt {attempt + 1}): {type(e).__name__}: {str(e)}")
                
            except Exception as e:
                last_error = Exception(f"MCP Gateway unexpected error: {type(e).__name__}: {str(e)}")
                logger.error(f"MCP Gateway unexpected error (attempt {attempt + 1}): {type(e).__name__}: {str(e)}")
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries:
                logger.info(f"Retrying in {self.retry_delay} seconds...")
                await asyncio.sleep(self.retry_delay)
        
        # 所有重试都失败
        logger.error(f"MCP Gateway call failed after {self.max_retries + 1} attempts")
        raise last_error
    
    async def call_async(self, tool_name: str, params: dict) -> str:
        """
        异步调用工具，返回 task_id
        
        Args:
            tool_name: 工具名称
            params: 工具参数
        
        Returns:
            task_id: 任务 ID
        """
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.post(
                    f"{self.gateway_url}/call/async",
                    json={
                        "tool": tool_name,
                        "params": params,
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result.get("task_id")
            except httpx.HTTPStatusError as e:
                raise Exception(f"MCP Gateway error: {e.response.status_code} - {e.response.text}")
            except httpx.RequestError as e:
                raise Exception(f"MCP Gateway request error: {e}")
    
    async def get_progress(self, tool_name: str, task_id: str) -> dict:
        """
        查询异步任务进度
        
        Args:
            tool_name: 工具名称
            task_id: 任务 ID
        
        Returns:
            进度信息
        """
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.get(
                    f"{self.gateway_url}/progress/{tool_name}/{task_id}"
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                raise Exception(f"MCP Gateway error: {e.response.status_code} - {e.response.text}")
            except httpx.RequestError as e:
                raise Exception(f"MCP Gateway request error: {e}")
    
    async def get_result(self, tool_name: str, task_id: str) -> dict:
        """
        获取异步任务结果
        
        Args:
            tool_name: 工具名称
            task_id: 任务 ID
        
        Returns:
            任务结果
        """
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.get(
                    f"{self.gateway_url}/result/{tool_name}/{task_id}"
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                raise Exception(f"MCP Gateway error: {e.response.status_code} - {e.response.text}")
            except httpx.RequestError as e:
                raise Exception(f"MCP Gateway request error: {e}")

    async def cancel(self, tool_name: str, task_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.gateway_url}/cancel/{tool_name}/{task_id}")
            response.raise_for_status()
            return response.json()
    
    async def call_with_progress(
        self,
        tool_name: str,
        params: dict,
        on_progress: Optional[Callable[[dict], None]] = None,
        poll_interval: float = 2.0,
    ) -> dict:
        """
        异步调用工具并轮询进度
        
        Args:
            tool_name: 工具名称
            params: 工具参数
            on_progress: 进度回调函数
            poll_interval: 轮询间隔（秒）
        
        Returns:
            工具返回结果
        """
        # 启动异步任务
        task_id = await self.call_async(tool_name, params)
        last_contact = asyncio.get_running_loop().time()
        last_progress: dict = {}
        
        try:
            # 轮询进度
            while True:
                try:
                    progress = await self.get_progress(tool_name, task_id)
                    last_contact = asyncio.get_running_loop().time()
                    last_progress = progress
                except Exception as exc:
                    disconnected_for = asyncio.get_running_loop().time() - last_contact
                    if disconnected_for >= self.progress_stale_seconds:
                        raise Exception(
                            f"工具任务已连续 {int(disconnected_for)} 秒无法获取心跳，"
                            "执行状态无法确认，请检查 MCP Gateway 或工具容器"
                        ) from exc
                    reconnecting = {
                        **last_progress,
                        "status": "running",
                        "alive": None,
                        "connection_state": "reconnecting",
                        "message": (
                            f"进度通道暂时中断，正在重连（已失联 {int(disconnected_for)} 秒）"
                        ),
                    }
                    if on_progress:
                        on_progress(reconnecting)
                    await asyncio.sleep(poll_interval)
                    continue
            
                # 回调进度
                if on_progress:
                    on_progress(progress)
            
                # 检查是否完成
                status = progress.get("status")
                if status == "completed":
                    return await self.get_result(tool_name, task_id)
                if status == "failed":
                    raise Exception(f"Task failed: {progress.get('error', 'Unknown error')}")
                if status == "cancelled":
                    raise Exception("Task cancelled")

                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            try:
                await self.cancel(tool_name, task_id)
            except Exception as exc:
                logger.warning("Failed to cancel MCP task %s/%s: %s", tool_name, task_id, exc)
            raise
    
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
