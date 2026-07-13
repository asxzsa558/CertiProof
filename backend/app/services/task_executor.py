"""
流程任务执行器 - 桥接 FlowEngine 和 ExecutionEngine

将流程任务类型映射到具体的安全工具执行
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingStatus, Judgment, JudgmentEngine, Severity
from app.models.remediation import RemediationTicket, RemediationStatus
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy

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
    "remediation": None,
    "retest": None,
    "html_report": None,
    "interview": None,
}


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
        for sub in result.get("sub_results") or []:
            if not isinstance(sub, dict):
                continue
            if sub.get("status") in {"failed", "warning", "skipped"}:
                return sub.get("error") or sub.get("message") or f"{sub.get('name') or sub.get('capability') or '子检测'}未完成"
        return None

    @staticmethod
    def _risk_items(capability: str, execution: dict, target: str) -> list[dict]:
        data = execution.get("result") or {}
        items = []
        issue = execution.get("warning") or execution.get("error") or TaskExecutor._tool_issue(capability, data)
        if issue:
            items.append({
                "description": f"{target}: {capability} 检测未完成（不代表通过）：{issue}",
                "severity": "medium",
                "remediation": "先恢复目标连通性、凭证或工具运行条件，再重新执行该检测。",
            })
        if capability == "scan_ports":
            risky = {21, 23, 135, 139, 445, 1433, 1521, 3306, 3389, 5432, 5900, 6379, 9200, 11211, 27017}
            items.extend(
                {"description": f"{target} 暴露高风险端口 {port.get('port')}/{port.get('protocol', 'tcp')}", "severity": "high"}
                for port in data.get("open_ports", [])
                if port.get("port") in risky
            )
        for key in ("findings", "vulnerabilities", "issues", "found", "injection_points", "failed_checks"):
            for item in data.get(key) or []:
                item = item if isinstance(item, dict) else {"description": str(item)}
                description = item.get("description") or item.get("name") or item.get("title") or str(item)
                items.append({"description": f"{target}: {description}", "severity": item.get("severity") or "medium"})
        if data.get("unauthorized") or data.get("empty_password"):
            items.append({"description": f"{target}: 数据库存在未授权或空密码访问", "severity": "critical"})
        return items

    async def _sync_findings(self, scan_task: ScanTask, results: list[dict], target: str) -> int:
        created = 0
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
            existing_result = await self.db.execute(
                select(Finding).where(
                    Finding.project_id == scan_task.project_id,
                    Finding.clause_id == clause_id,
                    Finding.status != FindingStatus.RESOLVED,
                    Finding.description.like(f"{target}%"),
                )
            )
            existing = {finding.description: finding for finding in existing_result.scalars().all()}
            descriptions = {item["description"] for item in current}
            # Never resolve an earlier finding merely because this run was partial or failed.
            # A missing result is evidence only after the same capability completed cleanly.
            if result.get("status") == "completed":
                for description, finding in existing.items():
                    if description not in descriptions:
                        finding.status = FindingStatus.RESOLVED
                        finding.resolved_at = datetime.utcnow()
                        ticket_result = await self.db.execute(
                            select(RemediationTicket).where(RemediationTicket.finding_id == finding.id)
                        )
                        ticket = ticket_result.scalar_one_or_none()
                        if ticket and ticket.status not in (RemediationStatus.CLOSED, RemediationStatus.SKIPPED):
                            ticket.status = RemediationStatus.RESOLVED
                            ticket.resolved_at = ticket.resolved_at or datetime.utcnow()
            for item in current:
                if item["description"] in existing:
                    continue
                finding = Finding(
                    project_id=scan_task.project_id,
                    scan_task_id=scan_task.id,
                    clause_id=clause_id,
                    clause_name="自动化技术检测",
                    severity=severity_map.get(str(item["severity"]).lower(), Severity.MEDIUM),
                    judgment=Judgment.FAIL,
                    judgment_engine=JudgmentEngine.RULE,
                    description=item["description"],
                    remediation_suggestion=item.get("remediation") or "确认风险是否为业务必要；按最小暴露原则修复配置后重新检测。",
                    status=FindingStatus.OPEN,
                )
                self.db.add(finding)
                await self.db.flush()
                self.db.add(RemediationTicket(
                    finding_id=finding.id,
                    project_id=scan_task.project_id,
                    title=item["description"][:500],
                    description=item["description"],
                    remediation_plan=finding.remediation_suggestion,
                    priority="high" if finding.severity in (Severity.CRITICAL, Severity.HIGH) else "medium",
                    status=RemediationStatus.OPEN,
                ))
                created += 1
        return created
    
    async def execute_task(
        self,
        task_type: str,
        target: str,
        project_id: int,
        user_id: int,
        params: Dict[str, Any] = None,
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

        scan_task = ScanTask(
            project_id=project_id,
            asset_id=asset.id,
            task_type=ScanTaskType.TARGETED,
            status=ScanTaskStatus.RUNNING,
            triggered_by=TriggeredBy.MANUAL,
            parameters={"source": "assessment_task", "task_type": task_type, "target": target, **scan_params},
            started_at=datetime.utcnow(),
        )
        self.db.add(scan_task)
        await self.db.flush()
        
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
            except Exception as e:
                logger.error(f"Capability {capability} failed: {e}")
                failed.append({
                    "capability": capability,
                    "status": "failed",
                    "error": str(e),
                })
        
        overall_status = "completed" if not failed and not warnings else ("partial" if results else "failed")

        scan_task.status = ScanTaskStatus.COMPLETED if results else ScanTaskStatus.FAILED
        scan_task.completed_at = datetime.utcnow()
        scan_task.error_message = "; ".join(item["error"] for item in failed) or None
        scan_task.findings_count = await self._sync_findings(scan_task, [*results, *failed], target)
        port_results = {
            target: {
                "capability": item["capability"],
                "status": "success",
                "parameters": scan_params,
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
            "change_detection": {"port_changes": port_changes},
        }
        await self.db.commit()
        
        return {
            "status": overall_status,
            "task_type": task_type,
            "target": target,
            "results": results,
            "failed": failed,
            "warnings": warnings,
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
