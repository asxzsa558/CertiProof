from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class ProviderType(str, enum.Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    AZURE = "azure"
    CUSTOM = "custom"


class ModelProvider(Base):
    __tablename__ = "model_providers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # "OpenAI", "Anthropic", "Local"
    provider_type = Column(SQLEnum(ProviderType), nullable=False)
    api_key = Column(String(500), nullable=True)  # Encrypted API Key
    api_base = Column(String(500), nullable=True)  # API endpoint
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    configs = relationship("ModelConfig", back_populates="provider", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<ModelProvider(id={self.id}, name={self.name}, type={self.provider_type})>"


class ModelConfig(Base):
    __tablename__ = "model_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("model_providers.id"), nullable=False)
    
    model_name = Column(String(100), nullable=False)  # "gpt-4", "claude-3-opus"
    display_name = Column(String(200), nullable=False)  # "GPT-4 Turbo"
    capabilities = Column(JSON, nullable=True)  # ["chat", "vision", "code"]
    
    max_tokens = Column(Integer, default=4096)
    
    is_default = Column(Boolean, default=False, nullable=False)
    priority = Column(Integer, default=0)  # Fallback priority (lower = higher priority)
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    provider = relationship("ModelProvider", back_populates="configs")
    usage_records = relationship("ModelUsage", back_populates="model_config", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<ModelConfig(id={self.id}, model={self.model_name}, provider_id={self.provider_id})>"


class ModelUsage(Base):
    __tablename__ = "model_usage"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    model_config_id = Column(Integer, ForeignKey("model_configs.id"), nullable=False)
    
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    
    task_type = Column(String(50), nullable=True)  # "chat", "vision", "code", "ocr"
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    model_config = relationship("ModelConfig", back_populates="usage_records")
    
    def __repr__(self):
        return f"<ModelUsage(id={self.id}, user_id={self.user_id}, model_id={self.model_config_id})>"
