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
from sqlalchemy import select, update, delete, or_, func

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


def workflow_progress(phases: List[PhaseInstance]) -> float:
    if not phases:
        return 0.0
    values = [100.0 if phase.status == "completed" else float(phase.progress or 0) for phase in phases]
    return sum(max(0.0, min(100.0, value)) for value in values) / len(values)


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
        "pending": ["active"],
        "active": ["completed", "failed"],
        "completed": ["pending"],  # 允许重置
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
        """创建或更新默认四阶段等保企业自查模板。"""
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
            template.description = "被测企业四阶段等保自查流程"
            template.version = "3.0"
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

        prior_phases = [
            item for item in await self.get_phases(phase.assessment_id)
            if item.order < phase.order and item.status != "completed"
        ]
        if prior_phases:
            names = "、".join(item.name for item in prior_phases)
            raise ValueError(f"请先完成前置阶段：{names}")
        
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

        if phase.phase_id == "remediation_verification":
            assessment = await self.get_assessment(phase.assessment_id)
            from app.services.verification_service import reconcile_verification_phase
            from app.models.finding import Finding, FindingStatus
            from app.models.verification import VerificationRun, VerificationRunStatus

            prior_phases = [
                item for item in await self.get_phases(phase.assessment_id)
                if item.order < phase.order and item.status != "completed"
            ]
            if prior_phases:
                names = "、".join(item.name for item in prior_phases)
                raise ValueError(f"请先完成前置阶段：{names}")

            await reconcile_verification_phase(self.db, assessment.project_id)
            await self.db.commit()
            await self.db.refresh(phase)
            if phase.status not in {"active", "completed"}:
                raise ValueError("请先完成现场测评，再进入整改与复测")
            active_run = (await self.db.execute(select(VerificationRun.id).where(
                VerificationRun.project_id == assessment.project_id,
                VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
            ).limit(1))).scalar_one_or_none()
            if active_run:
                raise ValueError("仍有重新检查任务正在执行，请等待完成或停止后再生成报告")

            findings = list((await self.db.execute(select(Finding).where(
                Finding.project_id == assessment.project_id,
                Finding.status != FindingStatus.FALSE_POSITIVE,
            ))).scalars().all())
            now = datetime.utcnow()
            review_progress = round(float(phase.progress or 0), 1)
            phase.status = "completed"
            phase.started_at = phase.started_at or now
            phase.completed_at = now
            phase.progress = 100.0
            phase.outputs = {
                **(outputs or {}),
                "continued_to_report": True,
                "finalized_at": now.isoformat(),
                "review_progress": review_progress,
                "finding_summary": {
                    "total": len(findings),
                    "open": sum(finding.status == FindingStatus.OPEN for finding in findings),
                    "fixed": sum(finding.status == FindingStatus.FIXED for finding in findings),
                },
            }
            await self.db.commit()
            await self._activate_next_phase(phase.assessment_id)
            await self._update_assessment_progress(phase.assessment_id)
            await self.emit_event(phase.assessment_id, "phase_completed", {
                "phase_id": phase_id,
                "continued_to_report": True,
            })
            return phase
        
        if not StateMachine.can_transition(phase.status, "completed", "phase"):
            raise ValueError(f"Cannot transition from {phase.status} to completed")
        
        # 检查是否所有任务都已完成/跳过
        tasks = await self.get_tasks(phase.id, official_only=True)
        unfinished_tasks = [t for t in tasks if t.status not in ["completed", "failed", "cancelled"]]
        
        if unfinished_tasks:
            raise ValueError(f"阶段仍有 {len(unfinished_tasks)} 个检查未执行，不能直接完成")
        
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
        """正式四阶段流程不允许跳过阶段。"""
        phase = await self.get_phase(phase_id)
        if not phase:
            raise ValueError(f"Phase {phase_id} not found")

        raise ValueError("正式测评阶段不能跳过；请完成、重试或重置阶段内的检查")

    async def jump_to_phase(self, phase_id: int, reason: str = "") -> PhaseInstance:
        """正式四阶段流程不允许跨阶段执行。"""
        target_phase = await self.get_phase(phase_id)
        if not target_phase:
            raise ValueError(f"Phase {phase_id} not found")
        raise ValueError("正式测评必须按差距分析、现场测评、整改与复测、生成报告顺序执行")
    
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
        phases = await self.get_phases(phase.assessment_id)
        if any(item.order < phase.order and item.status != "completed" for item in phases):
            return False
        if not phase.depends_on:
            return True

        phase_map = {p.phase_id: p for p in phases}
        
        for dep_id in phase.depends_on:
            dep_phase = phase_map.get(dep_id)
            if not dep_phase or dep_phase.status != "completed":
                return False
        
        return True
    
    async def _update_assessment_progress(self, assessment_id: int):
        """更新测评进度"""
        assessment = await self.get_assessment(assessment_id)
        phases = await self.get_phases(assessment_id)
        
        completed = sum(1 for p in phases if p.status == "completed")
        assessment.completed_phases = completed
        assessment.progress = workflow_progress(phases)
        
        # 检查是否所有阶段完成
        if phases and all(p.status == "completed" for p in phases):
            assessment.status = "completed"
            assessment.completed_at = datetime.utcnow()
            await self.emit_event(assessment_id, "assessment_completed")
        elif assessment.status == "completed":
            assessment.status = "in_progress"
            assessment.completed_at = None

        # 阶段重跑期间清除过期分数，重新完成后立即计算最新分数。
        await self._sync_project_assessment(assessment)
        await self.db.commit()

    async def reconcile_all_assessment_progress(self) -> int:
        """Repair persisted phase/assessment progress from the authoritative task states."""
        assessments = (await self.db.execute(select(Assessment))).scalars().all()
        repaired = 0
        for assessment in assessments:
            phases = await self.get_phases(assessment.id)
            all_tasks = []
            for phase in phases:
                tasks = await self.get_tasks(phase.id, official_only=True)
                all_tasks.extend(tasks)
                total = len(tasks)
                if phase.phase_id == "remediation_verification":
                    continue
                completed = sum(task.status in {"completed", "failed", "cancelled"} for task in tasks)
                if phase.total_tasks != total or phase.completed_tasks != completed:
                    phase.total_tasks = total
                    phase.completed_tasks = completed
                    phase.progress = (completed / total * 100) if total else 0
                    repaired += 1
                if total and completed == total and phase.status != "completed":
                    phase.status = "completed"
                    repaired += 1
                elif total and completed < total and phase.status == "completed":
                    phase.status = "pending"
                    phase.completed_at = None
                    repaired += 1

            from app.services.verification_service import reconcile_verification_phase
            await reconcile_verification_phase(self.db, assessment.project_id)
            prior_completed = True
            for phase in phases:
                if not prior_completed and phase.status != "pending":
                    phase.status = "pending"
                    phase.completed_at = None
                    repaired += 1
                if phase.status != "completed":
                    prior_completed = False
            completed_phases = sum(phase.status == "completed" for phase in phases)
            progress = workflow_progress(phases)
            if assessment.completed_phases != completed_phases or assessment.progress != progress:
                assessment.completed_phases = completed_phases
                assessment.progress = progress
                repaired += 1
            if phases and completed_phases == len(phases):
                assessment.status = "completed"
            elif any(task.status != "todo" for task in all_tasks):
                assessment.status = "in_progress"
                assessment.completed_at = None
            else:
                assessment.status = "not_started"
                assessment.started_at = None
                assessment.completed_at = None
            await self._sync_project_assessment(assessment)
        await self.db.commit()
        return repaired
    
    async def _sync_project_assessment(self, assessment):
        """同步最新一次测评的 ProjectAssessment 状态和分数。"""
        from app.models.assessment_type import ProjectAssessment, AssessmentType
        from app.models.project import Project

        latest_assessment_id = await self.db.scalar(
            select(func.max(Assessment.id)).where(Assessment.project_id == assessment.project_id)
        )
        if assessment.id != latest_assessment_id:
            return
        
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
    
    async def _calculate_compliance_score(self, assessment) -> Optional[float]:
        return (await self._calculate_compliance_metrics(assessment))["score"]

    async def _calculate_compliance_metrics(self, assessment) -> Dict[str, Any]:
        """Score latest reliable controls; keep coverage and workflow completion separate."""
        from app.models.document_knowledge import DocumentControlResult
        from app.models.finding import Finding, FindingStatus, Judgment
        from app.services.task_executor import TASK_CAPABILITY_MAP

        phases = await self.get_phases(assessment.id)
        measured_phases = [phase for phase in phases if phase.phase_id in {"gap_analysis", "field_assessment"}]
        tasks = [task for phase in measured_phases for task in await self.get_tasks(phase.id, official_only=True)]
        if not tasks:
            return {"score": None, "coverage": 0.0, "reliable": 0, "unable": 0, "not_applicable": 0}
        score_ready = not any(task.status in {"todo", "in_progress"} for task in tasks)

        findings = list((await self.db.execute(select(Finding).where(
            Finding.project_id == assessment.project_id,
            Finding.status != FindingStatus.FALSE_POSITIVE,
        ))).scalars().all())
        document_findings = {
            (finding.scope_key, finding.source_key): finding
            for finding in findings
            if finding.source_type == "document"
        }

        control_rows = list((await self.db.execute(select(DocumentControlResult).where(
            DocumentControlResult.assessment_id == assessment.id,
        ).order_by(DocumentControlResult.created_at, DocumentControlResult.id))).scalars().all())
        latest_controls = {(row.task_id, row.control_uid): row for row in control_rows}

        points = 0.0
        reliable = 0
        unable = 0
        not_applicable = 0
        for control in latest_controls.values():
            verdict = (control.verdict or "").lower()
            if verdict in {"unable", "not_tested"}:
                unable += 1
                continue
            if verdict not in {"pass", "partial", "fail", "contradict"}:
                unable += 1
                continue
            reliable += 1
            finding = document_findings.get((f"task:{control.task_id}", control.control_uid))
            if finding and finding.status == FindingStatus.FIXED:
                points += 1.0
            elif finding and finding.status == FindingStatus.OPEN:
                points += 0.0
            else:
                points += {"pass": 1.0, "partial": 0.5}.get(verdict, 0.0)

        def scan_task_ids(value: Any) -> set[int]:
            ids: set[int] = set()
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"scan_task_id", "baseline_scan_task_id"}:
                        try:
                            ids.add(int(item))
                        except (TypeError, ValueError):
                            pass
                    else:
                        ids.update(scan_task_ids(item))
            elif isinstance(value, list):
                for item in value:
                    ids.update(scan_task_ids(item))
            return ids

        def is_not_applicable(value: Any) -> bool:
            if not isinstance(value, dict):
                return False
            if value.get("outcome") == "not_applicable":
                return True
            if str(value.get("skip_reason") or "").startswith("不适用："):
                return True
            asset_results = value.get("asset_results")
            return bool(asset_results) and all(is_not_applicable(item) for item in asset_results.values())

        control_task_ids = {row.task_id for row in latest_controls.values()}
        for task in (task for task in tasks if task.task_type == "doc_review"):
            if task.status in {"completed", "cancelled"} and is_not_applicable(task.result or {}):
                not_applicable += 1
            elif task.status in {"failed", "cancelled"} and task.id not in control_task_ids:
                unable += 1

        technical_findings = [finding for finding in findings if finding.source_type == "technical"]
        consumed_findings: set[int] = set()
        for task in (task for task in tasks if task.task_type != "doc_review"):
            mapping = TASK_CAPABILITY_MAP.get(task.task_type) or {}
            capabilities = set(mapping.get("capabilities") or [])
            ids = scan_task_ids(task.result or {})
            related = [
                finding for finding in technical_findings
                if finding.id not in consumed_findings and (
                    (finding.scan_task_id is not None and finding.scan_task_id in ids)
                    or (not ids and finding.source_key in capabilities)
                )
            ]
            if task.status in {"completed", "cancelled"} and is_not_applicable(task.result or {}):
                not_applicable += 1
                consumed_findings.update(finding.id for finding in related)
                continue
            if task.status in {"todo", "in_progress"}:
                continue
            if not related:
                if task.status in {"failed", "cancelled"}:
                    unable += 1
                    continue
                reliable += 1
                points += 1.0
                continue
            consumed_findings.update(finding.id for finding in related)
            for finding in related:
                if finding.judgment == Judgment.NOT_TESTED:
                    unable += 1
                    continue
                reliable += 1
                if finding.status == FindingStatus.FIXED:
                    points += 1.0

        for finding in technical_findings:
            if finding.id in consumed_findings:
                continue
            if finding.judgment == Judgment.NOT_TESTED:
                unable += 1
                continue
            reliable += 1
            if finding.status == FindingStatus.FIXED:
                points += 1.0

        coverage_denominator = reliable + unable
        score = round(points / coverage_denominator * 100, 1) if coverage_denominator and score_ready else None
        coverage = round(reliable / coverage_denominator * 100, 1) if coverage_denominator else 0.0
        return {
            "score": score,
            "coverage": coverage,
            "reliable": reliable,
            "unable": unable,
            "not_applicable": not_applicable,
        }
    
    # ========== 任务管理 ==========
    
    async def get_tasks(self, phase_id: int, official_only: bool = False) -> List[TaskInstance]:
        """获取阶段任务。official_only 只返回当前四阶段模板中的正式任务。"""
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

    async def reconcile_phase_progress(self, phase_id: int) -> PhaseInstance:
        """Recompute execution coverage; failed/unable checks are terminal but never pass."""
        phase = await self.get_phase(phase_id)
        if not phase:
            raise ValueError(f"Phase {phase_id} not found")
        if phase.phase_id == "remediation_verification":
            assessment = await self.get_assessment(phase.assessment_id)
            from app.services.verification_service import reconcile_verification_phase
            await reconcile_verification_phase(self.db, assessment.project_id)
            await self.db.commit()
            return phase

        tasks = await self.get_tasks(phase.id, official_only=True)
        terminal = sum(task.status in {"completed", "failed", "cancelled"} for task in tasks)
        dependencies_met = await self._check_dependencies(phase)
        phase.total_tasks = len(tasks)
        phase.completed_tasks = terminal
        phase.progress = terminal / len(tasks) * 100 if tasks else 0
        if tasks and terminal == len(tasks) and dependencies_met:
            phase.status = "completed"
            phase.started_at = phase.started_at or datetime.utcnow()
            phase.completed_at = phase.completed_at or datetime.utcnow()
        elif not dependencies_met:
            phase.status = "pending"
            phase.completed_at = None
        elif any(task.status != "todo" for task in tasks):
            phase.status = "active"
            phase.started_at = phase.started_at or datetime.utcnow()
            phase.completed_at = None
        await self.db.commit()
        if phase.status == "completed":
            await self._activate_next_phase(phase.assessment_id)
            assessment = await self.get_assessment(phase.assessment_id)
            if phase.phase_id == "field_assessment":
                from app.services.verification_service import reconcile_verification_phase
                await reconcile_verification_phase(self.db, assessment.project_id)
        await self._update_assessment_progress(phase.assessment_id)
        return phase
    
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

        phase = await self.get_phase(task.phase_id)
        if phase.status == "pending":
            if not await self._check_dependencies(phase):
                raise ValueError("前置阶段尚未完成，当前任务不能执行")
            phase.status = "active"
            phase.started_at = phase.started_at or datetime.utcnow()
        elif phase.status not in {"active", "completed"}:
            raise ValueError(f"当前阶段状态为 {phase.status}，任务不能执行")

        if not StateMachine.can_transition(task.status, "in_progress", "task"):
            raise ValueError(f"Cannot transition from {task.status} to in_progress")
        
        task.status = "in_progress"
        task.started_at = datetime.utcnow()
        task.cancel_requested_at = None
        task.completed_at = None
        await self.db.commit()
        
        await self.emit_event(phase.assessment_id, "task_started", {"task_id": task_id})
        
        return task
    
    async def complete_task(self, task_id: int, result: dict = None) -> TaskInstance:
        """完成任务"""
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        await self.db.refresh(task)
        if task.cancel_requested_at:
            raise ValueError("Task was stopped before completion")
        already_completed = task.status == "completed"
        if not already_completed and not StateMachine.can_transition(task.status, "completed", "task"):
            raise ValueError(f"Cannot transition from {task.status} to completed")

        if already_completed:
            if result:
                task.result = result
        else:
            values = {"status": "completed", "completed_at": datetime.utcnow()}
            if result:
                values["result"] = result
            completed = await self.db.execute(
                update(TaskInstance)
                .where(
                    TaskInstance.id == task_id,
                    TaskInstance.status == "in_progress",
                    TaskInstance.cancel_requested_at.is_(None),
                )
                .values(**values)
            )
            if completed.rowcount != 1:
                await self.db.rollback()
                raise ValueError("Task was stopped before completion")
            await self.db.refresh(task)

        # 重新计算阶段进度（基于 completed + cancelled）
        phase = await self.get_phase(task.phase_id)
        all_tasks = await self.get_tasks(phase.id, official_only=True)
        total = len(all_tasks)
        finished = sum(1 for t in all_tasks if t.status in ["completed", "failed", "cancelled"])
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
            if phase.phase_id == "field_assessment":
                assessment = await self.get_assessment(phase.assessment_id)
                from app.services.verification_service import reconcile_verification_phase
                await reconcile_verification_phase(self.db, assessment.project_id)
        await self._update_assessment_progress(phase.assessment_id)

        await self.emit_event(phase.assessment_id, "task_completed", {"task_id": task_id})

        logger.info(f"Completed task {task_id}")
        return task

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

        if not reason.strip().startswith("不适用："):
            raise ValueError("正式检查只能在系统判定为不适用时跳过")

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
        finished = sum(1 for t in all_tasks if t.status in ["completed", "failed", "cancelled"])
        phase.completed_tasks = finished
        phase.progress = (finished / total * 100) if total > 0 else 0

        # 如果阶段是 pending（前面的阶段没完成），先激活它
        if phase.status == "pending":
            phase.status = "active"
            if not phase.started_at:
                phase.started_at = datetime.utcnow()

        # 全部任务已执行或被系统判定为不适用时，阶段完成。
        if total > 0 and finished == total:
            phase.status = "completed"
            phase.completed_at = datetime.utcnow()
            if not phase.started_at:
                phase.started_at = datetime.utcnow()

        await self.db.commit()

        if phase.status == "completed":
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

        now = datetime.utcnow()
        existing = dict(task.result or {})
        execution = dict(existing.get("execution") or {})
        if execution:
            execution.update({"state": "cancelled", "cancelled_at": now.isoformat()})
            existing["execution"] = execution
        existing.update({"status": "cancelled", "stop_reason": reason or "用户已停止任务"})
        stopped = await self.db.execute(
            update(TaskInstance)
            .where(TaskInstance.id == task_id, TaskInstance.status == "in_progress")
            .values(
                status="failed",
                completed_at=now,
                cancel_requested_at=now,
                lease_owner=None,
                lease_expires_at=None,
                result=existing,
            )
        )
        if stopped.rowcount != 1:
            await self.db.rollback()
            raise ValueError("Task finished before it could be stopped")

        await self.db.commit()
        await self.db.refresh(task)

        phase = await self.get_phase(task.phase_id)
        await self.emit_event(phase.assessment_id, "task_stopped", {"task_id": task_id, "reason": reason})

        logger.info(f"Task {task_id} stopped with reason: {reason}")
        return task

    async def reset_task(self, task_id: int, *, reset_downstream: bool = True) -> TaskInstance:
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
        task.lease_owner = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        task.cancel_requested_at = None

        phase = await self.get_phase(task.phase_id)
        assessment = await self.get_assessment(phase.assessment_id)
        from app.services.report_service import invalidate_report_artifacts
        await invalidate_report_artifacts(self.db, assessment.project_id, f"测评任务已重置：{task.name}")
        if task.task_type == "doc_review":
            from app.models.document_knowledge import DocumentAnalysisRun, DocumentFile, DocumentRunFile
            from app.models.finding import Finding
            from app.services.file_storage import file_storage
            from app.services.verification_service import delete_verification_data
            document_rows = (await self.db.execute(
                select(DocumentFile.id, DocumentFile.storage_path)
                .where(DocumentFile.assessment_id == assessment.id, DocumentFile.task_id == task.id)
            )).all()
            document_ids = [row.id for row in document_rows]
            batch_run_ids = []
            if document_ids:
                batch_run_ids = (await self.db.execute(
                    select(DocumentRunFile.analysis_run_id)
                    .join(DocumentAnalysisRun, DocumentAnalysisRun.id == DocumentRunFile.analysis_run_id)
                    .where(
                        DocumentRunFile.document_file_id.in_(document_ids),
                        DocumentAnalysisRun.run_kind == "batch",
                    )
                )).scalars().all()
            await self.db.execute(delete(DocumentFile).where(
                DocumentFile.assessment_id == assessment.id,
                DocumentFile.task_id == task.id,
            ))
            await self.db.execute(delete(DocumentAnalysisRun).where(DocumentAnalysisRun.task_id == task.id))
            if batch_run_ids:
                await self.db.execute(delete(DocumentAnalysisRun).where(DocumentAnalysisRun.id.in_(batch_run_ids)))
            from app.services.knowledge_graph import knowledge_graph
            for document_id in document_ids:
                await knowledge_graph.purge_file(self.db, document_id)
            await knowledge_graph.purge_task(self.db, task.id)
            for _, document_path in document_rows:
                await file_storage.delete_file(document_path)
            finding_ids = list((await self.db.execute(select(Finding.id).where(
                Finding.project_id == assessment.project_id,
                Finding.clause_id.like(f"DOC-TASK-{task.id}-%"),
            ))).scalars().all())
            await delete_verification_data(self.db, assessment.project_id, finding_ids)
            await self.db.execute(delete(Finding).where(Finding.id.in_(finding_ids)))
        tasks = await self.get_tasks(task.phase_id, official_only=True)
        phase.completed_tasks = sum(1 for item in tasks if item.id != task.id and item.status in ("completed", "cancelled"))
        phase.progress = (phase.completed_tasks / phase.total_tasks * 100) if phase.total_tasks > 0 else 0
        if phase.status == "completed":
            phase.status = "pending"
            phase.completed_at = None

        if reset_downstream:
            downstream = [
                item for item in await self.get_phases(phase.assessment_id)
                if item.order > phase.order
            ]
            for item in downstream:
                await self._reset_phase_state(item)
            if any(item.phase_id == "remediation_verification" for item in downstream):
                from app.services.verification_service import reset_verification_data
                await reset_verification_data(self.db, assessment.project_id)

        await self.db.commit()

        await self.emit_event(phase.assessment_id, "task_reset", {"task_id": task_id})
        await self._update_assessment_progress(phase.assessment_id)

        logger.info(f"Task {task_id} reset to todo")
        return task

    async def _reset_phase_state(self, phase: PhaseInstance) -> None:
        """Clear persisted phase/task execution state without touching project assets."""
        phase.status = "pending"
        phase.completed_tasks = 0
        phase.progress = 0
        phase.started_at = None
        phase.completed_at = None
        phase.outputs = None
        for task in await self.get_tasks(phase.id, official_only=True):
            task.status = "todo"
            task.started_at = None
            task.completed_at = None
            task.result = None
            task.evidence_ids = None
            task.lease_owner = None
            task.lease_expires_at = None
            task.heartbeat_at = None
            task.cancel_requested_at = None

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

        if phase.status not in ("pending", "active", "completed", "failed"):
            raise ValueError(f"Cannot reset phase with status {phase.status}")

        assessment = await self.get_assessment(phase.assessment_id)
        from app.services.report_service import invalidate_report_artifacts
        await invalidate_report_artifacts(self.db, assessment.project_id, f"测评阶段已重置：{phase.name}")
        tasks = await self.get_tasks(phase_id, official_only=True)
        affected_phases = [
            item for item in await self.get_phases(phase.assessment_id)
            if item.order >= phase.order
        ]
        for item in affected_phases:
            await self._reset_phase_state(item)

        if any(item.phase_id == "remediation_verification" for item in affected_phases):
            from app.services.verification_service import reset_verification_data
            await reset_verification_data(self.db, assessment.project_id)

        document_task_ids = [task.id for task in tasks if task.task_type == "doc_review"]
        if document_task_ids:
            from app.models.document_knowledge import DocumentAnalysisRun, DocumentFile
            from app.models.finding import Finding
            from app.services.file_storage import file_storage
            from app.services.verification_service import delete_verification_data
            document_paths = (await self.db.execute(
                select(DocumentFile.storage_path).where(
                    DocumentFile.assessment_id == assessment.id,
                    DocumentFile.task_id.in_(document_task_ids),
                )
            )).scalars().all()
            await self.db.execute(delete(DocumentFile).where(
                DocumentFile.assessment_id == assessment.id,
                DocumentFile.task_id.in_(document_task_ids),
            ))
            await self.db.execute(delete(DocumentAnalysisRun).where(DocumentAnalysisRun.phase_id == phase.id))
            from app.services.knowledge_graph import knowledge_graph
            await knowledge_graph.purge_phase(self.db, phase.id)
            for document_path in document_paths:
                await file_storage.delete_file(document_path)
            finding_ids = list((await self.db.execute(select(Finding.id).where(
                Finding.project_id == assessment.project_id,
                or_(*[Finding.clause_id.like(f"DOC-TASK-{task_id}-%") for task_id in document_task_ids]),
            ))).scalars().all())
            await delete_verification_data(self.db, assessment.project_id, finding_ids)
            await self.db.execute(delete(Finding).where(Finding.id.in_(finding_ids)))

        await self.db.commit()

        await self.emit_event(phase.assessment_id, "phase_reset", {"phase_id": phase_id})
        await self._update_assessment_progress(phase.assessment_id)

        logger.info(f"Phase {phase_id} reset to pending")
        return phase

    async def _cancel_project_assessment_jobs(self, project_id: int) -> dict:
        """Stop durable project jobs before their rows are removed by a full reset."""
        from app.models.document_knowledge import DocumentAnalysisRun
        from app.models.scan_task import ScanTask, ScanTaskStatus
        from app.models.verification import VerificationRun, VerificationRunStatus
        from app.orchestrator.orchestrator import orchestrator

        now = datetime.utcnow()
        scan_rows = (await self.db.execute(select(
            ScanTask.id, ScanTask.orchestrator_task_id
        ).where(
            ScanTask.project_id == project_id,
            ScanTask.status.in_([ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING]),
        ))).all()
        for row in scan_rows:
            if row.orchestrator_task_id:
                try:
                    await orchestrator.stop_task(row.orchestrator_task_id)
                except Exception as exc:  # pragma: no cover - durable flags remain authoritative
                    logger.warning("Failed to stop in-memory scan task %s: %s", row.orchestrator_task_id, exc)
        if scan_rows:
            await self.db.execute(update(ScanTask).where(
                ScanTask.id.in_([row.id for row in scan_rows])
            ).values(
                status=ScanTaskStatus.CANCELLED,
                control_state="cancelled",
                cancel_requested_at=now,
                completed_at=now,
                lease_owner=None,
                lease_expires_at=None,
            ))

        document_result = await self.db.execute(update(DocumentAnalysisRun).where(
            DocumentAnalysisRun.project_id == project_id,
            DocumentAnalysisRun.status.in_(["queued", "running"]),
        ).values(
            status="cancelled",
            cancel_requested_at=now,
            completed_at=now,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            progress={"stage": "cancelled", "percent": 0, "message": "测评已完全重置"},
        ))
        verification_result = await self.db.execute(update(VerificationRun).where(
            VerificationRun.project_id == project_id,
            VerificationRun.status.in_([VerificationRunStatus.QUEUED, VerificationRunStatus.RUNNING]),
        ).values(
            status=VerificationRunStatus.CANCELLED,
            cancel_requested_at=now,
            completed_at=now,
            credential_envelope=None,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
        ))
        task_result = await self.db.execute(update(TaskInstance).where(
            TaskInstance.phase_id.in_(
                select(PhaseInstance.id).join(Assessment).where(Assessment.project_id == project_id)
            ),
            TaskInstance.status == "in_progress",
        ).values(
            status="failed",
            completed_at=now,
            cancel_requested_at=now,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            result={"status": "cancelled", "error": "测评已完全重置"},
        ))
        await self.db.commit()
        return {
            "scan_tasks": len(scan_rows),
            "document_runs": document_result.rowcount or 0,
            "verification_runs": verification_result.rowcount or 0,
            "assessment_tasks": task_result.rowcount or 0,
        }

    async def _clear_project_assessment_outputs(self, project_id: int) -> dict:
        """Delete project-scoped assessment outputs while preserving its assets and configuration."""
        from app.models.assessment_type import ProjectAssessment
        from app.models.change_snapshot import ChangeSnapshot
        from app.models.context import ActionHistory, ConversationHistory, ResultCache
        from app.models.evidence import Evidence
        from app.models.finding import Finding
        from app.models.monitoring import ScanHistory, ScheduledScan
        from app.models.questionnaire import QuestionnaireRecord
        from app.models.document_knowledge import DocumentAnalysisRun, DocumentFile
        from app.models.report import ReportArtifact
        from app.models.scan_task import ScanTask
        from app.models.project import Project
        from app.services.data_lifecycle import delete_storage_files
        from app.services.knowledge_graph import knowledge_graph
        from app.services.verification_service import delete_verification_data

        assessment_ids = list((await self.db.execute(select(Assessment.id).where(
            Assessment.project_id == project_id
        ))).scalars().all())
        scan_task_ids = list((await self.db.execute(select(ScanTask.id).where(
            ScanTask.project_id == project_id
        ))).scalars().all())
        finding_ids = select(Finding.id).where(Finding.project_id == project_id)
        questionnaire_ids = select(QuestionnaireRecord.id).where(QuestionnaireRecord.project_id == project_id)
        evidence_scope = or_(
            Evidence.project_id == project_id,
            Evidence.finding_id.in_(finding_ids),
            Evidence.questionnaire_record_id.in_(questionnaire_ids),
        )
        evidence_rows = (await self.db.execute(select(
            Evidence.file_path, Evidence.file_size
        ).where(evidence_scope, Evidence.file_path.is_not(None)))).all()
        document_rows = (await self.db.execute(select(
            DocumentFile.storage_path, DocumentFile.size_bytes
        ).where(DocumentFile.project_id == project_id))).all()
        report_rows = (await self.db.execute(select(
            ReportArtifact.html_path, ReportArtifact.html_size
        ).where(ReportArtifact.project_id == project_id))).all()
        counts = {
            "scan_tasks": len(scan_task_ids),
            "findings": int((await self.db.execute(select(func.count(Finding.id)).where(Finding.project_id == project_id))).scalar_one()),
            "evidences": int((await self.db.execute(select(func.count(Evidence.id)).where(evidence_scope))).scalar_one()),
            "document_files": len(document_rows),
            "document_runs": int((await self.db.execute(select(func.count(DocumentAnalysisRun.id)).where(DocumentAnalysisRun.project_id == project_id))).scalar_one()),
            "reports": len(report_rows),
            "change_snapshots": int((await self.db.execute(select(func.count(ChangeSnapshot.id)).where(ChangeSnapshot.project_id == project_id))).scalar_one()),
        }

        await delete_verification_data(self.db, project_id)
        await self.db.execute(delete(Evidence).where(evidence_scope))
        await self.db.execute(delete(QuestionnaireRecord).where(QuestionnaireRecord.project_id == project_id))
        await self.db.execute(delete(Finding).where(Finding.project_id == project_id))
        await self.db.execute(delete(ProjectAssessment).where(ProjectAssessment.project_id == project_id))
        await self.db.execute(delete(ReportArtifact).where(ReportArtifact.project_id == project_id))
        await self.db.execute(delete(DocumentAnalysisRun).where(DocumentAnalysisRun.project_id == project_id))
        await self.db.execute(delete(DocumentFile).where(DocumentFile.project_id == project_id))
        if assessment_ids:
            await self.db.execute(delete(FlowEvent).where(FlowEvent.assessment_id.in_(assessment_ids)))
        if scan_task_ids:
            await self.db.execute(delete(ScanHistory).where(ScanHistory.scan_task_id.in_(scan_task_ids)))
        await self.db.execute(delete(ChangeSnapshot).where(ChangeSnapshot.project_id == project_id))
        await self.db.execute(delete(ScanTask).where(ScanTask.project_id == project_id))
        await self.db.execute(delete(ResultCache).where(ResultCache.project_id == project_id))
        await self.db.execute(delete(ActionHistory).where(ActionHistory.project_id == project_id))
        reset_marker = datetime.utcnow().isoformat()
        conversations = (await self.db.execute(select(ConversationHistory).where(
            ConversationHistory.project_id == project_id,
            ConversationHistory.context_snapshot.is_not(None),
        ))).scalars().all()
        for conversation in conversations:
            snapshot = dict(conversation.context_snapshot or {})
            if snapshot.pop("scan_results", None) is not None:
                snapshot["assessment_data_reset"] = reset_marker
                snapshot["is_multi_asset"] = False
                conversation.context_snapshot = snapshot
        await self.db.execute(update(ScheduledScan).where(ScheduledScan.project_id == project_id).values(last_run_at=None))
        await knowledge_graph.purge_project(self.db, project_id)
        project = await self.db.get(Project, project_id)
        if project:
            project.compliance_score = None
        await self.db.commit()

        file_rows = [*evidence_rows, *document_rows, *report_rows]
        file_cleanup = await delete_storage_files(row[0] for row in file_rows)
        return {
            **counts,
            **file_cleanup,
            "released_file_bytes": sum(int(row[1] or 0) for row in file_rows),
        }

    async def restart_assessment(self, assessment_id: int, mode: str = "reset") -> tuple[Assessment, dict]:
        """
        重新打开或重置整个测评。
        """
        assessment = await self.get_assessment(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")

        if mode == "continue":
            from app.services.report_service import invalidate_report_artifacts
            await invalidate_report_artifacts(self.db, assessment.project_id, "测评已重新打开")
            assessment.status = "in_progress"
            assessment.completed_at = None
            if not assessment.started_at:
                assessment.started_at = datetime.utcnow()
            await self.db.commit()
            await self.emit_event(assessment_id, "assessment_reopened", {"assessment_id": assessment_id})
            logger.info(f"Assessment {assessment_id} reopened without clearing evidence")
            return assessment, {}

        cancelled_jobs = await self._cancel_project_assessment_jobs(assessment.project_id)

        phases = await self.get_phases(assessment_id)
        for phase in phases:
            await self._reset_phase_state(phase)

        assessment.status = "not_started"
        assessment.progress = 0
        assessment.completed_phases = 0
        assessment.started_at = None
        assessment.completed_at = None
        assessment.extra_data = None

        cleanup = await self._clear_project_assessment_outputs(assessment.project_id)

        await self.emit_event(assessment_id, "assessment_reset", {"assessment_id": assessment_id})

        logger.info("Assessment %s reset to not_started: %s", assessment_id, cleanup)
        return assessment, {**cleanup, "cancelled_jobs": cancelled_jobs}

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
