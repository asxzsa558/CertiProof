"""
流程引擎 - 编排等保测评流程执行

设计原则：
- 状态机驱动：阶段转换由状态机管理
- 事件驱动：阶段变化发出事件
- 依赖管理：阶段间依赖关系自动处理
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.assessment import (
    FlowTemplate, Assessment, PhaseInstance, TaskInstance, FlowEvent
)

logger = logging.getLogger(__name__)


class StateMachine:
    """流程状态机 - 管理状态转换"""
    
    # 测评状态转换
    ASSESSMENT_TRANSITIONS = {
        "not_started": ["in_progress"],
        "in_progress": ["paused", "completed", "failed"],
        "paused": ["in_progress"],
        "completed": [],  # 终态
        "failed": ["in_progress"],  # 可重试
    }
    
    # 阶段状态转换
    PHASE_TRANSITIONS = {
        "pending": ["active", "skipped"],
        "active": ["completed", "failed"],
        "completed": [],  # 终态
        "skipped": [],  # 终态
        "failed": ["active"],  # 可重试
    }
    
    # 任务状态转换
    TASK_TRANSITIONS = {
        "todo": ["in_progress", "cancelled"],
        "in_progress": ["completed", "failed"],
        "completed": [],  # 终态
        "failed": ["in_progress"],  # 可重试
        "cancelled": [],  # 终态
    }
    
    @staticmethod
    def can_transition(current: str, target: str, entity_type: str) -> bool:
        """检查状态转换是否合法"""
        transitions = {
            "assessment": StateMachine.ASSESSMENT_TRANSITIONS,
            "phase": StateMachine.PHASE_TRANSITIONS,
            "task": StateMachine.TASK_TRANSITIONS,
        }
        return target in transitions[entity_type].get(current, [])


class FlowEngine:
    """流程引擎 - 编排流程执行"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ========== 模板管理 ==========
    
    async def get_template(self, template_id: int) -> Optional[FlowTemplate]:
        """获取流程模板"""
        result = await self.db.execute(
            select(FlowTemplate).where(FlowTemplate.id == template_id)
        )
        return result.scalar_one_or_none()
    
    async def list_templates(self, active_only: bool = True) -> List[FlowTemplate]:
        """列出流程模板"""
        query = select(FlowTemplate)
        if active_only:
            query = query.where(FlowTemplate.is_active == True)
        result = await self.db.execute(query.order_by(FlowTemplate.compliance_level))
        return result.scalars().all()
    
    async def create_template(self, name: str, compliance_level: int, phases_config: dict) -> FlowTemplate:
        """创建流程模板"""
        template = FlowTemplate(
            name=name,
            compliance_level=compliance_level,
            phases_config=phases_config,
        )
        self.db.add(template)
        await self.db.commit()
        await self.db.refresh(template)
        return template
    
    # ========== 测评管理 ==========
    
    async def create_assessment(
        self, 
        project_id: int, 
        template_id: int,
        name: str = None,
        owner_id: int = None
    ) -> Assessment:
        """创建测评实例"""
        # 加载流程模板
        template = await self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        # 创建测评实例
        assessment = Assessment(
            project_id=project_id,
            template_id=template_id,
            name=name or f"{template.name} - {datetime.now().strftime('%Y%m%d')}",
            assessment_level=template.compliance_level,
            total_phases=len(template.phases_config),
            owner_id=owner_id,
        )
        self.db.add(assessment)
        await self.db.flush()
        
        # 创建阶段实例
        for phase_config in template.phases_config:
            phase = PhaseInstance(
                assessment_id=assessment.id,
                phase_id=phase_config["id"],
                name=phase_config["name"],
                description=phase_config.get("description", ""),
                order=phase_config["order"],
                depends_on=phase_config.get("depends_on", []),
            )
            self.db.add(phase)
            await self.db.flush()
            
            # 创建默认任务
            for task_config in phase_config.get("default_tasks", []):
                task = TaskInstance(
                    phase_id=phase.id,
                    task_type=task_config["type"],
                    name=task_config["name"],
                    description=task_config.get("description", ""),
                )
                self.db.add(task)
                phase.total_tasks += 1
        
        await self.db.commit()
        await self.db.refresh(assessment)
        
        # 发出事件
        await self.emit_event(assessment.id, "assessment_created")
        
        logger.info(f"Created assessment {assessment.id} for project {project_id}")
        return assessment
    
    async def get_assessment(self, assessment_id: int) -> Optional[Assessment]:
        """获取测评实例"""
        result = await self.db.execute(
            select(Assessment).where(Assessment.id == assessment_id)
        )
        return result.scalar_one_or_none()
    
    async def list_assessments(self, project_id: int = None) -> List[Assessment]:
        """列出测评实例"""
        query = select(Assessment)
        if project_id:
            query = query.where(Assessment.project_id == project_id)
        result = await self.db.execute(query.order_by(Assessment.created_at.desc()))
        return result.scalars().all()
    
    async def start_assessment(self, assessment_id: int) -> Assessment:
        """启动测评"""
        assessment = await self.get_assessment(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")
        
        # 状态转换
        if not StateMachine.can_transition(assessment.status, "in_progress", "assessment"):
            raise ValueError(f"Cannot transition from {assessment.status} to in_progress")
        
        assessment.status = "in_progress"
        assessment.started_at = datetime.utcnow()
        
        # 激活第一个阶段
        first_phase = await self.get_first_phase(assessment_id)
        if first_phase:
            await self.activate_phase(first_phase.id)
        
        await self.db.commit()
        
        # 发出事件
        await self.emit_event(assessment_id, "assessment_started")
        
        logger.info(f"Started assessment {assessment_id}")
        return assessment
    
    async def pause_assessment(self, assessment_id: int) -> Assessment:
        """暂停测评"""
        assessment = await self.get_assessment(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")
        
        if not StateMachine.can_transition(assessment.status, "paused", "assessment"):
            raise ValueError(f"Cannot transition from {assessment.status} to paused")
        
        assessment.status = "paused"
        await self.db.commit()
        
        await self.emit_event(assessment_id, "assessment_paused")
        return assessment
    
    async def resume_assessment(self, assessment_id: int) -> Assessment:
        """恢复测评"""
        assessment = await self.get_assessment(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")
        
        if not StateMachine.can_transition(assessment.status, "in_progress", "assessment"):
            raise ValueError(f"Cannot transition from {assessment.status} to in_progress")
        
        assessment.status = "in_progress"
        await self.db.commit()
        
        await self.emit_event(assessment_id, "assessment_resumed")
        return assessment
    
    # ========== 阶段管理 ==========
    
    async def get_phases(self, assessment_id: int) -> List[PhaseInstance]:
        """获取测评的所有阶段"""
        result = await self.db.execute(
            select(PhaseInstance)
            .where(PhaseInstance.assessment_id == assessment_id)
            .order_by(PhaseInstance.order)
        )
        return result.scalars().all()
    
    async def get_phase(self, phase_id: int) -> Optional[PhaseInstance]:
        """获取阶段"""
        result = await self.db.execute(
            select(PhaseInstance).where(PhaseInstance.id == phase_id)
        )
        return result.scalar_one_or_none()
    
    async def get_first_phase(self, assessment_id: int) -> Optional[PhaseInstance]:
        """获取第一个阶段"""
        result = await self.db.execute(
            select(PhaseInstance)
            .where(PhaseInstance.assessment_id == assessment_id)
            .order_by(PhaseInstance.order)
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def activate_phase(self, phase_id: int) -> PhaseInstance:
        """激活阶段"""
        phase = await self.get_phase(phase_id)
        if not phase:
            raise ValueError(f"Phase {phase_id} not found")
        
        if not StateMachine.can_transition(phase.status, "active", "phase"):
            raise ValueError(f"Cannot transition from {phase.status} to active")
        
        phase.status = "active"
        phase.started_at = datetime.utcnow()
        await self.db.commit()
        
        await self.emit_event(phase.assessment_id, "phase_started", {"phase_id": phase_id})
        return phase
    
    async def complete_phase(self, phase_id: int, outputs: dict = None) -> PhaseInstance:
        """完成阶段"""
        phase = await self.get_phase(phase_id)
        if not phase:
            raise ValueError(f"Phase {phase_id} not found")
        
        if not StateMachine.can_transition(phase.status, "completed", "phase"):
            raise ValueError(f"Cannot transition from {phase.status} to completed")
        
        phase.status = "completed"
        phase.completed_at = datetime.utcnow()
        phase.progress = 100.0
        if outputs:
            phase.outputs = outputs
        
        await self.db.commit()
        
        # 检查是否可以激活下一阶段
        await self._activate_next_phase(phase.assessment_id)
        
        # 更新测评进度
        await self._update_assessment_progress(phase.assessment_id)
        
        # 发出事件
        await self.emit_event(phase.assessment_id, "phase_completed", {"phase_id": phase_id})
        
        logger.info(f"Completed phase {phase_id}")
        return phase
    
    async def skip_phase(self, phase_id: int, reason: str = "") -> PhaseInstance:
        """跳过阶段"""
        phase = await self.get_phase(phase_id)
        if not phase:
            raise ValueError(f"Phase {phase_id} not found")
        
        if not StateMachine.can_transition(phase.status, "skipped", "phase"):
            raise ValueError(f"Cannot transition from {phase.status} to skipped")
        
        phase.status = "skipped"
        phase.completed_at = datetime.utcnow()
        if reason:
            phase.outputs = {"skip_reason": reason}
        
        await self.db.commit()
        
        # 检查是否可以激活下一阶段
        await self._activate_next_phase(phase.assessment_id)
        
        # 更新测评进度
        await self._update_assessment_progress(phase.assessment_id)
        
        await self.emit_event(phase.assessment_id, "phase_skipped", {"phase_id": phase_id, "reason": reason})
        return phase
    
    async def _activate_next_phase(self, assessment_id: int):
        """激活下一个可执行的阶段"""
        phases = await self.get_phases(assessment_id)
        
        for phase in phases:
            if phase.status == "pending":
                # 检查依赖是否满足
                if await self._check_dependencies(phase):
                    await self.activate_phase(phase.id)
                    break
    
    async def _check_dependencies(self, phase: PhaseInstance) -> bool:
        """检查阶段依赖是否满足"""
        if not phase.depends_on:
            return True
        
        phases = await self.get_phases(phase.assessment_id)
        phase_map = {p.phase_id: p for p in phases}
        
        for dep_id in phase.depends_on:
            dep_phase = phase_map.get(dep_id)
            if not dep_phase or dep_phase.status not in ["completed", "skipped"]:
                return False
        
        return True
    
    async def _update_assessment_progress(self, assessment_id: int):
        """更新测评进度"""
        assessment = await self.get_assessment(assessment_id)
        phases = await self.get_phases(assessment_id)
        
        completed = sum(1 for p in phases if p.status in ["completed", "skipped"])
        assessment.completed_phases = completed
        assessment.progress = (completed / assessment.total_phases * 100) if assessment.total_phases > 0 else 0
        
        # 检查是否所有阶段完成
        if all(p.status in ["completed", "skipped"] for p in phases):
            assessment.status = "completed"
            assessment.completed_at = datetime.utcnow()
            await self.emit_event(assessment_id, "assessment_completed")
        
        await self.db.commit()
    
    # ========== 任务管理 ==========
    
    async def get_tasks(self, phase_id: int) -> List[TaskInstance]:
        """获取阶段的所有任务"""
        result = await self.db.execute(
            select(TaskInstance)
            .where(TaskInstance.phase_id == phase_id)
            .order_by(TaskInstance.priority.desc(), TaskInstance.created_at)
        )
        return result.scalars().all()
    
    async def get_task(self, task_id: int) -> Optional[TaskInstance]:
        """获取任务"""
        result = await self.db.execute(
            select(TaskInstance).where(TaskInstance.id == task_id)
        )
        return result.scalar_one_or_none()
    
    async def create_task(
        self, 
        phase_id: int, 
        task_type: str, 
        name: str,
        description: str = None,
        assignee_id: int = None
    ) -> TaskInstance:
        """创建任务"""
        phase = await self.get_phase(phase_id)
        if not phase:
            raise ValueError(f"Phase {phase_id} not found")
        
        task = TaskInstance(
            phase_id=phase_id,
            task_type=task_type,
            name=name,
            description=description,
            assignee_id=assignee_id,
        )
        self.db.add(task)
        
        phase.total_tasks += 1
        await self.db.commit()
        await self.db.refresh(task)
        
        return task
    
    async def start_task(self, task_id: int) -> TaskInstance:
        """开始任务"""
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        if not StateMachine.can_transition(task.status, "in_progress", "task"):
            raise ValueError(f"Cannot transition from {task.status} to in_progress")
        
        task.status = "in_progress"
        task.started_at = datetime.utcnow()
        await self.db.commit()
        
        phase = await self.get_phase(task.phase_id)
        await self.emit_event(phase.assessment_id, "task_started", {"task_id": task_id})
        
        return task
    
    async def complete_task(self, task_id: int, result: dict = None) -> TaskInstance:
        """完成任务"""
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        if not StateMachine.can_transition(task.status, "completed", "task"):
            raise ValueError(f"Cannot transition from {task.status} to completed")
        
        task.status = "completed"
        task.completed_at = datetime.utcnow()
        if result:
            task.result = result
        
        # 更新阶段进度
        phase = await self.get_phase(task.phase_id)
        phase.completed_tasks += 1
        phase.progress = (phase.completed_tasks / phase.total_tasks * 100) if phase.total_tasks > 0 else 0
        
        await self.db.commit()
        
        await self.emit_event(phase.assessment_id, "task_completed", {"task_id": task_id})
        
        logger.info(f"Completed task {task_id}")
        return task
    
    # ========== 事件管理 ==========
    
    async def emit_event(
        self, 
        assessment_id: int, 
        event_type: str, 
        event_data: dict = None,
        phase_id: int = None,
        task_id: int = None,
        user_id: int = None
    ) -> FlowEvent:
        """发出流程事件"""
        event = FlowEvent(
            assessment_id=assessment_id,
            phase_id=phase_id,
            task_id=task_id,
            event_type=event_type,
            event_data=event_data,
            user_id=user_id,
        )
        self.db.add(event)
        await self.db.commit()
        return event
    
    async def get_events(self, assessment_id: int, limit: int = 50) -> List[FlowEvent]:
        """获取流程事件"""
        result = await self.db.execute(
            select(FlowEvent)
            .where(FlowEvent.assessment_id == assessment_id)
            .order_by(FlowEvent.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()


# 全局流程引擎实例（需要在请求中通过依赖注入使用）
def get_flow_engine(db: AsyncSession) -> FlowEngine:
    """获取流程引擎实例"""
    return FlowEngine(db)
