"""
上下文管理相关的数据模型
- ConversationHistory: 对话历史
- ActionHistory: 操作历史
- ResultCache: 结果缓存
- ProjectMemory: 项目记忆
- UserMemory: 用户记忆
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class ConversationHistory(Base):
    """对话历史 - 记录所有用户与 AI 的对话"""
    __tablename__ = "conversation_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    context_snapshot = Column(JSON)  # 上下文快照（引用了哪些操作、结果等）
    tokens_used = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<ConversationHistory(id={self.id}, role={self.role}, user_id={self.user_id})>"


class ActionHistory(Base):
    """操作历史 - 记录所有执行的操作（扫描、创建项目等）"""
    __tablename__ = "action_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    
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
