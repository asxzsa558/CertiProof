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
from app.core.rbac import require_org_permission_for_user_id
from app.core.redaction import redact_sensitive
from app.services.execution_policy import NETWORK_CAPABILITIES, validate_execution_parameters

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """执行引擎"""

    def __init__(self, registry: CapabilityRegistry = None):
        self.registry = registry or capability_registry

    def _normalize_capability_name(self, capability_name: str) -> str:
        aliases = {
            "ping_host": "ping_asset",
            "ssh_check": "ssh_config_check",
            "nmap_scan": "scan_ports",
            "port_scan": "scan_ports",
            "nikto": "nikto_scan",
            "gobuster": "web_discovery_scan",
            "dirbust": "web_discovery_scan",
            "sqlmap": "sqlmap_scan",
            "ffuf": "web_discovery_scan",
            "testssl_scan": "scan_ssl",
            "ssl_check": "scan_ssl",
            "nuclei_scan": "scan_vulnerabilities",
            "vuln_scan": "scan_vulnerabilities",
            "hydra_bruteforce": "scan_weak_passwords",
            "password_test": "scan_weak_passwords",
            "redis": "redis_check",
            "mysql": "mysql_check",
            "mongodb": "mongodb_check",
            "mongo": "mongodb_check",
            "oracle": "oracle_check",
            "memcached": "memcached_check",
            "db": "database_security_scan",
            "database_check": "database_security_scan",
            "database_scan": "database_security_scan",
            "snmp": "network_device_scan",
            "snmpget": "snmp_get",
            "windows": "windows_security_scan",
            "smb": "windows_security_scan",
            "cme": "crackmapexec_scan",
            "baseline": "baseline_check",
            "linux_baseline": "baseline_check",
        }
        return aliases.get(capability_name, capability_name)

    async def _project_for_user_id(
        self,
        db: AsyncSession,
        project_id: int,
        user_id: int,
        permission: str,
    ):
        from app.models.project import Project
        from sqlalchemy import select

        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            return None
        if project.organization_id:
            try:
                await require_org_permission_for_user_id(db, project.organization_id, user_id, permission)
            except Exception:
                return None
        elif project.user_id != user_id and project.owner_id != user_id:
            return None
        return project

    def _ssh_params(self, parameters: Dict) -> Dict:
        params = {
            "target": parameters["target"],
            "username": parameters.get("username") or parameters.get("ssh_username") or "root",
            "port": parameters.get("port") or parameters.get("ssh_port") or 22,
        }
        password = parameters.get("password") or parameters.get("ssh_password")
        key_file = parameters.get("key_file") or parameters.get("ssh_key_file")
        if password:
            params["password"] = password
        if key_file:
            params["key_file"] = key_file
        if "categories" in parameters:
            params["categories"] = parameters["categories"]
        return params

    def _clean_error_message(self, error: Any) -> str:
        message = str(error or "未知错误")
        if '{"detail":"' in message:
            message = message.split('{"detail":"', 1)[1].split('"}', 1)[0]
        return message.replace("\\n", "\n").strip()

    def _error_detail(self, error: Any, capability: str = None) -> Dict[str, str]:
        message = self._clean_error_message(error)
        lower = message.lower()

        if "filtered" in lower or "no-response" in lower or "无法连接到目标" in message or "unreachable" in lower:
            error_type = "network_filtered_or_unreachable"
            reason = "目标端口无响应或被防火墙/安全组过滤，工具无法建立连接。"
            remediation = "确认目标端口状态是 open 而不是 filtered；检查云安全组、防火墙、ACL、来源 IP 白名单和实际服务端口。"
        elif "timeout" in lower or "timed out" in lower:
            error_type = "timeout"
            reason = "工具等待目标响应超时，可能是网络丢包、目标限速或服务响应过慢。"
            remediation = "降低并发或速率后重试；确认目标允许扫描来源访问；必要时延长超时时间。"
        elif "auth" in lower or "permission denied" in lower or "认证失败" in message:
            error_type = "authentication_failed"
            reason = "已连到服务，但认证失败或权限不足。"
            remediation = "检查用户名、密码/密钥、root 登录策略、密码登录开关和账号权限。"
        elif "必须提供 password 或 key_file" in message or "missing required parameter" in lower or "缺少必要参数" in message:
            error_type = "missing_parameter"
            reason = "工具缺少必要参数。"
            remediation = "补齐目标、端口、账号凭据或工具要求的参数后重试。"
        elif "not installed" in lower or "工具未安装" in message:
            error_type = "tool_dependency_missing"
            reason = "工具服务缺少依赖或二进制。"
            remediation = "检查工具容器镜像和 /diagnose 依赖检测结果，重建对应工具服务。"
        elif "connection refused" in lower or "refused" in lower:
            error_type = "connection_refused"
            reason = "目标明确拒绝连接，通常表示端口关闭或服务未监听。"
            remediation = "确认服务已启动并监听正确端口；检查本机防火墙是否拒绝连接。"
        elif "name or service not known" in lower or "dns" in lower:
            error_type = "dns_resolution_failed"
            reason = "域名无法解析。"
            remediation = "检查域名拼写、DNS 解析和容器网络 DNS 配置。"
        else:
            error_type = "tool_execution_failed"
            reason = message
            remediation = "查看工具详情和 /diagnose；如目标受防护或限速，调整参数后重试。"

        if capability in {"baseline_check", "ssh_config_check", "password_policy_check"} and error_type == "network_filtered_or_unreachable":
            remediation = "确认 SSH 端口实际开放为 open；检查云安全组/防火墙是否允许当前扫描出口 IP；确认 SSH 端口是否不是 22。"

        return {
            "error_type": error_type,
            "error_reason": reason,
            "remediation": remediation,
            "raw_error": message,
        }

    def _ssh_unavailable_payload(self, parameters: Dict, error: Exception) -> Dict:
        detail = self._error_detail(error, "baseline_check")
        message = detail["raw_error"]
        return {
            "target": parameters.get("target"),
            "os_type": "unknown",
            "supported": False,
            "skipped": True,
            "connection_error": True,
            "skip_reason": message,
            "tool_error": message,
            "error_detail": detail,
            "summary": {
                "total_checks": 0,
                "compliant": 0,
                "non_compliant": 0,
                "info_only": 0,
                "compliance_rate": 0,
            },
            "metadata": {},
            "tool_status": "skipped",
        }

    async def _call_ssh_checker(self, tool_name: str, parameters: Dict) -> Dict:
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = self._ssh_params(parameters)
        try:
            result = await client.call_with_progress(tool_name, params)
            return self._gateway_payload(result)
        except Exception as e:
            return self._ssh_unavailable_payload(parameters, e)

    def _target_from_parameters(self, parameters: Dict) -> str:
        if parameters.get("target"):
            return parameters["target"]
        if parameters.get("url"):
            return parameters["url"]
        if parameters.get("network"):
            return parameters["network"]
        if isinstance(parameters.get("targets"), list):
            return ",".join(parameters["targets"][:3])
        return "unknown"

    def _tool_display_status(self, data: Dict) -> str:
        if not isinstance(data, dict):
            return "success"
        if data.get("tool_status") == "warning":
            return "warning"
        error = str(data.get("tool_error") or data.get("connection_error") or "").lower()
        if (data.get("reachable") is False or data.get("scan_completed") is False) and any(marker in error for marker in (
            "connection refused", "errno 111", "can't connect to server", "service not listening",
        )):
            return "skipped"
        if data.get("scan_completed") is False or data.get("success") is False or data.get("reachable") is False:
            return "warning"
        return "success"

    async def _run_subtool(
        self,
        capability_name: str,
        parameters: Dict,
        user_id: int,
        project_id: int,
        db: AsyncSession,
        label: str = None,
    ) -> Dict:
        """Run one child tool and always return the same result shape."""
        normalized = self._normalize_capability_name(capability_name)
        target = self._target_from_parameters(parameters)
        try:
            data = await self._execute_capability(normalized, dict(parameters), user_id, project_id, db)
            metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
            sub_status = self._tool_display_status(data)
            return {
                "status": sub_status,
                "target": target,
                "capability": normalized,
                "label": label or normalized,
                "data": data if isinstance(data, dict) else {"value": data},
                "metadata": metadata,
                "error": None,
            }
        except Exception as e:
            logger.warning(f"Subtool {normalized}({target}) failed: {e}")
            error_detail = self._error_detail(e, normalized)
            return {
                "status": "failed",
                "target": target,
                "capability": normalized,
                "label": label or normalized,
                "data": {},
                "metadata": {},
                "error": error_detail["raw_error"],
                "error_detail": error_detail,
            }

    def _skipped_subtool(self, capability_name: str, target: str, reason: str, label: str = None) -> Dict:
        normalized = self._normalize_capability_name(capability_name)
        return {
            "status": "skipped",
            "target": target,
            "capability": normalized,
            "label": label or normalized,
            "data": {},
            "metadata": {},
            "error": reason,
        }

    def _summarize_subtools(self, sub_results: List[Dict]) -> Dict:
        return {
            "total": len(sub_results),
            "success": sum(1 for r in sub_results if r.get("status") == "success"),
            "warning": sum(1 for r in sub_results if r.get("status") == "warning"),
            "failed": sum(1 for r in sub_results if r.get("status") == "failed"),
            "skipped": sum(1 for r in sub_results if r.get("status") == "skipped"),
        }

    def _url_param(self, parameters: Dict, *, require_fuzz: bool = False) -> str:
        url = parameters.get("url") or parameters.get("target")
        if not url:
            raise ValueError("缺少目标 URL")
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        if require_fuzz and "FUZZ" not in url:
            url = url.rstrip("/") + "/FUZZ"
        return url

    async def execute_plan(
        self,
        plan: List[Dict],
        user_id: int,
        project_id: int = None,
        db: AsyncSession = None,
        context_manager: ContextManager = None,
        task_id: str = None,
        progress_callback: Callable = None,
        check_stop: Callable = None,
        wait_if_paused: Callable = None,
        step_result_callback: Callable = None,
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
        warning_count = 0
        failed_count = 0

        for i, step in enumerate(plan):
            checkpoint_index = step.get("_checkpoint_index", i)
            if check_stop and check_stop():
                logger.info(f"Task stopped before step {i}")
                for remaining in range(i, len(plan)):
                    results.append({
                        "capability": plan[remaining].get("capability"),
                        "status": "cancelled",
                        "error": "Task was stopped",
                    })
                    failed_count += 1
                break

            if wait_if_paused:
                stopped = await wait_if_paused()
                if stopped:
                    logger.info(f"Task stopped while paused before step {i}")
                    for remaining in range(i, len(plan)):
                        results.append({
                            "capability": plan[remaining].get("capability"),
                            "status": "cancelled",
                            "error": "Task was stopped while paused",
                        })
                        failed_count += 1
                    break

            capability_name = self._normalize_capability_name(step.get("capability"))
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
                safe_parameters = redact_sensitive(parameters)
                logger.info(f"Executing capability: {capability_name} with params: {safe_parameters}")

                # 根据能力类型调用不同的处理器
                result = await self._execute_capability(capability_name, parameters, user_id, project_id, db)
                execution_status = self._tool_display_status(result)

                results.append({
                    "capability": capability_name,
                    "status": execution_status,
                    "target": parameters.get("target", "unknown"),
                    "parameters": safe_parameters,
                    "result": result,
                })
                if execution_status == "success":
                    success_count += 1
                else:
                    warning_count += 1
                if step_result_callback:
                    await step_result_callback(checkpoint_index, results[-1])

                # 记录操作历史
                if context_manager:
                    await context_manager.add_action(
                        action_type=capability_name,
                        parameters=safe_parameters,
                        result=result,
                        status=execution_status,
                    )

                    # 缓存结果
                    cache_key = f"{capability_name}:{self._generate_cache_key(safe_parameters)}"
                    await context_manager.cache_result(cache_key, result)

                # 通知执行完成
                if progress_callback and task_id:
                    progress_callback(task_id, i, len(plan), capability_name, "completed" if execution_status == "success" else execution_status)

                logger.info(f"Capability {capability_name} executed successfully")

            except Exception as e:
                logger.error(f"Capability {capability_name} failed: {e}", exc_info=True)

                results.append({
                    "capability": capability_name,
                    "status": "failed",
                    "target": parameters.get("target", "unknown"),
                    "error": str(e),
                })
                failed_count += 1
                if step_result_callback:
                    await step_result_callback(checkpoint_index, results[-1])

                # 通知执行失败
                if progress_callback and task_id:
                    progress_callback(task_id, i, len(plan), capability_name, "failed")

                # 记录失败的操作
                if context_manager:
                    await context_manager.add_action(
                        action_type=capability_name,
                        parameters=redact_sensitive(parameters),
                        result={"error": str(e)},
                        status="failed"
                    )

        return {
            "results": results,
            "action_ids": action_ids,
            "success_count": success_count,
            "warning_count": warning_count,
            "failed_count": failed_count,
        }

    async def execute_plan_concurrent(
        self,
        plan: List[Dict],
        user_id: int = None,
        project_id: int = None,
        db: AsyncSession = None,
        context_manager: ContextManager = None,
        task_id: str = None,
        progress_callback: Callable = None,
        max_concurrent: int = 5,
        max_retries: int = 3,
        check_stop: Callable = None,
        wait_if_paused: Callable = None,
        step_result_callback: Callable = None,
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
                wait_if_paused=wait_if_paused,
                step_result_callback=step_result_callback,
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
                    error_detail = self._error_detail(result, plan[i].get("capability"))
                    processed_results.append({
                        "capability": plan[i].get("capability"),
                        "target": plan[i].get("parameters", {}).get("target", "unknown"),
                        "status": "failed",
                        "error": error_detail["raw_error"],
                        "error_detail": error_detail,
                        "attempts": 0,
                    })
            else:
                processed_results.append(result)

        # 统计结果
        success_count = sum(1 for r in processed_results if r.get("status") == "success")
        warning_count = sum(1 for r in processed_results if r.get("status") in ("warning", "skipped"))
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
            "warning_count": warning_count,
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
                return {
                    "status": self._tool_display_status(result),
                    "result": result,
                    "attempts": attempt + 1,
                }
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
        error_detail = self._error_detail(last_error, capability_name)
        return {
            "status": "failed",
            "error": error_detail["raw_error"],
            "error_detail": error_detail,
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
        db: AsyncSession = None,
        context_manager: ContextManager = None,
        task_id: str = None,
        progress_callback: Callable = None,
        max_retries: int = 3,
        check_stop: Callable = None,
        wait_if_paused: Callable = None,
        step_result_callback: Callable = None,
    ) -> Dict:
        """
        执行单个资产任务（L2 Skill Worker）

        重要约束（来自 design-v2.md）：
        - Skill 没有写权限，不能直接修改全局看板
        - 每个 Skill 使用独立 session，避免并发冲突
        - Skill 只返回结果到内存，由 Agent 统一写 DB
        """
        capability_name = self._normalize_capability_name(step.get("capability"))
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

        # 如果暂停，等待恢复
        if wait_if_paused:
            stopped = await wait_if_paused()
            if stopped:
                logger.info(f"Task {asset_index} stopped while paused for {capability_name}({target})")
                return {
                    "capability": capability_name,
                    "target": target,
                    "status": "cancelled",
                    "error": "Task was stopped while paused",
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

            # 再次检查是否暂停（可能在等待 semaphore 期间被暂停）
            if wait_if_paused:
                stopped = await wait_if_paused()
                if stopped:
                    logger.info(f"Task {asset_index} stopped while paused after semaphore for {capability_name}({target})")
                    return {
                        "capability": capability_name,
                        "target": target,
                        "status": "cancelled",
                        "error": "Task was stopped while paused",
                        "attempts": 0,
                    }

            logger.info(f"Task {asset_index} acquired semaphore, starting {capability_name}({target})")

            # 通知开始
            if progress_callback and task_id:
                progress_callback(
                    task_id, asset_index, total_assets, target,
                    "running", capability_name
                )

            # 为每个并发任务创建独立的数据库 session，避免共享 session 导致的并发冲突
            # 这是 L2 Skill 的隔离原则（design-v2.md）
            from app.core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as task_db:
                # 执行（带重试）
                result = await self._execute_with_retry(
                    capability_name, parameters, user_id, project_id, task_db, max_retries
                )

                # 通知完成
                if progress_callback and task_id:
                    progress_callback(
                        task_id, asset_index, total_assets, target,
                        result["status"], capability_name
                    )

            # L2 Skill 没有写权限！
            # 之前的代码会在这里调用 context_manager.add_action() 和 cache_result()
            # 现在改为只返回结果，由 Agent（主流程）统一处理 DB 写入

            outcome = {
                "capability": capability_name,
                "target": target,
                "parameters": redact_sensitive(parameters),
                "status": result.get("status"),
                "result": result.get("result"),
                "error": result.get("error"),
                "error_detail": result.get("error_detail"),
                "attempts": result.get("attempts", 1),
            }
            if step_result_callback:
                await step_result_callback(step.get("_checkpoint_index", asset_index), outcome)
            return outcome

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
        capability_name = self._normalize_capability_name(capability_name)
        if capability_name in NETWORK_CAPABILITIES and project_id and db:
            if not await self._project_for_user_id(db, project_id, user_id, "scan:execute"):
                raise ValueError("当前用户无权在该项目执行安全检测")
        parameters = await validate_execution_parameters(
            capability_name,
            parameters,
            project_id=project_id,
            db=db,
        )

        # 标准化目标地址：localhost -> host.docker.internal（容器内访问宿主机）
        if "target" in parameters:
            target = parameters["target"]
            if target in ["localhost", "127.0.0.1", "本机", "本地"]:
                parameters["target"] = "host.docker.internal"

        # 扫描类能力
        if capability_name == "scan_ports":
            return await self._scan_ports(parameters, user_id, project_id, db)

        elif capability_name == "masscan_scan":
            return await self._masscan_scan(parameters, user_id, project_id, db)

        elif capability_name == "fping_scan":
            return await self._fping_scan(parameters, user_id, project_id, db)

        elif capability_name == "nikto_scan":
            return await self._nikto_scan(parameters, user_id, project_id, db)

        elif capability_name == "sqlmap_scan":
            return await self._sqlmap_scan(parameters, user_id, project_id, db)

        elif capability_name == "gobuster_scan":
            return await self._gobuster_scan(parameters, user_id, project_id, db)

        elif capability_name == "ffuf_scan":
            return await self._ffuf_scan(parameters, user_id, project_id, db)

        elif capability_name == "web_discovery_scan":
            return await self._web_discovery_scan(parameters, user_id, project_id, db)

        elif capability_name == "snmp_walk":
            return await self._snmp_walk(parameters, user_id, project_id, db)

        elif capability_name == "snmp_bruteforce":
            return await self._snmp_bruteforce(parameters, user_id, project_id, db)

        elif capability_name == "snmp_get":
            return await self._snmp_get(parameters, user_id, project_id, db)

        elif capability_name == "network_device_scan":
            return await self._network_device_scan(parameters, user_id, project_id, db)

        elif capability_name == "enum4linux_scan":
            return await self._enum4linux_scan(parameters, user_id, project_id, db)

        elif capability_name == "crackmapexec_scan":
            return await self._crackmapexec_scan(parameters, user_id, project_id, db)

        elif capability_name == "smb_enum":
            return await self._smb_enum(parameters, user_id, project_id, db)

        elif capability_name == "windows_security_scan":
            return await self._windows_security_scan(parameters, user_id, project_id, db)

        elif capability_name == "redis_check":
            return await self._redis_check(parameters, user_id, project_id, db)

        elif capability_name == "oracle_check":
            return await self._oracle_check(parameters, user_id, project_id, db)

        elif capability_name == "mongodb_check":
            return await self._mongodb_check(parameters, user_id, project_id, db)

        elif capability_name == "memcached_check":
            return await self._memcached_check(parameters, user_id, project_id, db)

        elif capability_name == "mysql_check":
            return await self._mysql_check(parameters, user_id, project_id, db)

        elif capability_name == "database_security_scan":
            return await self._database_security_scan(parameters, user_id, project_id, db)

        elif capability_name == "scan_ssl":
            return await self._scan_ssl(parameters, user_id, project_id, db)

        elif capability_name == "scan_vulnerabilities":
            return await self._scan_vulnerabilities(parameters, user_id, project_id, db)

        elif capability_name == "scan_weak_passwords":
            return await self._scan_weak_passwords(parameters, user_id, project_id, db)

        elif capability_name == "full_compliance_scan":
            return await self._full_compliance_scan(parameters, user_id, project_id, db)

        elif capability_name == "tech_assessment":
            return await self._tech_assessment(parameters, user_id, project_id, db)

        # SSH 白盒配置核查能力
        elif capability_name == "baseline_check":
            return await self._baseline_check(parameters, user_id, project_id, db)

        elif capability_name == "password_policy_check":
            return await self._password_policy_check(parameters, user_id, project_id, db)

        elif capability_name == "ssh_config_check":
            return await self._ssh_config_check(parameters, user_id, project_id, db)

        elif capability_name == "audit_config_check":
            return await self._audit_config_check(parameters, user_id, project_id, db)

        elif capability_name == "service_port_check":
            return await self._service_port_check(parameters, user_id, project_id, db)

        elif capability_name == "file_permission_check":
            return await self._file_permission_check(parameters, user_id, project_id, db)

        elif capability_name == "mac_check":
            return await self._mac_check(parameters, user_id, project_id, db)

        # 查询类能力
        elif capability_name == "view_open_ports":
            return await self._view_open_ports(parameters, user_id, project_id, db)

        elif capability_name == "view_vulnerabilities":
            return await self._view_vulnerabilities(parameters, user_id, project_id, db)

        elif capability_name == "view_findings":
            return await self._view_findings(parameters, user_id, project_id, db)

        elif capability_name == "view_project_status":
            return await self._view_project_status(parameters, user_id, project_id, db)

        elif capability_name == "view_compliance_score":
            return await self._view_compliance_score(parameters, user_id, project_id, db)

        elif capability_name == "view_scan_history":
            return await self._view_scan_history(parameters, user_id, project_id, db)

        elif capability_name == "assessment_flow_action":
            return await self._assessment_flow_action(parameters, user_id, project_id, db)

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
        # 报告生成类能力
        elif capability_name == "generate_html_report":
            return await self._generate_html_report(parameters, user_id, project_id, db)

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

        # 使用 call_with_progress 避免长时间阻塞
        def on_progress(progress):
            logger.info(f"Scan progress: {progress}")

        result = await client.call_with_progress(
            "nmap_scan",
            {
                "target": parameters["target"],
                "port_range": parameters.get("port_range", "high-risk"),
            },
            on_progress=on_progress,
            poll_interval=2.0
        )

        data = result.get("data", {})

        # 如果主机不可达，抛出异常（会被重试机制捕获并标记为失败）
        if data.get("host_status") == "down":
            raise ValueError(f"主机 {data.get('target')} 不可达")

        # 包含 metadata 以便后续检查端口范围
        return {
            **data,
            "metadata": result.get("metadata", {}),
        }

    def _gateway_payload(self, result: Dict, *, allow_tool_failed: bool = False) -> Dict:
        data = result.get("data") or {}
        metadata = result.get("metadata") or {}
        tool_status = result.get("status", "success")
        tool_error = result.get("error") or metadata.get("error")
        payload = data if isinstance(data, dict) else {"value": data}
        payload = {
            **payload,
            "metadata": metadata,
            "tool_status": tool_status,
        }
        if tool_error:
            payload["tool_error"] = tool_error
        if tool_status == "failed" and not allow_tool_failed:
            raise ValueError(tool_error or "工具执行失败")
        return payload

    async def _masscan_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """masscan 超高速端口扫描"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {
            "target": parameters["target"],
            "port_range": parameters.get("port_range", "1-65535"),
        }
        if "rate" in parameters:
            params["rate"] = parameters["rate"]
        if "banner_grab" in parameters:
            params["banner_grab"] = parameters["banner_grab"]

        result = await client.call("masscan_scan", params)

        data = result.get("data", {})
        return self._gateway_payload(result)

    async def _fping_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """fping 批量存活检测"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {}
        if "network" in parameters:
            params["network"] = parameters["network"]
        elif "target" in parameters:
            # AI 可能传 target 而不是 network，兼容处理
            params["network"] = parameters["target"]
        if "targets" in parameters:
            params["targets"] = parameters["targets"]

        result = await client.call("fping_scan", params)
        return self._gateway_payload(result)

    async def _nikto_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """nikto Web 服务器扫描"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        # 标准化目标：移除 scheme 前缀（如果用户传了完整 URL）
        target = parameters["target"]
        if target.startswith("http://"):
            target = target[7:]  # 去掉 "http://"
        elif target.startswith("https://"):
            target = target[8:]  # 去掉 "https://"

        params = {"target": target}
        if "port" in parameters:
            params["port"] = parameters["port"]
        if "ssl" in parameters:
            params["ssl"] = parameters["ssl"]
        if "timeout" in parameters:
            params["timeout"] = parameters["timeout"]

        result = await client.call("nikto_scan", params)
        return self._gateway_payload(result)

    async def _sqlmap_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """sqlmap SQL 注入检测"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"url": self._url_param(parameters)}
        if "data" in parameters:
            params["data"] = parameters["data"]
        if "level" in parameters:
            params["level"] = parameters["level"]
        if "risk" in parameters:
            params["risk"] = parameters["risk"]
        if "timeout" in parameters:
            params["timeout"] = parameters["timeout"]

        result = await client.call("sqlmap_scan", params)
        return self._gateway_payload(result)

    async def _gobuster_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """gobuster 目录/文件爆破"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        url = self._url_param(parameters)

        params = {"url": url}
        if "wordlist" in parameters:
            params["wordlist"] = parameters["wordlist"]
        if "extensions" in parameters:
            params["extensions"] = parameters["extensions"]
        if "threads" in parameters:
            params["threads"] = parameters["threads"]
        if "timeout" in parameters:
            params["timeout"] = parameters["timeout"]

        result = await client.call("gobuster_scan", params)
        return self._gateway_payload(result)

    async def _ffuf_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """ffuf Web 模糊测试"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        url = self._url_param(parameters, require_fuzz=True)

        params = {"url": url}
        if "wordlist" in parameters:
            params["wordlist"] = parameters["wordlist"]
        if "method" in parameters:
            params["method"] = parameters["method"]
        if "timeout" in parameters:
            params["timeout"] = parameters["timeout"]

        result = await client.call("ffuf_scan", params)
        return self._gateway_payload(result)

    async def _web_discovery_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Web 路径/目录发现：组合 gobuster 与 ffuf。"""
        url = self._url_param(parameters)
        sub_params = {"url": url}
        if "timeout" in parameters:
            sub_params["timeout"] = parameters["timeout"]
        sub_results = await asyncio.gather(
            self._run_subtool("gobuster_scan", sub_params, user_id, project_id, db, "目录爆破"),
            self._run_subtool("ffuf_scan", sub_params, user_id, project_id, db, "Web 模糊测试"),
        )
        return {
            "target": url,
            "sub_results": sub_results,
            "summary": self._summarize_subtools(sub_results),
        }

    async def _snmp_walk(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """snmpwalk 获取 SNMP 信息"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "community" in parameters:
            params["community"] = parameters["community"]
        if "version" in parameters:
            params["version"] = parameters["version"]
        if "oid" in parameters:
            params["oid"] = parameters["oid"]

        result = await client.call("snmp_walk", params)
        return self._gateway_payload(result, allow_tool_failed=True)

    async def _snmp_bruteforce(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """SNMP 团体字爆破"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "wordlist" in parameters:
            params["wordlist"] = parameters["wordlist"]

        result = await client.call("snmp_bruteforce", params)
        return self._gateway_payload(result, allow_tool_failed=True)

    async def _snmp_get(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """snmpget 获取单个 OID 值"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"], "oid": parameters["oid"]}
        if "community" in parameters:
            params["community"] = parameters["community"]
        if "version" in parameters:
            params["version"] = parameters["version"]

        result = await client.call("snmp_get", params)
        return self._gateway_payload(result, allow_tool_failed=True)

    async def _network_device_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """网络设备检测：组合 SNMP 信息读取与默认团体字检测。"""
        target = parameters["target"]
        sub_results = await asyncio.gather(
            self._run_subtool("snmp_walk", {"target": target}, user_id, project_id, db, "SNMP 信息读取"),
            self._run_subtool("snmp_bruteforce", {"target": target}, user_id, project_id, db, "SNMP 团体字检测"),
        )
        return {
            "target": target,
            "sub_results": sub_results,
            "summary": self._summarize_subtools(sub_results),
        }

    async def _enum4linux_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """enum4linux Windows 信息枚举"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "username" in parameters:
            params["username"] = parameters["username"]
        if "password" in parameters:
            params["password"] = parameters["password"]
        if "scan_type" in parameters:
            params["scan_type"] = parameters["scan_type"]

        result = await client.call("enum4linux_scan", params)
        return self._gateway_payload(result, allow_tool_failed=True)

    async def _crackmapexec_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """crackmapexec SMB/Windows 枚举"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "username" in parameters:
            params["username"] = parameters["username"]
        if "password" in parameters:
            params["password"] = parameters["password"]
        if "scan_type" in parameters:
            params["scan_type"] = parameters["scan_type"]

        result = await client.call("crackmapexec_scan", params)
        return self._gateway_payload(result, allow_tool_failed=True)

    async def _smb_enum(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """SMB 共享枚举"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "username" in parameters:
            params["username"] = parameters["username"]
        if "password" in parameters:
            params["password"] = parameters["password"]

        result = await client.call("smb_enum", params)
        return self._gateway_payload(result, allow_tool_failed=True)

    async def _windows_security_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Windows/AD 安全检测：组合用户、SID 与 SMB 共享枚举。"""
        target = parameters["target"]
        base = {"target": target}
        if "username" in parameters:
            base["username"] = parameters["username"]
        if "password" in parameters:
            base["password"] = parameters["password"]
        sub_results = await asyncio.gather(
            self._run_subtool("enum4linux_scan", base, user_id, project_id, db, "Windows 用户/组枚举"),
            self._run_subtool("crackmapexec_scan", base, user_id, project_id, db, "Windows SID 枚举"),
            self._run_subtool("smb_enum", base, user_id, project_id, db, "SMB 共享枚举"),
        )
        return {
            "target": target,
            "sub_results": sub_results,
            "summary": self._summarize_subtools(sub_results),
        }

    async def _redis_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Redis 未授权访问检查"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "port" in parameters:
            params["port"] = parameters["port"]

        result = await client.call("redis_check", params)
        return self._gateway_payload(result)

    async def _oracle_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Oracle TNS 版本信息检查"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "port" in parameters:
            params["port"] = parameters["port"]

        result = await client.call("oracle_check", params)
        return self._gateway_payload(result)

    async def _mongodb_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """MongoDB 未授权访问检查"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "port" in parameters:
            params["port"] = parameters["port"]

        result = await client.call("mongodb_check", params)
        return self._gateway_payload(result)

    async def _memcached_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Memcached 未授权访问检查"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "port" in parameters:
            params["port"] = parameters["port"]

        result = await client.call("memcached_check", params)
        return self._gateway_payload(result)

    async def _mysql_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """MySQL 空口令检查"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}
        if "port" in parameters:
            params["port"] = parameters["port"]
        if "username" in parameters:
            params["username"] = parameters["username"]

        result = await client.call("mysql_check", params)
        return self._gateway_payload(result, allow_tool_failed=True)

    async def _database_security_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """数据库安全组合检测：Redis/MySQL/MongoDB/Memcached/Oracle。"""
        target = parameters["target"]
        sub_tasks = [
            ("redis_check", {"target": target}, "Redis 未授权检测"),
            ("mysql_check", {"target": target}, "MySQL 空口令检测"),
            ("mongodb_check", {"target": target}, "MongoDB 未授权检测"),
            ("memcached_check", {"target": target}, "Memcached 未授权检测"),
            ("oracle_check", {"target": target}, "Oracle TNS 检测"),
        ]
        sub_results = await asyncio.gather(*[
            self._run_subtool(capability, params, user_id, project_id, db, label)
            for capability, params, label in sub_tasks
        ])

        return {
            "target": target,
            "sub_results": sub_results,
            "summary": self._summarize_subtools(sub_results),
        }

    async def _scan_ssl(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """SSL 扫描"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        result = await client.call_with_progress("testssl_scan", {
            "target": parameters["target"],
            "port": parameters.get("port", 443),
            **({"timeout": parameters["timeout"]} if "timeout" in parameters else {}),
        })

        return self._gateway_payload(result)

    async def _scan_vulnerabilities(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """漏洞扫描"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        params = {"target": parameters["target"]}

        if "templates" in parameters:
            params["templates"] = parameters["templates"]
        if "severity" in parameters:
            params["severity"] = parameters["severity"]
        if "timeout" in parameters:
            params["timeout"] = parameters["timeout"]

        result = await client.call_with_progress("nuclei_scan", params)
        return self._gateway_payload(result, allow_tool_failed=True)

    async def _scan_weak_passwords(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """弱口令扫描"""
        from app.mcp.gateway_client import MCPGatewayClient

        client = MCPGatewayClient()
        result = await client.call_with_progress("hydra_bruteforce", {
            "target": parameters["target"],
            "service": parameters.get("service", "ssh"),
            "port": parameters.get("port", 22),
        })

        return self._gateway_payload(result)

    async def _full_compliance_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """全量合规扫描"""
        target = parameters["target"]
        sub_tasks = [
            ("scan_ports", {"target": target, "port_range": parameters.get("port_range", "high-risk")}, "端口扫描"),
            ("scan_ssl", {"target": target, "port": parameters.get("ssl_port", 443)}, "SSL/TLS 检测"),
            ("scan_vulnerabilities", {"target": target}, "漏洞扫描"),
            ("scan_weak_passwords", {"target": target}, "弱口令检测"),
        ]
        sub_results = await asyncio.gather(*[
            self._run_subtool(capability, params, user_id, project_id, db, label)
            for capability, params, label in sub_tasks
        ])

        return {
            "target": target,
            "sub_results": sub_results,
            "summary": self._summarize_subtools(sub_results),
        }

    async def _tech_assessment(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """等保技术要求测评（10项检查）"""
        target = parameters["target"]

        # 构建 SSH 凭据参数
        ssh_params = self._ssh_params(parameters)
        has_ssh_credential = bool(ssh_params.get("password") or ssh_params.get("key_file"))

        sub_coroutines = [
            self._run_subtool("scan_ports", {"target": target}, user_id, project_id, db, "端口扫描"),
            self._run_subtool("scan_vulnerabilities", {"target": target}, user_id, project_id, db, "漏洞扫描"),
            self._run_subtool("nikto_scan", {"target": target}, user_id, project_id, db, "Web 扫描"),
            self._run_subtool("scan_ssl", {"target": target}, user_id, project_id, db, "SSL/TLS 检测"),
            self._run_subtool("redis_check", {"target": target}, user_id, project_id, db, "Redis 检测"),
            self._run_subtool("mysql_check", {"target": target}, user_id, project_id, db, "MySQL 检测"),
            self._run_subtool("mongodb_check", {"target": target}, user_id, project_id, db, "MongoDB 检测"),
            self._run_subtool("snmp_walk", {"target": target}, user_id, project_id, db, "SNMP 检测"),
        ]

        sub_results = await asyncio.gather(*sub_coroutines)
        if has_ssh_credential:
            sub_results.append(await self._run_subtool(
                "baseline_check",
                ssh_params,
                user_id,
                project_id,
                db,
                "安全基线",
            ))
            sub_results.append(await self._run_subtool(
                "scan_weak_passwords",
                {"target": target},
                user_id,
                project_id,
                db,
                "弱口令检测",
            ))
        else:
            sub_results.append(self._skipped_subtool("baseline_check", target, "未提供 SSH 凭据", "安全基线"))
            sub_results.append(self._skipped_subtool("scan_weak_passwords", target, "未提供 SSH 凭据", "弱口令检测"))

        return {
            "target": target,
            "sub_results": sub_results,
            "summary": self._summarize_subtools(sub_results),
        }

    # ========== SSH 白盒配置核查方法 ==========

    async def _baseline_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """安全基线核查：由工具侧自动识别操作系统。"""
        return await self._call_ssh_checker("linux_baseline", parameters)

    async def _password_policy_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """密码策略检查"""
        return await self._call_ssh_checker("password_policy_check", parameters)

    async def _ssh_config_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """SSH 配置检查"""
        return await self._call_ssh_checker("ssh_config_check", parameters)

    async def _audit_config_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """审计配置检查"""
        return await self._call_ssh_checker("audit_config_check", parameters)

    async def _service_port_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """服务端口检查"""
        return await self._call_ssh_checker("service_port_check", parameters)

    async def _file_permission_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """文件权限检查"""
        return await self._call_ssh_checker("file_permission_check", parameters)

    async def _mac_check(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """强制访问控制检查"""
        return await self._call_ssh_checker("mac_check", parameters)

    async def _view_open_ports(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Read persisted port observations; a query must never start a scan."""
        from app.models.context import ResultCache
        from sqlalchemy import select

        if not await self._project_for_user_id(db, project_id, user_id, "scan:read"):
            return {"observations": [], "message": "项目不存在或无权查看检测结果"}

        rows = list((await db.execute(
            select(ResultCache)
            .where(
                ResultCache.user_id == user_id,
                ResultCache.project_id == project_id,
                ResultCache.cache_key.like("scan_ports:%")
            )
            .order_by(ResultCache.created_at.desc())
            .limit(100)
        )).scalars().all())
        observations = []
        seen = set()
        for cache in rows:
            target = cache.cache_key.split("target=", 1)[-1]
            if target in seen:
                continue
            seen.add(target)
            data = cache.result_data or {}
            if isinstance(data.get("data"), dict):
                data = data["data"]
            observations.append({
                "target": target,
                "open_ports": data.get("open_ports") or [],
                "filtered_count": data.get("filtered_count") or len(data.get("filtered_ports") or []),
                "port_range": (data.get("metadata") or {}).get("port_range"),
                "observed_at": cache.created_at.isoformat() if cache.created_at else None,
            })
        return {
            "observations": observations,
            "total_assets": len(observations),
            "message": "没有已保存的端口扫描结果，请先执行端口扫描" if not observations else "已读取最近的端口扫描结果",
        }

    async def _view_vulnerabilities(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Read the latest persisted vulnerability observations per target."""
        from app.models.context import ResultCache
        from sqlalchemy import select

        if not await self._project_for_user_id(db, project_id, user_id, "scan:read"):
            return {"observations": [], "message": "项目不存在或无权查看检测结果"}

        rows = list((await db.execute(
            select(ResultCache)
            .where(
                ResultCache.user_id == user_id,
                ResultCache.project_id == project_id,
                ResultCache.cache_key.like("scan_vulnerabilities:%")
            )
            .order_by(ResultCache.created_at.desc())
            .limit(100)
        )).scalars().all())
        observations = []
        seen = set()
        for cache in rows:
            target = cache.cache_key.split("target=", 1)[-1]
            if target in seen:
                continue
            seen.add(target)
            data = cache.result_data or {}
            if isinstance(data.get("data"), dict):
                data = data["data"]
            observations.append({
                "target": target,
                "findings": data.get("findings") or data.get("vulnerabilities") or [],
                "scan_completed": data.get("scan_completed"),
                "tool_error": data.get("tool_error"),
                "observed_at": cache.created_at.isoformat() if cache.created_at else None,
            })
        return {
            "observations": observations,
            "total_assets": len(observations),
            "message": "没有已保存的漏洞扫描结果，请先执行漏洞扫描" if not observations else "已读取最近的漏洞扫描结果",
        }

    async def _view_findings(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看发现"""
        from app.models.finding import Finding
        from sqlalchemy import func, select

        if not await self._project_for_user_id(db, project_id, user_id, "assessment:read"):
            return {"findings": [], "total": 0, "message": "项目不存在或无权查看问题"}

        query = select(Finding).where(Finding.project_id == project_id)
        count_query = select(func.count(Finding.id)).where(Finding.project_id == project_id)

        if "status" in parameters:
            query = query.where(Finding.status == parameters["status"])
            count_query = count_query.where(Finding.status == parameters["status"])

        result = await db.execute(query.order_by(Finding.updated_at.desc(), Finding.id.desc()).limit(100))
        findings = result.scalars().all()
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings.sort(key=lambda finding: (
            0 if getattr(finding.status, "value", finding.status) == "open" else 1,
            severity_rank.get(getattr(finding.severity, "value", finding.severity), 9),
            -finding.id,
        ))

        return {
            "findings": [
                {
                    "id": f.id,
                    "clause_id": f.clause_id,
                    "clause_name": f.clause_name,
                    "severity": f.severity.value if f.severity else None,
                    "status": f.status.value if f.status else None,
                    "judgment": f.judgment.value if f.judgment else None,
                    "source_type": f.source_type,
                    "description": f.description,
                    "remediation_suggestion": f.remediation_suggestion,
                }
                for f in findings
            ],
            "total": int((await db.execute(count_query)).scalar_one() or 0),
            "returned": len(findings),
            "message": "项目问题清单已更新",
        }

    async def _view_compliance_score(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """评分查询复用完整状态快照，防止把评分和流程完成度混为一谈。"""
        return await self._view_project_status(parameters, user_id, project_id, db)

    async def _view_project_status(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """返回不经模型改写的项目合规状态快照。"""
        from sqlalchemy import func, select
        from app.models.asset import Asset
        from app.models.assessment import Assessment, PhaseInstance
        from app.models.finding import Finding, FindingStatus, Judgment
        from app.models.report import ReportArtifact
        from app.services.flow_engine import get_flow_engine

        pid = parameters.get("project_id") or project_id
        if not pid:
            return {"found": False, "message": "当前未选择项目"}
        project = await self._project_for_user_id(db, int(pid), user_id, "project:read")
        if not project:
            return {"found": False, "message": "项目不存在或无权访问"}

        assessment = (await db.execute(
            select(Assessment)
            .where(Assessment.project_id == project.id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        phases = []
        score_metrics = {"score": None, "coverage": 0.0, "reliable": 0, "unable": 0, "not_applicable": 0}
        if assessment:
            phase_rows = list((await db.execute(
                select(PhaseInstance)
                .where(PhaseInstance.assessment_id == assessment.id)
                .order_by(PhaseInstance.order)
            )).scalars().all())
            phases = [{
                "id": phase.id,
                "phase_id": phase.phase_id,
                "name": phase.name,
                "status": phase.status,
                "progress": round(float(phase.progress or 0), 1),
            } for phase in phase_rows]
            score_metrics = await get_flow_engine(db)._calculate_compliance_metrics(assessment)

        finding_rows = (await db.execute(
            select(Finding.status, Finding.judgment, func.count(Finding.id))
            .where(
                Finding.project_id == project.id,
                Finding.status != FindingStatus.FALSE_POSITIVE,
            )
            .group_by(Finding.status, Finding.judgment)
        )).all()
        findings = {"total": 0, "open": 0, "fixed": 0, "unable": 0}
        for status, judgment, count in finding_rows:
            count = int(count or 0)
            findings["total"] += count
            if status == FindingStatus.OPEN:
                findings["open"] += count
            if status == FindingStatus.FIXED:
                findings["fixed"] += count
            if judgment == Judgment.NOT_TESTED:
                findings["unable"] += count

        open_findings = list((await db.execute(
            select(Finding).where(
                Finding.project_id == project.id,
                Finding.status == FindingStatus.OPEN,
            ).limit(200)
        )).scalars().all())
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        open_findings.sort(key=lambda finding: (
            severity_rank.get(getattr(finding.severity, "value", finding.severity), 9),
            0 if finding.judgment != Judgment.NOT_TESTED else 1,
            -finding.id,
        ))
        severity_counts = {}
        source_counts = {}
        for finding in open_findings:
            severity = getattr(finding.severity, "value", finding.severity) or "unknown"
            source = finding.source_type or "unknown"
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            source_counts[source] = source_counts.get(source, 0) + 1

        gap_groups = {}
        for finding in open_findings:
            title = finding.clause_name or finding.clause_id or "未命名问题"
            key = (title, finding.source_type or "unknown")
            group = gap_groups.setdefault(key, {
                "id": finding.id,
                "title": title,
                "severity": getattr(finding.severity, "value", finding.severity),
                "judgment": getattr(finding.judgment, "value", finding.judgment),
                "source_type": finding.source_type,
                "count": 0,
                "scopes": [],
                "descriptions": [],
                "remediation_suggestion": finding.remediation_suggestion,
            })
            group["count"] += 1
            if (
                finding.scope_key
                and not finding.scope_key.startswith("task:")
                and finding.scope_key not in group["scopes"]
            ):
                group["scopes"].append(finding.scope_key)
            if finding.description and finding.description not in group["descriptions"] and len(group["descriptions"]) < 2:
                group["descriptions"].append(finding.description)

        current_phase = next((phase for phase in phases if phase["status"] == "active"), None)
        if not current_phase:
            current_phase = next((phase for phase in phases if phase["status"] not in {"completed", "skipped"}), None)
        if not current_phase and phases:
            current_phase = phases[-1]
        report = (await db.execute(
            select(ReportArtifact)
            .where(ReportArtifact.project_id == project.id)
            .order_by(ReportArtifact.version.desc())
            .limit(1)
        )).scalar_one_or_none()
        asset_count = int((await db.execute(
            select(func.count(Asset.id)).where(Asset.project_id == project.id)
        )).scalar_one())
        score = score_metrics.get("score")
        grade = "未形成评分" if score is None else (
            "优秀" if score >= 90 else "良好" if score >= 75 else "一般" if score >= 60 else "风险较高"
        )
        return {
            "found": True,
            "project_id": project.id,
            "project_name": project.name,
            "compliance_level": project.compliance_level.value if project.compliance_level else None,
            "asset_count": asset_count,
            "assessment_id": assessment.id if assessment else None,
            "assessment_status": assessment.status if assessment else "not_started",
            "workflow_progress": round(float(assessment.progress or 0), 1) if assessment else 0.0,
            "compliance_score": score,
            "grade": grade,
            "coverage": round(float(score_metrics.get("coverage") or 0), 1),
            "score_metrics": score_metrics,
            "current_phase": current_phase,
            "phases": phases,
            "findings": findings,
            "finding_breakdown": {
                "severity": severity_counts,
                "source": source_counts,
            },
            "major_gaps": list(gap_groups.values())[:8],
            "report": {
                "available": bool(report and report.status == "current"),
                "version": report.version if report else None,
                "status": report.status if report else None,
            },
            "view": parameters.get("view") if parameters.get("view") in {"status", "readiness", "gaps", "executive"} else "status",
            "message": "项目合规状态已更新",
        }

    async def _assessment_flow_action(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Perform only state-safe current-project assessment actions."""
        from sqlalchemy import func, select
        from app.models.assessment import Assessment
        from app.models.finding import Finding, FindingStatus
        from app.services.flow_engine import get_flow_engine

        if not project_id or not await self._project_for_user_id(db, project_id, user_id, "assessment:manage"):
            return {"success": False, "message": "项目不存在或无权管理测评", "action": parameters.get("action")}
        assessment = (await db.execute(
            select(Assessment).where(Assessment.project_id == project_id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1)
        )).scalar_one_or_none()
        if not assessment:
            return {"success": False, "message": "当前项目尚未创建等保测评", "action": parameters.get("action")}

        action = parameters.get("action")
        flow = get_flow_engine(db)
        if action == "start":
            if assessment.status == "not_started":
                assessment = await flow.start_assessment(assessment.id)
                return {"success": True, "action": action, "assessment_id": assessment.id, "status": assessment.status, "message": "测评已启动，当前进入差距分析阶段"}
            if assessment.status == "paused":
                assessment = await flow.resume_assessment(assessment.id)
                return {"success": True, "action": action, "assessment_id": assessment.id, "status": assessment.status, "message": "测评已恢复执行"}
            if assessment.status == "in_progress":
                return {"success": True, "action": action, "assessment_id": assessment.id, "status": assessment.status, "message": "测评已经在进行中，无需重复启动"}
            return {"success": False, "action": action, "assessment_id": assessment.id, "status": assessment.status, "message": "当前测评已完成；如需重新评估，请明确选择重新打开或完全重置"}

        if action == "reset":
            if parameters.get("confirm") is not True:
                return {
                    "success": True,
                    "action": action,
                    "requires_confirmation": True,
                    "assessment_id": assessment.id,
                    "message": "完全重置会清除测评阶段、任务、文档分析、证据、问题、复测记录和报告，但保留项目与资产。请回复“确认彻底重置测评”后执行。",
                }
            assessment, cleanup = await flow.restart_assessment(assessment.id, mode="reset")
            await db.commit()
            return {
                "success": True,
                "action": action,
                "assessment_id": assessment.id,
                "status": assessment.status,
                "cleanup": cleanup,
                "message": "测评数据已彻底清除，项目与资产保持不变",
            }

        if action == "retest":
            rows = (await db.execute(
                select(Finding.source_type, func.count(Finding.id)).where(
                    Finding.project_id == project_id,
                    Finding.status == FindingStatus.OPEN,
                ).group_by(Finding.source_type)
            )).all()
            counts = {str(source or "unknown"): int(count or 0) for source, count in rows}
            technical = counts.get("technical", 0)
            document = counts.get("document", 0)
            if not technical and not document:
                message = "当前没有待复测的技术或文档问题"
            else:
                parts = []
                if technical:
                    parts.append(f"{technical} 个技术问题可在整改与复测中选择后重新检测")
                if document:
                    parts.append(f"{document} 个文档问题需要先提交改进后的材料，再对对应文档类别重新分析")
                message = "；".join(parts) + "。系统不会在缺少目标、凭据或改进材料时伪造复测结论。"
            return {
                "success": True,
                "action": action,
                "assessment_id": assessment.id,
                "started": False,
                "counts": {"technical": technical, "document": document},
                "message": message,
            }

        return {"success": False, "action": action, "message": "不支持的测评流程操作"}

    async def _view_scan_history(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看扫描历史"""
        from app.models.scan_task import ScanTask
        from sqlalchemy import select

        if not await self._project_for_user_id(db, project_id, user_id, "scan:read"):
            return {"scan_history": [], "total": 0, "message": "项目不存在或无权查看检测历史"}

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
        from app.models.organization import OrganizationMember
        from sqlalchemy import select

        compliance_level = parameters.get("compliance_level", "三级")
        level_enum = ComplianceLevel.LEVEL_3 if compliance_level == "三级" else ComplianceLevel.LEVEL_2
        organization_id = parameters.get("organization_id")

        if organization_id:
            try:
                await require_org_permission_for_user_id(db, int(organization_id), user_id, "project:create")
            except Exception:
                return {"message": "组织不存在或无权创建项目"}
        else:
            result = await db.execute(
                select(OrganizationMember).where(OrganizationMember.user_id == user_id)
            )
            memberships = result.scalars().all()
            for member in memberships:
                try:
                    await require_org_permission_for_user_id(db, member.organization_id, user_id, "project:create")
                    organization_id = member.organization_id
                    break
                except Exception:
                    continue
            if memberships and not organization_id:
                return {"message": "无权在当前组织创建项目"}

        project = Project(
            user_id=user_id,
            owner_id=user_id,
            organization_id=organization_id,
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
        from app.models.organization import OrganizationMember
        from sqlalchemy import select, or_

        result = await db.execute(
            select(Project)
            .outerjoin(OrganizationMember, Project.organization_id == OrganizationMember.organization_id)
            .where(or_(Project.user_id == user_id, Project.owner_id == user_id, OrganizationMember.user_id == user_id))
            .distinct()
            .order_by(Project.created_at.desc())
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
        project_id = parameters.get("project_id")

        project = await self._project_for_user_id(db, project_id, user_id, "project:update")

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
        from sqlalchemy import delete

        project_id = parameters.get("project_id")

        project = await self._project_for_user_id(db, project_id, user_id, "project:delete")

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

        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目"}

        if not await self._project_for_user_id(db, pid, user_id, "asset:create"):
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
        from sqlalchemy import select

        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目", "assets": []}

        if not await self._project_for_user_id(db, pid, user_id, "asset:read"):
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

        pid = pid or asset.project_id
        if not await self._project_for_user_id(db, pid, user_id, "asset:update"):
            return {"message": "项目不存在或无权访问"}

        token = f"verisure-{uuid_mod.uuid4().hex[:16]}"
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

    async def _generate_html_report(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """生成 HTML 报告"""
        from sqlalchemy import select
        from app.models.assessment import Assessment, PhaseInstance, TaskInstance
        from app.services.flow_engine import get_flow_engine
        from app.services.report_service import create_report_artifact, ensure_report_generation_ready, get_latest_report_artifact, report_artifact_payload

        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目 ID"}

        task = None
        try:
            if not await self._project_for_user_id(db, pid, user_id, "report:export"):
                return {"message": "项目不存在或无权生成报告"}
            assessment = (await db.execute(select(Assessment).where(
                Assessment.project_id == pid
            ).order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(1))).scalar_one_or_none()
            if not assessment:
                return {"message": "当前项目尚未创建等保测评"}
            phase = (await db.execute(select(PhaseInstance).where(
                PhaseInstance.assessment_id == assessment.id,
                PhaseInstance.phase_id == "report",
            ))).scalar_one_or_none()
            task = (await db.execute(select(TaskInstance).where(
                TaskInstance.phase_id == phase.id,
                TaskInstance.task_type == "html_report",
            ))).scalar_one_or_none() if phase else None
            latest = await get_latest_report_artifact(db, pid, assessment_id=assessment.id)
            if task and task.status == "completed" and latest and latest.status == "current":
                return {"message": f"正式报告 V{latest.version} 已存在", "artifact": report_artifact_payload(latest)}
            if not phase or phase.status != "active" or not task or task.status != "todo":
                return {"message": "请先完成整改与复测，并进入生成报告阶段"}
            flow = get_flow_engine(db)
            await ensure_report_generation_ready(db, pid, assessment.id)
            await flow.start_task(task.id)
            artifact = await create_report_artifact(
                db,
                project_id=pid,
                assessment_id=assessment.id,
                task_id=task.id,
                generated_by=user_id,
            )
            await flow.complete_task(task.id, {
                "status": "completed",
                "format": "html",
                "artifact": report_artifact_payload(artifact),
                "summary": artifact.snapshot["summary"],
            })
            return {
                "message": f"正式 HTML 报告 V{artifact.version} 已生成",
                "project_id": pid,
                "format": "html",
                "size_bytes": artifact.html_size,
                "artifact": report_artifact_payload(artifact),
            }
        except Exception as e:
            await db.rollback()
            failed_task = await db.get(TaskInstance, task.id) if task else None
            if failed_task and failed_task.status == "in_progress":
                failed_task.status = "todo"
                failed_task.started_at = None
                await db.commit()
            return {"message": f"报告生成失败: {str(e)}"}

    async def _generate_json_report(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """读取正式报告使用的 JSON 快照"""
        from app.services.report_service import get_latest_report_artifact

        pid = parameters.get("project_id", project_id)
        if not pid:
            return {"message": "请指定项目 ID"}

        try:
            if not await self._project_for_user_id(db, pid, user_id, "report:export"):
                return {"message": "项目不存在或无权读取报告"}
            artifact = await get_latest_report_artifact(db, pid)
            if not artifact:
                return {"message": "该项目尚未生成正式报告"}
            return {
                "message": f"正式报告 V{artifact.version} 的 JSON 快照已读取",
                "project_id": pid,
                "format": "json",
                "report": artifact.snapshot,
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
        if not await self._project_for_user_id(db, pid, user_id, "scan:execute"):
            return {"message": "项目不存在或无权创建监控任务"}

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
            next_run_at=datetime.utcnow(),
            scan_parameters=parameters.get("scan_parameters"),
            notify_on_change=parameters.get("notify_on_change", True),
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
        from app.models.project import Project
        from app.models.organization import OrganizationMember
        from sqlalchemy import select

        pid = parameters.get("project_id", project_id)
        if pid:
            if not await self._project_for_user_id(db, pid, user_id, "scan:read"):
                return {"message": "项目不存在或无权访问", "scans": []}
            query = select(ScheduledScan).where(ScheduledScan.project_id == pid)
        else:
            query = (
                select(ScheduledScan)
                .join(Project, Project.id == ScheduledScan.project_id)
                .outerjoin(OrganizationMember, Project.organization_id == OrganizationMember.organization_id)
                .where((Project.user_id == user_id) | (Project.owner_id == user_id) | (OrganizationMember.user_id == user_id))
            )

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
        from sqlalchemy import select

        scan_id = parameters.get("scan_id")
        if not scan_id:
            return {"message": "请指定定时扫描 ID"}

        result = await db.execute(select(ScheduledScan).where(ScheduledScan.id == scan_id))
        scan = result.scalar_one_or_none()
        if not scan:
            return {"message": "定时扫描任务不存在"}
        if not await self._project_for_user_id(db, scan.project_id, user_id, "scan:execute"):
            return {"message": "无权触发该定时扫描"}

        from app.api.monitoring import run_scheduled_scan_now
        from app.models.user import User
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return {"message": "用户不存在"}
        result = await run_scheduled_scan_now(scan.project_id, scan.id, db, user)
        return {
            "message": f"定时扫描 '{scan.name}' 已触发",
            "scan_id": scan.id,
            "result": result,
        }

    async def _show_help(self) -> Dict:
        """显示帮助"""
        return {
            "message": """我是 VeriSure 智能合规验证助手，可以帮你：

🔍 **扫描检测**
- 端口扫描：扫描目标资产的开放端口
- SSL 检测：检查 SSL/TLS 配置
- 漏洞扫描：检测安全漏洞
- 弱口令检测：发现弱密码
- 全量扫描：执行完整的等保合规检测

📊 **数据查询**
- 查看开放端口
- 查看漏洞列表
- 查看合规评分
- 查看扫描历史

📁 **项目管理**
- 创建项目
- 列出项目
- 更新项目
- 删除项目

📝 **整改与复测**
- 在项目测评页查看问题
- 提交改进文档并复测
- 重新执行技术检测

📄 **报告生成**
- 生成 HTML 报告
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
        parameters = redact_sensitive(parameters)

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
