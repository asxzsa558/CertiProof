from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import re


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "CertiProof"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    
    # Database - Using SQLite for development
    DATABASE_URL: str = "sqlite+aiosqlite:///./certiproof.db"
    GRAPH_NAME: str = "certiproof"
    GRAPH_REQUIRED: bool = False
    
    # JWT
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    # OpenAI / LLM (legacy, for initialization)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_BASE: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4"
    
    # MCP Gateway
    MCP_GATEWAY_URL: str = "http://localhost:9000"

    # AI 行为配置
    AI_HISTORY_TURNS: int = 5  # LLM 调用时携带的历史对话轮数（1-20）
    AI_ENABLE_CACHE: bool = True  # 是否启用 prompt cache
    AI_ENABLE_ASSESSMENT_CONTEXT: bool = True  # 是否注入测评流程状态到 prompt
    AI_CACHE_MIN_TOKENS: int = 1024  # 触发 cache 的最小 token 数（Anthropic 限制）

    # 测评流程配置
    ASSESSMENT_AUTO_START: bool = False  # 创建后是否自动开始
    ASSESSMENT_AUTO_EXECUTE_TASKS: bool = True  # 是否自动执行扫描类任务
    ASSESSMENT_MAX_CONCURRENT: int = 5  # 多资产扫描最大并发数

    # 任务执行配置
    TASK_EXECUTION_MODE: str = "inline"  # inline: API 进程执行；worker: 只入库，由 app.worker 执行
    TASK_WORKER_POLL_SECONDS: int = 3
    WORKER_ROLE: str = "interactive"
    INTERACTIVE_SCAN_MAX_CONCURRENT: int = 5
    TASK_LEASE_MINUTES: int = 2
    TASK_HEARTBEAT_SECONDS: int = 10
    TASK_MAX_RECOVERY_ATTEMPTS: int = 3
    MONITORING_WORKER_BATCH_SIZE: int = 5

    # 文件上传
    UPLOAD_DIR: str = "./uploads"  # 容器内解析为 /app/uploads，本机也可直接运行
    OCR_SERVER_URL: str = "http://ocr-server:8005"
    EMBEDDING_SERVER_URL: str = "http://embedding-server:8017"
    DOCUMENT_MAX_TOTAL_PAGES: int = 200
    DOCUMENT_WORKER_BATCH_SIZE: int = 2
    DOCUMENT_LEASE_MINUTES: int = 15
    DOCUMENT_RUN_TIMEOUT_MINUTES: int = 240
    DOCUMENT_MAX_RECOVERY_ATTEMPTS: int = 3
    DOCUMENT_FILE_RETRY_ATTEMPTS: int = 3
    DOCUMENT_ANALYSIS_MODE: str = "standard"  # standard/deep
    DOCUMENT_EMBEDDING_MODEL: str = "intfloat/multilingual-e5-large"
    DOCUMENT_EMBEDDING_DIMENSION: int = 1024

    # 报告配置
    REPORT_DEFAULT_FORMAT: str = "html"  # 默认报告格式
    REPORT_INCLUDE_RAW_SCANS: bool = False  # 报告是否包含原始扫描数据
    REPORT_LANGUAGE: str = "zh"  # 报告语言

    def validate_runtime_security(self) -> None:
        """Fail fast on unsafe production settings."""
        if self.TASK_EXECUTION_MODE not in {"inline", "worker"}:
            raise RuntimeError("Invalid configuration: TASK_EXECUTION_MODE must be 'inline' or 'worker'")
        if self.WORKER_ROLE not in {"interactive", "document", "assessment", "verification", "maintenance"}:
            raise RuntimeError("Invalid configuration: unsupported WORKER_ROLE")
        if self.INTERACTIVE_SCAN_MAX_CONCURRENT < 1:
            raise RuntimeError("Invalid configuration: INTERACTIVE_SCAN_MAX_CONCURRENT must be positive")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.GRAPH_NAME):
            raise RuntimeError("Invalid configuration: GRAPH_NAME must be a safe PostgreSQL identifier")
        if self.DOCUMENT_EMBEDDING_DIMENSION != 1024:
            raise RuntimeError("Invalid configuration: DOCUMENT_EMBEDDING_DIMENSION must match the 1024-dimensional vector schema")

        if self.APP_ENV.lower() not in {"prod", "production"}:
            return

        problems = []
        if self.DEBUG:
            problems.append("DEBUG must be false in production")
        if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
            problems.append("SECRET_KEY must be set to a strong non-default value in production")
        if "*" in self.CORS_ORIGINS:
            problems.append("CORS_ORIGINS must not contain '*' in production")

        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
