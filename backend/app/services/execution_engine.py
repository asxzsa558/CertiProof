"""
执行引擎 - 执行 AI 生成的执行计划
负责按顺序执行能力，记录操作历史，缓存结果
支持并发执行（多资产场景）
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.capability_registry import CapabilityRegistry, capability_registry
from app.services.context_manager import ContextManager

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """执行引擎"""
    
    def __init__(self, registry: CapabilityRegistry = None):
        self.registry = registry or capability_registry
    
    async def execute_plan(
        self,
        plan: List[Dict],
        user_id: int,
        project_id: int = None,
        db: AsyncSession = None,
        context_manager: ContextManager = None,
        task_id: str = None,
        progress_callback: Callable = None,
    ) -> Dict:
        """
        执行计划中的每个步骤
        
        Args:
            plan: 执行计划，每个步骤包含 capability 和 parameters
            user_id: 用户 ID
            project_id: 项目 ID（可选）
            db: 数据库会话（可选）
            context_manager: 上下文管理器（可选）
            task_id: 任务 ID（可选，用于进度回调）
            progress_callback: 进度回调函数（可选）
        
        Returns:
            {
                "results": [...],  # 每个步骤的结果
                "action_ids": [...],  # 记录的操作 ID
                "success_count": int,  # 成功执行的能力数量
                "failed_count": int,  # 失败的能力数量
            }
        """
        results = []
        action_ids = []
        success_count = 0
        failed_count = 0
        
        for i, step in enumerate(plan):
            capability_name = step.get("capability")
            parameters = step.get("parameters", {})
            
            # 获取能力
            capability = self.registry.get(capability_name)
            
            if not capability:
                logger.warning(f"Unknown capability: {capability_name}")
                results.append({
                    "capability": capability_name,
                    "status": "failed",
                    "error": f"未知能力: {capability_name}",
                })
                failed_count += 1
                if progress_callback and task_id:
                    progress_callback(task_id, i, len(plan), capability_name, "failed")
                continue
            
            try:
                # 通知开始执行
                if progress_callback and task_id:
                    progress_callback(task_id, i, len(plan), capability_name, "running")
                
                # 执行能力
                logger.info(f"Executing capability: {capability_name} with params: {parameters}")
                
                # 根据能力类型调用不同的处理器
                result = await self._execute_capability(capability_name, parameters, user_id, project_id, db)
                
                results.append({
                    "capability": capability_name,
                    "status": "success",
                    "result": result,
                })
                success_count += 1
                
                # 记录操作历史
                if context_manager:
                    await context_manager.add_action(
                        action_type=capability_name,
                        parameters=parameters,
                        result=result,
                        status="success"
                    )
                    
                    # 缓存结果
                    cache_key = f"{capability_name}:{self._generate_cache_key(parameters)}"
                    await context_manager.cache_result(cache_key, result)
                
                # 通知执行完成
                if progress_callback and task_id:
                    progress_callback(task_id, i, len(plan), capability_name, "completed")
                
                logger.info(f"Capability {capability_name} executed successfully")
                
            except Exception as e:
                logger.error(f"Capability {capability_name} failed: {e}", exc_info=True)
                
                results.append({
                    "capability": capability_name,
                    "status": "failed",
                    "error": str(e),
                })
                failed_count += 1
                
                # 通知执行失败
                if progress_callback and task_id:
                    progress_callback(task_id, i, len(plan), capability_name, "failed")
                
                # 记录失败的操作
                if context_manager:
                    await context_manager.add_action(
                        action_type=capability_name,
                        parameters=parameters,
                        result={"error": str(e)},
                        status="failed"
                    )
        
        return {
            "results": results,
            "action_ids": action_ids,
            "success_count": success_count,
            "failed_count": failed_count,
        }
    
    async def execute_plan_concurrent(
        self,
        plan: List[Dict],
        user_id: int,
        project_id: int = None,
        db: AsyncSession = None,
        context_manager: ContextManager = None,
        task_id: str = None,
        progress_callback: Callable = None,
        max_concurrent: int = 5,
        max_retries: int = 3,
        check_stop: Callable = None,
    ) -> Dict:
        """
        并发执行计划（多资产场景）
        
        Args:
            plan: 执行计划，每个步骤包含 capability 和 parameters
            max_concurrent: 最大并发数（默认 5）
            max_retries: 最大重试次数（默认 3）
            check_stop: 检查是否被停止的回调函数
        
        Returns:
            {
                "results": [...],  # 每个步骤的结果
                "success_count": int,
                "failed_count": int,
                "asset_results": {...},  # 按资产分组的结果
            }
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        total_steps = len(plan)
        
        logger.info(f"Starting concurrent execution with {total_steps} tasks, max_concurrent={max_concurrent}")
        
        # 创建并发任务
        tasks = []
        for i, step in enumerate(plan):
            logger.info(f"Creating task {i} for {step.get('capability')}({step.get('parameters', {}).get('target')})")
            task = self._execute_asset_task(
                semaphore=semaphore,
                step=step,
                asset_index=i,
                total_assets=total_steps,
                user_id=user_id,
                project_id=project_id,
                db=db,
                context_manager=context_manager,
                task_id=task_id,
                progress_callback=progress_callback,
                max_retries=max_retries,
                check_stop=check_stop,
            )
            tasks.append(task)
        
        logger.info(f"Starting asyncio.gather with {len(tasks)} tasks")
        
        # 并发执行所有任务
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info(f"asyncio.gather completed with {len(results)} results")
        
        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                if isinstance(result, asyncio.CancelledError):
                    logger.info(f"Task {i} was cancelled")
                    processed_results.append({
                        "capability": plan[i].get("capability"),
                        "target": plan[i].get("parameters", {}).get("target", "unknown"),
                        "status": "cancelled",
                        "error": "Task was stopped",
                        "attempts": 0,
                    })
                else:
                    logger.error(f"Task {i} raised exception: {result}", exc_info=result)
                    processed_results.append({
                        "capability": plan[i].get("capability"),
                        "target": plan[i].get("parameters", {}).get("target", "unknown"),
                        "status": "failed",
                        "error": str(result),
                        "attempts": 0,
                    })
            else:
                processed_results.append(result)
        
        # 统计结果
        success_count = sum(1 for r in processed_results if r.get("status") == "success")
        failed_count = sum(1 for r in processed_results if r.get("status") in ("failed", "cancelled"))
        cancelled_count = sum(1 for r in processed_results if r.get("status") == "cancelled")
        
        # 按资产分组汇总
        asset_results = {}
        for result in processed_results:
            target = result.get("target", "unknown")
            if target not in asset_results:
                asset_results[target] = []
            asset_results[target].append(result)
        
        return {
            "results": processed_results,
            "success_count": success_count,
            "failed_count": failed_count,
            "cancelled_count": cancelled_count,
            "asset_results": asset_results,
            "total_assets": total_steps,
            "was_stopped": cancelled_count > 0,
        }
    
    async def _execute_with_retry(
        self, 
        capability_name: str, 
        parameters: Dict, 
        user_id: int, 
        project_id: int, 
        db: AsyncSession,
        max_retries: int = 3
    ) -> Dict:
        """带重试的执行"""
        last_error = None
        target = parameters.get("target", "unknown")
        
        logger.info(f"_execute_with_retry starting for {capability_name}({target}), max_retries={max_retries}")
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempt {attempt + 1}/{max_retries} for {capability_name}({target})")
                result = await self._execute_capability(
                    capability_name, parameters, user_id, project_id, db
                )
                logger.info(f"Attempt {attempt + 1} succeeded for {capability_name}({target})")
                if attempt > 0:
                    logger.info(
                        f"Retry succeeded for {capability_name}({target}) "
                        f"on attempt {attempt + 1}"
                    )
                return {"status": "success", "result": result, "attempts": attempt + 1}
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed for "
                    f"{capability_name}({target}): {e}"
                )
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    await asyncio.sleep(wait_time)
        
        logger.error(
            f"All {max_retries} attempts failed for {capability_name}({target}): {last_error}",
            exc_info=last_error
        )
        return {
            "status": "failed", 
            "error": str(last_error), 
            "attempts": max_retries
        }
    
    async def _execute_asset_task(
        self,
        semaphore: asyncio.Semaphore,
        step: Dict,
        asset_index: int,
        total_assets: int,
        user_id: int,
        project_id: int,
        db: AsyncSession,
        context_manager: ContextManager,
        task_id: str,
        progress_callback: Callable,
        max_retries: int,
        check_stop: Callable = None,
    ) -> Dict:
        """执行单个资产任务"""
        capability_name = step.get("capability")
        parameters = step.get("parameters", {})
        target = parameters.get("target", "unknown")
        
        # 检查是否被停止
        if check_stop and check_stop():
            logger.info(f"Task {asset_index} stopped before execution for {capability_name}({target})")
            return {
                "capability": capability_name,
                "target": target,
                "status": "cancelled",
                "error": "Task was stopped",
                "attempts": 0,
            }
        
        logger.info(f"Task {asset_index} waiting for semaphore for {capability_name}({target})")
        
        async with semaphore:
            # 再次检查是否被停止（可能在等待 semaphore 期间被停止）
            if check_stop and check_stop():
                logger.info(f"Task {asset_index} stopped after semaphore for {capability_name}({target})")
                return {
                    "capability": capability_name,
                    "target": target,
                    "status": "cancelled",
                    "error": "Task was stopped",
                    "attempts": 0,
                }
            
            logger.info(f"Task {asset_index} acquired semaphore, starting {capability_name}({target})")
            
            # 通知开始
            if progress_callback and task_id:
                progress_callback(
                    task_id, asset_index, total_assets, target, 
                    "running", capability_name
                )
            
            # 执行（带重试）
            result = await self._execute_with_retry(
                capability_name, parameters, user_id, project_id, db, max_retries
            )
            
            # 通知完成
            if progress_callback and task_id:
                progress_callback(
                    task_id, asset_index, total_assets, target, 
                    result["status"], capability_name
                )
            
            # 记录操作历史
            if context_manager:
                await context_manager.add_action(
                    action_type=capability_name,
                    parameters=parameters,
                    result=result,
                    status=result["status"]
                )
                
                if result["status"] == "success":
                    cache_key = f"{capability_name}:{self._generate_cache_key(parameters)}"
                    await context_manager.cache_result(cache_key, result["result"])
            
            return {
                "capability": capability_name,
                "target": target,
                **result
            }
    
    async def _execute_capability(
        self,
        capability_name: str,
        parameters: Dict,
        user_id: int,
        project_id: int = None,
        db: AsyncSession = None,
    ) -> Dict:
        """
        执行单个能力
        
        根据能力类型调用不同的处理器
        """
        # 标准化目标地址：localhost -> host.docker.internal（容器内访问宿主机）
        if "target" in parameters:
            target = parameters["target"]
            if target in ["localhost", "127.0.0.1", "本机", "本地"]:
                parameters["target"] = "host.docker.internal"
        
        # 扫描类能力
        if capability_name == "scan_ports":
            return await self._scan_ports(parameters, user_id, project_id, db)
        
        elif capability_name == "scan_ssl":
            return await self._scan_ssl(parameters, user_id, project_id, db)
        
        elif capability_name == "scan_vulnerabilities":
            return await self._scan_vulnerabilities(parameters, user_id, project_id, db)
        
        elif capability_name == "scan_weak_passwords":
            return await self._scan_weak_passwords(parameters, user_id, project_id, db)
        
        elif capability_name == "full_compliance_scan":
            return await self._full_compliance_scan(parameters, user_id, project_id, db)
        
        # 查询类能力
        elif capability_name == "view_scan_results":
            return await self._view_scan_results(parameters, user_id, project_id, db)
        
        elif capability_name == "view_open_ports":
            return await self._view_open_ports(parameters, user_id, project_id, db)
        
        elif capability_name == "view_vulnerabilities":
            return await self._view_vulnerabilities(parameters, user_id, project_id, db)
        
        elif capability_name == "view_findings":
            return await self._view_findings(parameters, user_id, project_id, db)
        
        elif capability_name == "view_compliance_score":
            return await self._view_compliance_score(parameters, user_id, project_id, db)
        
        elif capability_name == "view_scan_history":
            return await self._view_scan_history(parameters, user_id, project_id, db)
        
        # 项目管理类能力
        elif capability_name == "create_project":
            return await self._create_project(parameters, user_id, db)
        
        elif capability_name == "list_projects":
            return await self._list_projects(user_id, db)
        
        elif capability_name == "update_project":
            return await self._update_project(parameters, user_id, db)
        
        elif capability_name == "delete_project":
            return await self._delete_project(parameters, user_id, db)
        
        # 资产管理类能力
        elif capability_name == "add_asset":
            return await self._add_asset(parameters, user_id, project_id, db)
        
        elif capability_name == "list_assets":
            return await self._list_assets(parameters, user_id, project_id, db)
        
        elif capability_name == "verify_asset":
            return await self._verify_asset(parameters, user_id, project_id, db)
        
        elif capability_name == "ping_asset":
            return await self._ping_asset(parameters, user_id, project_id, db)
        
        # 整改管理类能力
        elif capability_name == "create_remediation_ticket":
            return await self._create_remediation_ticket(parameters, user_id, project_id, db)
        
        elif capability_name == "list_remediation_tickets":
            return await self._list_remediation_tickets(parameters, user_id, project_id, db)
        
        elif capability_name == "update_ticket_status":
            return await self._update_ticket_status(parameters, user_id, project_id, db)
        
        # 报告生成类能力
        elif capability_name == "generate_pdf_report":
            return await self._generate_pdf_report(parameters, user_id, project_id, db)
        
        elif capability_name == "generate_json_report":
            return await self._generate_json_report(parameters, user_id, project_id, db)
        
        # 监控管理类能力
        elif capability_name == "create_scheduled_scan":
            return await self._create_scheduled_scan(parameters, user_id, project_id, db)
        
        elif capability_name == "list_scheduled_scans":
            return await self._list_scheduled_scans(parameters, user_id, project_id, db)
        
        elif capability_name == "trigger_scheduled_scan":
            return await self._trigger_scheduled_scan(parameters, user_id, project_id, db)
        
        # 系统类能力
        elif capability_name == "chat":
            return {"message": parameters.get("message", "")}
        
        elif capability_name == "help":
            return await self._show_help()
        
        else:
            raise ValueError(f"未实现的能力: {capability_name}")
    
    async def _scan_ports(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """端口扫描"""
        from app.mcp.gateway_client import MCPGatewayClient
        
        client = MCPGatewayClient()
        result = await client.call("nmap_scan", {
            "target": parameters["target"],
            "port_range": parameters.get("port_range", "1-65535"),
        })
        
        # 包含 metadata 以便后续检查端口范围
        return {
            **result.get("data", {}),
            "metadata": result.get("metadata", {}),
        }
    
    async def _scan_ssl(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """SSL 扫描"""
        from app.mcp.gateway_client import MCPGatewayClient
        
        client = MCPGatewayClient()
        result = await client.call("testssl_scan", {
            "target": parameters["target"],
            "port": parameters.get("port", 443),
        })
        
        return result.get("data", {})
    
    async def _scan_vulnerabilities(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """漏洞扫描"""
        from app.mcp.gateway_client import MCPGatewayClient
        
        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        
        if "templates" in parameters:
            params["templates"] = parameters["templates"]
        if "severity" in parameters:
            params["severity"] = parameters["severity"]
        
        result = await client.call("nuclei_scan", params)
        return result.get("data", {})
    
    async def _scan_weak_passwords(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """弱口令扫描"""
        from app.mcp.gateway_client import MCPGatewayClient
        
        client = MCPGatewayClient()
        result = await client.call("hydra_bruteforce", {
            "target": parameters["target"],
            "service": parameters.get("service", "ssh"),
            "port": parameters.get("port", 22),
        })
        
        return result.get("data", {})
    
    async def _full_compliance_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """全量合规扫描"""
        # 执行所有扫描
        target = parameters["target"]
        
        results = {
            "port_scan": await self._scan_ports({"target": target}, user_id, project_id, db),
            "ssl_scan": await self._scan_ssl({"target": target}, user_id, project_id, db),
            "vuln_scan": await self._scan_vulnerabilities({"target": target}, user_id, project_id, db),
            "password_scan": await self._scan_weak_passwords({"target": target}, user_id, project_id, db),
        }
        
        return results
    
    async def _view_scan_results(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看扫描结果"""
        # 从缓存或数据库获取最近的扫描结果
        from app.models.context import ResultCache
        from sqlalchemy import select
        
        result = await db.execute(
            select(ResultCache)
            .where(ResultCache.user_id == user_id)
            .order_by(ResultCache.created_at.desc())
            .limit(5)
        )
        caches = result.scalars().all()
        
        return {
            "recent_scans": [
                {
                    "cache_key": c.cache_key,
                    "result": c.result_data,
                    "created_at": c.created_at.isoformat(),
                }
                for c in caches
            ]
        }
    
    async def _view_open_ports(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看开放端口 - 如果没有缓存则自动触发全端口扫描"""
        from app.models.context import ResultCache
        from sqlalchemy import select
        
        result = await db.execute(
            select(ResultCache)
            .where(
                ResultCache.user_id == user_id,
                ResultCache.cache_key.like("scan_ports:%")
            )
            .order_by(ResultCache.created_at.desc())
            .limit(1)
        )
        cache = result.scalar_one_or_none()
        
        if cache:
            result_data = cache.result_data
            # 检查是否是全端口扫描结果
            metadata = result_data.get("metadata", {})
            port_range = metadata.get("port_range", "")
            
            # 如果没有 metadata（旧缓存）或端口范围是 1-65535，视为全端口扫描
            if not port_range or port_range == "1-65535":
                return result_data
            
            # 部分端口扫描，提示需要重新扫描
            return {
                "message": f"最近的扫描只覆盖了端口范围 {port_range}，不是全端口扫描。建议重新执行全端口扫描以获取完整结果。",
                "partial_result": True,
                "current_port_range": port_range,
                "data": result_data.get("data", result_data),
            }
        
        # 没有缓存，自动触发全端口扫描
        target = parameters.get("target", "host.docker.internal")
        if target in ["localhost", "127.0.0.1", "本机", "本地"]:
            target = "host.docker.internal"
        
        # 执行全端口扫描
        scan_result = await self._scan_ports({"target": target}, user_id, project_id, db)
        return {
            **scan_result,
            "auto_scanned": True,
            "message": "没有找到之前的扫描结果，已自动执行全端口扫描。",
        }
    
    async def _view_vulnerabilities(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看漏洞"""
        # 从缓存获取最近的漏洞扫描结果
        from app.models.context import ResultCache
        from sqlalchemy import select
        
        result = await db.execute(
            select(ResultCache)
            .where(
                ResultCache.user_id == user_id,
                ResultCache.cache_key.like("scan_vulnerabilities:%")
            )
            .order_by(ResultCache.created_at.desc())
            .limit(1)
        )
        cache = result.scalar_one_or_none()
        
        if cache:
            return cache.result_data
        else:
            return {"message": "没有找到漏洞扫描结果，请先执行漏洞扫描"}
    
    async def _view_findings(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看发现"""
        from app.models.finding import Finding
        from sqlalchemy import select
        
        query = select(Finding).where(Finding.project_id == project_id)
        
        if "status" in parameters:
            query = query.where(Finding.status == parameters["status"])
        
        result = await db.execute(query.limit(20))
        findings = result.scalars().all()
        
        return {
            "findings": [
                {
                    "id": f.id,
                    "clause_id": f.clause_id,
                    "clause_name": f.clause_name,
                    "severity": f.severity.value if f.severity else None,
                    "status": f.status.value if f.status else None,
                    "description": f.description,
                }
                for f in findings
            ],
            "total": len(findings),
        }
    
    async def _view_compliance_score(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看合规评分"""
        from app.models.project import Project
        from sqlalchemy import select
        
        pid = parameters.get("project_id", project_id)
        
        result = await db.execute(
            select(Project).where(Project.id == pid)
        )
        project = result.scalar_one_or_none()
        
        if project:
            return {
                "project_id": project.id,
                "project_name": project.name,
                "compliance_score": project.compliance_score,
                "compliance_level": project.compliance_level.value if project.compliance_level else None,
            }
        else:
            return {"message": "项目不存在"}
    
    async def _view_scan_history(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看扫描历史"""
        from app.models.scan_task import ScanTask
        from sqlalchemy import select
        
        limit = parameters.get("limit", 10)
        
        query = select(ScanTask).where(ScanTask.project_id == project_id)
        result = await db.execute(
            query.order_by(ScanTask.created_at.desc()).limit(limit)
        )
        tasks = result.scalars().all()
        
        return {
            "scan_history": [
                {
                    "id": t.id,
                    "task_type": t.task_type.value if t.task_type else None,
                    "status": t.status.value if t.status else None,
                    "findings_count": t.findings_count,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                }
                for t in tasks
            ],
            "total": len(tasks),
        }
    
    async def _create_project(self, parameters: Dict, user_id: int, db: AsyncSession) -> Dict:
        """创建项目"""
        from app.models.project import Project, ComplianceLevel
        
        compliance_level = parameters.get("compliance_level", "三级")
        level_enum = ComplianceLevel.LEVEL_3 if compliance_level == "三级" else ComplianceLevel.LEVEL_2
        
        project = Project(
            user_id=user_id,
            name=parameters["name"],
            description=parameters.get("description"),
            compliance_level=level_enum,
        )
        
        db.add(project)
        await db.flush()
        await db.refresh(project)
        
        return {
            "project_id": project.id,
            "name": project.name,
            "compliance_level": compliance_level,
            "message": f"项目 '{project.name}' 创建成功",
        }
    
    async def _list_projects(self, user_id: int, db: AsyncSession) -> Dict:
        """列出项目"""
        from app.models.project import Project
        from sqlalchemy import select
        
        result = await db.execute(
            select(Project).where(Project.user_id == user_id)
        )
        projects = result.scalars().all()
        
        return {
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "compliance_level": p.compliance_level.value if p.compliance_level else None,
                    "compliance_score": p.compliance_score,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in projects
            ],
            "total": len(projects),
        }
    
    async def _update_project(self, parameters: Dict, user_id: int, db: AsyncSession) -> Dict:
        """更新项目"""
        from app.models.project import Project
        from sqlalchemy import select
        
        project_id = parameters.get("project_id")
        
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            return {"message": "项目不存在或无权访问"}
        
        if "name" in parameters:
            project.name = parameters["name"]
        if "description" in parameters:
            project.description = parameters["description"]
        
        await db.flush()
        
        return {
            "project_id": project.id,
            "message": "项目更新成功",
        }
    
    async def _delete_project(self, parameters: Dict, user_id: int, db: AsyncSession) -> Dict:
        """删除项目"""
        from app.models.project import Project
        from sqlalchemy import select, delete
        
        project_id = parameters.get("project_id")
        
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            return {"message": "项目不存在或无权访问"}
        
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.flush()
        
        return {
            "message": f"项目 '{project.name}' 已删除",
        }
    
    async def _add_asset(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """添加资产"""
        from app.models.asset import Asset, AssetType
        from app.models.project import Project
        from sqlalchemy import select
        
        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目"}
        
        result = await db.execute(
            select(Project).where(Project.id == pid, Project.user_id == user_id)
        )
        if not result.scalar_one_or_none():
            return {"message": "项目不存在或无权访问"}
        
        asset_type_str = parameters.get("asset_type", "ip").lower()
        try:
            asset_type = AssetType(asset_type_str)
        except ValueError:
            asset_type = AssetType.IP
        
        value = parameters.get("value", "").strip()
        if not value:
            return {"message": "资产地址不能为空"}
        
        asset = Asset(
            project_id=pid,
            asset_type=asset_type,
            value=value,
            name=parameters.get("name", ""),
        )
        db.add(asset)
        await db.flush()
        await db.refresh(asset)
        
        return {
            "message": f"已添加资产: {value} ({asset_type.value})",
            "asset_id": asset.id,
            "asset_type": asset_type.value,
            "value": value,
        }
    
    async def _list_assets(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """列出项目资产"""
        from app.models.asset import Asset
        from app.models.project import Project
        from sqlalchemy import select
        
        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目", "assets": []}
        
        result = await db.execute(
            select(Project).where(Project.id == pid, Project.user_id == user_id)
        )
        if not result.scalar_one_or_none():
            return {"message": "项目不存在或无权访问", "assets": []}
        
        result = await db.execute(
            select(Asset).where(Asset.project_id == pid).order_by(Asset.created_at.desc())
        )
        assets = result.scalars().all()
        
        return {
            "message": f"项目共有 {len(assets)} 个资产",
            "assets": [
                {
                    "id": a.id,
                    "name": a.name or "",
                    "type": a.asset_type.value,
                    "value": a.value,
                    "verification_status": a.verification_status.value if a.verification_status else "pending",
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in assets
            ],
        }
    
    async def _verify_asset(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """验证资产所有权"""
        import uuid as uuid_mod
        from app.models.asset import Asset, VerificationStatus
        from app.models.project import Project
        from sqlalchemy import select
        
        pid = parameters.get("project_id", project_id)
        asset_id = parameters.get("asset_id")
        
        if not asset_id:
            return {"message": "请指定资产 ID"}
        
        result = await db.execute(
            select(Asset).where(Asset.id == asset_id)
        )
        asset = result.scalar_one_or_none()
        
        if not asset:
            return {"message": "资产不存在"}
        
        if pid:
            result = await db.execute(
                select(Project).where(Project.id == pid, Project.user_id == user_id)
            )
            if not result.scalar_one_or_none():
                return {"message": "项目不存在或无权访问"}
        
        token = f"certiproof-{uuid_mod.uuid4().hex[:16]}"
        asset.verification_token = token
        asset.verification_status = VerificationStatus.PENDING
        await db.flush()
        
        return {
            "message": f"请在 DNS TXT 记录中添加: {token}",
            "asset_id": asset.id,
            "verification_token": token,
            "verification_method": "dns_txt",
        }
    
    async def _ping_asset(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Ping 资产检测可达性"""
        from app.mcp.gateway_client import MCPGatewayClient
        
        target = parameters.get("target")
        if not target:
            return {"message": "请指定目标地址"}
        
        client = MCPGatewayClient()
        result = await client.call("ping_host", {
            "target": target,
            "count": parameters.get("count", 3),
        })
        
        data = result.get("data", {})
        reachable = data.get("reachable", False)
        
        if reachable:
            latency = data.get("avg_latency_ms")
            latency_str = f"，平均延迟 {latency:.1f}ms" if latency else ""
            return {
                "message": f"{target} 可达{latency_str}",
                "target": target,
                "reachable": True,
                "avg_latency_ms": latency,
                "packet_loss": data.get("packet_loss", 0),
            }
        else:
            return {
                "message": f"{target} 不可达",
                "target": target,
                "reachable": False,
                "packet_loss": data.get("packet_loss", 100),
            }
    
    async def _create_remediation_ticket(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """创建整改工单"""
        from app.models.remediation import RemediationTicket, RemediationStatus
        from app.models.finding import Finding
        from sqlalchemy import select
        
        finding_id = parameters.get("finding_id")
        if not finding_id:
            return {"message": "请指定发现 ID"}
        
        result = await db.execute(select(Finding).where(Finding.id == finding_id))
        finding = result.scalar_one_or_none()
        if not finding:
            return {"message": "发现不存在"}
        
        pid = parameters.get("project_id", project_id) or finding.project_id
        
        ticket = RemediationTicket(
            finding_id=finding_id,
            project_id=pid,
            assigned_by=user_id,
            title=parameters.get("title", f"整改: {finding.check_item}"),
            description=parameters.get("description"),
            priority=parameters.get("priority", "medium"),
            status=RemediationStatus.OPEN,
        )
        db.add(ticket)
        await db.flush()
        await db.refresh(ticket)
        
        return {
            "message": f"整改工单已创建: {ticket.title}",
            "ticket_id": ticket.id,
            "status": ticket.status.value,
            "priority": ticket.priority,
        }
    
    async def _list_remediation_tickets(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """列出整改工单"""
        from app.models.remediation import RemediationTicket
        from sqlalchemy import select
        
        query = select(RemediationTicket)
        
        pid = parameters.get("project_id", project_id)
        if pid:
            query = query.where(RemediationTicket.project_id == pid)
        
        status_filter = parameters.get("status")
        if status_filter:
            from app.models.remediation import RemediationStatus
            try:
                query = query.where(RemediationTicket.status == RemediationStatus(status_filter))
            except ValueError:
                pass
        
        result = await db.execute(query.order_by(RemediationTicket.created_at.desc()).limit(50))
        tickets = result.scalars().all()
        
        return {
            "message": f"共 {len(tickets)} 个整改工单",
            "tickets": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "priority": t.priority,
                    "finding_id": t.finding_id,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tickets
            ],
        }
    
    async def _update_ticket_status(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """更新工单状态"""
        from app.models.remediation import RemediationTicket, RemediationStatus
        from sqlalchemy import select
        
        ticket_id = parameters.get("ticket_id")
        if not ticket_id:
            return {"message": "请指定工单 ID"}
        
        result = await db.execute(select(RemediationTicket).where(RemediationTicket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        if not ticket:
            return {"message": "工单不存在"}
        
        new_status = parameters.get("status")
        if not new_status:
            return {"message": "请指定新状态"}
        
        try:
            ticket.status = RemediationStatus(new_status)
        except ValueError:
            return {"message": f"无效状态: {new_status}"}
        
        if parameters.get("resolution_notes"):
            ticket.resolution_notes = parameters["resolution_notes"]
        
        if new_status in ("resolved", "verified", "closed"):
            from datetime import datetime
            ticket.resolved_at = datetime.utcnow()
        
        await db.flush()
        
        return {
            "message": f"工单 #{ticket.id} 状态已更新为 {new_status}",
            "ticket_id": ticket.id,
            "status": new_status,
        }
    
    async def _generate_pdf_report(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """生成 PDF 报告"""
        from app.services.report_service import generate_report
        
        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目 ID"}
        
        try:
            pdf_buffer = await generate_report(db, pid)
            return {
                "message": f"PDF 报告已生成（{len(pdf_buffer.getvalue())} 字节）",
                "project_id": pid,
                "format": "pdf",
                "size_bytes": len(pdf_buffer.getvalue()),
            }
        except Exception as e:
            return {"message": f"报告生成失败: {str(e)}"}
    
    async def _generate_json_report(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """生成 JSON 报告"""
        from app.services.report_service import generate_json_report
        
        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目 ID"}
        
        try:
            report_data = await generate_json_report(db, pid)
            return {
                "message": f"JSON 报告已生成",
                "project_id": pid,
                "format": "json",
                "report": report_data,
            }
        except Exception as e:
            return {"message": f"报告生成失败: {str(e)}"}
    
    async def _create_scheduled_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """创建定时扫描"""
        from app.models.monitoring import ScheduledScan, ScheduleFrequency
        from app.models.asset import Asset
        from sqlalchemy import select
        
        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目 ID"}
        
        asset_id = parameters.get("asset_id")
        if not asset_id:
            return {"message": "请指定资产 ID"}
        
        result = await db.execute(select(Asset).where(Asset.id == asset_id, Asset.project_id == pid))
        if not result.scalar_one_or_none():
            return {"message": "资产不存在或不属于该项目"}
        
        frequency_str = parameters.get("frequency", "weekly")
        try:
            frequency = ScheduleFrequency(frequency_str)
        except ValueError:
            frequency = ScheduleFrequency.WEEKLY
        
        scan = ScheduledScan(
            project_id=pid,
            asset_id=asset_id,
            name=parameters.get("name", f"定时扫描 - {frequency_str}"),
            frequency=frequency,
            is_active=True,
        )
        db.add(scan)
        await db.flush()
        await db.refresh(scan)
        
        return {
            "message": f"定时扫描已创建: {scan.name}",
            "scan_id": scan.id,
            "frequency": frequency.value,
        }
    
    async def _list_scheduled_scans(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """列出定时扫描"""
        from app.models.monitoring import ScheduledScan
        from sqlalchemy import select
        
        query = select(ScheduledScan)
        
        pid = parameters.get("project_id", project_id)
        if pid:
            query = query.where(ScheduledScan.project_id == pid)
        
        result = await db.execute(query.order_by(ScheduledScan.created_at.desc()).limit(50))
        scans = result.scalars().all()
        
        return {
            "message": f"共 {len(scans)} 个定时扫描任务",
            "scans": [
                {
                    "id": s.id,
                    "name": s.name,
                    "frequency": s.frequency.value,
                    "is_active": s.is_active,
                    "asset_id": s.asset_id,
                    "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in scans
            ],
        }
    
    async def _trigger_scheduled_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """触发定时扫描"""
        from app.models.monitoring import ScheduledScan
        from app.models.asset import Asset
        from sqlalchemy import select
        
        scan_id = parameters.get("scan_id")
        if not scan_id:
            return {"message": "请指定定时扫描 ID"}
        
        result = await db.execute(select(ScheduledScan).where(ScheduledScan.id == scan_id))
        scan = result.scalar_one_or_none()
        if not scan:
            return {"message": "定时扫描任务不存在"}
        
        result = await db.execute(select(Asset).where(Asset.id == scan.asset_id))
        asset = result.scalar_one_or_none()
        
        target = asset.value if asset else "unknown"
        
        from app.mcp.gateway_client import MCPGatewayClient
        client = MCPGatewayClient()
        scan_result = await client.call("nmap_scan", {
            "target": target,
            "port_range": "1-65535",
        })
        
        from datetime import datetime
        scan.last_run_at = datetime.utcnow()
        await db.flush()
        
        return {
            "message": f"定时扫描 '{scan.name}' 已触发，目标: {target}",
            "scan_id": scan.id,
            "target": target,
            "result": scan_result.get("data", {}),
        }
    
    async def _show_help(self) -> Dict:
        """显示帮助"""
        return {
            "message": """我是 CertiProof 等保合规智能助手，可以帮你：

🔍 **扫描检测**
- 端口扫描：扫描目标资产的开放端口
- SSL 检测：检查 SSL/TLS 配置
- 漏洞扫描：检测安全漏洞
- 弱口令检测：发现弱密码
- 全量扫描：执行完整的等保合规检测

📊 **数据查询**
- 查看扫描结果
- 查看开放端口
- 查看漏洞列表
- 查看合规评分
- 查看扫描历史

📁 **项目管理**
- 创建项目
- 列出项目
- 更新项目
- 删除项目

📝 **整改管理**
- 创建整改工单
- 列出工单
- 更新工单状态

📄 **报告生成**
- 生成 PDF 报告
- 生成 JSON 报告

⏰ **定时任务**
- 创建定时扫描
- 列出定时任务
- 触发定时扫描

有什么可以帮你的？"""
        }
    
    def _generate_cache_key(self, parameters: Dict) -> str:
        """生成缓存键"""
        import hashlib
        
        # 简单实现：将参数排序后拼接
        parts = []
        for key in sorted(parameters.keys()):
            value = str(parameters[key])
            # 对于长文本，使用哈希值避免超过数据库字段限制
            if len(value) > 100:
                value = hashlib.md5(value.encode()).hexdigest()[:32]
            parts.append(f"{key}={value}")
        
        cache_key = "&".join(parts)
        # 确保不超过 255 字符
        if len(cache_key) > 250:
            cache_key = hashlib.md5(cache_key.encode()).hexdigest()
        
        return cache_key


# 全局单例
execution_engine = ExecutionEngine()
