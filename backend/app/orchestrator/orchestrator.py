"""
Orchestrator - 调度中枢（包工头）
负责：AI 意图识别、能力编排、异步执行、AI 结果描述
"""

import asyncio
import uuid
import logging
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.orchestrator.agent import Agent
from app.orchestrator.skill_loader import SkillLoader
from app.mcp.gateway_client import MCPGatewayClient
from app.services.ai_engine import ai_engine
from app.services.execution_engine import execution_engine
from app.services.context_manager import ContextManager
from app.services.llm_service import llm_service
from app.models.scan_task import ScanTask, ScanTaskType, ScanTaskStatus, TriggeredBy
from app.models.finding import Finding
from app.models.project import Project
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class Orchestrator:
    """调度中枢 - 包工头，永远不阻塞"""
    
    def __init__(self):
        self.skill_loader = SkillLoader()
        self.mcp_client = MCPGatewayClient()
        self.ai_engine = ai_engine
        self.execution_engine = execution_engine
        
        # Agent 管理
        self.active_agents: Dict[str, Agent] = {}
        self.completed_tasks: List[dict] = []
        self.task_progress: Dict[str, Dict] = {}
        
        # 回调管理
        self.task_callbacks: Dict[str, Dict[str, Callable]] = {}
        
        # 任务控制
        self.task_stop_flags: Dict[str, bool] = {}  # 停止标志
        self.task_status: Dict[str, str] = {}  # running/paused/stopped
        self.active_tasks: Dict[str, asyncio.Task] = {}  # asyncio Task 引用
    
    async def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        if task_id in self.task_status and self.task_status[task_id] == "running":
            self.task_status[task_id] = "paused"
            logger.info(f"Task {task_id} paused")
            
            try:
                from app.api.websocket import broadcast_agent_status
                await broadcast_agent_status(task_id, {
                    "task_id": task_id,
                    "type": "task_paused",
                    "status": "paused",
                })
            except Exception as e:
                logger.error(f"Failed to broadcast pause: {e}")
            
            return True
        return False
    
    async def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        if task_id in self.task_status and self.task_status[task_id] == "paused":
            self.task_status[task_id] = "running"
            logger.info(f"Task {task_id} resumed")
            
            try:
                from app.api.websocket import broadcast_agent_status
                await broadcast_agent_status(task_id, {
                    "task_id": task_id,
                    "type": "task_resumed",
                    "status": "running",
                })
            except Exception as e:
                logger.error(f"Failed to broadcast resume: {e}")
            
            return True
        return False
    
    async def stop_task(self, task_id: str) -> bool:
        """停止任务"""
        if task_id in self.task_status:
            self.task_stop_flags[task_id] = True
            self.task_status[task_id] = "stopped"
            
            if task_id in self.active_tasks:
                self.active_tasks[task_id].cancel()
            
            try:
                from app.api.websocket import broadcast_agent_failed
                await broadcast_agent_failed(task_id, "任务已停止")
            except Exception as e:
                logger.error(f"Failed to broadcast stop: {e}")
            
            logger.info(f"Task {task_id} stopped")
            return True
        return False
    
    def is_task_stopped(self, task_id: str) -> bool:
        """检查任务是否被停止"""
        return self.task_stop_flags.get(task_id, False)
    
    def get_task_status(self, task_id: str) -> Optional[str]:
        """获取任务状态"""
        return self.task_status.get(task_id)
    
    async def handle_user_input(
        self,
        user_input: str,
        project_id: int,
        user_id: int,
        asset: str = None,
        db: Optional[AsyncSession] = None,
        on_agent_status: Optional[Callable] = None,
        on_agent_complete: Optional[Callable] = None,
        thread_id: int = None,
    ) -> dict:
        """
        处理用户输入 - AI 驱动意图识别和能力编排
        
        流程：
        1. 构建上下文
        2. AI 决策：理解用户需求，生成执行计划
        3. 记录对话历史
        4. 如果有执行计划，异步执行
        5. 立即返回 AI 回复 + task_id
        
        Returns:
            {
                "message": "AI 的即时回复",
                "task_ids": [...],  // 异步任务 ID
                "agents": [],
                "task_id": "xxx",  // 异步任务 ID（如果有）
            }
        """
        if not db:
            return {
                "task_ids": [],
                "agents": [],
                "message": "系统错误：缺少数据库会话",
            }
        
        # 1. 构建上下文
        context_manager = ContextManager(db, user_id, project_id, thread_id)
        context = await context_manager.build_context()
        
        if asset:
            context["default_asset"] = asset
        
        # 2. AI 决策：理解用户需求，生成执行计划
        plan_result = await self.ai_engine.decide(user_input, context, db, user_id)
        
        plan = plan_result.get("plan", [])
        response = plan_result.get("response", "")
        
        logger.info(f"AI plan: {plan}")
        
        # 3. 记录用户输入到对话历史
        await context_manager.add_conversation("user", user_input)
        
        # 4. 记录助手回复到对话历史
        await context_manager.add_conversation("assistant", response)
        
        # 显式提交对话历史，确保持久化
        await db.commit()
        
        # 5. 如果有执行计划，异步执行
        if plan:
            # 检查是否只有纯对话/帮助类能力（不需要异步执行）
            non_async_capabilities = ["chat", "help"]
            has_async_capability = any(
                step.get("capability") not in non_async_capabilities 
                for step in plan
            )
            
            if not has_async_capability:
                # 只有 chat/help，直接返回，不触发异步执行
                return {
                    "task_ids": [],
                    "agents": [],
                    "message": response,
                }
            
            # 生成 task_id
            task_id = str(uuid.uuid4())
            
            logger.info(f"Creating async task {task_id} with plan: {plan}")
            
            # 异步执行计划（不阻塞）
            # ScanTask 将在异步任务内创建，避免提前创建导致空记录
            task = asyncio.create_task(self._execute_plan_async(
                task_id=task_id,
                plan=plan,
                user_id=user_id,
                project_id=project_id,
                db=db,
                context_manager=context_manager,
                ai_response=response,
                user_input=user_input,
                thread_id=thread_id,
            ))
            logger.info(f"Async task {task_id} created successfully")
            
            # 立即返回 AI 回复 + task_id
            return {
                "task_ids": [task_id],
                "agents": [],
                "message": response,
                "task_id": task_id,
            }
        else:
            # 没有执行计划，直接返回回复
            return {
                "task_ids": [],
                "agents": [],
                "message": response,
            }
    
    async def _execute_plan_async(
        self,
        task_id: str,
        plan: List[Dict],
        user_id: int,
        project_id: int,
        db: AsyncSession,
        context_manager: ContextManager,
        ai_response: str = "",
        user_input: str = "",
        thread_id: int = None,
    ):
        """异步执行计划，完成后用 AI 生成结果描述"""
        # 初始化任务控制状态
        self.task_stop_flags[task_id] = False
        self.task_status[task_id] = "running"
        
        # 创建停止检查回调
        def check_stop():
            return self.is_task_stopped(task_id)
        
        # 创建暂停检查回调（异步等待直到恢复或停止）
        async def wait_if_paused():
            while self.task_status.get(task_id) == "paused":
                if self.is_task_stopped(task_id):
                    return True
                await asyncio.sleep(0.5)
            return self.is_task_stopped(task_id)
        
        # 创建新的数据库会话用于异步任务
        async with AsyncSessionLocal() as async_db:
            scan_task_id = None
            try:
                logger.info(f"Task {task_id} started")
                
                # 创建扫描任务记录（如果是扫描类）
                scan_capabilities = ["scan_ports", "scan_ssl", "scan_vulnerabilities", 
                                   "scan_weak_passwords", "full_compliance_scan"]
                has_scan = any(step.get("capability") in scan_capabilities for step in plan)
                
                if has_scan and project_id:
                    scan_task = ScanTask(
                        project_id=project_id,
                        task_type=ScanTaskType.FULL,
                        status=ScanTaskStatus.RUNNING,
                        triggered_by=TriggeredBy.MANUAL,
                        parameters={"plan": plan},
                    )
                    async_db.add(scan_task)
                    await async_db.commit()
                    await async_db.refresh(scan_task)
                    scan_task_id = scan_task.id
                
                # 初始化任务进度
                self.task_progress[task_id] = {
                    "current_step": "准备执行...",
                    "step_index": 0,
                    "total_steps": len(plan),
                    "steps": [],
                }
                
                try:
                    from app.api.websocket import broadcast_agent_status
                    await broadcast_agent_status(task_id, {
                        "task_id": task_id,
                        "status": "running",
                        "total_steps": len(plan),
                    })
                except Exception:
                    pass
                
                # 创建新的上下文管理器使用新的数据库会话
                async_context_manager = ContextManager(async_db, user_id, project_id, thread_id)
                
                # 检测是否为多资产扫描
                is_multi_asset = self._is_multi_asset_scan(plan)
                
                # 执行计划（传入停止检查回调）
                if is_multi_asset:
                    # 多资产并发执行
                    execution_result = await self.execution_engine.execute_plan_concurrent(
                        plan=plan,
                        user_id=user_id,
                        project_id=project_id,
                        db=async_db,
                        context_manager=async_context_manager,
                        task_id=task_id,
                        progress_callback=self._update_task_progress_multi_asset,
                        max_concurrent=5,
                        max_retries=3,
                        check_stop=check_stop,
                        wait_if_paused=wait_if_paused,
                    )
                else:
                    # 单资产串行执行
                    execution_result = await self.execution_engine.execute_plan(
                        plan=plan,
                        user_id=user_id,
                        project_id=project_id,
                        db=async_db,
                        context_manager=async_context_manager,
                        task_id=task_id,
                        progress_callback=self._update_task_progress,
                        check_stop=check_stop,
                        wait_if_paused=wait_if_paused,
                    )
                
                # 提取扫描结果
                scan_results = self._extract_scan_results_from_execution(execution_result)
                
                # 用 AI 生成结果描述
                result_description = await self._generate_result_description(
                    execution_result=execution_result,
                    ai_response=ai_response,
                    context_manager=async_context_manager,
                    db=async_db,
                    user_id=user_id,
                )
                
                # 更新扫描任务状态
                if scan_task_id:
                    result = await async_db.execute(
                        select(ScanTask).where(ScanTask.id == scan_task_id)
                    )
                    scan_task = result.scalar_one_or_none()
                    if scan_task:
                        scan_task.status = ScanTaskStatus.COMPLETED
                        scan_task.completed_at = datetime.utcnow()
                        await async_db.commit()
                
                # 计算合规分数并更新 Project
                if project_id and scan_results.get("open_ports"):
                    await self._calculate_and_update_score(async_db, project_id)
                
                # 记录项目记忆
                if project_id:
                    await self._record_project_memory(
                        async_context_manager, plan, execution_result, scan_results
                    )
                
                # 记录用户记忆
                await self._record_user_memory(
                    async_context_manager, user_input, execution_result
                )
                
                # 记录完成的任务
                self.completed_tasks.append({
                    "task_id": task_id,
                    "agent_name": "AI 执行任务",
                    "result": execution_result,
                    "evidence_count": execution_result.get("success_count", 0),
                    "scan_results": scan_results,
                    "result_description": result_description,
                    "completed_at": datetime.utcnow().isoformat(),
                })
                
                # 清理进度记录
                if task_id in self.task_progress:
                    del self.task_progress[task_id]
                
                try:
                    from app.api.websocket import broadcast_agent_completed
                    await broadcast_agent_completed(task_id, {
                        "task_id": task_id,
                        "result_description": result_description,
                        "scan_results": scan_results,
                    })
                except Exception:
                    pass
                
                # 记录助手结果到对话历史
                await async_context_manager.add_conversation("assistant", result_description)
                await async_db.commit()
                
                logger.info(f"Task {task_id} completed: {result_description[:100]}")
                
            except (Exception, asyncio.CancelledError) as e:
                if isinstance(e, asyncio.CancelledError):
                    logger.info(f"Task {task_id} was cancelled")
                else:
                    logger.error(f"Task {task_id} failed: {str(e)}", exc_info=True)
                
                # 记录失败
                self.completed_tasks.append({
                    "task_id": task_id,
                    "agent_name": "AI 执行任务",
                    "result": {"error": str(e)},
                    "evidence_count": 0,
                    "scan_results": {},
                    "result_description": f"任务执行失败：{str(e)}",
                    "completed_at": datetime.utcnow().isoformat(),
                })
                
                # 清理进度记录
                if task_id in self.task_progress:
                    del self.task_progress[task_id]
                
                try:
                    from app.api.websocket import broadcast_agent_failed
                    await broadcast_agent_failed(task_id, str(e))
                except Exception:
                    pass
                
                # 更新扫描任务状态为失败
                if scan_task_id:
                    result = await async_db.execute(
                        select(ScanTask).where(ScanTask.id == scan_task_id)
                    )
                    scan_task = result.scalar_one_or_none()
                    if scan_task:
                        scan_task.status = ScanTaskStatus.FAILED
                        scan_task.error_message = str(e)
                        await async_db.commit()
    
    def _update_task_progress(self, task_id: str, step_index: int, total_steps: int, capability_name: str, status: str):
        """更新任务执行进度"""
        if task_id not in self.task_progress:
            self.task_progress[task_id] = {
                "current_step": "",
                "step_index": 0,
                "total_steps": total_steps,
                "steps": [],
            }
        
        capability_display_names = {
            "scan_ports": "端口扫描",
            "scan_ssl": "SSL/TLS 检测",
            "scan_vulnerabilities": "漏洞扫描",
            "scan_weak_passwords": "弱口令检测",
            "full_compliance_scan": "全量合规扫描",
            "view_open_ports": "查看开放端口",
            "view_scan_results": "查看扫描结果",
            "view_vulnerabilities": "查看漏洞",
            "view_findings": "查看合规发现",
            "view_compliance_score": "查看合规评分",
            "view_scan_history": "查看扫描历史",
            "create_project": "创建项目",
            "list_projects": "列出项目",
            "update_project": "更新项目",
            "delete_project": "删除项目",
            "add_asset": "添加资产",
            "list_assets": "列出资产",
            "verify_asset": "验证资产",
            "create_remediation_ticket": "创建整改工单",
            "list_remediation_tickets": "列出整改工单",
            "update_ticket_status": "更新工单状态",
            "generate_pdf_report": "生成 PDF 报告",
            "generate_json_report": "生成 JSON 报告",
            "create_scheduled_scan": "创建定时扫描",
            "list_scheduled_scans": "列出定时扫描",
            "trigger_scheduled_scan": "触发定时扫描",
            "help": "显示帮助",
            "chat": "对话",
        }
        
        display_name = capability_display_names.get(capability_name, capability_name)
        
        if status == "running":
            self.task_progress[task_id]["current_step"] = f"正在执行: {display_name}..."
        elif status == "completed":
            self.task_progress[task_id]["current_step"] = f"已完成: {display_name}"
        elif status == "failed":
            self.task_progress[task_id]["current_step"] = f"失败: {display_name}"
        
        self.task_progress[task_id]["step_index"] = step_index
        self.task_progress[task_id]["total_steps"] = total_steps
        self.task_progress[task_id]["steps"].append({
            "capability": capability_name,
            "display_name": display_name,
            "status": status,
        })
        
        try:
            import asyncio
            from app.api.websocket import broadcast_agent_status
            asyncio.create_task(broadcast_agent_status(task_id, {
                "task_id": task_id,
                "status": status,
                "step_index": step_index,
                "total_steps": total_steps,
                "capability": capability_name,
                "display_name": display_name,
            }))
        except Exception:
            pass
    
    def _is_multi_asset_scan(self, plan: List[Dict]) -> bool:
        """
        检测是否为多资产扫描
        
        判断标准：plan 中有多个步骤，且都是相同的扫描能力
        """
        if len(plan) <= 1:
            return False
        
        scan_capabilities = ["scan_ports", "scan_ssl", "scan_vulnerabilities", 
                           "scan_weak_passwords", "full_compliance_scan"]
        
        # 检查是否所有步骤都是扫描能力
        all_scan = all(step.get("capability") in scan_capabilities for step in plan)
        
        # 检查是否有不同的目标
        targets = set()
        for step in plan:
            target = step.get("parameters", {}).get("target")
            if target:
                targets.add(target)
        
        return all_scan and len(targets) > 1
    
    def _update_task_progress_multi_asset(
        self, 
        task_id: str, 
        asset_index: int, 
        total_assets: int, 
        asset_name: str, 
        status: str,
        capability_name: str = None
    ):
        """更新多资产任务进度"""
        # 线程安全的初始化
        if task_id not in self.task_progress:
            self.task_progress[task_id] = {
                "type": "multi_asset",
                "asset_index": 0,
                "total_assets": total_assets,
                "assets": [],
            }
        
        # 确保 assets 列表存在（防止并发初始化问题）
        if "assets" not in self.task_progress[task_id]:
            self.task_progress[task_id]["assets"] = []
        
        # 更新资产状态
        asset_progress = {
            "index": asset_index,
            "name": asset_name,
            "capability": capability_name,
            "status": status,
        }
        
        # 更新或添加资产进度
        assets_list = self.task_progress[task_id].get("assets", [])
        existing = next(
            (a for a in assets_list if a.get("index") == asset_index), 
            None
        )
        if existing:
            existing.update(asset_progress)
        else:
            assets_list.append(asset_progress)
        
        self.task_progress[task_id]["asset_index"] = asset_index
        
        # WebSocket 推送
        try:
            import asyncio
            from app.api.websocket import broadcast_agent_status
            asyncio.create_task(broadcast_agent_status(task_id, {
                "task_id": task_id,
                "type": "multi_asset_progress",
                "asset_index": asset_index,
                "total_assets": total_assets,
                "asset_name": asset_name,
                "status": status,
                "capability": capability_name,
            }))
        except Exception:
            pass
    
    async def _record_project_memory(
        self,
        context_manager: ContextManager,
        plan: List[Dict],
        execution_result: Dict,
        scan_results: Dict,
    ):
        """根据执行结果记录项目记忆"""
        try:
            scan_capabilities = ["scan_ports", "scan_ssl", "scan_vulnerabilities",
                                 "scan_weak_passwords", "full_compliance_scan"]
            executed_scans = [s for s in plan if s.get("capability") in scan_capabilities]
            
            if executed_scans:
                parts = []
                open_ports = scan_results.get("open_ports", [])
                if open_ports:
                    parts.append(f"发现 {len(open_ports)} 个开放端口")
                
                vulns = scan_results.get("vulnerabilities", [])
                if vulns:
                    parts.append(f"发现 {len(vulns)} 个漏洞")
                
                ssl_issues = scan_results.get("ssl_issues", [])
                if ssl_issues:
                    parts.append(f"发现 {len(ssl_issues)} 个 SSL 问题")
                
                if parts:
                    summary = f"扫描结果: {', '.join(parts)}"
                    await context_manager.add_project_memory(
                        memory_type="scan_summary",
                        content=summary,
                    )
            
            remediation_capabilities = ["create_remediation_ticket", "list_remediation_tickets",
                                        "update_ticket_status"]
            executed_remediation = [s for s in plan if s.get("capability") in remediation_capabilities]
            if executed_remediation:
                await context_manager.add_project_memory(
                    memory_type="remediation_status",
                    content=f"执行了 {len(executed_remediation)} 个整改操作",
                )
        except Exception as e:
            logger.warning(f"Failed to record project memory: {e}")
    
    async def _record_user_memory(
        self,
        context_manager: ContextManager,
        user_input: str,
        execution_result: Dict,
    ):
        """从用户交互中提取偏好，记录到用户记忆"""
        try:
            scan_capabilities = ["scan_ports", "scan_ssl", "scan_vulnerabilities",
                                 "scan_weak_passwords", "full_compliance_scan"]
            executed_scans = [s for s in execution_result.get("results", []) 
                             if s.get("capability") in scan_capabilities and s.get("status") == "success"]
            
            if executed_scans:
                targets = [s.get("target", "") for s in executed_scans if s.get("target")]
                if targets:
                    await context_manager.add_user_memory(
                        memory_type="scan_targets",
                        content=f"常用扫描目标: {', '.join(set(targets))}",
                    )
            
            if "创建项目" in user_input or "create_project" in str(execution_result):
                await context_manager.add_user_memory(
                    memory_type="preferences",
                    content="用户倾向于创建新项目进行管理",
                )
        except Exception as e:
            logger.warning(f"Failed to record user memory: {e}")
    
    async def _generate_result_description(
        self,
        execution_result: Dict,
        ai_response: str,
        context_manager: ContextManager,
        db: AsyncSession,
        user_id: int,
    ) -> str:
        """用 AI 根据执行结果生成自然语言描述"""
        try:
            # 获取对话历史
            conversation_history = await context_manager._get_conversation_history(limit=5)
            
            # 构建执行结果摘要
            results_summary = self._summarize_execution_result(execution_result)
            
            # 如果执行结果为空或只有 chat 能力，直接返回 AI 原始回复
            if not results_summary or results_summary == "无具体结果":
                return ai_response
            
            # 构建 prompt
            prompt = f"""根据执行结果，用简洁的中文描述结果。

对话历史：
{self._format_history(conversation_history)}

执行结果：
{results_summary}

请用简洁的中文描述执行结果，包含具体的数据（如端口列表、漏洞数量等）。直接输出描述内容，不要加引号或其他格式。"""
            
            # 调用 LLM 生成描述
            messages = [
                {"role": "system", "content": "你是 CertiProof 等保合规智能助手，负责描述任务执行结果。"},
                {"role": "user", "content": prompt},
            ]
            
            import asyncio
            try:
                response = await asyncio.wait_for(
                    self.ai_engine._call_llm_direct(db, messages),
                    timeout=45.0
                )
                description = response.get("content", "").strip()
                
                # 清理 <think> 标签
                import re
                description = re.sub(r'<think>.*?</think>', '', description, flags=re.DOTALL).strip()
                
                if description:
                    return description
                else:
                    return self._generate_fallback_description(execution_result)
            except asyncio.TimeoutError:
                logger.warning("Result description LLM timed out (45s), using fallback")
                return self._generate_fallback_description(execution_result)
            
        except Exception as e:
            logger.error(f"Failed to generate result description: {e}", exc_info=True)
            return self._generate_fallback_description(execution_result)
    
    def _summarize_execution_result(self, execution_result: Dict) -> str:
        """摘要执行结果用于 AI 描述"""
        results = execution_result.get("results", [])
        if not results:
            return "无具体结果"
        
        parts = []
        for result in results:
            status = result.get("status")
            capability = result.get("capability")
            target = result.get("target", "")
            data = result.get("result", {})
            
            if status != "success":
                error = result.get("error", "未知错误")
                target_str = f"({target})" if target else ""
                parts.append(f"{capability}{target_str}: 失败 - {error}")
                continue
            
            if capability == "scan_ports":
                open_ports = data.get("open_ports", [])
                host_status = data.get("host_status", "unknown")
                target_str = f"({target})" if target else ""
                if open_ports:
                    port_list = ", ".join([f"{p['port']}/{p.get('protocol', 'tcp')} ({p.get('service', 'unknown')})" for p in open_ports])
                    parts.append(f"端口扫描{target_str}: 主机可达，发现 {len(open_ports)} 个开放端口：{port_list}")
                elif host_status == "up":
                    parts.append(f"端口扫描{target_str}: 主机可达，未发现开放端口")
                else:
                    parts.append(f"端口扫描{target_str}: 主机状态未知，未发现开放端口")
            
            elif capability == "scan_ssl":
                issues = data.get("issues", [])
                tls_version = data.get("tls_version")
                parts.append(f"SSL 检测：TLS 版本={tls_version}, 问题数={len(issues)}")
            
            elif capability == "scan_vulnerabilities":
                findings = data.get("findings", [])
                parts.append(f"漏洞扫描：发现 {len(findings)} 个漏洞")
            
            elif capability == "scan_weak_passwords":
                found = data.get("found", [])
                parts.append(f"弱口令检测：发现 {len(found)} 个弱口令")
            
            elif capability == "view_open_ports":
                open_ports = data.get("open_ports", [])
                if open_ports:
                    port_list = ", ".join([f"{p['port']}/{p.get('protocol', 'tcp')} ({p.get('service', 'unknown')})" for p in open_ports])
                    parts.append(f"开放端口：共 {len(open_ports)} 个，{port_list}")
                else:
                    parts.append("开放端口：无")
            
            elif capability == "view_scan_results":
                recent_scans = data.get("recent_scans", [])
                parts.append(f"扫描结果：共 {len(recent_scans)} 条记录")
            
            elif capability == "list_projects":
                projects = data.get("projects", [])
                project_list = ", ".join([f"{p['name']}(ID:{p['id']})" for p in projects[:5]])
                parts.append(f"项目列表：{project_list}")
            
            elif capability == "create_project":
                parts.append(f"项目创建成功：{data.get('name', '未知')}")
            
            elif capability == "chat":
                msg = data.get("message", "")
                if msg:
                    parts.append(msg)
            
            elif capability == "help":
                parts.append("显示帮助信息")
            
            else:
                parts.append(f"{capability}: 执行完成")
        
        return "\n".join(parts) if parts else "无具体结果"
    
    def _generate_fallback_description(self, execution_result: Dict) -> str:
        """降级方案：硬编码的结果描述"""
        results = execution_result.get("results", [])
        success_count = execution_result.get("success_count", 0)
        
        parts = []
        for result in results:
            status = result.get("status")
            capability = result.get("capability")
            target = result.get("target", "")
            data = result.get("result", {})
            
            if status != "success":
                error = result.get("error", "未知错误")
                target_str = f"({target})" if target else ""
                parts.append(f"扫描失败：{capability}{target_str} - {error}")
                continue
            
            if capability == "scan_ports":
                open_ports = data.get("open_ports", [])
                host_status = data.get("host_status", "unknown")
                target_str = f"({target})" if target else ""
                if open_ports:
                    parts.append(f"端口扫描{target_str}: 主机可达，发现 {len(open_ports)} 个开放端口：")
                    for port in open_ports[:5]:
                        parts.append(f"  - {port['port']}/{port.get('protocol', 'tcp')}: {port.get('service', 'unknown')}")
                    if len(open_ports) > 5:
                        parts.append(f"  ... 还有 {len(open_ports) - 5} 个")
                elif host_status == "up":
                    parts.append(f"端口扫描{target_str}: 主机可达，未发现开放端口")
                else:
                    parts.append(f"端口扫描{target_str}: 主机状态未知")
            
            elif capability == "view_open_ports":
                open_ports = data.get("open_ports", [])
                if open_ports:
                    parts.append(f"开放端口：")
                    for port in open_ports[:5]:
                        parts.append(f"  - {port['port']}/{port.get('protocol', 'tcp')}: {port.get('service', 'unknown')}")
            
            elif capability == "list_projects":
                projects = data.get("projects", [])
                if projects:
                    parts.append("项目列表：")
                    for p in projects[:5]:
                        parts.append(f"  - {p['name']} (ID: {p['id']})")
            
            elif capability == "chat":
                msg = data.get("message", "")
                if msg:
                    return msg
        
        return "\n".join(parts) if parts else f"任务执行完成（成功 {success_count} 个）"
    
    def _format_history(self, history: List[Dict]) -> str:
        """格式化对话历史"""
        if not history:
            return "（无对话历史）"
        lines = []
        for h in history[-5:]:
            role = "用户" if h["role"] == "user" else "助手"
            lines.append(f"{role}: {h['content']}")
        return "\n".join(lines)
    
    def _extract_scan_results_from_execution(self, execution_result: dict) -> dict:
        """从执行结果中提取扫描结果
        
        判断逻辑（基于实际扫描结果，不依赖 nmap 的主机检测）：
        - 有开放端口 → success（主机确实可达）
        - 无开放端口但扫描完成 → warning（可能不可达，或无服务）
        - 扫描超时/失败 → failed
        """
        results = {
            "open_ports": [],
            "vulnerabilities": [],
            "ssl_issues": [],
            "compliance_score": None,
            "asset_results": {},  # 按资产分组的结果
        }
        
        for result in execution_result.get("results", []):
            target = result.get("target", "unknown")
            status = result.get("status")
            data = result.get("result", {})
            error = result.get("error")
            
            # 初始化资产结果
            if target not in results["asset_results"]:
                results["asset_results"][target] = {
                    "status": status,
                    "result": {},
                    "error": error,
                }
            
            if status == "success":
                # 更新资产状态
                results["asset_results"][target]["status"] = "success"
                results["asset_results"][target]["result"] = data
                
                # 判断显示状态：基于实际扫描结果，不依赖 host_status
                open_ports = data.get("open_ports", [])
                
                if len(open_ports) > 0:
                    # 有开放端口 → 主机确实可达
                    results["asset_results"][target]["display_status"] = "success"
                else:
                    # 无开放端口 → 可能不可达，或防火墙过滤，或无服务
                    results["asset_results"][target]["display_status"] = "warning"
                
                # 合并到全局结果（保持向后兼容）
                if "open_ports" in data:
                    results["open_ports"].extend(data["open_ports"])
                if "findings" in data:
                    results["vulnerabilities"].extend(data["findings"])
                if "issues" in data:
                    results["ssl_issues"].extend(data["issues"])
                if "compliance_score" in data:
                    results["compliance_score"] = data["compliance_score"]
            else:
                # 失败的情况（扫描超时、网络错误等）
                results["asset_results"][target]["status"] = "failed"
                results["asset_results"][target]["display_status"] = "failed"
                results["asset_results"][target]["error"] = error
        
        return results
    
    async def _calculate_and_update_score(self, db: AsyncSession, project_id: int):
        """计算合规分数并更新 Project"""
        try:
            result = await db.execute(
                select(Finding).where(Finding.project_id == project_id)
            )
            findings = result.scalars().all()
            
            if not findings:
                return
            
            passed = sum(1 for f in findings if f.judgment and f.judgment.value == "pass")
            total = len(findings)
            
            score = int((passed / total) * 100) if total > 0 else 0
            
            result = await db.execute(
                select(Project).where(Project.id == project_id)
            )
            project = result.scalar_one_or_none()
            
            if project:
                project.compliance_score = score
                await db.commit()
                logger.info(f"Project {project_id} compliance score updated: {score}")
            
        except Exception as e:
            logger.error(f"Failed to calculate score for project {project_id}: {e}", exc_info=True)
            await db.rollback()
    
    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "running": [
                {
                    "agent_id": tid,
                    "name": "AI 执行任务",
                    "status": "running",
                    "progress": 0,
                }
                for tid in self.active_agents
            ],
            "completed": [
                {
                    "task_id": t["task_id"],
                    "agent_name": t["agent_name"],
                    "evidence_count": t.get("evidence_count", 0),
                    "scan_results": t.get("scan_results", {}),
                    "result_description": t.get("result_description", ""),
                    "completed_at": t["completed_at"],
                }
                for t in self.completed_tasks
            ],
        }


# 全局单例
orchestrator = Orchestrator()
