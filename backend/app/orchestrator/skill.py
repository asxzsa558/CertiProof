"""
L2 Skill - Worker 类

根据 design-v2.md 设计：
- L1 Agent（协调者）：意图理解、任务规划、派发 Skill、接收结果、合成判定
- L2 Skill（Worker）：执行具体检查逻辑、调用 MCP 工具、返回结构化结果

约束：
- Skill 没有写权限，不能直接修改全局看板
- 每个 Skill 实例有唯一 ID，深度=1
- 工具调用历史克隆（独立），不影响其他 Skill 的视图
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

from app.mcp.gateway_client import MCPGatewayClient

logger = logging.getLogger(__name__)


class Skill:
    """L2 Skill Worker - 独立执行具体检查"""

    def __init__(
        self,
        skill_id: str,
        capability: str,
        parameters: Dict,
        user_id: int,
        project_id: int = None,
        max_retries: int = 3,
    ):
        self.skill_id = skill_id
        self.skill_id = skill_id
        self.capability = self._gateway_capability_name(capability)
        self.parameters = self._normalize_parameters(self.capability, parameters)
        self.user_id = user_id
        self.project_id = project_id
        self.max_retries = max_retries

        # Skill 状态
        self.status = "pending"  # pending, running, completed, failed
        self.started_at = None
        self.completed_at = None
        self.error = None

        # 执行结果（只保存到内存，由 Agent 统一写 DB）
        self.result = None

        # 重试计数
        self.attempts = 0

    @staticmethod
    def _gateway_capability_name(capability: str) -> str:
        aliases = {
            "ping_asset": "ping_host",
            "ssh_check": "ssh_config_check",
        }
        return aliases.get(capability, capability)

    @staticmethod
    def _normalize_parameters(capability: str, parameters: Dict) -> Dict:
        params = dict(parameters or {})
        if capability in {"sqlmap_scan", "gobuster_scan", "ffuf_scan"} and "url" not in params:
            url = params.get("target")
            if url:
                if not url.startswith(("http://", "https://")):
                    url = f"http://{url}"
                if capability == "ffuf_scan" and "FUZZ" not in url:
                    url = url.rstrip("/") + "/FUZZ"
                params["url"] = url
        return params

    async def execute(self) -> Dict[str, Any]:
        """
        执行 Skill，调用 MCP 工具

        Returns:
            结构化结果：
            {
                "skill_id": ...,
                "capability": ...,
                "target": ...,
                "status": "completed" | "failed",
                "result": ...,
                "error": ...,
                "attempts": ...,
            }
        """
        self.status = "running"
        self.started_at = datetime.utcnow()

        target = self.parameters.get("target", "unknown")
        logger.info(f"Skill {self.skill_id} starting: {self.capability}({target})")

        last_error = None

        for attempt in range(self.max_retries):
            self.attempts = attempt + 1
            try:
                logger.info(f"Skill {self.skill_id} attempt {attempt + 1}/{self.max_retries}")

                # 调用 Gateway Client（MCPGatewayClient 不支持 async with）
                client = MCPGatewayClient()
                result = await client.call(self.capability, self.parameters)

                self.result = result
                self.status = "completed"
                self.completed_at = datetime.utcnow()

                logger.info(f"Skill {self.skill_id} completed: {self.capability}({target})")
                return {
                    "skill_id": self.skill_id,
                    "capability": self.capability,
                    "target": target,
                    "status": "completed",
                    "result": result,
                    "error": None,
                    "attempts": self.attempts,
                }

            except Exception as e:
                last_error = str(e)
                logger.warning(f"Skill {self.skill_id} attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)

        # 所有重试都失败
        self.status = "failed"
        self.error = last_error
        self.completed_at = datetime.utcnow()

        logger.error(f"Skill {self.skill_id} failed: {self.capability}({target}) - {last_error}")

        return {
            "skill_id": self.skill_id,
            "capability": self.capability,
            "target": target,
            "status": "failed",
            "result": None,
            "error": last_error,
            "attempts": self.attempts,
        }

    @staticmethod
    async def dispatch_skills_concurrent(
        skills: List["Skill"],
        max_concurrent: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Agent 派发多个 Skill 并发执行

        Args:
            skills: Skill 实例列表
            max_concurrent: 最大并发数

        Returns:
            所有 Skill 的执行结果列表
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _execute_with_semaphore(skill):
            async with semaphore:
                return await skill.execute()

        logger.info(f"Dispatching {len(skills)} Skills concurrently (max={max_concurrent})")
        results = await asyncio.gather(
            *[_execute_with_semaphore(skill) for skill in skills],
            return_exceptions=True
        )

        # 处理异常
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Skill {skills[i].skill_id} raised exception: {result}")
                processed.append({
                    "skill_id": skills[i].skill_id,
                    "capability": skills[i].capability,
                    "target": skills[i].parameters.get("target", "unknown"),
                    "status": "failed",
                    "result": None,
                    "error": str(result),
                    "attempts": 0,
                })
            else:
                processed.append(result)

        return processed
