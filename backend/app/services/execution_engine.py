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
from app.core.redaction import redact_sensitive

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
            result = await client.call(tool_name, params)
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
                
                results.append({
                    "capability": capability_name,
                    "status": "success",
                    "target": parameters.get("target", "unknown"),
                    "result": result,
                })
                success_count += 1
                
                # 记录操作历史
                if context_manager:
                    await context_manager.add_action(
                        action_type=capability_name,
                        parameters=safe_parameters,
                        result=result,
                        status="success"
                    )
                    
                    # 缓存结果
                    cache_key = f"{capability_name}:{self._generate_cache_key(safe_parameters)}"
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
                    "target": parameters.get("target", "unknown"),
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
                        parameters=redact_sensitive(parameters),
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

            return {
                "capability": capability_name,
                "target": target,
                "status": result.get("status"),
                "result": result.get("result"),
                "error": result.get("error"),
                "error_detail": result.get("error_detail"),
                "attempts": result.get("attempts", 1),
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
        capability_name = self._normalize_capability_name(capability_name)

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
        
        result = await client.call("ffuf_scan", params)
        return self._gateway_payload(result)

    async def _web_discovery_scan(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """Web 路径/目录发现：组合 gobuster 与 ffuf。"""
        url = self._url_param(parameters)
        sub_results = await asyncio.gather(
            self._run_subtool("gobuster_scan", {"url": url}, user_id, project_id, db, "目录爆破"),
            self._run_subtool("ffuf_scan", {"url": url}, user_id, project_id, db, "Web 模糊测试"),
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
        result = await client.call("testssl_scan", {
            "target": parameters["target"],
            "port": parameters.get("port", 443),
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
        
        result = await client.call("nuclei_scan", params)
        return self._gateway_payload(result)
    
    async def _scan_weak_passwords(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """弱口令扫描"""
        from app.mcp.gateway_client import MCPGatewayClient
        
        client = MCPGatewayClient()
        result = await client.call("hydra_bruteforce", {
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
    
    async def _view_scan_results(self, parameters: Dict, user_id: int, project_id: int, db: AsyncSession) -> Dict:
        """查看扫描结果"""
        # 从缓存或数据库获取最近的扫描结果
        from app.models.context import ResultCache
        from sqlalchemy import select
        
        result = await db.execute(
            select(ResultCache)
            .where(ResultCache.user_id == user_id)
            .where(ResultCache.project_id == project_id)
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
                ResultCache.project_id == project_id,
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
                ResultCache.project_id == project_id,
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
            "message": """我是 VeriSure 智能合规验证助手，可以帮你：

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
