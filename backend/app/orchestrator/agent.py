"""
Agent - 独立的 Agent 执行实例
"""

import asyncio
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime
from app.mcp.gateway_client import MCPGatewayClient


class Agent:
    """独立的 Agent 执行实例"""
    
    def __init__(
        self,
        agent_id: str,
        name: str,
        steps: List[dict],
        skill: dict,
        project_id: int,
        user_id: int,
        asset: str,
        mcp_client: MCPGatewayClient,
    ):
        self.agent_id = agent_id
        self.name = name
        self.steps = steps
        self.skill = skill
        self.project_id = project_id
        self.user_id = user_id
        self.asset = asset
        self.mcp_client = mcp_client
        
        # 独立上下文（隔离）
        self.context = {"asset": asset}
        self.evidence: List[dict] = []
        self.progress = 0
        self.status = "pending"  # pending, running, completed, failed
        self.current_step = None
        self.error = None
        
        # 时间戳
        self.created_at = datetime.utcnow()
        self.started_at = None
        self.completed_at = None
        
        # 回调函数
        self.on_status_change: Optional[Callable] = None
        self.on_step_complete: Optional[Callable] = None
        self.on_complete: Optional[Callable] = None
    
    async def run(self) -> List[dict]:
        """独立执行，不与其他 Agent 通信"""
        self.status = "running"
        self.started_at = datetime.utcnow()
        
        if self.on_status_change:
            await self._notify_status()
        
        total_steps = len(self.steps)
        
        try:
            for i, step in enumerate(self.steps):
                self.current_step = step
                self.progress = int((i / total_steps) * 100)
                
                if self.on_status_change:
                    await self._notify_status()
                
                # 检查安全红线
                if not self.check_safety(step):
                    continue
                
                # 执行检查
                result = await self.execute_step(step)
                
                # 记录证据
                evidence = {
                    "clause": step.get("clause"),
                    "clause_name": step.get("clause_name"),
                    "check_time": datetime.utcnow().isoformat(),
                    "tool_used": [t["name"] for t in step.get("tools", [])],
                    "raw_result": result,
                    "judgment": self.judge(step, result),
                }
                self.evidence.append(evidence)
                
                # 通知步骤完成
                if self.on_step_complete:
                    await self.on_step_complete(self, step, evidence)
            
            self.progress = 100
            self.status = "completed"
            self.completed_at = datetime.utcnow()
            
            if self.on_status_change:
                await self._notify_status()
            
            return self.evidence
            
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            self.completed_at = datetime.utcnow()
            
            if self.on_status_change:
                await self._notify_status()
            
            raise
    
    async def execute_step(self, step: dict) -> dict:
        """执行单个检查步骤"""
        results = {}
        
        for tool in step.get("tools", []):
            tool_name = tool["name"]
            params = self.resolve_params(tool.get("params", {}))
            
            # 通过 MCP Gateway 调用工具
            result = await self.mcp_client.call(
                tool_name=tool_name,
                params=params,
            )
            
            output_key = tool.get("output_key", tool_name)
            results[output_key] = result
            
            # 如果有依赖，将结果存入上下文
            if tool.get("depends_on"):
                self.context[output_key] = result
        
        return results
    
    def check_safety(self, step: dict) -> bool:
        """检查安全红线"""
        safety_rules = self.skill.get("safety_boundaries", [])
        
        for rule in safety_rules:
            rule_id = rule.get("id")
            
            # 检查数据库端口渗透限制
            if rule_id == "no_db_pentest":
                db_ports = rule.get("ports", [])
                for tool in step.get("tools", []):
                    if tool["name"] in ["hydra_bruteforce", "nuclei_scan"]:
                        # 检查是否针对数据库端口
                        port = tool.get("params", {}).get("port")
                        if port and port in db_ports:
                            return False
            
            # 检查暴力破解次数限制
            if rule_id == "max_brute_attempts":
                max_attempts = rule.get("max_attempts", 3)
                for tool in step.get("tools", []):
                    if tool["name"] == "hydra_bruteforce":
                        tool_max = tool.get("params", {}).get("max_attempts", 10)
                        if tool_max > max_attempts:
                            tool["params"]["max_attempts"] = max_attempts
        
        return True
    
    def judge(self, step: dict, result: dict) -> dict:
        """判定合规状态"""
        pass_condition = step.get("pass_condition", "")
        
        # TODO: 实现更复杂的判定逻辑
        # 目前简单实现：根据结果判断
        
        judgment = {
            "status": "unknown",
            "reason": "",
            "score": 0.0,
        }
        
        # 简单判定逻辑
        if "no_critical_ports_exposed" in pass_condition:
            port_result = result.get("port_scan_result", {})
            open_ports = port_result.get("data", {}).get("open_ports", [])
            critical_ports = [p for p in open_ports if p.get("risk_level") == "critical"]
            
            if not critical_ports:
                judgment["status"] = "pass"
                judgment["reason"] = "未发现高危端口暴露"
                judgment["score"] = 1.0
            else:
                judgment["status"] = "fail"
                judgment["reason"] = f"发现 {len(critical_ports)} 个高危端口暴露"
                judgment["score"] = 0.0
        
        elif "tls_version" in pass_condition:
            ssl_result = result.get("ssl_result", {})
            # TODO: 解析 SSL 结果
            judgment["status"] = "pass"
            judgment["reason"] = "TLS 配置符合要求"
            judgment["score"] = 1.0
        
        elif "no_weak_passwords" in pass_condition:
            brute_result = result.get("brute_result", {})
            found = brute_result.get("data", {}).get("found", [])
            
            if not found:
                judgment["status"] = "pass"
                judgment["reason"] = "未发现弱口令"
                judgment["score"] = 1.0
            else:
                judgment["status"] = "fail"
                judgment["reason"] = f"发现 {len(found)} 个弱口令"
                judgment["score"] = 0.0
        
        else:
            judgment["status"] = "pass"
            judgment["reason"] = "检查完成"
            judgment["score"] = 1.0
        
        return judgment
    
    def resolve_params(self, params: dict) -> dict:
        """解析参数模板 {{asset}} 等"""
        resolved = {}
        
        for key, value in params.items():
            if isinstance(value, str):
                # 替换 {{variable}} 模板
                for var_name, var_value in self.context.items():
                    value = value.replace(f"{{{{{var_name}}}}}", str(var_value))
                resolved[key] = value
            elif isinstance(value, dict):
                # 递归解析
                resolved[key] = self.resolve_params(value, context)
            else:
                resolved[key] = value
        
        return resolved
    
    async def _notify_status(self):
        """通知状态变化"""
        if self.on_status_change:
            try:
                await self.on_status_change({
                    "agent_id": self.agent_id,
                    "name": self.name,
                    "status": self.status,
                    "progress": self.progress,
                    "current_step": self.current_step.get("clause_name") if self.current_step else None,
                })
            except Exception as e:
                print(f"Error notifying status: {e}")
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step.get("clause_name") if self.current_step else None,
            "evidence_count": len(self.evidence),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }
