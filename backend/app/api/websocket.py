"""
WebSocket API - 实时推送 Agent 状态
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Dict, List
import json
import logging

from app.orchestrator import orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        # task_id -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # 全局连接（不绑定 task_id，用于系统级广播）
        self.global_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket, task_id: str):
        """接受新的 WebSocket 连接"""
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)
        # 同时加入全局连接池
        self.global_connections.append(websocket)
        logger.info(f"WebSocket connected for task {task_id}, total: {len(self.active_connections[task_id])}")
    
    def disconnect(self, websocket: WebSocket, task_id: str):
        """断开 WebSocket 连接"""
        if task_id in self.active_connections:
            self.active_connections[task_id].remove(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
        # 从全局连接池移除
        if websocket in self.global_connections:
            self.global_connections.remove(websocket)
        logger.info(f"WebSocket disconnected for task {task_id}")
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """发送消息到特定 WebSocket"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
    
    async def broadcast_to_task(self, message: dict, task_id: str):
        """广播消息到特定任务的所有连接"""
        if task_id in self.active_connections:
            for connection in self.active_connections[task_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Failed to broadcast to task {task_id}: {e}")
    
    async def broadcast(self, message: dict):
        """广播消息到所有连接（全局广播）"""
        for connection in self.global_connections[:]:  # 使用切片避免迭代时修改
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to broadcast: {e}")


manager = ConnectionManager()


@router.websocket("/agents/{task_id}")
async def agent_websocket(websocket: WebSocket, task_id: str):
    """
    WebSocket 端点：实时推送 Agent 状态
    
    客户端连接后会收到：
    - Agent 状态变化（running, completed, failed）
    - 进度更新
    - 扫描进度（端口扫描）
    """
    await manager.connect(websocket, task_id)
    
    try:
        # 发送当前状态
        if task_id in orchestrator.active_agents:
            agent = orchestrator.active_agents[task_id]
            await manager.send_personal_message({
                "type": "status",
                "data": agent.to_dict(),
            }, websocket)
        else:
            # 检查是否已完成
            for task in orchestrator.completed_tasks:
                if task["task_id"] == task_id:
                    await manager.send_personal_message({
                        "type": "completed",
                        "data": {
                            "task_id": task["task_id"],
                            "agent_name": task["agent_name"],
                            "evidence_count": task.get("evidence_count", 0),
                            "result_description": task.get("result_description", ""),
                            "scan_results": task.get("scan_results", {}),
                            "is_multi_asset": task.get("is_multi_asset", False),
                            "completed_at": task["completed_at"],
                        },
                    }, websocket)
                    break
        
        # 保持连接，等待断开
        while True:
            # 接收客户端消息（可用于心跳或控制）
            data = await websocket.receive_text()
            if data == "ping":
                await manager.send_personal_message({"type": "pong"}, websocket)
    
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket, task_id)


async def broadcast_agent_status(task_id: str, status: dict):
    """
    广播 Agent 状态变化
    
    由 Agent 在状态变化时调用
    """
    await manager.broadcast_to_task({
        "type": "status",
        "data": status,
    }, task_id)


async def broadcast_agent_completed(task_id: str, result: dict):
    """
    广播 Agent 完成事件
    
    由 Agent 在完成时调用
    """
    await manager.broadcast_to_task({
        "type": "completed",
        "data": result,
    }, task_id)


async def broadcast_agent_failed(task_id: str, error: str):
    """
    广播 Agent 失败事件
    
    由 Agent 在失败时调用
    """
    await manager.broadcast_to_task({
        "type": "failed",
        "data": {
            "task_id": task_id,
            "error": error,
        },
    }, task_id)
