"""
问卷记录数据模型
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class QuestionnaireRecord(Base):
    """问卷记录"""
    __tablename__ = "questionnaire_records"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    clause_id = Column(String(50), nullable=False, index=True)  # 等保条款编号，如 8.1.1.1.2
    clause_name = Column(String(200), nullable=False)  # 条款名称
    
    # 问卷内容（从条款库加载）
    questions = Column(JSON, nullable=False)  # 问题列表
    evidence_required = Column(JSON)  # 每个问题需要的证据类型
    
    # 答案（用户填写）
    answers = Column(JSON)  # 答案列表 [{"question_id": "q1", "answer": "yes", "evidence": [...]}]
    
    # 评估结果
    evaluation = Column(JSON)  # 评估结果 {"pass": true, "score": 1.0, "details": {...}}
    
    # 元数据
    status = Column(String(20), default="pending")  # pending/completed/evaluated
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True))
    
    # Relationships
    project = relationship("Project", back_populates="questionnaires")
    evidences = relationship("Evidence", back_populates="questionnaire_record", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<QuestionnaireRecord(id={self.id}, clause_id={self.clause_id}, status={self.status})>"
