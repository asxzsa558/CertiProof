"""
上下文管理相关的数据模型
- ConversationHistory: 对话历史
- ActionHistory: 操作历史
- ResultCache: 结果缓存
- ProjectMemory: 项目记忆
- UserMemory: 用户记忆
- ConversationArchive: 对话归档
- ConversationThread: 对话线程
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class ConversationHistory(Base):
    """对话历史 - 记录所有用户与 AI 的对话"""
    __tablename__ = "conversation_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    thread_id = Column(Integer, ForeignKey("conversation_threads.id"), nullable=True, index=True)
    archive_id = Column(Integer, ForeignKey("conversation_archives.id"), nullable=True, index=True)
    
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    context_snapshot = Column(JSON)  # 上下文快照（引用了哪些操作、结果等）
    tokens_used = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    def __repr__(self):
        return f"<ConversationHistory(id={self.id}, role={self.role}, user_id={self.user_id}, thread_id={self.thread_id})>"


class ActionHistory(Base):
    """操作历史 - 记录所有执行的操作（扫描、创建项目等）"""
    __tablename__ = "action_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    thread_id = Column(Integer, ForeignKey("conversation_threads.id"), nullable=True, index=True)
    
    action_type = Column(String(50), nullable=False)  # 'scan_ports', 'create_project', etc.
    parameters = Column(JSON, nullable=False)  # 执行参数
    result = Column(JSON)  # 执行结果
    status = Column(String(20), nullable=False, default="pending")  # 'success', 'failed', 'pending'
    error_message = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f"<ActionHistory(id={self.id}, action_type={self.action_type}, status={self.status})>"


class ResultCache(Base):
    """结果缓存 - 缓存扫描结果，避免重复扫描"""
    __tablename__ = "result_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    
    cache_key = Column(String(255), nullable=False, index=True)  # 'scan_ports:localhost'
    result_data = Column(JSON, nullable=False)
    
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<ResultCache(id={self.id}, cache_key={self.cache_key})>"


class ProjectMemory(Base):
    """项目记忆 - 记录项目相关的知识和经验"""
    __tablename__ = "project_memory"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    
    memory_type = Column(String(50), nullable=False)  # 'architecture', 'conventions', 'commands', 'findings'
    content = Column(Text, nullable=False)
    extra_data = Column(JSON)  # 额外元数据（避免使用 metadata 保留字）
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<ProjectMemory(id={self.id}, project_id={self.project_id}, type={self.memory_type})>"


class UserMemory(Base):
    """用户记忆 - 记录用户偏好和习惯"""
    __tablename__ = "user_memory"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    memory_type = Column(String(50), nullable=False)  # 'preferences', 'habits', 'shortcuts', 'corrections'
    content = Column(Text, nullable=False)
    extra_data = Column(JSON)  # 额外元数据（避免使用 metadata 保留字）
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<UserMemory(id={self.id}, user_id={self.user_id}, type={self.memory_type})>"


class ConversationArchive(Base):
    """对话归档 - 归档的对话历史（用于任务交接）"""
    __tablename__ = "conversation_archives"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    thread_id = Column(Integer, ForeignKey("conversation_threads.id"), nullable=True, index=True)
    
    title = Column(String(200))  # 归档标题
    summary = Column(Text)  # 归档摘要（LLM 生成的交接摘要）
    message_count = Column(Integer, default=0)  # 包含的消息数量
    token_count = Column(Integer, default=0)  # 包含的 token 数
    
    # 结构化交接信息
    completed_tasks = Column(JSON)  # 已完成任务列表 [{"task": "端口扫描", "result": "发现 3 个端口"}]
    current_task = Column(JSON)     # 当前进行中的任务 {"task": "SSL 检测", "progress": "已扫描 443 端口"}
    interrupt_point = Column(Text)  # 中断点描述（从哪里继续）
    key_findings = Column(JSON)     # 关键发现 [{"finding": "开放端口 22,80,443"}]

    # 摘要由持久化 Worker 生成。原始消息通过 ConversationHistory.archive_id 保留。
    status = Column(String(20), nullable=False, default="queued", index=True)
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    lease_owner = Column(String(128), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    summary_generated_at = Column(DateTime(timezone=True), nullable=True)
    source_message_ids = Column(JSON, nullable=True)
    related_refs = Column(JSON, nullable=True)
    legacy_summary_only = Column(Boolean, nullable=False, default=False)
    
    archived_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<ConversationArchive(id={self.id}, user_id={self.user_id}, title={self.title})>"


class ConversationThread(Base):
    """对话线程 - 管理对话会话"""
    __tablename__ = "conversation_threads"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    
    title = Column(String(200))  # 线程标题
    parent_thread_id = Column(Integer, ForeignKey("conversation_threads.id"), nullable=True)  # 父线程
    source_archive_id = Column(Integer, ForeignKey("conversation_archives.id"), nullable=True, index=True)
    
    is_active = Column(Boolean, default=True)  # 是否活跃
    is_archived = Column(Boolean, default=False)  # 是否已归档
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<ConversationThread(id={self.id}, user_id={self.user_id}, title={self.title})>"


class ConversationSummary(Base):
    """线程分段摘要；原文不删除，只减少后续 LLM 上下文负担。"""
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    thread_id = Column(Integer, ForeignKey("conversation_threads.id"), nullable=True, index=True)
    source_start_message_id = Column(Integer, nullable=False)
    source_end_message_id = Column(Integer, nullable=False)
    message_count = Column(Integer, nullable=False, default=0)
    token_count = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    lease_owner = Column(String(128), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
