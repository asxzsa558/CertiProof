"""
流程引擎 - 编排等保测评流程执行

设计原则：
- 状态机驱动：阶段转换由状态机管理
- 事件驱动：阶段变化发出事件
- 依赖管理：阶段间依赖关系自动处理
"""

import logging
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, or_

from app.models.assessment import (
    FlowTemplate, Assessment, PhaseInstance, TaskInstance, FlowEvent
)

logger = logging.getLogger(__name__)


def current_template_task_keys(assessment_level: int, phase_id: str) -> set[tuple[str, str]]:
    from app.services.assessment_templates import LEVEL_2_TEMPLATE, LEVEL_3_TEMPLATE

    template_config = LEVEL_2_TEMPLATE if assessment_level == 2 else LEVEL_3_TEMPLATE
    phase_config = next((phase for phase in template_config["phases_config"] if phase["id"] == phase_id), None)
    if not phase_config:
        return set()
    return {(task["type"], task["name"]) for task in phase_config.get("default_tasks", [])}


class StateMachine:
    """流程状态机 - 管理状态转换"""
    
    # 测评状态转换
    ASSESSMENT_TRANSITIONS = {
        "not_started": ["in_progress"],
        "in_progress": ["paused", "completed", "failed"],
        "paused": ["in_progress"],
        "completed": ["not_started"],  # 允许重置
        "failed": ["in_progress"],  # 可重试
    }
    
    # 阶段状态转换
    PHASE_TRANSITIONS = {
        "pending": ["active", "skipped"],
        "active": ["completed", "failed"],
        "completed": ["pending"],  # 允许重置
        "skipped": ["pending"],
        "failed": ["active"],  # 可重试
    }
    
    # 任务状态转换
    TASK_TRANSITIONS = {
        "todo": ["in_progress", "cancelled"],
        "in_progress": ["completed", "failed"],
        "completed": ["todo"],  # 允许重置
        "failed": ["in_progress"],  # 可重试
        "cancelled": ["todo"],
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

    async def upsert_default_templates(self) -> List[FlowTemplate]:
        """创建或更新默认 5 阶段等保自查模板。"""
        from app.services.assessment_templates import LEVEL_2_TEMPLATE, LEVEL_3_TEMPLATE

        templates = []
        for config in (LEVEL_2_TEMPLATE, LEVEL_3_TEMPLATE):
            result = await self.db.execute(
                select(FlowTemplate).where(FlowTemplate.compliance_level == config["compliance_level"])
            )
            template = result.scalars().first()
            if not template:
                template = FlowTemplate(compliance_level=config["compliance_level"])
                self.db.add(template)
            template.name = config["name"]
            template.description = "被测企业 5 阶段等保自查流程"
            template.version = "2.0"
            template.phases_config = config["phases_config"]
            template.is_active = True
            templates.append(template)
        await self.db.commit()
        return templates
    
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
        assessment = result.scalar_one_or_none()
        if assessment:
            await self.ensure_five_stage_assessment(assessment)
        return assessment
    
    async def list_assessments(self, project_id: int = None) -> List[Assessment]:
        """列出测评实例"""
        query = select(Assessment)
        if project_id:
            query = query.where(Assessment.project_id == project_id)
        result = await self.db.execute(query.order_by(Assessment.created_at.desc()))
        assessments = result.scalars().all()
        for assessment in assessments:
            await self.ensure_five_stage_assessment(assessment)
        return assessments

    async def ensure_five_stage_assessment(self, assessment: Assessment) -> Assessment:
        """将旧等保阶段兼容迁移为 5 阶段，保留任务和任务结果。"""
        from app.services.assessment_templates import LEVEL_2_TEMPLATE, LEVEL_3_TEMPLATE, FIVE_STAGE_PHASE_IDS

        phases = await self.get_phases(assessment.id)
        if len(phases) == 5 and [p.phase_id for p in phases] == FIVE_STAGE_PHASE_IDS:
            await self._ensure_template_tasks(assessment)
            return assessment

        template_config = LEVEL_2_TEMPLATE if assessment.assessment_level == 2 else LEVEL_3_TEMPLATE
        configs = template_config["phases_config"]
        by_id = {p.phase_id: p for p in phases}
        by_name = {p.name: p for p in phases}
        target_phases = {}

        for config in configs:
            phase = by_id.get(config["id"]) or by_name.get(config["name"])
            if not phase:
                phase = PhaseInstance(
                    assessment_id=assessment.id,
                    phase_id=config["id"],
                    name=config["name"],
                    description=config.get("description", ""),
                    order=config["order"],
                    depends_on=config.get("depends_on", []),
                    status="pending",
                )
                self.db.add(phase)
                await self.db.flush()
                for task_config in config.get("default_tasks", []):
                    self.db.add(TaskInstance(
                        phase_id=phase.id,
                        task_type=task_config["type"],
                        name=task_config["name"],
                        description=task_config.get("description", ""),
                    ))
            phase.phase_id = config["id"]
            phase.name = config["name"]
            phase.description = config.get("description", "")
            phase.order = config["order"]
            phase.depends_on = config.get("depends_on", [])
            target_phases[config["id"]] = phase

        def target_id_for(old_phase: PhaseInstance) -> str:
            text = f"{old_phase.phase_id} {old_phase.name}"
            if any(key in text for key in ("系统定级", "备案", "差距", "phase_1", "phase_2", "phase_3")):
                return "gap_analysis"
            if any(key in text for key in ("现场", "phase_4")):
                return "field_assessment"
            if any(key in text for key in ("整改", "phase_5")):
                return "remediation"
            if any(key in text for key in ("复测", "phase_6")):
                return "retest"
            if any(key in text for key in ("报告", "phase_7")):
                return "report"
            return "gap_analysis"

        target_ids = {phase.id for phase in target_phases.values()}
        for phase in phases:
            if phase.id in target_ids:
                continue
            target = target_phases[target_id_for(phase)]
            tasks = await self.get_tasks(phase.id)
            for task in tasks:
                task.phase_id = target.id
            if target.status in ("pending", "active") and phase.status in ("active", "completed", "skipped", "failed"):
                target.status = phase.status
                target.started_at = target.started_at or phase.started_at
                target.completed_at = target.completed_at or phase.completed_at
            await self.db.delete(phase)

        await self.db.flush()
        for phase in target_phases.values():
            tasks = await self.get_tasks(phase.id)
            official_keys = current_template_task_keys(assessment.assessment_level, phase.phase_id)
            official_tasks = [task for task in tasks if (task.task_type, task.name) in official_keys]
            phase.total_tasks = len(official_tasks)
            phase.completed_tasks = sum(1 for t in official_tasks if t.status in ("completed", "cancelled"))
            phase.progress = (phase.completed_tasks / phase.total_tasks * 100) if phase.total_tasks else 0

        assessment.total_phases = 5
        assessment.completed_phases = sum(1 for p in target_phases.values() if p.status in ("completed", "skipped"))
        assessment.progress = (assessment.completed_phases / 5) * 100
        assessment.name = assessment.name or template_config["name"]
        await self.db.commit()
        await self._ensure_template_tasks(assessment)
        return assessment

    async def _ensure_template_tasks(self, assessment: Assessment):
        """补齐当前 5 阶段模板新增的任务，保留历史任务和结果。"""
        from app.services.assessment_templates import LEVEL_2_TEMPLATE, LEVEL_3_TEMPLATE

        template_config = LEVEL_2_TEMPLATE if assessment.assessment_level == 2 else LEVEL_3_TEMPLATE
        configs = {phase["id"]: phase for phase in template_config["phases_config"]}
        phases = await self.get_phases(assessment.id)
        changed = False

        for phase in phases:
            config = configs.get(phase.phase_id)
            if not config:
                continue
            tasks = await self.get_tasks(phase.id)
            existing = {(task.task_type, task.name) for task in tasks}
            for task_config in config.get("default_tasks", []):
                key = (task_config["type"], task_config["name"])
                if key in existing:
                    continue
                self.db.add(TaskInstance(
                    phase_id=phase.id,
                    task_type=task_config["type"],
                    name=task_config["name"],
                    description=task_config.get("description", ""),
                ))
                changed = True

        if changed:
            await self.db.flush()

        for phase in phases:
            tasks = await self.get_tasks(phase.id)
            official_keys = current_template_task_keys(assessment.assessment_level, phase.phase_id)
            official_tasks = [task for task in tasks if (task.task_type, task.name) in official_keys]
            phase.total_tasks = len(official_tasks)
            phase.completed_tasks = sum(1 for t in official_tasks if t.status in ("completed", "cancelled"))
            phase.progress = (phase.completed_tasks / phase.total_tasks * 100) if phase.total_tasks else 0
            if phase.total_tasks and phase.completed_tasks == phase.total_tasks and phase.status in ("pending", "active"):
                phase.status = "completed"
                phase.completed_at = phase.completed_at or datetime.utcnow()

        active_exists = any(phase.status == "active" for phase in phases)
        can_advance = any(phase.status in ("completed", "skipped") for phase in phases)
        if can_advance and not active_exists:
            for phase in sorted(phases, key=lambda item: item.order):
                if phase.status == "pending" and await self._check_dependencies(phase):
                    phase.status = "active"
                    phase.started_at = phase.started_at or datetime.utcnow()
                    break

        assessment.completed_phases = sum(1 for phase in phases if phase.status in ("completed", "skipped"))
        assessment.progress = (assessment.completed_phases / assessment.total_phases * 100) if assessment.total_phases else 0
        if assessment.progress > 0 and assessment.status == "not_started":
            assessment.status = "in_progress"
            assessment.started_at = assessment.started_at or datetime.utcnow()
        await self.db.commit()
    
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
        
        # 检查是否所有任务都已完成/跳过
        tasks = await self.get_tasks(phase.id, official_only=True)
        unfinished_tasks = [t for t in tasks if t.status not in ["completed", "cancelled"]]
        
        if unfinished_tasks:
            # 有未完成的任务，自动将它们标记为 cancelled
            for task in unfinished_tasks:
                task.status = "cancelled"
                task.completed_at = datetime.utcnow()
                if not task.result:
                    task.result = {}
                task.result["skip_reason"] = "阶段完成时自动跳过"
            
            # 重新计算阶段进度
            phase.completed_tasks = len(tasks)
            phase.progress = 100.0
        
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

    async def jump_to_phase(self, phase_id: int, reason: str = "") -> PhaseInstance:
        """
        跳到指定阶段：
        1. 跳过当前 active 阶段（如果有）
        2. 跳过所有中间阶段（order < target 且 pending/active）
        3. 激活目标阶段
        """
        target_phase = await self.get_phase(phase_id)
        if not target_phase:
            raise ValueError(f"Phase {phase_id} not found")

        if target_phase.status not in ["pending", "active"]:
            raise ValueError(f"Cannot jump to phase with status {target_phase.status}")

        assessment_id = target_phase.assessment_id
        phases = await self.get_phases(assessment_id)

        # 1. 跳过当前 active 阶段
        current_active = [p for p in phases if p.status == "active"]
        for p in current_active:
            if p.id != target_phase.id:
                try:
                    p.status = "skipped"
                    p.completed_at = datetime.utcnow()
                    p.outputs = {"skip_reason": reason or "跳到其他阶段"}
                except Exception:
                    pass

        # 2. 跳过所有中间阶段（order < target 且还没完成）
        for p in phases:
            if p.id == target_phase.id:
                continue
            if p.status in ["pending", "active"] and p.order < target_phase.order:
                try:
                    p.status = "skipped"
                    p.completed_at = datetime.utcnow()
                    p.outputs = {"skip_reason": reason or "跳过中间阶段"}
                except Exception:
                    pass

        # 3. 如果目标 phase 是 pending，激活它
        if target_phase.status == "pending":
            target_phase.status = "active"
            target_phase.started_at = datetime.utcnow()
        elif target_phase.status == "active":
            # 已经是 active，只需确保 started_at 有值
            if not target_phase.started_at:
                target_phase.started_at = datetime.utcnow()

        await self.db.commit()

        # 4. 更新测评进度
        await self._update_assessment_progress(assessment_id)

        # 5. 更新测评状态
        assessment = await self.get_assessment(assessment_id)
        if assessment.status == "not_started":
            assessment.status = "in_progress"
            assessment.started_at = datetime.utcnow()
            await self.db.commit()

        await self.emit_event(assessment_id, "phase_jumped", {
            "phase_id": phase_id,
            "reason": reason,
            "skipped_phases": [p.id for p in phases if p.status == "skipped"],
        })

        logger.info(f"Jumped to phase {phase_id}, reason: {reason}")
        return target_phase
    
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
            
            # 同步 ProjectAssessment 并计算合规分数
            await self._sync_project_assessment(assessment)
        elif assessment.status == "completed":
            assessment.status = "in_progress"
            assessment.completed_at = None
        
        await self.db.commit()
    
    async def _sync_project_assessment(self, assessment):
        """同步 ProjectAssessment 状态和分数"""
        from app.models.assessment_type import ProjectAssessment, AssessmentType
        from app.models.project import Project
        from sqlalchemy import select
        
        # 获取项目
        result = await self.db.execute(
            select(Project).where(Project.id == assessment.project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            return
        
        # 获取或创建 AssessmentType
        result = await self.db.execute(
            select(AssessmentType).where(AssessmentType.code == "dengbao")
        )
        assessment_type = result.scalar_one_or_none()
        if not assessment_type:
            assessment_type = AssessmentType(
                code="dengbao",
                name="等级保护测评",
                description="网络安全等级保护测评",
                icon="safety-certificate",
            )
            self.db.add(assessment_type)
            await self.db.flush()
        
        # 获取或创建 ProjectAssessment
        result = await self.db.execute(
            select(ProjectAssessment).where(
                ProjectAssessment.project_id == assessment.project_id,
                ProjectAssessment.assessment_type_id == assessment_type.id,
            )
        )
        pa = result.scalar_one_or_none()
        if not pa:
            pa = ProjectAssessment(
                project_id=assessment.project_id,
                assessment_type_id=assessment_type.id,
            )
            self.db.add(pa)
        
        # 更新状态
        pa.status = assessment.status
        pa.progress = assessment.progress
        pa.level = f"{project.compliance_level.value if project.compliance_level else ''}等保"
        pa.started_at = assessment.started_at
        pa.completed_at = assessment.completed_at
        
        # 计算合规分数
        score = await self._calculate_compliance_score(assessment)
        pa.score = score
        project.compliance_score = score
    
    async def _calculate_compliance_score(self, assessment) -> float:
        """计算合规分数（0-100）"""
        phases = await self.get_phases(assessment.id)
        
        total_tasks = 0
        completed_tasks = 0
        failed_tasks = 0
        
        for phase in phases:
            tasks = await self.get_tasks(phase.id, official_only=True)
            for task in tasks:
                total_tasks += 1
                if task.status == "completed":
                    completed_tasks += 1
                elif task.status == "failed":
                    failed_tasks += 1
                # cancelled (skipped) tasks count as 0
        
        if total_tasks == 0:
            return 0.0
        
        # 基础分 = 完成率 * 80
        completion_rate = completed_tasks / total_tasks
        base_score = completion_rate * 80
        
        # 失败惩罚 = 失败率 * 20
        fail_rate = failed_tasks / total_tasks
        penalty = fail_rate * 20
        
        score = max(0, base_score - penalty)
        return round(score, 1)
    
    # ========== 任务管理 ==========
    
    async def get_tasks(self, phase_id: int, official_only: bool = False) -> List[TaskInstance]:
        """获取阶段任务。official_only 只返回当前 5 阶段模板任务。"""
        result = await self.db.execute(
            select(TaskInstance)
            .where(TaskInstance.phase_id == phase_id)
            .order_by(TaskInstance.priority.desc(), TaskInstance.created_at)
        )
        tasks = result.scalars().all()
        if not official_only:
            return tasks

        phase = await self.get_phase(phase_id)
        if not phase:
            return []
        result = await self.db.execute(select(Assessment).where(Assessment.id == phase.assessment_id))
        assessment = result.scalar_one_or_none()
        if not assessment:
            return tasks
        official_keys = current_template_task_keys(assessment.assessment_level, phase.phase_id)
        return [task for task in tasks if (task.task_type, task.name) in official_keys] if official_keys else tasks
    
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

        already_completed = task.status == "completed"
        if not already_completed and not StateMachine.can_transition(task.status, "completed", "task"):
            raise ValueError(f"Cannot transition from {task.status} to completed")

        task.status = "completed"
        task.completed_at = datetime.utcnow()
        if result:
            task.result = result

        # 重新计算阶段进度（基于 completed + cancelled）
        phase = await self.get_phase(task.phase_id)
        all_tasks = await self.get_tasks(phase.id, official_only=True)
        total = len(all_tasks)
        finished = sum(1 for t in all_tasks if t.status in ["completed", "cancelled"])
        phase.completed_tasks = finished
        phase.progress = (finished / total * 100) if total > 0 else 0

        # 如果阶段是 pending（前面的阶段没完成），先激活它
        if phase.status == "pending":
            phase.status = "active"
            if not phase.started_at:
                phase.started_at = datetime.utcnow()

        # 如果阶段下所有任务都已完成，自动完成该阶段
        if total > 0 and finished == total:
            phase.status = "completed"
            phase.completed_at = datetime.utcnow()
            if not phase.started_at:
                phase.started_at = datetime.utcnow()

        await self.db.commit()

        # 如果阶段刚完成，激活下一个阶段并更新测评进度
        if phase.status == "completed":
            await self._activate_next_phase(phase.assessment_id)
        await self._update_assessment_progress(phase.assessment_id)

        await self.emit_event(phase.assessment_id, "task_completed", {"task_id": task_id})

        logger.info(f"Completed task {task_id}")
        return task

    async def upload_task_document(
        self,
        task_id: int,
        file_path: str,
        file_name: str,
        file_size: int,
        mime_type: str,
        project_id: int,
        document_level: str = None,
        validation_result: dict = None,
        analysis_result: dict = None,
    ) -> dict:
        """
        上传任务文档（定级报告等）

        Args:
            task_id: 任务ID
            file_path: 文件存储路径
            file_name: 文件名
            file_size: 文件大小
            mime_type: MIME类型
            project_id: 项目ID
            document_level: 文档中识别的定级
            validation_result: 定级验证结果
            analysis_result: 文档标准项检查结果

        Returns:
            包含验证结果的字典
        """
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        already_completed = task.status == "completed"
        if task.status not in ("todo", "in_progress", "completed"):
            raise ValueError(f"Cannot transition from {task.status} to completed")

        # 严格验证：如果是系统定级任务，验证文档等级与项目等级
        if task.task_type == "doc_review" and "定级" in task.name:
            if validation_result and not validation_result.get("match", False):
                # 验证失败，标记任务为失败
                task.status = "failed"
                task.completed_at = datetime.utcnow()
                task.result = {
                    "type": "doc_review",
                    "file_name": file_name,
                    "file_path": file_path,
                    "validation": validation_result,
                    "error": validation_result.get("error", "定级验证失败"),
                }
                await self.db.commit()
                await self.emit_event(
                    task.phase_id and (await self.get_phase(task.phase_id)).assessment_id or 0,
                    "task_failed",
                    {"task_id": task_id, "reason": "定级验证失败"},
                )
                return {
                    "status": "failed",
                    "task_id": task_id,
                    "message": validation_result.get("error", "定级验证失败"),
                    "validation": validation_result,
                }

        # 验证通过或非定级任务，标记为完成
        task.status = "completed"
        task.completed_at = task.completed_at if already_completed else datetime.utcnow()
        task.result = {
            "type": "doc_review",
            "file_name": file_name,
            "file_path": file_path,
            "file_size": file_size,
            "mime_type": mime_type,
            "validation": validation_result,
            "analysis": analysis_result,
        }

        phase = await self.get_phase(task.phase_id)
        all_tasks = await self.get_tasks(phase.id, official_only=True)
        finished = sum(1 for t in all_tasks if t.status in ["completed", "cancelled"])
        phase.completed_tasks = finished
        phase.progress = (finished / phase.total_tasks * 100) if phase.total_tasks > 0 else 0

        await self.db.commit()

        await self.emit_event(phase.assessment_id, "task_completed", {"task_id": task_id})

        logger.info(f"Task {task_id} document uploaded and completed")
        return {
            "status": "completed",
            "task_id": task_id,
            "message": "文档上传成功，任务已完成",
            "validation": validation_result,
            "analysis": analysis_result,
        }

    async def skip_task(self, task_id: int, reason: str = "") -> TaskInstance:
        """
        跳过任务

        Args:
            task_id: 任务ID
            reason: 跳过原因（选填）
        """
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # 任务可以从 todo 或 in_progress 跳到 cancelled
        if task.status not in ("todo", "in_progress"):
            raise ValueError(f"Cannot skip task with status {task.status}")

        task.status = "cancelled"
        task.completed_at = datetime.utcnow()
        if reason:
            existing = task.result or {}
            existing["skip_reason"] = reason
            task.result = existing

        # 重新计算阶段进度（基于 completed + cancelled）
        phase = await self.get_phase(task.phase_id)
        all_tasks = await self.get_tasks(phase.id, official_only=True)
        total = len(all_tasks)
        finished = sum(1 for t in all_tasks if t.status in ["completed", "cancelled"])
        phase.completed_tasks = finished
        phase.progress = (finished / total * 100) if total > 0 else 0

        # 如果阶段是 pending（前面的阶段没完成），先激活它
        if phase.status == "pending":
            phase.status = "active"
            if not phase.started_at:
                phase.started_at = datetime.utcnow()

        # 如果阶段下所有任务都已完成或跳过，自动完成该阶段
        if total > 0 and finished == total:
            # 检查是否有任何任务真正完成（不是跳过）
            has_completed = any(t.status == "completed" for t in all_tasks)
            # 如果有任何任务完成，phase 状态为 completed；否则为 skipped
            phase.status = "completed" if has_completed else "skipped"
            phase.completed_at = datetime.utcnow()
            if not phase.started_at:
                phase.started_at = datetime.utcnow()

        await self.db.commit()

        # 如果阶段刚完成/跳过，激活下一个阶段并更新测评进度
        if phase.status in ["completed", "skipped"]:
            await self._activate_next_phase(phase.assessment_id)
        await self._update_assessment_progress(phase.assessment_id)

        await self.emit_event(phase.assessment_id, "task_skipped", {"task_id": task_id, "reason": reason})

        logger.info(f"Task {task_id} skipped with reason: {reason}")
        return task

    async def stop_task(self, task_id: int, reason: str = "") -> TaskInstance:
        """
        停止任务（将 in_progress 状态的任务标记为 failed）

        Args:
            task_id: 任务ID
            reason: 停止原因（选填）
        """
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # 任务只能从 in_progress 状态停止
        if task.status != "in_progress":
            raise ValueError(f"Cannot stop task with status {task.status}")

        task.status = "failed"
        task.completed_at = datetime.utcnow()
        if reason:
            existing = task.result or {}
            existing["stop_reason"] = reason
            task.result = existing

        await self.db.commit()

        phase = await self.get_phase(task.phase_id)
        await self.emit_event(phase.assessment_id, "task_stopped", {"task_id": task_id, "reason": reason})

        logger.info(f"Task {task_id} stopped with reason: {reason}")
        return task

    async def reset_task(self, task_id: int) -> TaskInstance:
        """
        重置任务（清空执行结果并回到 todo）

        Args:
            task_id: 任务ID
        """
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if task.status == "in_progress":
            raise ValueError(f"Cannot reset task with status {task.status}")

        task.status = "todo"
        task.started_at = None
        task.completed_at = None
        task.result = None

        phase = await self.get_phase(task.phase_id)
        if task.task_type == "doc_review":
            from app.models.evidence import Evidence
            from app.models.finding import Finding
            from app.models.remediation import RemediationTicket
            from app.services.file_storage import file_storage
            assessment = await self.get_assessment(phase.assessment_id)
            evidences = (await self.db.execute(
                select(Evidence).where(
                    Evidence.project_id == assessment.project_id,
                    Evidence.clause_id == f"DOC-TASK-{task.id}",
                )
            )).scalars().all()
            for evidence in evidences:
                if evidence.file_path:
                    await file_storage.delete_file(evidence.file_path)
                await self.db.delete(evidence)
            finding_ids = select(Finding.id).where(
                Finding.project_id == assessment.project_id,
                Finding.clause_id.like(f"DOC-TASK-{task.id}-%"),
            )
            await self.db.execute(delete(RemediationTicket).where(RemediationTicket.finding_id.in_(finding_ids)))
            await self.db.execute(delete(Finding).where(Finding.id.in_(finding_ids)))
        tasks = await self.get_tasks(task.phase_id, official_only=True)
        phase.completed_tasks = sum(1 for item in tasks if item.id != task.id and item.status in ("completed", "cancelled"))
        phase.progress = (phase.completed_tasks / phase.total_tasks * 100) if phase.total_tasks > 0 else 0
        if phase.status in ("completed", "skipped"):
            phase.status = "pending"
            phase.completed_at = None

        await self.db.commit()

        await self.emit_event(phase.assessment_id, "task_reset", {"task_id": task_id})
        await self._update_assessment_progress(phase.assessment_id)

        logger.info(f"Task {task_id} reset to todo")
        return task

    async def restart_phase(self, phase_id: int, mode: str = "reset") -> PhaseInstance:
        """
        重新打开或重置阶段。
        """
        phase = await self.get_phase(phase_id)
        if not phase:
            raise ValueError(f"Phase {phase_id} not found")

        if mode == "continue":
            phase.status = "active"
            phase.completed_at = None
            if not phase.started_at:
                phase.started_at = datetime.utcnow()
            await self.db.commit()
            await self.emit_event(phase.assessment_id, "phase_reopened", {"phase_id": phase_id})
            await self._update_assessment_progress(phase.assessment_id)
            logger.info(f"Phase {phase_id} reopened without clearing evidence")
            return phase

        if phase.status not in ("pending", "active", "completed", "skipped", "failed"):
            raise ValueError(f"Cannot reset phase with status {phase.status}")

        phase.status = "pending"
        phase.completed_tasks = 0
        phase.progress = 0
        phase.started_at = None
        phase.completed_at = None
        phase.outputs = None

        tasks = await self.get_tasks(phase_id, official_only=True)
        for task in tasks:
            task.status = "todo"
            task.started_at = None
            task.completed_at = None
            task.result = None
            task.evidence_ids = None

        document_task_ids = [task.id for task in tasks if task.task_type == "doc_review"]
        if document_task_ids:
            from app.models.evidence import Evidence
            from app.models.finding import Finding
            from app.models.remediation import RemediationTicket
            from app.services.file_storage import file_storage
            assessment = await self.get_assessment(phase.assessment_id)
            clause_ids = [f"DOC-TASK-{task_id}" for task_id in document_task_ids]
            evidences = (await self.db.execute(
                select(Evidence).where(
                    Evidence.project_id == assessment.project_id,
                    Evidence.clause_id.in_(clause_ids),
                )
            )).scalars().all()
            for evidence in evidences:
                if evidence.file_path:
                    await file_storage.delete_file(evidence.file_path)
                await self.db.delete(evidence)
            finding_ids = select(Finding.id).where(
                Finding.project_id == assessment.project_id,
                or_(*[Finding.clause_id.like(f"DOC-TASK-{task_id}-%") for task_id in document_task_ids]),
            )
            await self.db.execute(delete(RemediationTicket).where(RemediationTicket.finding_id.in_(finding_ids)))
            await self.db.execute(delete(Finding).where(Finding.id.in_(finding_ids)))

        await self.db.commit()

        await self.emit_event(phase.assessment_id, "phase_reset", {"phase_id": phase_id})
        await self._update_assessment_progress(phase.assessment_id)

        logger.info(f"Phase {phase_id} reset to pending")
        return phase

    async def _clear_project_assessment_outputs(self, project_id: int) -> None:
        """清理一次测评产生的项目级结论，保留资产、扫描历史和流程模板。"""
        from app.models.assessment_type import ProjectAssessment
        from app.models.evidence import Evidence
        from app.models.finding import Finding
        from app.models.questionnaire import QuestionnaireRecord
        from app.models.remediation import RemediationTicket
        from app.services.file_storage import file_storage

        finding_ids = select(Finding.id).where(Finding.project_id == project_id)
        questionnaire_ids = select(QuestionnaireRecord.id).where(QuestionnaireRecord.project_id == project_id)
        evidence_paths = (await self.db.execute(
            select(Evidence.file_path).where(Evidence.project_id == project_id, Evidence.file_path.is_not(None))
        )).scalars().all()

        await self.db.execute(delete(RemediationTicket).where(RemediationTicket.project_id == project_id))
        await self.db.execute(delete(Evidence).where(Evidence.project_id == project_id))
        await self.db.execute(delete(Evidence).where(Evidence.finding_id.in_(finding_ids)))
        await self.db.execute(delete(Evidence).where(Evidence.questionnaire_record_id.in_(questionnaire_ids)))
        await self.db.execute(delete(QuestionnaireRecord).where(QuestionnaireRecord.project_id == project_id))
        await self.db.execute(delete(Finding).where(Finding.project_id == project_id))
        await self.db.execute(delete(ProjectAssessment).where(ProjectAssessment.project_id == project_id))
        for file_path in evidence_paths:
            await file_storage.delete_file(file_path)

    async def restart_assessment(self, assessment_id: int, mode: str = "reset") -> Assessment:
        """
        重新打开或重置整个测评。
        """
        assessment = await self.get_assessment(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")

        if mode == "continue":
            assessment.status = "in_progress"
            assessment.completed_at = None
            if not assessment.started_at:
                assessment.started_at = datetime.utcnow()
            await self.db.commit()
            await self.emit_event(assessment_id, "assessment_reopened", {"assessment_id": assessment_id})
            logger.info(f"Assessment {assessment_id} reopened without clearing evidence")
            return assessment

        phases = await self.get_phases(assessment_id)
        for phase in phases:
            phase.status = "pending"
            phase.completed_tasks = 0
            phase.progress = 0
            phase.started_at = None
            phase.completed_at = None
            phase.outputs = None

            tasks = await self.get_tasks(phase.id, official_only=True)
            for task in tasks:
                task.status = "todo"
                task.started_at = None
                task.completed_at = None
                task.result = None
                task.evidence_ids = None

        assessment.status = "not_started"
        assessment.progress = 0
        assessment.completed_phases = 0
        assessment.started_at = None
        assessment.completed_at = None
        assessment.extra_data = None

        await self._clear_project_assessment_outputs(assessment.project_id)

        await self.db.commit()

        await self.emit_event(assessment_id, "assessment_reset", {"assessment_id": assessment_id})

        logger.info(f"Assessment {assessment_id} reset to not_started")
        return assessment

    async def validate_classification_document(
        self,
        project_id: int,
        document_content: str,
    ) -> dict:
        """
        严格验证定级报告与项目等级是否一致

        Args:
            project_id: 项目ID
            document_content: 文档内容（已提取的文本）

        Returns:
            验证结果字典
        """
        from app.models.project import Project

        # 获取项目等级
        result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            return {
                "match": False,
                "error": "项目不存在",
            }

        project_level = project.compliance_level  # "二级" or "三级"

        # 从文档中提取定级信息
        document_level = self._extract_classification_level(document_content)

        if not document_level:
            return {
                "match": False,
                "project_level": project_level,
                "document_level": None,
                "error": "未能从文档中识别出定级信息，请确认文档包含明确的等保定级（如'等保二级'或'等保三级'）",
            }

        if document_level != project_level:
            return {
                "match": False,
                "project_level": project_level,
                "document_level": document_level,
                "error": f"文档中定级为 {document_level}，与项目等级 {project_level} 不一致。请重新上传正确的定级报告。",
            }

        return {
            "match": True,
            "project_level": project_level,
            "document_level": document_level,
            "message": f"定级验证通过：项目等级 {project_level} 与文档定级一致",
        }

    def _extract_classification_level(self, content: str) -> Optional[str]:
        """
        从文档内容中提取定级信息

        支持的格式：
        - 等保二级 / 等保三级
        - 二级 / 三级
        - 等保 2 级 / 等保 3 级
        """
        if not content:
            return None

        # 优先级匹配
        patterns = [
            (r'等保\s*[三3]\s*级', '三级'),
            (r'等保\s*[二2]\s*级', '二级'),
            (r'定级\s*[三3]\s*级', '三级'),
            (r'定级\s*[二2]\s*级', '二级'),
            (r'等级\s*[三3]\s*级', '三级'),
            (r'等级\s*[二2]\s*级', '二级'),
            (r'(?<![一二三四五六七八九\d])[三3]\s*级(?![一二三四五六七八九\d])', '三级'),
            (r'(?<![一二三四五六七八九\d])[二2]\s*级(?![一二三四五六七八九\d])', '二级'),
        ]

        for pattern, level in patterns:
            if re.search(pattern, content):
                return level

        return None

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
