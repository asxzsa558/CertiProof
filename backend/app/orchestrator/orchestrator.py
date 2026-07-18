"""
Orchestrator - 调度中枢（包工头）
负责：AI 意图识别、能力编排、异步执行、AI 结果描述
"""

import asyncio
import json
import re
import uuid
import logging
import socket
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_

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
from app.core.config import settings
from app.core.redaction import redact_sensitive
from app.services.audit import record_audit_event
from app.services.asset_scope import target_identity

logger = logging.getLogger(__name__)


class Orchestrator:
    """调度中枢 - 包工头，永远不阻塞"""

    SCAN_CAPABILITIES = {
        "scan_ports", "masscan_scan", "fping_scan", "scan_ssl",
        "scan_vulnerabilities", "scan_weak_passwords",
        "nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan", "web_discovery_scan",
        "database_security_scan", "redis_check", "mysql_check", "mongodb_check", "oracle_check", "memcached_check",
        "snmp_walk", "snmp_get", "snmp_bruteforce", "network_device_scan",
        "enum4linux_scan", "crackmapexec_scan", "smb_enum", "windows_security_scan",
        "baseline_check", "linux_baseline", "ssh_config_check",
        "full_compliance_scan", "tech_assessment",
    }
    
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
        self.task_metadata: Dict[str, Dict[str, Any]] = {}
        self.worker_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
    
    async def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        if task_id in self.task_status and self.task_status[task_id] == "running":
            self.task_status[task_id] = "paused"
            self._update_task_metadata(task_id, status="paused")
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
            self._update_task_metadata(task_id, status="running")
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
            self._update_task_metadata(
                task_id,
                status="stopped",
                completed_at=datetime.utcnow().isoformat(),
            )
            
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
        return self.task_status.get(task_id) or self.get_task_metadata(task_id).get("status")

    def get_task_metadata(self, task_id: str) -> Dict[str, Any]:
        """获取任务归属和状态元数据"""
        if task_id in self.task_metadata:
            return self.task_metadata[task_id]
        if task_id in self.task_progress:
            return self.task_progress[task_id]
        for task in reversed(self.completed_tasks):
            if task.get("task_id") == task_id:
                return task
        return {}

    def _update_task_metadata(self, task_id: str, **values: Any) -> None:
        metadata = self.task_metadata.setdefault(task_id, {"task_id": task_id})
        metadata.update(values)

    def _plan_has_scan(self, plan: List[Dict]) -> bool:
        return any(step.get("capability") in self.SCAN_CAPABILITIES for step in plan)

    async def _create_scan_task_record(
        self,
        db: AsyncSession,
        project_id: int,
        plan: List[Dict],
        task_id: str,
        *,
        user_id: Optional[int] = None,
        thread_id: Optional[int] = None,
        ai_response: str = "",
        user_input: str = "",
        status: ScanTaskStatus = ScanTaskStatus.RUNNING,
        task_type: ScanTaskType = ScanTaskType.FULL,
        asset_id: Optional[int] = None,
    ) -> Optional[int]:
        if not db or not project_id or not self._plan_has_scan(plan):
            return None

        scan_task = ScanTask(
            project_id=project_id,
            asset_id=asset_id,
            task_type=task_type,
            status=status,
            triggered_by=TriggeredBy.MANUAL,
            parameters={
                "plan": plan,
                "orchestrator_task_id": task_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "ai_response": ai_response,
                "user_input": user_input,
            },
            orchestrator_task_id=task_id,
            progress={
                "task_id": task_id,
                "status": status.value,
                "current_step": "等待 worker 执行..." if status == ScanTaskStatus.PENDING else "准备执行...",
                "step_index": 0,
                "total_steps": len(plan),
                "steps": [],
            },
            control_state="queued" if status == ScanTaskStatus.PENDING else "running",
            checkpoint={"completed_results": [], "updated_at": datetime.utcnow().isoformat()},
            started_at=datetime.utcnow() if status == ScanTaskStatus.RUNNING else None,
        )
        db.add(scan_task)
        from app.services.report_service import invalidate_report_artifacts
        await invalidate_report_artifacts(db, project_id, "已发起新的安全检测")
        await db.commit()
        await db.refresh(scan_task)
        return scan_task.id

    async def start_async_plan(
        self,
        plan: List[Dict],
        user_id: int,
        project_id: int,
        db: AsyncSession,
        context_manager: Optional[ContextManager] = None,
        ai_response: str = "",
        user_input: str = "",
        thread_id: int = None,
        task_type: ScanTaskType = ScanTaskType.FULL,
        asset_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create one tracked async execution and return its identifiers."""
        if project_id:
            from app.services.asset_scope import scope_plan_to_project_assets
            plan = await scope_plan_to_project_assets(db, project_id, plan)
        task_id = str(uuid.uuid4())
        worker_mode = settings.TASK_EXECUTION_MODE == "worker"
        scan_task_id = await self._create_scan_task_record(
            db,
            project_id,
            plan,
            task_id,
            user_id=user_id,
            thread_id=thread_id,
            ai_response=ai_response,
            user_input=user_input,
            status=ScanTaskStatus.PENDING if worker_mode else ScanTaskStatus.RUNNING,
            task_type=task_type,
            asset_id=asset_id,
        )
        if scan_task_id:
            await record_audit_event(
                db,
                event_type="scan.queued",
                resource_type="scan_task",
                resource_id=scan_task_id,
                actor_user_id=user_id,
                project_id=project_id,
                details={"orchestrator_task_id": task_id, "step_count": len(plan)},
            )
            await db.commit()
        self.task_stop_flags[task_id] = False
        self.task_status[task_id] = "running"
        self._update_task_metadata(
            task_id,
            user_id=user_id,
            project_id=project_id,
            scan_task_id=scan_task_id,
            status="running",
            created_at=datetime.utcnow().isoformat(),
        )

        if worker_mode and scan_task_id:
            logger.info("Queued task %s for worker execution", task_id)
            return {"task_id": task_id, "scan_task_id": scan_task_id}

        task = asyncio.create_task(self._execute_plan_async(
            task_id=task_id,
            plan=plan,
            user_id=user_id,
            project_id=project_id,
            db=db,
            context_manager=context_manager,
            ai_response=ai_response,
            user_input=user_input,
            thread_id=thread_id,
            scan_task_id=scan_task_id,
        ))
        self.active_tasks[task_id] = task
        return {"task_id": task_id, "scan_task_id": scan_task_id}

    async def _persist_scan_task_state(
        self,
        db: AsyncSession,
        scan_task_id: Optional[int],
        *,
        status: Optional[ScanTaskStatus] = None,
        progress: Optional[Dict[str, Any]] = None,
        result_summary: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
        control_state: Optional[str] = None,
    ) -> None:
        if not scan_task_id:
            return
        result = await db.execute(select(ScanTask).where(ScanTask.id == scan_task_id))
        scan_task = result.scalar_one_or_none()
        if not scan_task:
            return
        if status:
            scan_task.status = status
        if progress is not None:
            scan_task.progress = progress
        if result_summary is not None:
            scan_task.result_summary = result_summary
        if checkpoint is not None:
            scan_task.checkpoint = checkpoint
        if error_message is not None:
            scan_task.error_message = error_message
        if completed_at is not None:
            scan_task.completed_at = completed_at
        if control_state is not None:
            scan_task.control_state = control_state
        elif status == ScanTaskStatus.RUNNING and scan_task.control_state in (None, "queued", "running"):
            scan_task.control_state = "running"
        if status in (ScanTaskStatus.COMPLETED, ScanTaskStatus.FAILED, ScanTaskStatus.CANCELLED):
            scan_task.lease_owner = None
            scan_task.lease_expires_at = None
            scan_task.control_state = {
                ScanTaskStatus.COMPLETED: "completed",
                ScanTaskStatus.FAILED: "failed",
                ScanTaskStatus.CANCELLED: "cancelled",
            }[status]
        elif status == ScanTaskStatus.RUNNING and scan_task.control_state != "paused":
            scan_task.lease_owner = self.worker_id
            scan_task.lease_expires_at = datetime.utcnow() + timedelta(minutes=settings.TASK_LEASE_MINUTES)
        await db.commit()

    async def _persist_step_outcome(
        self,
        scan_task_id: Optional[int],
        step_index: int,
        outcome: Dict[str, Any],
    ) -> None:
        """Persist successful substeps so a restarted worker does not rerun them."""
        if not scan_task_id:
            return
        async with AsyncSessionLocal() as checkpoint_db:
            result = await checkpoint_db.execute(select(ScanTask).where(ScanTask.id == scan_task_id))
            scan_task = result.scalar_one_or_none()
            if not scan_task or scan_task.status not in (ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING):
                return
            checkpoint = dict(scan_task.checkpoint or {})
            completed = [item for item in checkpoint.get("completed_results", []) if item.get("index") != step_index]
            completed.append({
                "index": step_index,
                "capability": outcome.get("capability"),
                "target": outcome.get("target"),
                "parameters": redact_sensitive(outcome.get("parameters") or {}),
                "status": outcome.get("status"),
                "result": redact_sensitive(outcome.get("result") or {}),
                "error": outcome.get("error"),
            })
            checkpoint["completed_results"] = sorted(completed, key=lambda item: item["index"])
            checkpoint["updated_at"] = datetime.utcnow().isoformat()
            scan_task.checkpoint = checkpoint
            progress = dict(scan_task.progress or {})
            progress.update({
                "status": "running",
                "step_index": step_index,
                "current_step": f"已记录检查点: {outcome.get('capability') or '安全检测'}",
            })
            scan_task.progress = progress
            scan_task.lease_owner = self.worker_id
            scan_task.lease_expires_at = datetime.utcnow() + timedelta(minutes=settings.TASK_LEASE_MINUTES)
            await checkpoint_db.commit()

    async def recover_incomplete_scan_tasks(self, db: AsyncSession, limit: int = 20) -> int:
        """Restart persisted orchestrator tasks left running by a process restart."""
        now = datetime.utcnow()
        result = await db.execute(
            select(ScanTask)
            .where(
                ScanTask.orchestrator_task_id.is_not(None),
                ScanTask.status.in_([ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING]),
                or_(ScanTask.control_state.is_(None), ScanTask.control_state.notin_(["paused", "cancelled"])),
                or_(ScanTask.lease_expires_at.is_(None), ScanTask.lease_expires_at < now),
            )
            .order_by(ScanTask.created_at.asc())
            .limit(limit)
        )
        recovered = 0
        for scan_task in result.scalars().all():
            task_id = scan_task.orchestrator_task_id
            if not task_id or task_id in self.active_tasks:
                continue
            claim_result = await db.execute(
                update(ScanTask)
                .where(
                    ScanTask.id == scan_task.id,
                    ScanTask.status.in_([ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING]),
                    or_(ScanTask.control_state.is_(None), ScanTask.control_state.notin_(["paused", "cancelled"])),
                    or_(ScanTask.lease_expires_at.is_(None), ScanTask.lease_expires_at < now),
                )
                .values(
                    lease_owner=self.worker_id,
                    lease_expires_at=now + timedelta(minutes=settings.TASK_LEASE_MINUTES),
                )
            )
            if claim_result.rowcount != 1:
                continue
            await db.commit()
            await db.refresh(scan_task)

            parameters = scan_task.parameters or {}
            plan = parameters.get("plan") or []
            if not isinstance(plan, list) or not plan:
                scan_task.status = ScanTaskStatus.FAILED
                scan_task.control_state = "failed"
                scan_task.error_message = "任务缺少可恢复的执行计划"
                scan_task.completed_at = datetime.utcnow()
                scan_task.lease_owner = None
                scan_task.lease_expires_at = None
                continue

            project_result = await db.execute(select(Project).where(Project.id == scan_task.project_id))
            project = project_result.scalar_one_or_none()
            if not project:
                scan_task.status = ScanTaskStatus.FAILED
                scan_task.control_state = "failed"
                scan_task.error_message = "任务所属项目不存在，无法恢复"
                scan_task.completed_at = datetime.utcnow()
                scan_task.lease_owner = None
                scan_task.lease_expires_at = None
                continue

            user_id = parameters.get("user_id") or project.owner_id or project.user_id
            thread_id = parameters.get("thread_id")
            ai_response = parameters.get("ai_response") or "任务已从持久化队列恢复执行"
            user_input = parameters.get("user_input") or "恢复执行未完成的安全检测任务"
            checkpoint = dict(scan_task.checkpoint or {})
            prior_results = [
                item for item in checkpoint.get("completed_results", [])
                if item.get("status") == "success" and isinstance(item.get("index"), int)
            ]
            completed_indexes = {item["index"] for item in prior_results}
            plan = [
                {**step, "_checkpoint_index": index}
                for index, step in enumerate(plan)
                if index not in completed_indexes
            ]

            self.task_stop_flags[task_id] = False
            self.task_status[task_id] = "running"
            self._update_task_metadata(
                task_id,
                user_id=user_id,
                project_id=scan_task.project_id,
                scan_task_id=scan_task.id,
                status="running",
                recovered=True,
            )
            scan_task.status = ScanTaskStatus.RUNNING
            scan_task.control_state = "running"
            progress = dict(scan_task.progress or {})
            progress.update({
                "task_id": task_id,
                "user_id": user_id,
                "project_id": scan_task.project_id,
                "status": "running",
                "current_step": "服务重启后恢复执行...",
            })
            scan_task.progress = progress
            if not scan_task.started_at:
                scan_task.started_at = datetime.utcnow()

            task = asyncio.create_task(self._execute_plan_async(
                task_id=task_id,
                plan=plan,
                user_id=int(user_id),
                project_id=scan_task.project_id,
                db=db,
                context_manager=None,
                ai_response=ai_response,
                user_input=user_input,
                thread_id=thread_id,
                scan_task_id=scan_task.id,
                checkpoint_results=prior_results,
            ))
            self.active_tasks[task_id] = task
            recovered += 1

        await db.commit()
        if recovered:
            logger.info("Recovered %d persisted scan task(s)", recovered)
        return recovered
    
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
        plan, response = self._normalize_explicit_asset_plan(plan, context, user_input, response)
        plan, response = self._normalize_project_asset_plan(plan, context, user_input, response)
        plan, response = self._keep_current_command_targets(plan, user_input, response)
        plan = self._expand_project_asset_targets(plan, context)
        
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
            
            task_info = await self.start_async_plan(
                plan=plan,
                user_id=user_id,
                project_id=project_id,
                db=db,
                context_manager=context_manager,
                ai_response=response,
                user_input=user_input,
                thread_id=thread_id,
            )
            task_id = task_info["task_id"]
            logger.info(f"Async task {task_id} created successfully")
            
            # 立即返回 AI 回复 + task_id
            return {
                "task_ids": [task_id],
                "agents": [],
                "message": response,
                "task_id": task_id,
                "scan_task_id": task_info.get("scan_task_id"),
            }
        else:
            # 没有执行计划，直接返回回复
            return {
                "task_ids": [],
                "agents": [],
                "message": response,
            }

    def _normalize_explicit_asset_plan(
        self,
        plan: List[Dict],
        context: Dict,
        user_input: str,
        response: str = "",
    ) -> tuple[List[Dict], str]:
        """Use the current command as the source of truth for an explicitly named project asset."""
        capability = self._requested_scan_capability(user_input)
        if not capability:
            return plan, response

        text = (user_input or "").lower()
        matched = []
        for asset in context.get("project_assets") or []:
            value = asset.get("value")
            identity = target_identity(value)
            if identity and identity.lower() in text and value not in matched:
                matched.append(value)
        if not matched:
            return plan, response

        normalized = [{
            "capability": capability,
            "parameters": self._explicit_asset_parameters_for(capability, target, user_input),
        } for target in matched]
        return normalized, self._project_asset_scan_response(
            capability,
            [{"value": target} for target in matched],
            current_project=False,
        )

    def _normalize_project_asset_plan(
        self,
        plan: List[Dict],
        context: Dict,
        user_input: str,
        response: str = "",
    ) -> tuple[List[Dict], str]:
        """Keep project-wide scan requests scoped to the current project's assets."""
        if not plan:
            return plan, response

        assets = context.get("project_assets") or []
        if not assets:
            return plan, response

        text = user_input or ""
        wants_project_assets = any(
            phrase in text
            for phrase in ("全资产", "全部资产", "所有资产", "项目资产", "当前项目资产", "项目中的资产")
        )
        if not wants_project_assets:
            return plan, response

        normalized = []
        requested_capability = self._requested_scan_capability(user_input)
        if requested_capability and not any(step.get("capability") in self.SCAN_CAPABILITIES for step in plan):
            parameters = self._project_asset_parameters_for(requested_capability, text)
            return (
                [{"capability": requested_capability, "parameters": parameters}],
                self._project_asset_scan_response(requested_capability, assets),
            )

        for step in plan:
            capability = step.get("capability")
            if capability not in self.SCAN_CAPABILITIES:
                normalized.append(step)
                continue

            next_step = dict(step)
            if requested_capability:
                next_step["capability"] = requested_capability
                capability = requested_capability
            parameters = dict(next_step.get("parameters") or {})
            parameters.update(self._project_asset_parameters_for(capability, text))
            next_step["parameters"] = parameters
            normalized.append(next_step)

        if requested_capability:
            response = self._project_asset_scan_response(requested_capability, assets)

        return normalized, response

    def _keep_current_command_targets(
        self,
        plan: List[Dict],
        user_input: str,
        response: str,
    ) -> tuple[List[Dict], str]:
        """Drop targets copied from earlier turns when this command names a target."""
        capability = self._requested_scan_capability(user_input)
        if not capability or not plan:
            return plan, response

        current_text = (user_input or "").lower()
        retained = []
        retained_targets = []
        seen = set()
        for step in plan:
            parameters = step.get("parameters") if isinstance(step, dict) else None
            if not isinstance(parameters, dict):
                retained.append(step)
                continue
            raw_targets = [parameters.get("target"), parameters.get("url"), parameters.get("network")]
            if isinstance(parameters.get("targets"), list):
                raw_targets.extend(parameters["targets"])
            identities = [target_identity(value) for value in raw_targets if value]
            concrete = [value for value in identities if value and value not in {"项目资产", "项目资产网段"}]
            if concrete and not any(value in current_text for value in concrete):
                continue
            key = (step.get("capability"), json.dumps(parameters, sort_keys=True, ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            retained.append(step)
            retained_targets.extend(value for value in concrete if value not in retained_targets)

        if not retained or len(retained) == len(plan):
            return retained or plan, response
        if retained_targets:
            display_name = self._project_asset_scan_response(
                capability,
                [{"value": value} for value in retained_targets],
            ).split("执行", 1)[-1].split("：", 1)[0]
            response = f"好的，我将对 {', '.join(retained_targets)} 执行{display_name}。"
        return retained, response

    def _project_asset_parameters_for(self, capability: str, user_input: str) -> Dict:
        if capability == "fping_scan":
            return {"network": "项目资产网段"}

        parameters = {"target": "项目资产"}
        if capability == "scan_ports":
            parameters["port_range"] = "1-65535" if any(
                token in user_input for token in ("全端口", "全部端口", "1-65535")
            ) else "high-risk"
        return parameters

    def _explicit_asset_parameters_for(self, capability: str, target: str, user_input: str) -> Dict:
        if capability == "fping_scan":
            return {"targets": [target]}
        if capability in {"sqlmap_scan", "gobuster_scan", "ffuf_scan", "web_discovery_scan"}:
            match = re.search(r"https?://[^\s，。；]+", user_input or "", flags=re.IGNORECASE)
            url = match.group(0) if match else f"http://{target}"
            if capability == "ffuf_scan" and "FUZZ" not in url:
                url = f"{url.rstrip('/')}/FUZZ"
            return {"url": url}
        parameters = {"target": target}
        if capability == "scan_ports":
            parameters["port_range"] = "1-65535" if any(
                token in user_input for token in ("全端口", "全部端口", "1-65535")
            ) else "high-risk"
        return parameters

    def _project_asset_scan_response(
        self,
        capability: str,
        assets: List[Dict],
        *,
        current_project: bool = True,
    ) -> str:
        names = [asset.get("value") for asset in assets if asset.get("value")]
        display_name = {
            "scan_ports": "端口扫描",
            "scan_weak_passwords": "弱口令检测",
            "scan_vulnerabilities": "漏洞扫描",
            "database_security_scan": "数据库安全检测",
            "baseline_check": "安全基线核查",
            "scan_ssl": "SSL/TLS 检测",
            "nikto_scan": "Web 安全扫描",
            "network_device_scan": "网络设备检测",
            "windows_security_scan": "Windows/AD/SMB 检测",
            "web_discovery_scan": "Web 目录发现",
            "fping_scan": "批量存活检测",
            "ping_asset": "Ping 检测",
        }.get(capability, capability)
        if current_project:
            return f"好的，我将对当前项目的 {len(names)} 个资产执行{display_name}：{', '.join(names)}"
        return f"好的，我将对 {', '.join(names)} 执行{display_name}。"

    def _requested_scan_capability(self, user_input: str) -> Optional[str]:
        text = user_input or ""
        if "/scan" in text or "端口" in text:
            return "scan_ports"
        if "弱口令" in text or "密码" in text:
            return "scan_weak_passwords"
        if "数据库" in text:
            return "database_security_scan"
        if "基线" in text:
            return "baseline_check"
        if "SSL" in text or "ssl" in text or "TLS" in text or "tls" in text:
            return "scan_ssl"
        if "SNMP" in text or "snmp" in text or "网络设备" in text:
            return "network_device_scan"
        if "Windows" in text or "windows" in text or "SMB" in text or "smb" in text or "AD" in text:
            return "windows_security_scan"
        if "目录" in text or "爆破" in text or "模糊" in text:
            return "web_discovery_scan"
        if "SQL 注入" in text or "sql注入" in text.lower() or "/sqlmap" in text.lower():
            return "sqlmap_scan"
        if "Web" in text or "web" in text:
            return "nikto_scan"
        if "漏洞" in text:
            return "scan_vulnerabilities"
        if "存活" in text or "fping" in text or "批量 Ping" in text:
            return "fping_scan"
        if "Ping" in text or "ping" in text:
            return "ping_asset"
        return None
    
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
        scan_task_id: int = None,
        checkpoint_results: Optional[List[Dict[str, Any]]] = None,
    ):
        """异步执行计划，完成后用 AI 生成结果描述"""
        # 初始化任务控制状态
        self.task_stop_flags[task_id] = False
        self.task_status[task_id] = "running"
        self._update_task_metadata(
            task_id,
            user_id=user_id,
            project_id=project_id,
            status="running",
        )
        
        # 创建停止检查回调
        def check_stop():
            return self.is_task_stopped(task_id)
        
        # 创建暂停检查回调（异步等待直到恢复或停止）
        async def wait_if_paused():
            if scan_task_id:
                status_result = await async_db.execute(select(ScanTask).where(ScanTask.id == scan_task_id))
                persisted_task = status_result.scalar_one_or_none()
                if persisted_task:
                    await async_db.refresh(persisted_task)
                if persisted_task and persisted_task.status == ScanTaskStatus.CANCELLED:
                    self.task_stop_flags[task_id] = True
                    self.task_status[task_id] = "stopped"
                    return True
                if persisted_task and persisted_task.control_state == "paused":
                    self.task_status[task_id] = "paused"
            while self.task_status.get(task_id) == "paused":
                if scan_task_id:
                    status_result = await async_db.execute(select(ScanTask).where(ScanTask.id == scan_task_id))
                    persisted_task = status_result.scalar_one_or_none()
                    if persisted_task:
                        await async_db.refresh(persisted_task)
                    if persisted_task and persisted_task.status == ScanTaskStatus.CANCELLED:
                        self.task_stop_flags[task_id] = True
                        self.task_status[task_id] = "stopped"
                        return True
                    if persisted_task and persisted_task.control_state != "paused":
                        self.task_status[task_id] = "running"
                        return False
                if self.is_task_stopped(task_id):
                    return True
                await asyncio.sleep(0.5)
            return self.is_task_stopped(task_id)
        
        # 创建新的数据库会话用于异步任务
        async with AsyncSessionLocal() as async_db:
            try:
                logger.info(f"Task {task_id} started")
                
                # 创建扫描任务记录（如果是扫描类）
                has_scan = self._plan_has_scan(plan)
                
                if not scan_task_id and has_scan and project_id:
                    scan_task_id = await self._create_scan_task_record(
                        async_db,
                        project_id,
                        plan,
                        task_id,
                        user_id=user_id,
                        thread_id=thread_id,
                        ai_response=ai_response,
                        user_input=user_input,
                        task_type=task_type,
                        asset_id=asset_id,
                    )
                    self._update_task_metadata(task_id, scan_task_id=scan_task_id)
                
                # 初始化任务进度
                self.task_progress[task_id] = {
                    "task_id": task_id,
                    "user_id": user_id,
                    "project_id": project_id,
                    "current_step": "准备执行...",
                    "step_index": 0,
                    "total_steps": len(plan),
                    "steps": [],
                }
                await self._persist_scan_task_state(
                    async_db,
                    scan_task_id,
                    status=ScanTaskStatus.RUNNING,
                    progress=self.task_progress[task_id],
                )
                
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

                async def checkpoint_step(step_index: int, outcome: Dict[str, Any]) -> None:
                    await self._persist_step_outcome(scan_task_id, step_index, outcome)
                
                # 检测是否为多资产扫描
                is_multi_asset = self._is_multi_asset_scan(plan)

                if is_multi_asset:
                    # 根据资产数量动态调整并发数
                    asset_count = len(plan)
                    if asset_count <= 3:
                        dynamic_concurrent = 5
                    elif asset_count <= 8:
                        dynamic_concurrent = 8
                    elif asset_count <= 15:
                        dynamic_concurrent = 10
                    else:
                        dynamic_concurrent = 12
                    dynamic_concurrent = min(dynamic_concurrent, max(1, settings.ASSESSMENT_MAX_CONCURRENT))
                    logger.info(f"Multi-asset scan: {asset_count} assets, max_concurrent={dynamic_concurrent}")

                    execution_result = await self.execution_engine.execute_plan_concurrent(
                        plan=plan,
                        user_id=user_id,
                        project_id=project_id,
                        db=async_db,
                        context_manager=async_context_manager,
                        task_id=task_id,
                        progress_callback=self._update_task_progress_multi_asset,
                        max_concurrent=dynamic_concurrent,
                        max_retries=3,
                        check_stop=check_stop,
                        wait_if_paused=wait_if_paused,
                        step_result_callback=checkpoint_step,
                    )
                else:
                    # 单资产串行执行 - 保留原有逻辑
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
                        step_result_callback=checkpoint_step,
                    )

                # A tool may finish after a stop request. Never let its late
                # result overwrite the durable cancelled state during summary.
                if self.is_task_stopped(task_id):
                    raise asyncio.CancelledError("任务已停止")

                if checkpoint_results:
                    prior = [dict(item) for item in checkpoint_results]
                    execution_result["results"] = prior + execution_result.get("results", [])
                    execution_result["success_count"] = sum(
                        1 for item in execution_result["results"] if item.get("status") == "success"
                    )
                    execution_result["warning_count"] = sum(
                        1 for item in execution_result["results"] if item.get("status") in {"warning", "skipped"}
                    )
                    execution_result["failed_count"] = sum(
                        1 for item in execution_result["results"] if item.get("status") in {"failed", "cancelled"}
                    )

                # L1 Agent 统一汇总结果，写入 DB（design-v2.md 核心原则）
                # Skill 阶段已经执行完毕，Agent 现在汇总所有结果
                await self._agent_persist_results(
                    execution_result=execution_result,
                    context_manager=async_context_manager,
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
                completed_dt = datetime.utcnow()
                from app.services.change_detection import record_port_snapshots
                port_changes = await record_port_snapshots(
                    async_db,
                    project_id,
                    scan_task_id,
                    scan_results.get("port_results", {}),
                ) if project_id and scan_task_id else []
                await self._persist_scan_task_state(
                    async_db,
                    scan_task_id,
                    status=ScanTaskStatus.COMPLETED,
                    progress=None,
                    result_summary={
                        "task_id": task_id,
                        "result_description": result_description,
                        "scan_results": scan_results,
                        "success_count": execution_result.get("success_count", 0),
                        "failed_count": execution_result.get("failed_count", 0),
                        "change_detection": {"port_changes": port_changes},
                    },
                    completed_at=completed_dt,
                )
                await record_audit_event(
                    async_db,
                    event_type="scan.completed",
                    resource_type="scan_task",
                    resource_id=scan_task_id,
                    actor_user_id=user_id,
                    project_id=project_id,
                    outcome="success",
                    details={
                        "orchestrator_task_id": task_id,
                        "success_count": execution_result.get("success_count", 0),
                        "failed_count": execution_result.get("failed_count", 0),
                    },
                )

                # Any new technical fact may affect an assessment control.
                if project_id:
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
                completed_at = completed_dt.isoformat()
                self.completed_tasks.append({
                    "task_id": task_id,
                    "user_id": user_id,
                    "project_id": project_id,
                    "agent_name": "AI 执行任务",
                    "result": execution_result,
                    "evidence_count": execution_result.get("success_count", 0),
                    "scan_results": scan_results,
                    "is_multi_asset": is_multi_asset,
                    "result_description": result_description,
                    "completed_at": completed_at,
                })
                self.task_status[task_id] = "completed"
                self._update_task_metadata(
                    task_id,
                    status="completed",
                    completed_at=completed_at,
                    is_multi_asset=is_multi_asset,
                )
                self.active_tasks.pop(task_id, None)

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
                await async_context_manager.add_conversation(
                    "assistant",
                    result_description,
                    context_snapshot={
                        "scan_results": scan_results,
                        "is_multi_asset": is_multi_asset,
                        "task_id": task_id,
                    }
                )
                await async_db.commit()

                logger.info(f"Task {task_id} completed: {result_description[:100]}")
                
            except (Exception, asyncio.CancelledError) as e:
                cancelled = isinstance(e, asyncio.CancelledError) or self.task_status.get(task_id) == "stopped"
                if cancelled:
                    logger.info(f"Task {task_id} was cancelled")
                else:
                    logger.error(f"Task {task_id} failed: {str(e)}", exc_info=True)
                failed_status = "stopped" if cancelled else "failed"
                failed_at = datetime.utcnow().isoformat()
                result_description = "任务已停止" if cancelled else f"任务执行失败：{str(e)}"
                
                # 记录失败
                self.completed_tasks.append({
                    "task_id": task_id,
                    "user_id": user_id,
                    "project_id": project_id,
                    "agent_name": "AI 执行任务",
                    "result": {"cancelled": True} if cancelled else {"error": str(e)},
                    "evidence_count": 0,
                    "scan_results": {},
                    "result_description": result_description,
                    "completed_at": failed_at,
                })
                self.task_status[task_id] = failed_status
                self._update_task_metadata(
                    task_id,
                    status=failed_status,
                    completed_at=failed_at,
                    error=str(e),
                )
                self.active_tasks.pop(task_id, None)
                
                # 清理进度记录
                if task_id in self.task_progress:
                    del self.task_progress[task_id]
                
                try:
                    from app.api.websocket import broadcast_agent_failed
                    await broadcast_agent_failed(task_id, str(e))
                except Exception:
                    pass
                
                # 更新扫描任务状态为失败
                await self._persist_scan_task_state(
                    async_db,
                    scan_task_id,
                    status=ScanTaskStatus.CANCELLED if failed_status == "stopped" else ScanTaskStatus.FAILED,
                    progress=None,
                    result_summary={
                        "task_id": task_id,
                        "result_description": result_description,
                        "scan_results": {},
                    },
                    error_message=None if cancelled else str(e),
                    completed_at=datetime.utcnow(),
                )
                await record_audit_event(
                    async_db,
                    event_type="scan.cancelled" if failed_status == "stopped" else "scan.failed",
                    resource_type="scan_task",
                    resource_id=scan_task_id,
                    actor_user_id=user_id,
                    project_id=project_id,
                    outcome="cancelled" if failed_status == "stopped" else "failed",
                    details={"orchestrator_task_id": task_id, **({} if cancelled else {"error": str(e)} )},
                )
                await async_db.commit()

    def _expand_project_asset_targets(self, plan: List[Dict], context: Dict) -> List[Dict]:
        """Expand the LLM's project-asset placeholder into concrete asset targets."""
        assets = context.get("project_assets") or []
        asset_values = [a.get("value") for a in assets if a.get("value")]
        if not asset_values:
            return plan

        expanded = []
        placeholders = {"项目资产", "全部项目资产", "所有项目资产", "项目中的资产"}
        network_placeholders = {"项目资产网段", "项目网段", "资产网段"}

        for step in plan:
            parameters = dict(step.get("parameters") or {})
            if parameters.get("target") in placeholders:
                for value in asset_values:
                    next_step = dict(step)
                    next_params = dict(parameters)
                    next_params["target"] = value
                    next_step["parameters"] = next_params
                    expanded.append(next_step)
            elif parameters.get("network") in network_placeholders:
                next_step = dict(step)
                next_params = dict(parameters)
                next_params.pop("network", None)
                next_params["targets"] = asset_values
                next_step["parameters"] = next_params
                expanded.append(next_step)
            else:
                expanded.append(step)

        return expanded
    
    def _update_task_progress(self, task_id: str, step_index: int, total_steps: int, capability_name: str, status: str):
        """更新任务执行进度"""
        if task_id not in self.task_progress:
            metadata = self.get_task_metadata(task_id)
            self.task_progress[task_id] = {
                "task_id": task_id,
                "user_id": metadata.get("user_id"),
                "project_id": metadata.get("project_id"),
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
            "tech_assessment": "等保技术测评",
            "masscan_scan": "高速端口扫描",
            "fping_scan": "批量存活检测",
            "nikto_scan": "Web 安全扫描",
            "sqlmap_scan": "SQL 注入检测",
            "gobuster_scan": "目录爆破",
            "ffuf_scan": "Web 模糊测试",
            "web_discovery_scan": "Web 目录发现",
            "redis_check": "Redis 检测",
            "mysql_check": "MySQL 检测",
            "mongodb_check": "MongoDB 检测",
            "oracle_check": "Oracle 检测",
            "memcached_check": "Memcached 检测",
            "database_security_scan": "数据库安全检测",
            "snmp_walk": "SNMP 检测",
            "network_device_scan": "网络设备检测",
            "snmp_bruteforce": "SNMP 团体字检测",
            "snmp_get": "SNMP OID 读取",
            "enum4linux_scan": "Windows 用户/组枚举",
            "windows_security_scan": "Windows/AD/SMB 检测",
            "crackmapexec_scan": "Windows SID 枚举",
            "smb_enum": "SMB 共享枚举",
            "baseline_check": "安全基线核查",
            "linux_baseline": "安全基线核查",
            "ssh_config_check": "SSH 配置检查",
            "ping_asset": "Ping 检测",
            "view_open_ports": "查看开放端口",
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
            "generate_html_report": "生成 HTML 报告",
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
        elif status == "warning":
            self.task_progress[task_id]["current_step"] = f"未完整/无法判定: {display_name}"
        elif status == "skipped":
            self.task_progress[task_id]["current_step"] = f"已跳过: {display_name}"
        
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
        
        scan_capabilities = [
            "scan_ports", "scan_ssl", "scan_vulnerabilities",
            "scan_weak_passwords", "full_compliance_scan", "tech_assessment",
            "redis_check", "oracle_check", "mongodb_check", "database_security_scan",
            "memcached_check", "mysql_check",
            "snmp_walk", "snmp_bruteforce", "snmp_get", "network_device_scan",
            "enum4linux_scan", "crackmapexec_scan", "smb_enum", "windows_security_scan",
            "nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan", "web_discovery_scan",
            "masscan_scan", "fping_scan", "baseline_check", "linux_baseline",
            "password_policy_check", "ssh_config_check",
            "audit_config_check", "service_port_check",
            "file_permission_check", "mac_check",
            "ping_host",
            "ping_asset",
        ]
        
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
            metadata = self.get_task_metadata(task_id)
            self.task_progress[task_id] = {
                "task_id": task_id,
                "user_id": metadata.get("user_id"),
                "project_id": metadata.get("project_id"),
                "type": "multi_asset",
                "current_step": "任务执行中...",
                "step_index": 0,
                "total_steps": total_assets,
                "steps": [],
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
        
        capability_display_names = {
            "scan_ports": "端口扫描",
            "masscan_scan": "高速端口扫描",
            "fping_scan": "批量存活检测",
            "scan_ssl": "SSL/TLS 检测",
            "scan_vulnerabilities": "漏洞扫描",
            "scan_weak_passwords": "弱口令检测",
            "nikto_scan": "Web 安全扫描",
            "sqlmap_scan": "SQL 注入检测",
            "gobuster_scan": "目录爆破",
            "ffuf_scan": "Web 模糊测试",
            "web_discovery_scan": "Web 目录发现",
            "database_security_scan": "数据库安全检测",
            "baseline_check": "安全基线核查",
            "snmp_walk": "SNMP 检测",
            "network_device_scan": "网络设备检测",
            "enum4linux_scan": "Windows 用户/组枚举",
            "windows_security_scan": "Windows/AD/SMB 检测",
            "smb_enum": "SMB 共享枚举",
            "full_compliance_scan": "全量合规扫描",
            "tech_assessment": "等保技术测评",
        }
        display_name = capability_display_names.get(capability_name, capability_name or "安全检测")
        status_prefix = {
            "running": "正在执行",
            "completed": "已完成",
            "success": "已完成",
            "failed": "失败",
            "error": "失败",
            "warning": "未完整/无法判定",
            "skipped": "已跳过",
        }.get(status, "正在执行")
        self.task_progress[task_id]["current_step"] = (
            f"{status_prefix}: {display_name} ({asset_index + 1}/{total_assets}) - {asset_name}"
        )
        self.task_progress[task_id]["step_index"] = min(asset_index, max(total_assets - 1, 0))
        self.task_progress[task_id]["total_steps"] = total_assets
        self.task_progress[task_id]["steps"] = [
            {
                "capability": item.get("capability"),
                "display_name": f"{item.get('name')} - {capability_display_names.get(item.get('capability'), item.get('capability') or '安全检测')}",
                "status": item.get("status"),
            }
            for item in sorted(assets_list, key=lambda item: item.get("index", 0))
        ]
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
                                 "scan_weak_passwords", "full_compliance_scan", "database_security_scan",
                                 "baseline_check", "tech_assessment"]
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
                                 "scan_weak_passwords", "full_compliance_scan", "database_security_scan"]
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

    async def _agent_persist_results(
        self,
        execution_result: Dict,
        context_manager: ContextManager,
    ):
        """
        L1 Agent 统一汇总结果，写入 DB（design-v2.md 核心原则）

        根据 design-v2.md：
        - Skill 关闭写权限
        - Skill 不直接修改全局看板
        - 结果统一由 Agent 汇总后更新

        流程：
        1. 遍历所有 Skill 返回的结果
        2. 提取 action_history 数据
        3. 提取 cache_result 数据
        4. 统一写入 DB（使用一个 session 串行写入）
        """
        try:
            results = execution_result.get("results", [])
            if not results:
                return

            for result in results:
                if not isinstance(result, dict):
                    continue

                capability = result.get("capability", "")
                target = result.get("target", "")
                status = result.get("status", "unknown")
                result_data = result.get("result", {})
                error = result.get("error")

                if not capability:
                    continue

                # 写入 action_history
                try:
                    await context_manager.add_action(
                        action_type=capability,
                        parameters={"target": target},
                        result={"status": status, "result": result_data, "error": error},
                        status=status
                    )
                except Exception as e:
                    logger.warning(f"Failed to record action for {capability}: {e}")

                # 写入 cache_result（仅成功的）
                if status == "success" and result_data:
                    try:
                        cache_key = f"{capability}:target={target}"
                        await context_manager.cache_result(cache_key, result_data)
                    except Exception as e:
                        logger.warning(f"Failed to cache result for {capability}: {e}")

            logger.info(f"Agent persisted {len(results)} task results to DB")
        except Exception as e:
            logger.error(f"Failed to persist agent results: {e}", exc_info=True)
    
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
            if self._has_security_tool_result(execution_result) or any(
                result.get("capability") == "list_assets"
                for result in self._iter_execution_results(execution_result)
            ):
                return self._generate_fallback_description(execution_result)

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

请用简洁的中文描述执行结果，包含具体的数据（如端口列表、漏洞数量等）。
如果端口扫描未发现开放端口，只能说“本次扫描范围未发现开放端口”，不要推断为“无安全风险”。
如果存在 filtered 端口，说明可能被防火墙过滤，也不要推断为端口不存在。
直接输出描述内容，不要加引号或其他格式。"""
            
            # 调用 LLM 生成描述
            messages = [
                {"role": "system", "content": "你是 VeriSure 智能合规验证助手，负责描述任务执行结果。"},
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

    def _has_security_tool_result(self, execution_result: Dict) -> bool:
        security_capabilities = {
            "scan_ports", "masscan_scan", "fping_scan", "ping_host", "ping_asset",
            "scan_ssl", "testssl_scan", "scan_vulnerabilities", "nuclei_scan",
            "scan_weak_passwords", "hydra_bruteforce",
            "nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan", "web_discovery_scan",
            "redis_check", "mysql_check", "mongodb_check", "memcached_check", "oracle_check",
            "database_security_scan", "snmp_walk", "snmp_bruteforce", "snmp_get", "network_device_scan",
            "enum4linux_scan", "crackmapexec_scan", "smb_enum", "windows_security_scan",
            "baseline_check", "linux_baseline", "password_policy_check", "ssh_config_check",
            "audit_config_check", "service_port_check", "file_permission_check", "mac_check",
            "full_compliance_scan", "tech_assessment",
        }
        return any(
            result.get("capability") in security_capabilities
            for result in self._iter_execution_results(execution_result)
        )

    def _result_payload(self, result: Dict) -> Dict:
        data = result.get("result") or {}
        if not data and isinstance(result.get("data"), dict):
            data = result.get("data") or {}
        if isinstance(data, dict) and "data" in data and any(k in data for k in ("tool", "status", "metadata")):
            payload = data.get("data") or {}
            if isinstance(payload, dict) and data.get("metadata"):
                payload = {**payload, "metadata": data.get("metadata", {})}
            return payload
        return data if isinstance(data, dict) else {}

    def _iter_execution_results(self, execution_result: Dict):
        for result in execution_result.get("results", []):
            yield result
            data = self._result_payload(result)
            for sub in data.get("sub_results", []) if isinstance(data, dict) else []:
                if not isinstance(sub, dict):
                    continue
                yield {
                    "capability": sub.get("capability"),
                    "target": sub.get("target") or result.get("target"),
                    "status": sub.get("status"),
                    "result": sub.get("data") or {},
                    "error": sub.get("error"),
                    "error_detail": sub.get("error_detail"),
                    "label": sub.get("label"),
                }

    def _describe_result_line(self, capability: str, target: str, status: str, data: Dict, error: str = None) -> str:
        target_str = f"({target})" if target else ""
        label = self._capability_label(capability)
        error_detail = data.get("error_detail") if isinstance(data, dict) else None
        if error_detail:
            reason = error_detail.get("error_reason") or error_detail.get("raw_error") or error
            remediation = error_detail.get("remediation")
            detail = reason or error or "未知错误"
            if remediation:
                detail = f"{detail} 建议：{remediation}"
        else:
            detail = error or "未知错误"
        if status == "skipped":
            return f"{label}{target_str}: 跳过 - {detail or '条件不满足'}"
        if status not in ["success", "completed", "warning"]:
            return f"{label}{target_str}: 失败 - {detail}"
        if data.get("scan_completed") is False or data.get("success") is False or data.get("reachable") is False:
            reason = data.get("tool_error") or data.get("connection_error") or detail or "工具未完成执行"
            return f"{label}{target_str}: 未完成/无法判定 - {reason}"

        if capability == "list_assets":
            assets = data.get("assets") or []
            if not assets:
                return "资产清单: 当前项目暂无资产"
            asset_lines = []
            status_labels = {
                "verified": "已验证",
                "pending": "待验证",
                "failed": "验证失败",
            }
            type_labels = {
                "ip": "IP",
                "domain": "域名",
                "cloud_resource": "云资源",
            }
            for asset in assets:
                name = (asset.get("name") or "").strip()
                value = asset.get("value") or "未填写"
                asset_type = type_labels.get(asset.get("type"), asset.get("type") or "资产")
                verification = status_labels.get(
                    asset.get("verification_status"),
                    asset.get("verification_status") or "状态未知",
                )
                asset_lines.append(f"{name or '未命名资产'}（{asset_type}）：{value}，{verification}")
            return f"资产清单: 当前项目共有 {len(assets)} 个资产：\n- " + "\n- ".join(asset_lines)

        if capability in ("scan_ports", "masscan_scan"):
            open_ports = data.get("open_ports", [])
            filtered_count = data.get("filtered_count") or len(data.get("filtered_ports", []))
            if open_ports:
                port_list = ", ".join([f"{p.get('port')}/{p.get('protocol', 'tcp')}({p.get('service', 'unknown')})" for p in open_ports[:20]])
                suffix = f"，另有 {len(open_ports) - 20} 个" if len(open_ports) > 20 else ""
                filtered_suffix = f"；另有 {filtered_count} 个端口被过滤/未确认开放" if filtered_count else ""
                return f"端口扫描{target_str}: 发现 {len(open_ports)} 个明确开放端口：{port_list}{suffix}{filtered_suffix}"
            suffix = f"，{filtered_count} 个端口被过滤/未确认开放" if filtered_count else ""
            return f"端口扫描{target_str}: 本次扫描范围未发现明确开放端口{suffix}"

        if capability == "fping_scan":
            alive = data.get("alive_hosts") or data.get("alive") or []
            return f"批量存活检测{target_str}: 存活 {len(alive)} 个"
        if capability == "scan_ssl":
            if data.get("scan_completed") is False or data.get("reachable") is False:
                port = data.get("port", 443)
                reason = data.get("tool_error") or "未获取到 TLS 协议或证书信息"
                return f"SSL/TLS 检测{target_str}: 端口 {port} 未完成检测 - {reason}"
            issue_count = len(data.get("issues", []))
            vuln_count = len(data.get("vulnerabilities", []))
            tls_text = f"，TLS: {data.get('tls_version')}" if data.get("tls_version") else ""
            cert_text = "，已获取证书" if data.get("certificate") else "，未获取证书"
            return f"SSL/TLS 检测{target_str}: 问题 {issue_count} 个，漏洞 {vuln_count} 个{tls_text}{cert_text}"
        if capability == "scan_vulnerabilities":
            if data.get("scan_completed") is False:
                return f"漏洞扫描{target_str}: 未完成 - {data.get('tool_error') or '扫描引擎未完成执行'}"
            return f"漏洞扫描{target_str}: 发现 {len(data.get('findings', []))} 个"
        if capability == "scan_weak_passwords":
            if data.get("scan_completed") is False:
                return f"弱口令检测{target_str}: 未完成 - {data.get('tool_error') or 'Hydra 未完成执行'}"
            return f"弱口令检测{target_str}: 发现 {len(data.get('found', []))} 个"
        if capability in ("nikto_scan", "sqlmap_scan"):
            count = len(data.get("findings", [])) + len(data.get("injection_points", []))
            return f"Web 检测{target_str}: 发现 {count} 个问题"
        if capability in ("gobuster_scan", "ffuf_scan"):
            if data.get("scan_completed") is False:
                return f"Web 发现{target_str}: 未完成 - {data.get('tool_error') or '目录/模糊测试工具执行失败'}"
            return f"Web 发现{target_str}: 发现 {len(data.get('discovered', []))} 个路径/端点"
        if capability.endswith("_check") and capability in ("redis_check", "mysql_check", "mongodb_check", "memcached_check", "oracle_check"):
            labels = {
                "redis_check": "Redis 未授权访问检测",
                "mysql_check": "MySQL 空口令检测",
                "mongodb_check": "MongoDB 未授权访问检测",
                "memcached_check": "Memcached 未授权访问检测",
                "oracle_check": "Oracle TNS 检测",
            }
            risky = data.get("unauthorized") or data.get("empty_password") or data.get("version_info")
            port = data.get("port")
            port_str = f"，端口 {port}" if port else ""
            if data.get("reachable") is False:
                return f"{labels[capability]}{target_str}: 不可达/无响应{port_str}，无法判定是否存在数据库风险"
            return f"{labels[capability]}{target_str}: {'发现需关注项' if risky else '未发现明显风险'}{port_str}"
        if capability in ("snmp_walk", "snmp_bruteforce", "snmp_get"):
            if data.get("success") is False:
                return f"SNMP 检测{target_str}: 未完成/无响应 - {data.get('tool_error') or data.get('metadata', {}).get('error') or 'SNMP 无响应'}"
            count = data.get("total_results") or data.get("total_found") or (1 if data.get("value") else 0)
            return f"SNMP 检测{target_str}: 返回 {count} 条结果"
        if capability in ("enum4linux_scan", "crackmapexec_scan", "smb_enum"):
            if data.get("scan_completed") is False:
                return f"Windows/SMB 检测{target_str}: 未完成 - {data.get('tool_error') or 'Windows 工具未完成执行'}"
            return f"Windows/SMB 检测{target_str}: 已完成"
        if capability in ("baseline_check", "linux_baseline", "password_policy_check", "ssh_config_check", "audit_config_check", "service_port_check", "file_permission_check", "mac_check"):
            summary = data.get("summary") or {}
            failed = summary.get("non_compliant") or summary.get("failed") or summary.get("fail_count")
            os_type = data.get("os_type")
            os_text = f"{os_type} " if os_type and os_type != "unknown" else ""
            if data.get("skipped"):
                skip_detail = detail if error_detail else data.get("skip_reason") or data.get("tool_error") or "不适用"
                return f"安全基线核查{target_str}: {os_text}已跳过 - {skip_detail}"
            return f"安全基线核查{target_str}: {os_text}未通过 {failed or 0} 项"
        if capability in ("full_compliance_scan", "tech_assessment", "database_security_scan", "web_discovery_scan", "network_device_scan", "windows_security_scan"):
            labels = {
                "full_compliance_scan": "全量合规扫描",
                "tech_assessment": "等保技术测评",
                "database_security_scan": "数据库安全检测",
                "web_discovery_scan": "Web 目录发现",
                "network_device_scan": "网络设备检测",
                "windows_security_scan": "Windows/AD/SMB 检测",
            }
            summary = data.get("summary", {})
            warning = summary.get("warning", 0)
            warning_text = f"，告警/未完成 {warning}" if warning else ""
            return f"{labels[capability]}{target_str}: 子任务成功 {summary.get('success', 0)}{warning_text}，失败 {summary.get('failed', 0)}，跳过 {summary.get('skipped', 0)}"
        return f"{capability}{target_str}: 执行完成"

    def _capability_label(self, capability: str) -> str:
        labels = {
            "scan_ports": "端口扫描",
            "masscan_scan": "高速端口扫描",
            "fping_scan": "批量存活检测",
            "scan_ssl": "SSL/TLS 检测",
            "scan_vulnerabilities": "漏洞扫描",
            "scan_weak_passwords": "弱口令检测",
            "nikto_scan": "Web 安全扫描",
            "sqlmap_scan": "SQL 注入检测",
            "gobuster_scan": "目录爆破",
            "ffuf_scan": "Web 模糊测试",
            "baseline_check": "安全基线核查",
            "linux_baseline": "安全基线核查",
            "snmp_walk": "SNMP 检测",
            "snmp_bruteforce": "SNMP 团体字检测",
            "snmp_get": "SNMP OID 读取",
            "mongodb_check": "MongoDB 未授权访问检测",
            "redis_check": "Redis 未授权访问检测",
            "mysql_check": "MySQL 空口令检测",
            "memcached_check": "Memcached 未授权访问检测",
            "oracle_check": "Oracle TNS 检测",
            "database_security_scan": "数据库安全检测",
            "web_discovery_scan": "Web 目录发现",
            "network_device_scan": "网络设备检测",
            "windows_security_scan": "Windows/AD/SMB 检测",
        }
        return labels.get(capability, capability)
    
    def _summarize_execution_result(self, execution_result: Dict) -> str:
        """摘要执行结果用于 AI 描述"""
        results = execution_result.get("results", [])
        if not results:
            return "无具体结果"
        
        parts = []
        for result in self._iter_execution_results(execution_result):
            status = result.get("status")
            capability = result.get("capability")
            target = result.get("target", "")
            data = self._result_payload(result)
            parts.append(self._describe_result_line(capability, target, status, data, result.get("error")))
        
        return "\n".join(parts) if parts else "无具体结果"
    
    def _generate_fallback_description(self, execution_result: Dict) -> str:
        """降级方案：硬编码的结果描述"""
        results = execution_result.get("results", [])
        success_count = execution_result.get("success_count", 0)
        failed_count = execution_result.get("failed_count", 0)
        warning_count = execution_result.get("warning_count", 0)
        total_count = len(results)

        parts = []
        for result in self._iter_execution_results(execution_result):
            status = result.get("status")
            capability = result.get("capability")
            target = result.get("target", "")
            data = self._result_payload(result)
            parts.append(self._describe_result_line(capability, target, status, data, result.get("error")))

        if parts:
            summary = f"\n\n【汇总】共 {total_count} 个任务，成功 {success_count}，未完成/不可判定 {warning_count}，失败 {failed_count}"
            return "\n".join(parts) + summary

        for result in results:
            status = result.get("status")
            capability = result.get("capability")
            target = result.get("target", "")
            data = self._result_payload(result)

            # 支持 "success" 和 "completed" 两种成功状态
            if status not in ["success", "completed"]:
                error = result.get("error") or "未知错误"
                target_str = f"({target})" if target else ""
                parts.append(f"✗ 扫描失败：{capability}{target_str} - {error}")
                continue

            if capability == "scan_ports":
                open_ports = data.get("open_ports", [])
                host_status = data.get("host_status", "unknown")
                target_str = f"({target})" if target else ""
                if open_ports:
                    parts.append(f"✓ 端口扫描{target_str}: 发现 {len(open_ports)} 个明确开放端口")
                    for port in open_ports[:5]:
                        parts.append(f"  - {port['port']}/{port.get('protocol', 'tcp')}: {port.get('service', 'unknown')}")
                    if len(open_ports) > 5:
                        parts.append(f"  ... 还有 {len(open_ports) - 5} 个")
                elif host_status == "up":
                    filtered_count = data.get("filtered_count", 0)
                    suffix = f"，{filtered_count} 个端口被过滤/未确认开放" if filtered_count else ""
                    parts.append(f"⚠ 端口扫描{target_str}: 主机可达，本次扫描范围未发现明确开放端口{suffix}")
                else:
                    parts.append(f"⚠ 端口扫描{target_str}: 主机不可达或无响应")

            elif capability == "masscan_scan":
                open_ports = data.get("open_ports", [])
                total = data.get("total_open", 0)
                duration = data.get("metadata", {}).get("duration_ms", 0)
                target_str = f"({target})" if target else ""
                if total > 0:
                    parts.append(f"✓ 高速扫描{target_str}: 发现 {total} 个开放端口（{duration}ms）")
                else:
                    parts.append(f"⚠ 高速扫描{target_str}: 未发现开放端口（{duration}ms）")

            elif capability == "view_open_ports":
                open_ports = data.get("open_ports", [])
                if open_ports:
                    parts.append("开放端口列表：")
                    for port in open_ports[:5]:
                        parts.append(f"  - {port['port']}/{port.get('protocol', 'tcp')}: {port.get('service', 'unknown')}")

            elif capability == "scan_weak_passwords":
                found = data.get("found", [])
                tested_users = data.get("tested_users", 0)
                tested_passwords = data.get("tested_passwords", 0)
                total_combos = data.get("total_combinations", 0)
                service = data.get("service", "")
                port = data.get("port", "")
                target_str = f"({target})" if target else ""

                parts.append(f"弱口令检测{target_str}: 测试了 {tested_users} 个用户 × {tested_passwords} 个密码 = {total_combos} 种组合")
                if data.get("scan_completed") is False:
                    parts.append(f"  ⚠ 检测未完成，无法判定是否存在弱口令：{data.get('tool_error') or '目标服务不可达或工具未完成执行'}")
                elif found:
                    parts.append(f"  ⚠ 发现 {len(found)} 个弱口令！")
                    for fp in found[:5]:
                        parts.append(f"    - 用户: {fp.get('username', '?')} 密码: {fp.get('password', '?')}")
                    if len(found) > 5:
                        parts.append(f"    ... 还有 {len(found) - 5} 个")
                else:
                    parts.append("  ✓ 未发现弱口令")

            elif capability == "scan_vulnerabilities":
                findings = data.get("findings", [])
                target_str = f"({target})" if target else ""
                if findings:
                    parts.append(f"⚠ 漏洞扫描{target_str}: 发现 {len(findings)} 个漏洞")
                    for f in findings[:5]:
                        sev = f.get("severity", "未知")
                        name = f.get("name", f.get("id", "未知"))
                        parts.append(f"  - [{sev}] {name}")
                else:
                    parts.append(f"✓ 漏洞扫描{target_str}: 未发现漏洞")

            elif capability in ("nikto_scan", "sqlmap_scan"):
                findings = data.get("findings", [])
                target_str = f"({target})" if target else ""
                if findings:
                    parts.append(f"⚠ {capability}{target_str}: 发现 {len(findings)} 个问题")
                else:
                    parts.append(f"✓ {capability}{target_str}: 未发现问题")

            elif capability in ("baseline_check", "linux_baseline"):
                target_str = f"({target})" if target else ""
                parts.append(f"✓ 安全基线核查{target_str}: 已完成")
                # 显示一些关键检查结果
                if "checks" in data:
                    checks = data.get("checks", {})
                    failed_checks = [k for k, v in checks.items() if not v.get("compliant", True)]
                    if failed_checks:
                        parts.append(f"  ⚠ {len(failed_checks)} 项检查未通过")
                    else:
                        parts.append(f"  ✓ 所有检查项均通过")

            elif capability == "redis_check":
                unauthorized = data.get("unauthorized", False)
                target_str = f"({target})" if target else ""
                if unauthorized:
                    parts.append(f"⚠ Redis{target_str}: 存在未授权访问风险！")
                else:
                    parts.append(f"✓ Redis{target_str}: 未发现未授权访问")

            elif capability == "list_projects":
                projects = data.get("projects", [])
                if projects:
                    parts.append("项目列表：")
                    for p in projects[:5]:
                        parts.append(f"  - {p['name']} (ID: {p['id']})")

            elif capability == "create_project":
                project = data.get("project", {})
                if project:
                    parts.append(f"✓ 项目创建成功：{project.get('name', '')} (ID: {project.get('id', '')})")

            elif capability == "full_compliance_scan":
                open_ports = data.get("open_ports", [])
                findings = data.get("findings", [])
                target_str = f"({target})" if target else ""
                parts.append(f"✓ 等保全量合规扫描{target_str}: 完成")
                if open_ports:
                    parts.append(f"  - 开放端口: {len(open_ports)} 个")
                if findings:
                    parts.append(f"  - 漏洞: {len(findings)} 个")

            elif capability == "chat":
                msg = data.get("message", "")
                if msg:
                    return msg

        # 汇总
        if not parts:
            if total_count == 0:
                return f"任务执行完成（无任务）"
            elif success_count == total_count:
                return f"任务执行完成（成功 {success_count}/{total_count}）"
            else:
                return f"任务执行完成（成功 {success_count}，未完成/不可判定 {warning_count}，失败 {failed_count}，共 {total_count}）"

        summary = f"\n\n【汇总】共 {total_count} 个任务，成功 {success_count}，未完成/不可判定 {warning_count}，失败 {failed_count}"
        return "\n".join(parts) + summary
    
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
            "filtered_ports": [],
            "vulnerabilities": [],
            "ssl_issues": [],
            "weak_passwords": [],           # 弱口令详情
            "weak_password_stats": {},      # 弱口令统计（每个资产）
            "web_vulnerabilities": [],      # Web 漏洞（nikto/sqlmap）
            "web_discoveries": [],          # 目录/端点发现（gobuster/ffuf）
            "database_results": {},         # 数据库检测结果
            "database_issues": [],          # 数据库风险项
            "snmp_results": {},             # SNMP 检测结果
            "windows_results": {},          # Windows/SMB 检测结果
            "composite_results": [],        # 组合工具子任务矩阵
            "baseline_results": {},         # 安全基线核查结果
            "discovered_assets": {},         # 资产发现结果
            "port_results": {},              # 每个资产的端口快照输入
            "compliance_score": None,
            "asset_results": {},  # 按资产分组的结果
            "query_result": None,
        }

        for result in self._iter_execution_results(execution_result):
            target = result.get("target", "unknown")
            status = result.get("status")
            capability = result.get("capability", "")
            data = self._result_payload(result)
            error = result.get("error")
            error_detail = result.get("error_detail")
            if not error_detail and isinstance(data, dict):
                error_detail = data.get("error_detail")
            is_sub_result = bool(result.get("label"))

            if capability == "list_assets":
                display_status = "success" if status in ("success", "completed") else (
                    "warning" if status == "warning" else "failed"
                )
                results["query_result"] = {
                    "capability": capability,
                    "status": status,
                    "display_status": display_status,
                    "message": data.get("message") or "",
                    "assets": data.get("assets") or [],
                    "error": error,
                }
                continue

            if capability in ("scan_ports", "nmap_scan", "masscan_scan"):
                results["port_results"][target] = {
                    "capability": capability,
                    "status": status,
                    "parameters": result.get("parameters") or {},
                    "data": data,
                }

            # 初始化资产结果；组合子任务只进入详情，不单独生成资产卡
            if not is_sub_result and target not in results["asset_results"]:
                results["asset_results"][target] = {
                    "status": status,
                    "capability": capability,
                    "result": {},
                    "error": error,
                    "error_detail": error_detail,
                }

            # 支持 success/completed/warning；warning 表示工具执行但结果不可判定或未完整完成
            if status in ["success", "completed", "warning"]:
                # 更新资产状态
                if not is_sub_result:
                    results["asset_results"][target]["status"] = status
                    results["asset_results"][target]["result"] = data

                # 判断显示状态 - 根据工具类型区分
                if is_sub_result:
                    pass
                elif data.get("scan_completed") is False or data.get("success") is False or data.get("reachable") is False:
                    results["asset_results"][target]["display_status"] = "warning"
                    results["asset_results"][target]["error"] = (
                        data.get("tool_error") or data.get("connection_error") or "工具未完成执行，无法判定安全结论"
                    )
                elif capability in ("baseline_check", "linux_baseline", "password_policy_check", "ssh_config_check", "audit_config_check", "service_port_check", "file_permission_check", "mac_check") and data.get("skipped"):
                    detail = data.get("error_detail") or error_detail or {}
                    results["asset_results"][target]["display_status"] = "warning"
                    results["asset_results"][target]["error"] = detail.get("error_reason") or data.get("skip_reason") or data.get("tool_error")
                    results["asset_results"][target]["error_detail"] = detail or None
                elif capability in ("scan_ports", "nmap_scan", "masscan_scan"):
                    # 端口扫描工具：有开放端口才算 success，无则 warning
                    open_ports = data.get("open_ports", [])
                    if len(open_ports) > 0:
                        results["asset_results"][target]["display_status"] = "success"
                    else:
                        results["asset_results"][target]["display_status"] = "warning"
                elif capability == "scan_ssl":
                    if data.get("scan_completed") is False or data.get("reachable") is False:
                        results["asset_results"][target]["display_status"] = "warning"
                        results["asset_results"][target]["error"] = data.get("tool_error") or "SSL/TLS 检测未完成"
                    elif data.get("issues") or data.get("vulnerabilities"):
                        results["asset_results"][target]["display_status"] = "warning"
                    else:
                        results["asset_results"][target]["display_status"] = "success"
                elif capability == "scan_vulnerabilities":
                    if data.get("scan_completed") is False:
                        results["asset_results"][target]["display_status"] = "warning"
                        results["asset_results"][target]["error"] = data.get("tool_error") or "漏洞扫描未完成"
                    else:
                        results["asset_results"][target]["display_status"] = "warning" if data.get("findings") else "success"
                elif capability in ("gobuster_scan", "ffuf_scan"):
                    if data.get("scan_completed") is False:
                        results["asset_results"][target]["display_status"] = "warning"
                        results["asset_results"][target]["error"] = data.get("tool_error") or "Web 发现工具未完成"
                    else:
                        results["asset_results"][target]["display_status"] = "warning" if data.get("discovered") else "success"
                elif capability == "scan_weak_passwords":
                    if data.get("scan_completed") is False:
                        results["asset_results"][target]["display_status"] = "warning"
                        results["asset_results"][target]["error"] = data.get("tool_error") or "弱口令检测未完成"
                    else:
                        results["asset_results"][target]["display_status"] = "warning" if data.get("found") else "success"
                elif capability in ("snmp_walk", "snmp_bruteforce", "snmp_get"):
                    if data.get("success") is False:
                        results["asset_results"][target]["display_status"] = "warning"
                        results["asset_results"][target]["error"] = data.get("tool_error") or "SNMP 无响应或认证失败"
                    else:
                        results["asset_results"][target]["display_status"] = "success"
                elif capability in ("enum4linux_scan", "crackmapexec_scan", "smb_enum"):
                    if data.get("scan_completed") is False:
                        results["asset_results"][target]["display_status"] = "warning"
                        results["asset_results"][target]["error"] = data.get("tool_error") or "Windows/SMB 检测未完成"
                    else:
                        results["asset_results"][target]["display_status"] = "success"
                elif capability in ("full_compliance_scan", "tech_assessment", "database_security_scan", "web_discovery_scan", "network_device_scan", "windows_security_scan"):
                    summary = data.get("summary") or {}
                    if summary.get("failed") or summary.get("warning"):
                        results["asset_results"][target]["display_status"] = "warning"
                    else:
                        results["asset_results"][target]["display_status"] = "success"
                else:
                    # 其他工具（Web扫描、漏洞检测、基线核查等）：执行成功即为 success
                    results["asset_results"][target]["display_status"] = "success"

                # 合并到全局结果
                if "open_ports" in data:
                    results["open_ports"].extend(data["open_ports"])
                if "filtered_ports" in data:
                    results["filtered_ports"].extend(data["filtered_ports"])
                if "findings" in data:
                    for finding in data["findings"]:
                        if isinstance(finding, dict):
                            finding.setdefault("target", target)
                    results["vulnerabilities"].extend(data["findings"])
                if "issues" in data:
                    results["ssl_issues"].extend(data["issues"])
                if "compliance_score" in data:
                    results["compliance_score"] = data["compliance_score"]

                if capability in ("full_compliance_scan", "tech_assessment", "database_security_scan", "web_discovery_scan", "network_device_scan", "windows_security_scan") and data.get("sub_results"):
                    results["composite_results"].append({
                        "target": target,
                        "capability": capability,
                        "summary": data.get("summary", {}),
                        "sub_results": data.get("sub_results", []),
                    })

                # 弱口令结果处理
                if capability == "scan_weak_passwords":
                    found = data.get("found", [])
                    if found:
                        # 添加目标信息到每条弱口令记录
                        for fp in found:
                            fp["target"] = target
                        results["weak_passwords"].extend(found)
                    # 记录每个资产的统计
                    results["weak_password_stats"][target] = {
                        "found_count": len(found),
                        "tested_users": data.get("tested_users", 0),
                        "tested_passwords": data.get("tested_passwords", 0),
                        "total_combinations": data.get("total_combinations", 0),
                        "service": data.get("service", ""),
                        "port": data.get("port", 0),
                        "scan_completed": data.get("scan_completed"),
                        "tool_error": data.get("tool_error"),
                    }

                # Web 漏洞结果处理
                if capability in ("nikto_scan", "sqlmap_scan", "gobuster_scan", "ffuf_scan"):
                    if data.get("findings"):
                        for f in data["findings"]:
                            f["target"] = target
                            f["tool"] = capability
                        results["web_vulnerabilities"].extend(data["findings"])
                    elif data.get("vulnerabilities"):
                        for f in data["vulnerabilities"]:
                            f["target"] = target
                            f["tool"] = capability
                        results["web_vulnerabilities"].extend(data["vulnerabilities"])
                    if data.get("injection_points"):
                        for f in data["injection_points"]:
                            item = f if isinstance(f, dict) else {"detail": f}
                            item["target"] = target
                            item["tool"] = capability
                            item.setdefault("severity", "high")
                            item.setdefault("name", "SQL 注入点")
                            results["web_vulnerabilities"].append(item)
                    if data.get("discovered"):
                        for f in data["discovered"]:
                            item = f if isinstance(f, dict) else {"path": f}
                            item["target"] = target
                            item["tool"] = capability
                            results["web_discoveries"].append(item)

                if capability in ("redis_check", "mysql_check", "mongodb_check", "memcached_check", "oracle_check"):
                    results["database_results"].setdefault(target, {})[capability] = data
                    if data.get("unauthorized") or data.get("empty_password") or data.get("version_info"):
                        results["database_issues"].append({
                            "target": target,
                            "tool": capability,
                            "unauthorized": data.get("unauthorized"),
                            "empty_password": data.get("empty_password"),
                            "version_info": data.get("version_info"),
                            "port": data.get("port"),
                        })

                if capability in ("snmp_walk", "snmp_bruteforce", "snmp_get"):
                    results["snmp_results"].setdefault(target, {})[capability] = data

                if capability in ("enum4linux_scan", "crackmapexec_scan", "smb_enum"):
                    results["windows_results"].setdefault(target, {})[capability] = data

                # 安全基线核查结果
                if capability in ("baseline_check", "linux_baseline", "password_policy_check", "ssh_config_check", "audit_config_check", "service_port_check", "file_permission_check", "mac_check"):
                    results["baseline_results"].setdefault(target, {})[capability] = data

                # 资产发现结果
                if capability in ("masscan_scan", "scan_ports"):
                    if "open_ports" in data and data["open_ports"]:
                        results["discovered_assets"][target] = {
                            "open_ports": data["open_ports"],
                            "total_open": len(data["open_ports"]),
                        }
            else:
                # 失败的情况
                if is_sub_result:
                    pass
                elif status == "skipped":
                    detail = error_detail or {}
                    results["asset_results"][target]["display_status"] = "warning"
                    results["asset_results"][target]["error"] = detail.get("error_reason") or error
                    results["asset_results"][target]["error_detail"] = error_detail
                else:
                    detail = error_detail or {}
                    results["asset_results"][target]["status"] = "failed"
                    results["asset_results"][target]["display_status"] = "failed"
                    results["asset_results"][target]["error"] = detail.get("error_reason") or error
                    results["asset_results"][target]["error_detail"] = error_detail

        asset_values = list(results["asset_results"].values())
        quality_values = asset_values or ([results["query_result"]] if results["query_result"] else [])
        success_count = sum(1 for item in quality_values if item.get("display_status") == "success")
        warning_count = sum(1 for item in quality_values if item.get("display_status") == "warning")
        failed_count = sum(1 for item in quality_values if item.get("display_status") == "failed")
        incomplete_targets = [
            target
            for target, item in results["asset_results"].items()
            if item.get("display_status") in ("warning", "failed") and item.get("error")
        ]
        if failed_count:
            verdict = "partial"
            note = "部分资产或工具执行失败，结论只能代表已完成的检测项。"
        elif warning_count:
            verdict = "conditional"
            note = "部分资产或工具返回不可判定/未完成，需要结合网络连通性、权限和过滤状态复核。"
        else:
            verdict = "complete"
            note = "检测链路完成，未出现工具级失败或不可判定状态。"

        results["quality"] = {
            "verdict": verdict,
            "total_assets": len(results["query_result"]["assets"]) if results["query_result"] else len(asset_values),
            "success": success_count,
            "warning": warning_count,
            "failed": failed_count,
            "incomplete_targets": incomplete_targets,
            "note": note,
        }

        return results
    
    async def _calculate_and_update_score(self, db: AsyncSession, project_id: int):
        """Recalculate through Flow Engine, the sole owner of compliance scoring."""
        try:
            from app.models.assessment import Assessment
            from app.services.flow_engine import FlowEngine

            assessment = (await db.execute(
                select(Assessment)
                .where(Assessment.project_id == project_id)
                .order_by(Assessment.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if not assessment:
                return

            engine = FlowEngine(db)
            await engine._sync_project_assessment(assessment)
            await db.commit()
            logger.info("Project %s compliance score recalculated by Flow Engine", project_id)
        except Exception as e:
            logger.error(f"Failed to calculate score for project {project_id}: {e}", exc_info=True)
            await db.rollback()
    
    def get_status(self, user_id: int = None) -> dict:
        """获取当前状态，如果指定 user_id 则只返回该用户的任务"""
        return {
            "running": [
                {
                    "task_id": tid,
                    "name": "AI 执行任务",
                    "status": "running",
                    "current_step": progress.get("current_step", "任务执行中..."),
                    "step_progress": {
                        "step_index": progress.get("step_index", 0),
                        "total_steps": progress.get("total_steps", 0),
                        "steps": progress.get("steps", []),
                    },
                }
                for tid, progress in self.task_progress.items()
                if user_id is None or progress.get("user_id") == user_id
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
                if user_id is None or t.get("user_id") == user_id
            ],
        }


# 全局单例
orchestrator = Orchestrator()
