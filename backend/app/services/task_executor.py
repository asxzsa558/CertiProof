"""
流程任务执行器 - 桥接 FlowEngine 和 ExecutionEngine

将流程任务类型映射到具体的安全工具执行
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# 任务类型 → 执行引擎能力映射
# 每个任务类型可映射多个工具，按顺序执行
TASK_CAPABILITY_MAP = {
    "asset_discovery": {
        "capabilities": ["masscan_scan", "fping_scan", "scan_ports"],
        "default_params": {"port_range": "1-65535"},
        "description": "高速端口扫描发现信息资产",
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
    "doc_review": None,
    "interview": None,
}


class TaskExecutor:
    """流程任务执行器"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
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
        
        capabilities = mapping.get("capabilities", [])
        default_params = mapping.get("default_params", {}).copy()
        
        # 合并参数
        scan_params = {
            "target": target,
            **default_params,
            **(params or {}),
        }
        
        logger.info(f"Executing task {task_type} -> {capabilities} for target {target}")
        
        from app.services.execution_engine import ExecutionEngine
        engine = ExecutionEngine()
        
        results = []
        failed = []
        
        for capability in capabilities:
            try:
                result = await engine._execute_capability(
                    capability_name=capability,
                    parameters=scan_params,
                    user_id=user_id,
                    project_id=project_id,
                    db=self.db,
                )
                results.append({
                    "capability": capability,
                    "status": "completed",
                    "result": result,
                })
            except Exception as e:
                logger.error(f"Capability {capability} failed: {e}")
                failed.append({
                    "capability": capability,
                    "status": "failed",
                    "error": str(e),
                })
        
        overall_status = "completed" if not failed else ("partial" if results else "failed")
        
        return {
            "status": overall_status,
            "task_type": task_type,
            "target": target,
            "results": results,
            "failed": failed,
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
