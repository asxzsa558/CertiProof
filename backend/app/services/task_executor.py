"""
流程任务执行器 - 桥接 FlowEngine 和 ExecutionEngine

将流程任务类型映射到具体的安全工具执行
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# 任务类型 → 执行引擎能力映射
TASK_CAPABILITY_MAP = {
    "asset_discovery": {
        "capability": "scan_ports",
        "default_params": {"port_range": "1-1000"},
        "description": "通过端口扫描发现信息资产",
    },
    "config_check": {
        "capability": "full_compliance_scan",
        "default_params": {},
        "description": "全量合规扫描（端口+SSL+漏洞+弱口令）",
    },
    "vuln_scan": {
        "capability": "scan_vulnerabilities",
        "default_params": {},
        "description": "漏洞扫描（Nuclei）",
    },
    "pentest": {
        "capability": "scan_vulnerabilities",
        "default_params": {"severity": "critical,high"},
        "description": "渗透测试（高危漏洞扫描）",
    },
    "ssl_check": {
        "capability": "scan_ssl",
        "default_params": {"port": 443},
        "description": "SSL/TLS 安全检测",
    },
    "password_scan": {
        "capability": "scan_weak_passwords",
        "default_params": {"service": "ssh", "port": 22},
        "description": "弱口令检测",
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
        
        capability = mapping["capability"]
        default_params = mapping["default_params"].copy()
        
        # 合并参数
        scan_params = {
            "target": target,
            **default_params,
            **(params or {}),
        }
        
        logger.info(f"Executing task {task_type} -> {capability} for target {target}")
        
        try:
            from app.services.execution_engine import ExecutionEngine
            engine = ExecutionEngine()
            
            result = await engine._execute_capability(
                capability_name=capability,
                parameters=scan_params,
                user_id=user_id,
                project_id=project_id,
                db=self.db,
            )
            
            return {
                "status": "completed",
                "task_type": task_type,
                "capability": capability,
                "target": target,
                "result": result,
            }
        
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            return {
                "status": "failed",
                "task_type": task_type,
                "capability": capability,
                "target": target,
                "error": str(e),
            }
    
    def get_task_info(self, task_type: str) -> Optional[Dict[str, Any]]:
        """获取任务类型信息"""
        return TASK_CAPABILITY_MAP.get(task_type)
    
    def is_automated_task(self, task_type: str) -> bool:
        """检查任务是否可自动执行"""
        mapping = TASK_CAPABILITY_MAP.get(task_type)
        return mapping is not None


def get_task_executor(db: AsyncSession) -> TaskExecutor:
    """获取任务执行器实例"""
    return TaskExecutor(db)
