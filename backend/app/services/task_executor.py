"""
流程任务执行器 - 桥接 FlowEngine 和 ExecutionEngine

将流程任务类型映射到具体的安全工具执行
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import Assessment
from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy
from app.services.display_names import CAPABILITY_DISPLAY_NAMES
from app.services.verification_service import add_finding_event, make_finding_fingerprint, scrub_sensitive_parameters

logger = logging.getLogger(__name__)


# 任务类型 → 执行引擎能力映射
# 每个任务类型可映射多个工具，按顺序执行
TASK_CAPABILITY_MAP = {
    "asset_discovery": {
        "capabilities": ["masscan_scan", "fping_scan", "scan_ports"],
        "default_params": {"port_range": "1-65535"},
        "description": "高速端口扫描发现信息资产",
    },
    "high_risk_port_scan": {
        "capabilities": ["scan_ports"],
        "default_params": {"port_range": "high-risk"},
        "description": "高危端口扫描",
    },
    "basic_vulnerability_scan": {
        "capabilities": ["scan_vulnerabilities"],
        "default_params": {},
        "description": "基础漏洞扫描",
    },
    "basic_baseline_check": {
        "capabilities": ["baseline_check"],
        "default_params": {},
        "description": "配置/基线核查",
    },
    "basic_weak_password_scan": {
        "capabilities": ["scan_weak_passwords"],
        "default_params": {"service": "ssh", "port": 22},
        "description": "弱口令检测",
    },
    "basic_ssl_tls_scan": {
        "capabilities": ["scan_ssl"],
        "default_params": {"port": 443},
        "description": "SSL/TLS 检测",
    },
    "crypto_network_communication_assessment": {
        "capabilities": ["crypto_onsite_assessment"],
        "default_params": {"port": 443},
        "description": "密码协议、证书和算法标识辅助检测（不替代正式商用密码应用安全性评估）",
    },
    "config_check": {
        "capabilities": ["baseline_check"],
        "default_params": {},
        "description": "安全基线核查（自动识别操作系统）",
    },
    "vuln_scan": {
        "capabilities": ["scan_vulnerabilities", "nikto_scan"],
        "default_params": {},
        "description": "漏洞扫描（CVE + Web漏洞）",
    },
    "web_scan": {
        "capabilities": ["nikto_scan", "sqlmap_scan", "web_discovery_scan"],
        "default_params": {},
        "description": "Web 安全检测（漏洞/SQL 注入/目录发现）",
    },
    # pentest 任务已废弃：等保要求中渗透测试是文档审查（8.1.4.27），不是工具扫描
    # 保留仅用于兼容已有数据，不再作为可执行任务
    "pentest": None,
    "ssl_check": {
        "capabilities": ["scan_ssl"],
        "default_params": {"port": 443},
        "description": "SSL/TLS 安全检测",
    },
    "password_scan": {
        "capabilities": ["scan_weak_passwords"],
        "default_params": {"service": "ssh", "port": 22},
        "description": "弱口令检测（SSH/FTP/MySQL等）",
    },
    "db_check": {
        "capabilities": ["database_security_scan"],
        "default_params": {},
        "description": "数据库安全检测（未授权访问/空口令）",
    },
    "network_check": {
        "capabilities": ["network_device_scan"],
        "default_params": {},
        "description": "网络设备检测（SNMP团体字/配置读取）",
    },
    "windows_check": {
        "capabilities": ["windows_security_scan"],
        "default_params": {},
        "description": "Windows/AD/SMB组合检测（用户/SID/共享）",
    },
    "full_compliance_scan": {
        "capabilities": ["scan_ports", "scan_ssl", "scan_vulnerabilities", "scan_weak_passwords"],
        "default_params": {},
        "description": "全量合规扫描（端口+SSL+漏洞+弱口令）",
    },
    "full_asset_assessment": {
        "capabilities": ["scan_ports", "scan_ssl", "scan_vulnerabilities", "scan_weak_passwords"],
        "default_params": {"port_range": "high-risk"},
        "description": "全资产组合扫描（端口+SSL+漏洞+弱口令）",
    },
    "web_vulnerability_assessment": {
        "capabilities": ["nikto_scan"],
        "default_params": {},
        "description": "Web 漏洞扫描",
    },
    "directory_discovery_assessment": {
        "capabilities": ["web_discovery_scan"],
        "default_params": {},
        "description": "目录爆破/路径发现",
    },
    "web_fuzz_assessment": {
        "capabilities": ["ffuf_scan"],
        "default_params": {},
        "description": "Web 模糊测试",
    },
    "sql_injection_assessment": {
        "capabilities": ["sqlmap_scan"],
        "default_params": {},
        "description": "SQL 注入检测",
    },
    "database_security_assessment": {
        "capabilities": ["database_security_scan"],
        "default_params": {},
        "description": "数据库安全检测",
    },
    "network_device_assessment": {
        "capabilities": ["network_device_scan"],
        "default_params": {},
        "description": "网络设备检测",
    },
    "windows_ad_smb_assessment": {
        "capabilities": ["windows_security_scan"],
        "default_params": {},
        "description": "Windows/AD/SMB 检测",
    },
    "ssh_baseline_assessment": {
        "capabilities": ["baseline_check"],
        "default_params": {},
        "description": "SSH/主机基线核查",
    },
    "doc_review": None,
    "html_report": None,
    "interview": None,
}

CAPABILITY_NAMES = CAPABILITY_DISPLAY_NAMES


class TaskExecutor:
    """流程任务执行器"""
    
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _tool_issue(capability: str, result: dict) -> Optional[str]:
        """判断工具是否实际完成；未完成必须反馈给测评任务。"""
        if not isinstance(result, dict):
            return None
        if result.get("tool_error"):
            return str(result.get("tool_error"))
        if result.get("scan_completed") is False:
            return "扫描引擎未完整执行"
        if result.get("connection_error"):
            return result.get("skip_reason") or "目标连接失败，无法完成检测"
        if result.get("skipped") and result.get("supported") is False:
            return result.get("skip_reason") or "目标不支持或条件不足，检测已跳过"
        if result.get("tool_status") == "failed":
            return result.get("error") or "工具执行失败"
        sub_results = [sub for sub in result.get("sub_results") or [] if isinstance(sub, dict)]
        if sub_results and all(sub.get("status") == "skipped" for sub in sub_results):
            return None
        sub_issues = []
        for sub in sub_results:
            if not isinstance(sub, dict):
                continue
            if sub.get("status") in {"failed", "warning", "skipped"}:
                data = sub.get("data") if isinstance(sub.get("data"), dict) else {}
                reason = sub.get("error") or sub.get("message") or data.get("tool_error") or data.get("skip_reason") or "未完整执行"
                label = sub.get("label") or sub.get("name") or sub.get("capability") or "子检测"
                sub_issues.append(f"{label}：{reason}")
        if sub_issues:
            return "；".join(sub_issues[:5])
        return None

    @staticmethod
    def _risk_items(capability: str, execution: dict, target: str) -> list[dict]:
        data = execution.get("result") or {}
        items = []
        if execution.get("status") in {"warning", "failed"}:
            reason = execution.get("warning") or execution.get("error") or "检测未可靠完成"
            items.append({
                "description": f"{target}: {reason}",
                "severity": "medium",
                "judgment": "not_tested",
                "risk_key": "execution:unable",
                "remediation": "确认目标服务是否适用并恢复网络、凭据或工具条件后重新检测；未完成前不得视为通过。",
            })
        if capability == "scan_ports":
            risky = {21, 23, 135, 139, 445, 1433, 1521, 3306, 3389, 5432, 5900, 6379, 9200, 11211, 27017}
            items.extend(
                {
                    "description": f"{target} 暴露高风险端口 {port.get('port')}/{port.get('protocol', 'tcp')}",
                    "severity": "high",
                    "risk_key": f"port:{port.get('port')}/{port.get('protocol', 'tcp')}",
                }
                for port in data.get("open_ports", [])
                if port.get("port") in risky
            )
        if capability == "baseline_check":
            high_risk_checks = {"empty_passwords", "permit_root_login", "password_authentication", "danger_ports"}
            for check_key, check in (data.get("results") or {}).items():
                if not isinstance(check, dict) or check.get("compliant") is not False:
                    continue
                description = check.get("description") or check_key
                requirement = check.get("requirement") or "满足安全基线要求"
                output = check.get("output") or "未返回配置值"
                items.append({
                    "description": f"{target}: {description}不符合；要求：{requirement}；当前值：{output}",
                    "severity": "high" if check_key in high_risk_checks else "medium",
                    "risk_key": f"baseline:{check_key}",
                    "raw": check,
                })
        for key in ("findings", "vulnerabilities", "issues", "found", "injection_points", "failed_checks"):
            for item in data.get(key) or []:
                item = item if isinstance(item, dict) else {"description": str(item)}
                description = item.get("description") or item.get("name") or item.get("title")
                if not description and item.get("finding"):
                    description = (
                        f"testssl 总体评级：{item['finding']}（工具原始等级）"
                        if item.get("id") == "overall_grade"
                        else f"{item.get('id')}: {item['finding']}" if item.get("id") else item["finding"]
                    )
                description = description or item.get("id") or str(item)
                risk_key = item.get("id") or item.get("template_id") or item.get("matcher_name") or item.get("name") or item.get("title") or description
                items.append({
                    "description": f"{target}: {description}",
                    "severity": item.get("severity") or "medium",
                    "risk_key": str(risk_key),
                    "raw": item,
                })
        if data.get("unauthorized") or data.get("empty_password"):
            items.append({
                "description": f"{target}: 数据库存在未授权或空密码访问",
                "severity": "critical",
                "risk_key": "database:unauthorized_or_empty_password",
            })
        for sub in data.get("sub_results") or []:
            if not isinstance(sub, dict):
                continue
            items.extend(TaskExecutor._risk_items(
                sub.get("capability") or capability,
                {
                    "status": sub.get("status"),
                    "error": sub.get("error"),
                    "result": sub.get("data") or {},
                },
                sub.get("target") or target,
            ))
        return items

    async def _sync_findings(self, scan_task: ScanTask, results: list[dict], target: str) -> int:
        current_risk_count = 0
        severity_map = {
            "critical": Severity.CRITICAL,
            "high": Severity.HIGH,
            "medium": Severity.MEDIUM,
            "low": Severity.LOW,
            "info": Severity.INFO,
        }
        for result in results:
            capability = result["capability"]
            clause_id = f"TECH-{capability.upper()[:40]}"
            current = self._risk_items(capability, result, target)
            unable_fingerprint = make_finding_fingerprint("technical", target, capability, "execution:unable")
            if not any(item.get("judgment") == "not_tested" for item in current):
                recovered = (await self.db.execute(select(Finding).where(
                    Finding.project_id == scan_task.project_id,
                    Finding.assessment_id == scan_task.assessment_id,
                    Finding.fingerprint == unable_fingerprint,
                    Finding.status == FindingStatus.OPEN,
                    Finding.judgment == Judgment.NOT_TESTED,
                ))).scalar_one_or_none()
                if recovered:
                    recovered.status = FindingStatus.FIXED
                    recovered.resolved_at = datetime.utcnow()
                    recovered.scan_task_id = scan_task.id
                    await add_finding_event(self.db, recovered, "execution_recovered", data={"scan_task_id": scan_task.id})
            for item in current:
                fingerprint = make_finding_fingerprint("technical", target, capability, item.get("risk_key") or item["description"])
                judgment = Judgment.NOT_TESTED if item.get("judgment") == "not_tested" else Judgment.FAIL
                if judgment != Judgment.NOT_TESTED:
                    current_risk_count += 1
                finding = (await self.db.execute(
                    select(Finding).where(
                        Finding.project_id == scan_task.project_id,
                        Finding.assessment_id == scan_task.assessment_id,
                        Finding.fingerprint == fingerprint,
                    )
                )).scalar_one_or_none()
                if finding:
                    finding.scan_task_id = scan_task.id
                    finding.description = item["description"]
                    finding.severity = severity_map.get(str(item["severity"]).lower(), Severity.MEDIUM)
                    finding.judgment = judgment
                    if finding.status == FindingStatus.FIXED:
                        finding.status = FindingStatus.OPEN
                        finding.resolved_at = None
                    await add_finding_event(self.db, finding, "finding_detected", data={"scan_task_id": scan_task.id})
                    continue
                finding = Finding(
                    project_id=scan_task.project_id,
                    assessment_id=scan_task.assessment_id,
                    scan_task_id=scan_task.id,
                    fingerprint=fingerprint,
                    source_type="technical",
                    source_key=capability,
                    scope_key=target,
                    clause_id=clause_id,
                    clause_name=CAPABILITY_NAMES.get(capability, capability),
                    severity=severity_map.get(str(item["severity"]).lower(), Severity.MEDIUM),
                    judgment=judgment,
                    judgment_engine=JudgmentEngine.RULE,
                    description=item["description"],
                    remediation_suggestion=item.get("remediation") or "确认风险是否为业务必要；按最小暴露原则修复配置后重新检测。",
                    status=FindingStatus.OPEN,
                )
                self.db.add(finding)
                await self.db.flush()
                await add_finding_event(self.db, finding, "finding_created", data={"scan_task_id": scan_task.id})
        return current_risk_count
    
    async def execute_task(
        self,
        task_type: str,
        target: str,
        project_id: int,
        user_id: int,
        params: Dict[str, Any] = None,
        assessment_id: int | None = None,
    ) -> Dict[str, Any]:
        """
        执行流程任务
        
        Args:
            task_type: 任务类型（asset_discovery, vuln_scan, etc.）
            target: 目标地址
            project_id: 项目 ID
            user_id: 用户 ID
            params: 额外参数
        
        Returns:
            执行结果字典
        """
        mapping = TASK_CAPABILITY_MAP.get(task_type)
        
        if mapping is None:
            return {
                "status": "skipped",
                "message": f"任务类型 {task_type} 为人工任务，无需自动执行",
                "task_type": task_type,
            }

        from app.services.asset_scope import require_scannable_target
        asset = await require_scannable_target(self.db, project_id, target)
        
        capabilities = mapping.get("capabilities", [])
        default_params = mapping.get("default_params", {}).copy()
        
        # 合并参数
        scan_params = {
            "target": target,
            **default_params,
            **(params or {}),
        }
        
        logger.info(f"Executing task {task_type} -> {capabilities} for target {target}")

        persisted_params = scrub_sensitive_parameters(scan_params)
        assessment = await self.db.get(Assessment, assessment_id) if assessment_id else None
        scan_task = ScanTask(
            project_id=project_id,
            assessment_id=assessment_id,
            asset_id=asset.id,
            task_type=ScanTaskType.TARGETED,
            status=ScanTaskStatus.RUNNING,
            control_state="running",
            triggered_by=TriggeredBy.MANUAL,
            parameters={
                "source": "assessment_task",
                "assessment_code": assessment.assessment_type_code if assessment else None,
                "task_type": task_type,
                "target": target,
                **persisted_params,
            },
            started_at=datetime.utcnow(),
        )
        self.db.add(scan_task)
        await self.db.flush()
        from app.services.report_service import invalidate_report_artifacts
        await invalidate_report_artifacts(
            self.db,
            project_id,
            "已重新执行测评技术检测",
            assessment_id=assessment_id,
        )
        
        from app.services.execution_engine import ExecutionEngine
        engine = ExecutionEngine()
        
        results = []
        failed = []
        warnings = []
        
        for capability in capabilities:
            try:
                result = await engine._execute_capability(
                    capability_name=capability,
                    parameters=scan_params,
                    user_id=user_id,
                    project_id=project_id,
                    db=self.db,
                )
                issue = self._tool_issue(capability, result)
                results.append({
                    "capability": capability,
                    "status": "warning" if issue else "completed",
                    "result": result,
                    "warning": issue,
                })
                if issue:
                    warnings.append({
                        "capability": capability,
                        "status": "warning",
                        "error": issue,
                    })
            except asyncio.CancelledError:
                scan_task.status = ScanTaskStatus.CANCELLED
                scan_task.control_state = "cancelled"
                scan_task.cancel_requested_at = datetime.utcnow()
                scan_task.completed_at = datetime.utcnow()
                scan_task.error_message = "用户已停止检测"
                scan_task.result_summary = {
                    "target": target,
                    "task_type": task_type,
                    "results": results,
                    "status": "cancelled",
                }
                await self.db.commit()
                raise
            except Exception as e:
                logger.error(f"Capability {capability} failed: {e}")
                failed.append({
                    "capability": capability,
                    "status": "failed",
                    "error": str(e),
                })
        
        blocking = any(
            item.get("capability") == "baseline_check"
            and isinstance(item.get("result"), dict)
            and item["result"].get("connection_error")
            for item in results
        )
        not_applicable = bool(results) and all(
            isinstance(item.get("result"), dict)
            and (
                item["result"].get("skipped") is True
                or (
                    (item["result"].get("summary") or {}).get("total", 0) > 0
                    and (item["result"].get("summary") or {}).get("skipped")
                    == (item["result"].get("summary") or {}).get("total")
                )
            )
            for item in results
        )
        overall_status = "failed" if blocking else (
            "completed" if not failed and not warnings else ("partial" if results else "failed")
        )

        scan_task.status = ScanTaskStatus.FAILED if blocking or not results else ScanTaskStatus.COMPLETED
        scan_task.control_state = "failed" if scan_task.status == ScanTaskStatus.FAILED else "completed"
        scan_task.completed_at = datetime.utcnow()
        scan_task.error_message = "; ".join(item["error"] for item in (failed or warnings)) or None
        scan_task.findings_count = await self._sync_findings(scan_task, [*results, *failed], target)
        port_results = {
            target: {
                "capability": item["capability"],
                "status": "success",
                "parameters": persisted_params,
                "data": item["result"],
            }
            for item in results
            if item["capability"] in {"scan_ports", "masscan_scan"}
        }
        from app.services.change_detection import record_port_snapshots
        port_changes = await record_port_snapshots(self.db, project_id, scan_task.id, port_results)
        scan_task.result_summary = {
            "target": target,
            "task_type": task_type,
            "results": results,
            "failed": failed,
            "warnings": warnings,
            "outcome": "not_applicable" if not_applicable else overall_status,
            "change_detection": {"port_changes": port_changes},
        }
        await self.db.commit()
        
        return {
            "status": overall_status,
            "blocking": blocking,
            "scan_task_id": scan_task.id,
            "task_type": task_type,
            "target": target,
            "results": results,
            "failed": failed,
            "warnings": warnings,
            "outcome": "not_applicable" if not_applicable else overall_status,
        }
    
    def get_task_info(self, task_type: str) -> Optional[Dict[str, Any]]:
        """获取任务类型信息"""
        return TASK_CAPABILITY_MAP.get(task_type)
    
    def is_automated_task(self, task_type: str) -> bool:
        """检查任务是否可自动执行"""
        mapping = TASK_CAPABILITY_MAP.get(task_type)
        return mapping is not None
    
    def get_capabilities_for_task(self, task_type: str) -> list:
        """获取任务类型对应的所有工具"""
        mapping = TASK_CAPABILITY_MAP.get(task_type)
        if mapping is None:
            return []
        return mapping.get("capabilities", [])


def get_task_executor(db: AsyncSession) -> TaskExecutor:
    """获取任务执行器实例"""
    return TaskExecutor(db)
