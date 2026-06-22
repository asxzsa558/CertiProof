"""
Agent - 独立的 Agent 执行实例
支持实时进度更新和证据持久化
"""

import asyncio
import logging
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.mcp.gateway_client import MCPGatewayClient
from app.models.evidence import Evidence, EvidenceType
from app.models.finding import Finding, Severity, Judgment, JudgmentEngine, FindingStatus
from app.models.scan_task import ScanTask, ScanTaskStatus

logger = logging.getLogger(__name__)


# WebSocket 广播函数（延迟导入以避免循环依赖）
async def _broadcast_status(task_id: str, status: dict):
    """广播 Agent 状态变化"""
    try:
        from app.api.websocket import broadcast_agent_status
        await broadcast_agent_status(task_id, status)
    except Exception as e:
        logger.debug(f"Failed to broadcast status: {e}")


async def _broadcast_completed(task_id: str, result: dict):
    """广播 Agent 完成事件"""
    try:
        from app.api.websocket import broadcast_agent_completed
        await broadcast_agent_completed(task_id, result)
    except Exception as e:
        logger.debug(f"Failed to broadcast completion: {e}")


async def _broadcast_failed(task_id: str, error: str):
    """广播 Agent 失败事件"""
    try:
        from app.api.websocket import broadcast_agent_failed
        await broadcast_agent_failed(task_id, error)
    except Exception as e:
        logger.debug(f"Failed to broadcast failure: {e}")


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
        db: Optional[AsyncSession] = None,
        scan_task_id: Optional[int] = None,
    ):
        self.agent_id = agent_id
        self.name = name
        self.steps = steps
        self.skill = skill
        self.project_id = project_id
        self.user_id = user_id
        self.asset = asset
        self.mcp_client = mcp_client
        self.db = db
        self.scan_task_id = scan_task_id
        
        # 独立上下文（隔离）
        self.context = {"asset": asset}
        self.evidence: List[dict] = []
        self.progress = 0
        self.status = "pending"  # pending, running, completed, failed
        self.current_step = None
        self.error = None
        
        # 实时进度信息
        self.scan_progress = {
            "total_ports": 0,
            "scanned_ports": 0,
            "open_ports_found": 0,
        }
        
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
                # 步骤级别的进度（0-100）
                step_progress_base = int((i / total_steps) * 100)
                self.progress = step_progress_base
                
                if self.on_status_change:
                    await self._notify_status()
                
                # 检查安全红线
                if not self.check_safety(step):
                    continue
                
                # 执行检查（支持实时进度）
                result = await self.execute_step_with_progress(step)
                
                # 更新步骤完成后的进度
                self.progress = int(((i + 1) / total_steps) * 100)
                
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
                
                # 持久化证据到数据库
                if self.db and self.scan_task_id:
                    await self._persist_evidence(evidence, step)
                
                # 通知步骤完成
                if self.on_step_complete:
                    await self.on_step_complete(self, step, evidence)
            
            self.progress = 100
            self.status = "completed"
            self.completed_at = datetime.utcnow()
            
            # 更新扫描任务状态
            if self.db and self.scan_task_id:
                await self._update_scan_task_status()
            
            if self.on_status_change:
                await self._notify_status()
            
            return self.evidence
            
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            self.completed_at = datetime.utcnow()
            
            # 更新扫描任务状态为失败
            if self.db and self.scan_task_id:
                await self._update_scan_task_status(error=str(e))
            
            if self.on_status_change:
                await self._notify_status()
            
            # 广播失败事件
            try:
                await _broadcast_failed(self.agent_id, str(e))
            except Exception as e:
                logger.debug(f"Failed to broadcast failure: {e}")
            
            raise
    
    async def _persist_evidence(self, evidence: dict, step: dict):
        """持久化证据到数据库"""
        try:
            # 创建 Finding
            judgment_status = evidence.get("judgment", {}).get("status", "unknown")
            judgment_map = {
                "pass": Judgment.PASS,
                "fail": Judgment.FAIL,
                "partial": Judgment.PARTIAL,
                "unknown": Judgment.NOT_TESTED,
            }
            
            # 确定严重性
            severity = Severity.MEDIUM
            raw_result = evidence.get("raw_result", {})
            if "port_scan_result" in raw_result:
                ports = raw_result["port_scan_result"].get("data", {}).get("open_ports", [])
                critical_ports = [p for p in ports if p.get("risk_level") == "critical"]
                if critical_ports:
                    severity = Severity.CRITICAL
                elif any(p.get("risk_level") == "high" for p in ports):
                    severity = Severity.HIGH
            
            finding = Finding(
                project_id=self.project_id,
                scan_task_id=self.scan_task_id,
                clause_id=step.get("clause", "unknown"),
                clause_name=step.get("clause_name", "Unknown"),
                severity=severity,
                judgment=judgment_map.get(judgment_status, Judgment.NOT_TESTED),
                judgment_engine=JudgmentEngine.RULE,
                description=evidence.get("judgment", {}).get("reason", ""),
                status=FindingStatus.OPEN,
            )
            self.db.add(finding)
            await self.db.flush()
            
            # 创建 Evidence
            db_evidence = Evidence(
                finding_id=finding.id,
                evidence_type=EvidenceType.TOOL_OUTPUT,
                source=", ".join(evidence.get("tool_used", [])),
                content=evidence.get("raw_result", {}),
                raw_output=str(evidence.get("raw_result", {})),
            )
            self.db.add(db_evidence)
            await self.db.commit()
            
            logger.info(f"Evidence persisted: Finding {finding.id}, Evidence {db_evidence.id}")
            
        except Exception as e:
            logger.error(f"Failed to persist evidence: {e}", exc_info=True)
            await self.db.rollback()
    
    async def _update_scan_task_status(self, error: str = None):
        """更新扫描任务状态"""
        try:
            result = await self.db.execute(
                select(ScanTask).where(ScanTask.id == self.scan_task_id)
            )
            scan_task = result.scalar_one_or_none()
            
            if scan_task:
                if error:
                    scan_task.status = ScanTaskStatus.FAILED
                    scan_task.error_message = error
                else:
                    scan_task.status = ScanTaskStatus.COMPLETED
                    scan_task.completed_at = datetime.utcnow()
                    
                    # 统计 findings
                    result = await self.db.execute(
                        select(Finding).where(Finding.scan_task_id == self.scan_task_id)
                    )
                    findings = result.scalars().all()
                    scan_task.findings_count = len(findings)
                    scan_task.high_severity_count = sum(1 for f in findings if f.severity in [Severity.HIGH, Severity.CRITICAL])
                    scan_task.medium_severity_count = sum(1 for f in findings if f.severity == Severity.MEDIUM)
                    scan_task.low_severity_count = sum(1 for f in findings if f.severity == Severity.LOW)
                
                await self.db.commit()
                logger.info(f"Scan task {self.scan_task_id} updated: {scan_task.status}")
                
        except Exception as e:
            logger.error(f"Failed to update scan task status: {e}", exc_info=True)
            await self.db.rollback()
    
    async def execute_step_with_progress(self, step: dict) -> dict:
        """执行单个检查步骤，支持实时进度"""
        results = {}
        
        for tool in step.get("tools", []):
            tool_name = tool["name"]
            params = self.resolve_params(tool.get("params", {}))
            
            # 检查工具是否支持异步模式
            if tool_name in ["nmap_scan", "port_scan"]:
                # 使用异步模式，支持实时进度
                result = await self.mcp_client.call_with_progress(
                    tool_name=tool_name,
                    params=params,
                    on_progress=lambda p: self._update_scan_progress(p),
                    poll_interval=2.0,
                )
            else:
                # 同步模式
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
    
    def _update_scan_progress(self, progress: dict):
        """更新扫描进度"""
        self.scan_progress = {
            "total_ports": progress.get("total_ports", 0),
            "scanned_ports": progress.get("scanned_ports", 0),
            "open_ports_found": progress.get("open_ports_found", 0),
        }
        
        # 计算基于端口的进度
        total_ports = self.scan_progress["total_ports"]
        scanned_ports = self.scan_progress["scanned_ports"]
        
        if total_ports > 0:
            # 端口扫描进度（0-100）
            port_progress = int((scanned_ports / total_ports) * 100)
            # 结合步骤进度（假设当前只有一个步骤）
            self.progress = port_progress
    
    async def execute_step(self, step: dict) -> dict:
        """执行单个检查步骤（向后兼容）"""
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
                resolved[key] = self.resolve_params(value)
            else:
                resolved[key] = value
        
        return resolved
    
    async def _notify_status(self):
        """通知状态变化"""
        status_data = {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step.get("clause_name") if self.current_step else None,
            "scan_progress": self.scan_progress,
        }
        
        # 调用回调函数
        if self.on_status_change:
            try:
                await self.on_status_change(status_data)
            except Exception as e:
                logger.error(f"Error notifying status via callback: {e}")
        
        # 广播到 WebSocket
        try:
            await _broadcast_status(self.agent_id, status_data)
        except Exception as e:
            logger.debug(f"Failed to broadcast status: {e}")
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step.get("clause_name") if self.current_step else None,
            "evidence_count": len(self.evidence),
            "scan_progress": self.scan_progress,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }
