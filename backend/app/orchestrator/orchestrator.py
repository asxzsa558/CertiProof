"""
Orchestrator - 调度中枢（包工头）
负责：意图识别、加载 Skill、派发 Agent、汇聚结果、生成报告
"""

import asyncio
import uuid
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from app.orchestrator.agent import Agent
from app.orchestrator.skill_loader import SkillLoader
from app.mcp.gateway_client import MCPGatewayClient


class Orchestrator:
    """调度中枢 - 包工头，永远不阻塞"""
    
    def __init__(self):
        self.skill_loader = SkillLoader()
        self.mcp_client = MCPGatewayClient()
        
        # Agent 管理
        self.active_agents: Dict[str, Agent] = {}
        self.completed_tasks: List[dict] = []
        
        # 回调管理
        self.task_callbacks: Dict[str, Dict[str, Callable]] = {}
    
    async def handle_user_input(
        self,
        user_input: str,
        project_id: int,
        user_id: int,
        asset: str,
        on_agent_status: Optional[Callable] = None,
        on_agent_complete: Optional[Callable] = None,
    ) -> dict:
        """
        处理用户输入 - 立即响应，不阻塞
        
        Args:
            user_input: 用户输入
            project_id: 项目 ID
            user_id: 用户 ID
            asset: 目标资产
            on_agent_status: Agent 状态变化回调
            on_agent_complete: Agent 完成回调
        
        Returns:
            任务信息
        """
        # 1. 识别意图
        intent = await self.recognize_intent(user_input)
        
        # 2. 加载 Skill
        skill_name = intent.get("skill_name", "dengbao_level3")
        skill = self.skill_loader.load(skill_name)
        
        # 3. 决定：拆解成多个 Agent 还是单个 Agent
        if intent.get("should_split", True):
            agents = self.create_agents_from_skill(skill, project_id, user_id, asset)
        else:
            agents = [self.create_single_agent(intent, skill, project_id, user_id, asset)]
        
        # 4. 后台启动所有 Agent（不等待）
        task_ids = []
        for agent in agents:
            task_id = agent.agent_id
            self.active_agents[task_id] = agent
            
            # 设置回调
            if on_agent_status:
                agent.on_status_change = on_agent_status
            if on_agent_complete:
                agent.on_complete = on_agent_complete
            
            # 后台启动
            asyncio.create_task(self.run_agent(task_id, agent))
            task_ids.append(task_id)
        
        # 5. 立即返回（不阻塞）
        return {
            "task_ids": task_ids,
            "agents": [
                {
                    "id": tid,
                    "name": self.active_agents[tid].name,
                    "clause": self.active_agents[tid].steps[0].get("clause") if self.active_agents[tid].steps else None,
                }
                for tid in task_ids
            ],
            "message": f"已派出 {len(agents)} 个 Agent 执行任务",
        }
    
    async def run_agent(self, task_id: str, agent: Agent):
        """后台运行 Agent"""
        try:
            result = await agent.run()
            
            # 记录完成的任务
            self.completed_tasks.append({
                "task_id": task_id,
                "agent_name": agent.name,
                "result": result,
                "completed_at": datetime.utcnow().isoformat(),
            })
            
            # 通知完成
            if agent.on_complete:
                await agent.on_complete(task_id, result)
                
        except Exception as e:
            if agent.on_complete:
                await agent.on_complete(task_id, None, error=str(e))
        finally:
            if task_id in self.active_agents:
                del self.active_agents[task_id]
    
    def create_agents_from_skill(
        self,
        skill: dict,
        project_id: int,
        user_id: int,
        asset: str,
    ) -> List[Agent]:
        """从 Skill 创建多个 Agent（任务拆解）"""
        agents = []
        parallel_groups = self.skill_loader.get_parallel_groups(skill)
        
        for group in parallel_groups:
            group_name = group.get("name", "unknown")
            
            for step in group.get("steps", []):
                agent_id = str(uuid.uuid4())
                agent_name = f"{step.get('clause_name', 'unknown')}"
                
                agent = Agent(
                    agent_id=agent_id,
                    name=agent_name,
                    steps=[step],
                    skill=skill,
                    project_id=project_id,
                    user_id=user_id,
                    asset=asset,
                    mcp_client=self.mcp_client,
                )
                agents.append(agent)
        
        return agents
    
    def create_single_agent(
        self,
        intent: dict,
        skill: dict,
        project_id: int,
        user_id: int,
        asset: str,
    ) -> Agent:
        """创建单个 Agent"""
        agent_id = str(uuid.uuid4())
        agent_name = intent.get("description", "single_task")
        
        # 从 Skill 中找到对应的步骤
        steps = []
        parallel_groups = self.skill_loader.get_parallel_groups(skill)
        for group in parallel_groups:
            for step in group.get("steps", []):
                if step.get("clause") == intent.get("clause"):
                    steps.append(step)
                    break
        
        if not steps:
            # 如果没有找到，使用所有步骤
            for group in parallel_groups:
                steps.extend(group.get("steps", []))
        
        return Agent(
            agent_id=agent_id,
            name=agent_name,
            steps=steps,
            skill=skill,
            project_id=project_id,
            user_id=user_id,
            asset=asset,
            mcp_client=self.mcp_client,
        )
    
    async def recognize_intent(self, user_input: str) -> dict:
        """
        识别用户意图
        
        TODO: 使用 LLM 实现更智能的意图识别
        目前使用简单的规则匹配
        """
        user_input_lower = user_input.lower()
        
        # 简单的规则匹配
        if "等保" in user_input or "测评" in user_input or "检测" in user_input:
            return {
                "skill_name": "dengbao_level3",
                "should_split": True,
                "description": "等保三级全量检测",
            }
        elif "端口" in user_input or "扫描" in user_input:
            return {
                "skill_name": "dengbao_level3",
                "should_split": False,
                "clause": "8.1.3.1",
                "description": "端口扫描",
            }
        elif "ssl" in user_input or "tls" in user_input or "加密" in user_input:
            return {
                "skill_name": "dengbao_level3",
                "should_split": False,
                "clause": "8.1.2.2",
                "description": "SSL/TLS 检测",
            }
        elif "弱口令" in user_input or "密码" in user_input:
            return {
                "skill_name": "dengbao_level3",
                "should_split": False,
                "clause": "8.1.4.1",
                "description": "弱口令检测",
            }
        elif "漏洞" in user_input:
            return {
                "skill_name": "dengbao_level3",
                "should_split": False,
                "clause": "8.1.3.3",
                "description": "漏洞扫描",
            }
        else:
            # 默认执行全量检测
            return {
                "skill_name": "dengbao_level3",
                "should_split": True,
                "description": "全量检测",
            }
    
    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "running": [
                agent.to_dict()
                for agent in self.active_agents.values()
            ],
            "completed": self.completed_tasks,
        }
    
    def calculate_score(self, all_evidence: List[dict], skill: dict) -> dict:
        """计算合规分数"""
        scoring_rules = self.skill_loader.get_scoring_rules(skill)
        
        pass_score = scoring_rules.get("pass", 1.0)
        partial_score = scoring_rules.get("partial", 0.5)
        fail_score = scoring_rules.get("fail", 0.0)
        
        total_weight = 0
        total_score = 0
        
        for evidence in all_evidence:
            # 从 Skill 中找到对应的权重
            clause = evidence.get("clause")
            weight = 1.0  # 默认权重
            
            parallel_groups = self.skill_loader.get_parallel_groups(skill)
            for group in parallel_groups:
                for step in group.get("steps", []):
                    if step.get("clause") == clause:
                        weight = step.get("weight", 1.0)
                        break
            
            judgment = evidence.get("judgment", {})
            status = judgment.get("status", "unknown")
            
            if status == "pass":
                score = pass_score
            elif status == "partial":
                score = partial_score
            else:
                score = fail_score
            
            total_weight += weight
            total_score += score * weight
        
        # 计算最终分数
        if total_weight > 0:
            final_score = (total_score / total_weight) * 100
        else:
            final_score = 0
        
        # 确定等级
        levels = scoring_rules.get("levels", [])
        level_name = "未知"
        level_color = "#64748b"
        
        for level in levels:
            if level["min"] <= final_score <= level["max"]:
                level_name = level["name"]
                level_color = level["color"]
                break
        
        return {
            "score": round(final_score, 2),
            "level": level_name,
            "color": level_color,
            "total_checks": len(all_evidence),
            "passed": sum(1 for e in all_evidence if e.get("judgment", {}).get("status") == "pass"),
            "failed": sum(1 for e in all_evidence if e.get("judgment", {}).get("status") == "fail"),
        }


# 全局单例
orchestrator = Orchestrator()
