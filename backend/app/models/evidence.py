from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class EvidenceType(str, enum.Enum):
    TOOL_OUTPUT = "tool_output"
    SCREENSHOT = "screenshot"
    API_RESPONSE = "api_response"
    LOG = "log"
    DOCUMENT = "document"
    POLICY = "policy"  # 制度文档
    RECORD = "record"  # 记录文档


class Evidence(Base):
    __tablename__ = "evidences"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # 关联到 Finding（漏洞证据）
    finding_id = Column(Integer, ForeignKey("findings.id"), nullable=True, index=True)
    
    # 关联到 QuestionnaireRecord（问卷证据）
    questionnaire_record_id = Column(Integer, ForeignKey("questionnaire_records.id"), nullable=True, index=True)
    
    # 关联到项目（通用证据）
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    
    # Evidence info
    evidence_type = Column(SQLEnum(EvidenceType), nullable=False)
    source = Column(String(200), nullable=True)  # Tool name or "manual"
    
    # 文件信息
    file_name = Column(String(255), nullable=True)  # 原始文件名
    file_path = Column(String(500), nullable=True)  # 服务器存储路径
    file_size = Column(Integer, nullable=True)  # 文件大小（字节）
    mime_type = Column(String(100), nullable=True)  # MIME 类型
    
    # 内容
    content = Column(JSON, nullable=True)  # 结构化数据
    raw_output = Column(Text, nullable=True)  # 原始工具输出
    description = Column(Text, nullable=True)  # 证据描述
    
    # 关联的条款
    clause_id = Column(String(50), nullable=True, index=True)  # 等保条款编号
    
    # 完整性
    hash_sha256 = Column(String(64), nullable=True)  # SHA-256 哈希
    
    # 元数据
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    finding = relationship("Finding", back_populates="evidences")
    questionnaire_record = relationship("QuestionnaireRecord", back_populates="evidences")
    
    def __repr__(self):
        return f"<Evidence(id={self.id}, type={self.evidence_type}, source={self.source})>"
