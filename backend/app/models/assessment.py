"""
等保测评流程管理数据模型

设计原则：
- 领域驱动：流程管理作为独立限界上下文
- 状态机驱动：阶段转换由状态机管理
- 事件驱动：阶段变化发出事件
- 模板化：流程模板可配置
"""

from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class FlowTemplate(Base):
    """流程模板 - 定义等保测评的标准流程"""
    __tablename__ = "flow_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)  # "等保三级测评流程"
    description = Column(Text)
    compliance_level = Column(Integer)  # 2=二级, 3=三级
    version = Column(String(20), default="1.0")
    
    # 流程配置（JSON 存储阶段定义）
    phases_config = Column(JSON, nullable=False)
    # 示例:
    # [
    #   {
    #     "id": "phase_1",
    #     "name": "系统定级",
    #     "order": 1,
    #     "required": true,
    #     "description": "确定信息系统安全保护等级",
    #     "depends_on": [],
    #     "default_tasks": [
    #       {"type": "doc_review", "name": "审查定级报告"},
    #       {"type": "doc_review", "name": "审查专家评审意见"}
    #     ]
    #   },
    #   ...
    # ]
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # 关系
    assessments = relationship("Assessment", back_populates="template", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<FlowTemplate(id={self.id}, name={self.name}, level={self.compliance_level})>"


class Assessment(Base):
    """测评实例 - 某个项目的测评活动"""
    __tablename__ = "assessments"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("flow_templates.id"), nullable=False)
    
    # 基本信息
    name = Column(String(200))  # "2026年度等保三级测评"
    target_system = Column(String(500))  # 被测系统名称
    assessment_level = Column(Integer)  # 测评级别
    
    # 状态跟踪
    status = Column(String(20), default="not_started", nullable=False)
    # not_started / in_progress / paused / completed / failed
    
    # 进度统计
    total_phases = Column(Integer, default=0)
    completed_phases = Column(Integer, default=0)
    progress = Column(Float, default=0.0)  # 0-100
    
    # 时间线
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    estimated_completion = Column(DateTime(timezone=True))  # 预计完成时间
    
    # 负责人
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    # 扩展信息
    extra_data = Column(JSON)  # 扩展信息
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # 关系
    project = relationship("Project", backref="flow_assessments")
    template = relationship("FlowTemplate", back_populates="assessments")
    phases = relationship("PhaseInstance", back_populates="assessment", cascade="all, delete-orphan", 
                         order_by="PhaseInstance.order")
    events = relationship("FlowEvent", back_populates="assessment", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Assessment(id={self.id}, name={self.name}, status={self.status}, progress={self.progress})>"


class PhaseInstance(Base):
    """阶段实例 - 流程中的具体阶段"""
    __tablename__ = "phase_instances"
    
    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False, index=True)
    
    # 阶段信息
    phase_id = Column(String(50), nullable=False)  # 模板中的阶段ID
    name = Column(String(200), nullable=False)  # "系统定级"
    description = Column(Text)
    order = Column(Integer, nullable=False)  # 阶段顺序
    
    # 状态
    status = Column(String(20), default="pending", nullable=False)
    # pending / active / completed / skipped / failed
    
    # 进度
    total_tasks = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    progress = Column(Float, default=0.0)
    
    # 时间线
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    
    # 输入/输出
    inputs = Column(JSON)  # 阶段输入（前置阶段输出）
    outputs = Column(JSON)  # 阶段输出（交付物）
    
    # 依赖关系
    depends_on = Column(JSON)  # 依赖的阶段ID列表
    # 示例: ["phase_1", "phase_2"]
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # 关系
    assessment = relationship("Assessment", back_populates="phases")
    tasks = relationship("TaskInstance", back_populates="phase", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<PhaseInstance(id={self.id}, name={self.name}, status={self.status}, order={self.order})>"


class TaskInstance(Base):
    """任务实例 - 阶段中的具体任务"""
    __tablename__ = "task_instances"
    
    id = Column(Integer, primary_key=True, index=True)
    phase_id = Column(Integer, ForeignKey("phase_instances.id"), nullable=False, index=True)
    
    # 任务信息
    task_type = Column(String(50), nullable=False)
    # asset_discovery / config_check / vuln_scan / pentest / doc_review / interview
    
    name = Column(String(200), nullable=False)
    description = Column(Text)
    
    # 状态
    status = Column(String(20), default="todo", nullable=False)
    # todo / in_progress / completed / failed / cancelled
    
    # 执行信息
    assignee_id = Column(Integer, ForeignKey("users.id"))  # 执行人
    priority = Column(Integer, default=0)  # 优先级
    
    # 执行结果
    result = Column(JSON)  # 任务结果
    evidence_ids = Column(JSON)  # 关联的证据ID列表
    lease_owner = Column(String(128), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    # 时间
    estimated_hours = Column(Float)  # 预估工时
    actual_hours = Column(Float)  # 实际工时
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # 关系
    phase = relationship("PhaseInstance", back_populates="tasks")
    assignee = relationship("User", foreign_keys=[assignee_id])
    
    def __repr__(self):
        return f"<TaskInstance(id={self.id}, name={self.name}, type={self.task_type}, status={self.status})>"


class FlowEvent(Base):
    """流程事件 - 记录流程变化，用于审计和通知"""
    __tablename__ = "flow_events"
    
    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False, index=True)
    phase_id = Column(Integer, ForeignKey("phase_instances.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("task_instances.id"), nullable=True)
    
    # 事件信息
    event_type = Column(String(50), nullable=False)
    # assessment_created / assessment_started / assessment_completed
    # phase_started / phase_completed / phase_skipped
    # task_started / task_completed / task_failed
    
    event_data = Column(JSON)  # 事件数据
    user_id = Column(Integer, ForeignKey("users.id"))  # 触发用户
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # 关系
    assessment = relationship("Assessment", back_populates="events")
    
    def __repr__(self):
        return f"<FlowEvent(id={self.id}, type={self.event_type}, assessment_id={self.assessment_id})>"
