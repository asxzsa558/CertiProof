"""
系统配置服务 - 提供配置的读取、更新、初始化

配置来源优先级：
1. 数据库（SystemConfig 表）- 运行时修改的
2. 环境变量 / Settings - 启动时的默认值
"""
import logging
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.config import SystemConfig

logger = logging.getLogger(__name__)


# 默认配置定义（key -> {value, description, category}）
DEFAULT_CONFIGS = {
    # AI 行为
    "ai.history_turns": {
        "value": settings.AI_HISTORY_TURNS,
        "description": "LLM 调用时携带的历史对话轮数（1-20）",
        "category": "ai",
    },
    "ai.enable_cache": {
        "value": settings.AI_ENABLE_CACHE,
        "description": "是否启用 prompt cache（Anthropic 节省成本）",
        "category": "ai",
    },
    "ai.enable_assessment_context": {
        "value": settings.AI_ENABLE_ASSESSMENT_CONTEXT,
        "description": "是否在 prompt 中注入测评流程状态",
        "category": "ai",
    },
    # 测评流程
    "assessment.auto_start": {
        "value": settings.ASSESSMENT_AUTO_START,
        "description": "创建测评后是否自动开始",
        "category": "assessment",
    },
    "assessment.auto_execute_tasks": {
        "value": settings.ASSESSMENT_AUTO_EXECUTE_TASKS,
        "description": "是否自动执行扫描类任务（asset_discovery / vuln_scan 等）",
        "category": "assessment",
    },
    "assessment.max_concurrent": {
        "value": settings.ASSESSMENT_MAX_CONCURRENT,
        "description": "多资产扫描最大并发数（1-10）",
        "category": "assessment",
    },
    # 文档合规检查
    "document.analysis_mode": {
        "value": settings.DOCUMENT_ANALYSIS_MODE,
        "description": "默认文档分析模式（standard/deep）",
        "category": "document",
    },
    # 运行资源与推理策略
    "runtime.model_policy": {
        "value": settings.LLM_RUNTIME_POLICY,
        "description": "模型运行策略（auto/cloud/local/vllm/llama_cpp/ollama）",
        "category": "runtime",
    },
    "runtime.resource_mode": {
        "value": "auto",
        "description": "资源档位采用自动推荐或手动配置（auto/manual）",
        "category": "runtime",
    },
    "runtime.resource_profile": {
        "value": "standard",
        "description": "手动资源档位（light/standard/gpu/custom）",
        "category": "runtime",
    },
    "runtime.interactive_concurrency": {
        "value": settings.INTERACTIVE_SCAN_MAX_CONCURRENT,
        "description": "交互扫描最大并发数",
        "category": "runtime",
    },
    "runtime.assessment_concurrency": {
        "value": settings.ASSESSMENT_MAX_CONCURRENT,
        "description": "技术测评最大并发数",
        "category": "runtime",
    },
    "runtime.document_concurrency": {
        "value": settings.DOCUMENT_WORKER_BATCH_SIZE,
        "description": "文档分析最大并发数",
        "category": "runtime",
    },
    "runtime.verification_concurrency": {
        "value": 2,
        "description": "整改复测最大并发数",
        "category": "runtime",
    },
    "runtime.model_concurrency": {
        "value": 4,
        "description": "模型调用最大并发数",
        "category": "runtime",
    },
    "runtime.memory_pressure_percent": {
        "value": 90,
        "description": "暂停领取新任务的内存压力阈值",
        "category": "runtime",
    },
    "runtime.cpu_pressure_percent": {
        "value": 95,
        "description": "暂停领取新任务的 CPU 负载阈值",
        "category": "runtime",
    },
    # 报告
    "report.default_format": {
        "value": settings.REPORT_DEFAULT_FORMAT,
        "description": "默认报告格式（html/json）",
        "category": "report",
    },
    "report.include_raw_scans": {
        "value": settings.REPORT_INCLUDE_RAW_SCANS,
        "description": "报告是否包含原始扫描数据",
        "category": "report",
    },
}


class ConfigService:
    """系统配置服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, key: str, default: Any = None) -> Any:
        """获取单个配置项的值"""
        result = await self.db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()
        if config:
            return config.value
        # 回退到默认配置
        if key in DEFAULT_CONFIGS:
            return DEFAULT_CONFIGS[key]["value"]
        return default

    async def get_all(self) -> Dict[str, Any]:
        """获取所有配置，按 category 分组"""
        result = await self.db.execute(select(SystemConfig))
        db_configs = {c.key: c.value for c in result.scalars().all()}

        # 合并默认配置和数据库配置
        grouped = {"ai": {}, "assessment": {}, "document": {}, "runtime": {}, "report": {}}
        for key, meta in DEFAULT_CONFIGS.items():
            category = meta["category"]
            if key in db_configs:
                grouped[category][key] = db_configs[key]
            else:
                grouped[category][key] = meta["value"]

        return grouped

    async def update(self, key: str, value: Any) -> SystemConfig:
        """更新配置项"""
        if key not in DEFAULT_CONFIGS:
            raise ValueError(f"Unknown config key: {key}")
        value = self._validate(key, value)

        result = await self.db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if config:
            config.value = value
        else:
            meta = DEFAULT_CONFIGS[key]
            config = SystemConfig(
                key=key,
                value=value,
                category=meta["category"],
                description=meta["description"],
            )
            self.db.add(config)

        await self.db.commit()
        await self.db.refresh(config)
        logger.info(f"Config updated: {key} = {value}")
        return config

    @staticmethod
    def _validate(key: str, value: Any) -> Any:
        options = {
            "runtime.model_policy": {"auto", "cloud", "local", "vllm", "llama_cpp", "ollama"},
            "runtime.resource_mode": {"auto", "manual"},
            "runtime.resource_profile": {"light", "standard", "gpu", "custom"},
        }
        if key in options:
            if value not in options[key]:
                raise ValueError(f"Invalid value for {key}")
            return value
        ranges = {
            "runtime.interactive_concurrency": (1, 10),
            "runtime.assessment_concurrency": (1, 10),
            "runtime.document_concurrency": (1, 4),
            "runtime.verification_concurrency": (1, 5),
            "runtime.model_concurrency": (1, 16),
            "runtime.memory_pressure_percent": (50, 99),
            "runtime.cpu_pressure_percent": (50, 99),
        }
        if key in ranges:
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be an integer") from exc
            low, high = ranges[key]
            if not low <= number <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
            return number
        return value

    async def update_batch(self, updates: Dict[str, Any]) -> int:
        """批量更新配置"""
        count = 0
        for key, value in updates.items():
            if key in DEFAULT_CONFIGS:
                await self.update(key, value)
                count += 1
        return count

    async def init_defaults(self) -> int:
        """初始化默认配置到数据库（如果不存在）"""
        count = 0
        for key, meta in DEFAULT_CONFIGS.items():
            result = await self.db.execute(
                select(SystemConfig).where(SystemConfig.key == key)
            )
            if not result.scalar_one_or_none():
                config = SystemConfig(
                    key=key,
                    value=meta["value"],
                    category=meta["category"],
                    description=meta["description"],
                )
                self.db.add(config)
                count += 1

        if count > 0:
            await self.db.commit()
            logger.info(f"Initialized {count} default configs")
        return count

    async def get_meta(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配置的元信息（用于前端展示）"""
        return {
            key: {
                "value": meta["value"],
                "description": meta["description"],
                "category": meta["category"],
            }
            for key, meta in DEFAULT_CONFIGS.items()
        }


def get_config_service(db: AsyncSession) -> ConfigService:
    return ConfigService(db)
