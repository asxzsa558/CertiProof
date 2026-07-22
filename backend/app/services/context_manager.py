"""
上下文管理器 - 管理对话历史、操作历史、结果缓存、项目记忆、用户记忆
参考 Claude Code 的多层记忆系统设计
"""

import json
import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, update

from app.models.context import (
    ConversationHistory,
    ActionHistory,
    ResultCache,
    ProjectMemory,
    UserMemory,
    ConversationArchive,
    ConversationThread,
    ConversationSummary,
)
from app.core.redaction import redact_sensitive
from app.core.config import settings

logger = logging.getLogger(__name__)


class ArchiveCompletedTaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    result: str


class ArchiveCurrentTaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    progress: str


class ArchiveSummaryContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    completed_tasks: List[ArchiveCompletedTaskContract] = Field(max_length=5)
    current_task: Optional[ArchiveCurrentTaskContract]
    interrupt_point: str
    key_findings: List[str] = Field(max_length=5)


class ContextManager:
    """统一的上下文管理器"""
    
    # 上下文 token 限制
    MAX_CONVERSATION_TOKENS = 200000
    HARD_TOKEN_LIMIT = 500000
    SUMMARY_SEGMENT_MESSAGES = 40  # 约 20 轮
    SUMMARY_SEGMENT_TOKENS = 20000
    AUTO_ROLLOVER_MESSAGES = 160
    AUTO_ROLLOVER_TOKENS = 120000
    ACTIVE_HISTORY_RETENTION_DAYS = settings.ACTIVE_HISTORY_RETENTION_DAYS
    MAX_ACTION_HISTORY = 200  # 最大操作历史记录数（增加到 200）
    MAX_CACHE_ENTRIES = 100  # 最大缓存条目数
    
    def __init__(
        self,
        db: AsyncSession,
        user_id: int,
        project_id: int = None,
        thread_id: int = None,
        assessment_code: str = "dengbao",
    ):
        self.db = db
        self.user_id = user_id
        self.project_id = project_id
        self.thread_id = thread_id
        self.assessment_code = assessment_code if assessment_code in {"dengbao", "miping"} else "dengbao"

    def _thread_condition(self, column):
        """A missing thread means the legacy/default thread, never every thread."""
        return column.is_(None) if self.thread_id is None else column == self.thread_id

    def _history_conditions(self, *, include_archived: bool = False):
        conditions = [
            ConversationHistory.user_id == self.user_id,
            self._thread_condition(ConversationHistory.thread_id),
        ]
        if self.project_id is None:
            conditions.append(ConversationHistory.project_id.is_(None))
        else:
            conditions.append(ConversationHistory.project_id == self.project_id)
        if not include_archived:
            conditions.append(ConversationHistory.archive_id.is_(None))
        return conditions
    
    async def build_context(self) -> Dict:
        """
        构建完整上下文

        Returns:
            {
                "conversation_history": [...],
                "recent_messages": [...],          # 用于 LLM 调用的历史
                "action_history": [...],
                "result_cache": {...},
                "project_memory": [...],
                "user_memory": [...],
                "current_project": {...},
                "project_assets": [...],
                "project_archives_summary": "...",
                "assessment_state": {...},         # 测评流程状态
                "history_turns": int,              # 配置项
            }
        """
        history_turns = await self._get_config_value("ai.history_turns", 5)

        context = {
            "conversation_history": await self._get_conversation_history(),
            "recent_messages": await self._get_recent_messages_for_llm(history_turns),
            "action_history": await self._get_action_history(),
            "result_cache": await self._get_result_cache(),
            "project_memory": await self._get_project_memory(),
            "user_memory": await self._get_user_memory(),
            "current_project": await self._get_current_project(),
            "project_assets": await self._get_project_assets(),
            "thread_handoff_summary": await self.get_thread_handoff_summary(),
            "thread_summary": await self.get_thread_summary(),
            "assessment_state": await self._get_assessment_state(),
            "history_turns": history_turns,
        }

        return context

    async def _get_config_value(self, key: str, default: Any = None) -> Any:
        """从 system_config 表读取配置"""
        try:
            from app.models.config import SystemConfig
            from sqlalchemy import select
            result = await self.db.execute(
                select(SystemConfig).where(SystemConfig.key == key)
            )
            config = result.scalar_one_or_none()
            if config:
                return config.value
        except Exception as e:
            logger.warning(f"Failed to read config {key}: {e}")
        return default

    async def _get_recent_messages_for_llm(self, turns: int) -> List[Dict]:
        """获取最近 N 轮对话，用于 LLM 调用"""
        if turns <= 0:
            return []
        latest_summary = await self._get_latest_completed_summary()
        query = select(ConversationHistory).where(*self._history_conditions())
        if latest_summary:
            query = query.where(ConversationHistory.id > latest_summary.source_end_message_id)
        result = await self.db.execute(
            query.order_by(
                ConversationHistory.created_at.desc(),
                ConversationHistory.id.desc(),
            ).limit(turns * 2)
        )
        messages = [
            {"role": h.role, "content": h.content}
            for h in reversed(result.scalars().all())
        ]
        # 转换为 LLM 格式
        return [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") in ("user", "assistant")
        ]

    async def _get_assessment_state(self) -> Dict:
        """获取当前项目的测评流程状态"""
        if not self.project_id:
            return {}

        try:
            from app.models.assessment import Assessment, PhaseInstance, TaskInstance
            from sqlalchemy import select

            # 获取最新测评
            result = await self.db.execute(
                select(Assessment)
                .where(
                    Assessment.project_id == self.project_id,
                    Assessment.assessment_type_code == self.assessment_code,
                )
                .order_by(Assessment.created_at.desc(), Assessment.id.desc())
                .limit(1)
            )
            assessment = result.scalar_one_or_none()
            if not assessment:
                return {"has_assessment": False}

            # 获取所有阶段
            result = await self.db.execute(
                select(PhaseInstance)
                .where(PhaseInstance.assessment_id == assessment.id)
                .order_by(PhaseInstance.order)
            )
            phases = result.scalars().all()

            # 获取当前活跃阶段
            current_phase = None
            for p in phases:
                if p.status == "active":
                    # 获取该阶段的待办任务
                    result = await self.db.execute(
                        select(TaskInstance)
                        .where(
                            TaskInstance.phase_id == p.id,
                            TaskInstance.status.in_(["todo", "in_progress"])
                        )
                        .limit(5)
                    )
                    tasks = result.scalars().all()
                    current_phase = {
                        "id": p.id,
                        "name": p.name,
                        "order": p.order,
                        "progress": p.progress,
                        "pending_tasks": [
                            {"id": t.id, "name": t.name, "description": t.description or "", "type": t.task_type}
                            for t in tasks
                        ],
                    }
                    break

            return {
                "has_assessment": True,
                "id": assessment.id,
                "name": assessment.name,
                "assessment_type_code": assessment.assessment_type_code,
                "assessment_level": assessment.assessment_level,
                "status": assessment.status,
                "progress": assessment.progress,
                "completed_phases": assessment.completed_phases,
                "total_phases": assessment.total_phases,
                "current_phase": current_phase,
            }
        except Exception as e:
            logger.warning(f"Failed to get assessment state: {e}")
            return {}
    
    async def _get_conversation_history(self, limit: int = 20) -> List[Dict]:
        """获取最近的对话历史"""
        query = select(ConversationHistory).where(*self._history_conditions())
        
        query = query.order_by(
            ConversationHistory.created_at.desc(),
            ConversationHistory.id.desc(),
        ).limit(limit)
        result = await self.db.execute(query)
        histories = result.scalars().all()
        
        return [
            {
                "role": h.role,
                "content": h.content,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in reversed(histories)  # 按时间正序返回
        ]
    
    async def _get_action_history(self, limit: int = 20) -> List[Dict]:
        """获取最近的操作历史"""
        query = select(ActionHistory).where(
            ActionHistory.user_id == self.user_id,
            ActionHistory.project_id.is_(None) if self.project_id is None else ActionHistory.project_id == self.project_id,
            self._thread_condition(ActionHistory.thread_id),
        )
        
        result = await self.db.execute(
            query.order_by(ActionHistory.created_at.desc()).limit(limit)
        )
        actions = result.scalars().all()
        
        return [
            {
                "action_type": a.action_type,
                "parameters": a.parameters,
                "result_summary": self._summarize_result(a.result),
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in reversed(actions)
        ]
    
    async def _get_result_cache(self) -> Dict[str, Any]:
        """获取结果缓存"""
        # 清理过期缓存
        await self._cleanup_expired_cache()
        
        query = select(ResultCache).where(ResultCache.user_id == self.user_id)
        
        if self.project_id:
            query = query.where(ResultCache.project_id == self.project_id)
        
        result = await self.db.execute(
            query.order_by(ResultCache.created_at.desc()).limit(self.MAX_CACHE_ENTRIES)
        )
        caches = result.scalars().all()
        
        return {c.cache_key: c.result_data for c in caches}
    
    async def _get_project_memory(self) -> List[Dict]:
        """获取项目记忆"""
        if not self.project_id:
            return []
        
        result = await self.db.execute(
            select(ProjectMemory)
            .where(ProjectMemory.project_id == self.project_id)
            .order_by(ProjectMemory.updated_at.desc())
            .limit(20)
        )
        memories = result.scalars().all()
        
        return [
            {
                "memory_type": m.memory_type,
                "content": m.content,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in memories
        ]
    
    async def _get_user_memory(self) -> List[Dict]:
        """获取用户记忆"""
        result = await self.db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == self.user_id)
            .order_by(UserMemory.updated_at.desc())
            .limit(20)
        )
        memories = result.scalars().all()
        
        return [
            {
                "memory_type": m.memory_type,
                "content": m.content,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in memories
        ]
    
    async def _get_current_project(self) -> Optional[Dict]:
        """获取当前项目信息"""
        if not self.project_id:
            return None
        
        from app.models.project import Project
        from app.models.assessment_type import AssessmentType, ProjectAssessment
        
        result = await self.db.execute(
            select(Project).where(Project.id == self.project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            return None

        assessment_rows = (await self.db.execute(
            select(ProjectAssessment, AssessmentType)
            .join(AssessmentType, AssessmentType.id == ProjectAssessment.assessment_type_id)
            .where(ProjectAssessment.project_id == self.project_id)
            .order_by(AssessmentType.sort_order, AssessmentType.id)
        )).all()
        
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "compliance_level": project.compliance_level.value if project.compliance_level else None,
            "compliance_score": project.compliance_score,
            "active_assessment_code": self.assessment_code,
            "assessment_types": [
                {
                    "code": assessment_type.code,
                    "name": assessment_type.name,
                    "level": project_assessment.level,
                    "status": project_assessment.status,
                    "progress": project_assessment.progress,
                    "score": project_assessment.score,
                }
                for project_assessment, assessment_type in assessment_rows
            ],
        }
    
    async def _get_project_assets(self) -> List[Dict]:
        """获取项目资产列表"""
        if not self.project_id:
            return []
        
        from app.models.asset import Asset
        
        result = await self.db.execute(
            select(Asset).where(Asset.project_id == self.project_id).limit(50)
        )
        assets = result.scalars().all()
        
        return [
            {
                "id": a.id,
                "name": a.name or "",
                "type": a.asset_type.value if a.asset_type else "ip",
                "value": a.value,
            }
            for a in assets
        ]
    
    async def add_conversation(self, role: str, content: str, context_snapshot: Dict = None):
        """添加对话记录"""
        history = ConversationHistory(
            user_id=self.user_id,
            project_id=self.project_id,
            thread_id=self.thread_id,
            role=role,
            content=content,
            context_snapshot=context_snapshot,
            tokens_used=self._estimate_tokens(content),
        )
        self.db.add(history)
        await self.db.flush()
        
        await self._compress_conversation_if_needed()
        await self._auto_cleanup()
    
    async def add_action(self, action_type: str, parameters: Dict, result: Dict = None, status: str = "success"):
        """添加操作记录"""
        action = ActionHistory(
            user_id=self.user_id,
            project_id=self.project_id,
            thread_id=self.thread_id,
            action_type=action_type,
            parameters=redact_sensitive(parameters),
            result=result,
            status=status,
            completed_at=datetime.now(timezone.utc) if status in ["success", "failed"] else None,
        )
        self.db.add(action)
        await self.db.flush()
        
        await self._auto_cleanup()
    
    async def cache_result(self, cache_key: str, result_data: Dict, expires_in: int = 3600):
        """缓存结果"""
        # 检查是否已存在
        conditions = [
            ResultCache.user_id == self.user_id,
            ResultCache.project_id == self.project_id if self.project_id is not None else ResultCache.project_id.is_(None),
            ResultCache.cache_key == cache_key,
        ]
        result = await self.db.execute(
            select(ResultCache)
            .where(*conditions)
            .order_by(ResultCache.created_at.desc())
            .limit(1)
        )
        existing = result.scalars().first()
        
        if existing:
            # 更新现有缓存
            existing.result_data = result_data
            existing.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        else:
            # 创建新缓存
            cache = ResultCache(
                user_id=self.user_id,
                project_id=self.project_id,
                cache_key=cache_key,
                result_data=result_data,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            )
            self.db.add(cache)
        
        await self.db.flush()
    
    async def get_cached_result(self, cache_key: str) -> Optional[Dict]:
        """获取缓存的结果"""
        conditions = [
            ResultCache.user_id == self.user_id,
            ResultCache.project_id == self.project_id if self.project_id is not None else ResultCache.project_id.is_(None),
        ]
        conditions.extend([
            ResultCache.cache_key == cache_key,
            (ResultCache.expires_at > datetime.now(timezone.utc)) | (ResultCache.expires_at == None),
        ])
        result = await self.db.execute(
            select(ResultCache)
            .where(*conditions)
            .order_by(ResultCache.created_at.desc())
            .limit(1)
        )
        cache = result.scalars().first()
        return cache.result_data if cache else None
    
    async def add_project_memory(self, memory_type: str, content: str, extra_data: Dict = None):
        """添加项目记忆"""
        if not self.project_id:
            return
        
        result = await self.db.execute(
            select(ProjectMemory).where(
                ProjectMemory.project_id == self.project_id,
                ProjectMemory.memory_type == memory_type,
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.content = content
            if extra_data:
                existing.extra_data = extra_data
        else:
            memory = ProjectMemory(
                project_id=self.project_id,
                memory_type=memory_type,
                content=content,
                extra_data=extra_data,
            )
            self.db.add(memory)
        
        await self.db.flush()
    
    async def add_user_memory(self, memory_type: str, content: str, extra_data: Dict = None):
        """添加用户记忆"""
        result = await self.db.execute(
            select(UserMemory).where(
                UserMemory.user_id == self.user_id,
                UserMemory.memory_type == memory_type,
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.content = content
            if extra_data:
                existing.extra_data = extra_data
        else:
            memory = UserMemory(
                user_id=self.user_id,
                memory_type=memory_type,
                content=content,
                extra_data=extra_data,
            )
            self.db.add(memory)
        
        await self.db.flush()
    
    async def _cleanup_expired_cache(self):
        """清理过期缓存"""
        await self.db.execute(
            delete(ResultCache).where(
                ResultCache.expires_at < datetime.now(timezone.utc)
            )
        )
        await self.db.flush()
    
    async def _compress_conversation_if_needed(self):
        """Queue an immutable source-backed summary; never delete conversation rows."""
        result = await self.db.execute(
            select(ConversationHistory)
            .where(*self._history_conditions())
            .order_by(ConversationHistory.id.asc())
        )
        histories = list(result.scalars().all())
        if not histories:
            return

        latest = await self._get_latest_completed_summary()
        pending = await self.db.execute(
            select(ConversationSummary.id).where(
                ConversationSummary.user_id == self.user_id,
                self._thread_condition(ConversationSummary.thread_id),
                ConversationSummary.project_id.is_(None) if self.project_id is None else ConversationSummary.project_id == self.project_id,
                ConversationSummary.status.in_(["queued", "processing"]),
            ).limit(1)
        )
        if pending.scalar_one_or_none() is not None:
            return

        candidates = [h for h in histories if not latest or h.id > latest.source_end_message_id]
        token_count = sum(h.tokens_used or 0 for h in candidates)
        if len(candidates) < self.SUMMARY_SEGMENT_MESSAGES and token_count < self.SUMMARY_SEGMENT_TOKENS:
            return

        segment, segment_tokens = [], 0
        for history in candidates:
            next_tokens = segment_tokens + (history.tokens_used or 0)
            if segment and (len(segment) >= self.SUMMARY_SEGMENT_MESSAGES or next_tokens > self.SUMMARY_SEGMENT_TOKENS):
                break
            segment.append(history)
            segment_tokens = next_tokens

        summary = ConversationSummary(
            user_id=self.user_id,
            project_id=self.project_id,
            thread_id=self.thread_id,
            source_start_message_id=segment[0].id,
            source_end_message_id=segment[-1].id,
            message_count=len(segment),
            token_count=segment_tokens,
            status="queued",
        )
        self.db.add(summary)
        await self.db.flush()
        await self._broadcast_compression_status("started", segment_tokens, len(segment))

    async def _get_latest_completed_summary(self) -> Optional[ConversationSummary]:
        result = await self.db.execute(
            select(ConversationSummary)
            .where(
                ConversationSummary.user_id == self.user_id,
                self._thread_condition(ConversationSummary.thread_id),
                ConversationSummary.project_id.is_(None) if self.project_id is None else ConversationSummary.project_id == self.project_id,
                ConversationSummary.status == "completed",
            )
            .order_by(ConversationSummary.source_end_message_id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_thread_summary(self) -> str:
        result = await self.db.execute(
            select(ConversationSummary)
            .where(
                ConversationSummary.user_id == self.user_id,
                self._thread_condition(ConversationSummary.thread_id),
                ConversationSummary.project_id.is_(None) if self.project_id is None else ConversationSummary.project_id == self.project_id,
                ConversationSummary.status == "completed",
            )
            .order_by(ConversationSummary.source_end_message_id.desc())
            .limit(3)
        )
        summaries = list(reversed(result.scalars().all()))
        return "\n\n".join(item.summary for item in summaries if item.summary)

    async def recall_archived_messages(self, query_text: str, limit: int = 6) -> List[Dict]:
        """Return small source-backed excerpts only when a turn explicitly needs old context."""
        words = [word for word in re.findall(r"[\w\u4e00-\u9fff]{2,}", query_text or "") if word not in {"之前", "以前", "归档", "对话", "讨论", "内容"}]
        query = select(ConversationHistory, ConversationArchive).join(
            ConversationArchive, ConversationArchive.id == ConversationHistory.archive_id
        ).where(
            ConversationHistory.user_id == self.user_id,
            ConversationHistory.archive_id.is_not(None),
            ConversationHistory.project_id.is_(None) if self.project_id is None else ConversationHistory.project_id == self.project_id,
        )
        if words:
            query = query.where(func.lower(ConversationHistory.content).contains(words[0].lower()))
        rows = (await self.db.execute(
            query.order_by(
                ConversationHistory.created_at.desc(),
                ConversationHistory.id.desc(),
            ).limit(max(1, min(limit, 20)))
        )).all()
        return [{
            "archive_id": archive.id,
            "archive_title": archive.title,
            "role": history.role,
            "content": history.content[:1200],
            "created_at": history.created_at.isoformat() if history.created_at else None,
        } for history, archive in rows]

    async def maybe_auto_rollover(self) -> Optional[Dict]:
        """Archive a completed conversation boundary and create its continuation thread."""
        from app.models.scan_task import ScanTask, ScanTaskStatus

        active_parameters = (await self.db.execute(select(ScanTask.parameters).where(
            ScanTask.project_id == self.project_id,
            ScanTask.status.in_([ScanTaskStatus.PENDING, ScanTaskStatus.RUNNING]),
        ))).scalars().all() if self.project_id is not None else []
        if any(
            (parameters or {}).get("source") == "interactive"
            and (parameters or {}).get("user_id") == self.user_id
            and (parameters or {}).get("thread_id") == self.thread_id
            for parameters in active_parameters
        ):
            return None

        count, tokens = (await self.db.execute(select(
            func.count(ConversationHistory.id),
            func.coalesce(func.sum(ConversationHistory.tokens_used), 0),
        ).where(*self._history_conditions()))).one()
        if int(count or 0) < self.AUTO_ROLLOVER_MESSAGES and int(tokens or 0) < self.AUTO_ROLLOVER_TOKENS:
            return None

        summary = await self.get_thread_summary()
        if not summary:
            recent = (await self.db.execute(
                select(ConversationHistory).where(*self._history_conditions())
                .order_by(ConversationHistory.id.desc()).limit(8)
            )).scalars().all()
            summary = "\n".join(f"{item.role}: {item.content[:500]}" for item in reversed(recent))
        archive_id = await self.create_archive_placeholder(
            f"自动归档 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
        )
        if not archive_id:
            return None
        archive = await self.db.get(ConversationArchive, archive_id)
        archive.summary = summary[:4000]
        continuation_id = await self.create_thread(
            title=f"接续对话 {datetime.now(timezone.utc).strftime('%m-%d %H:%M')}",
            parent_thread_id=self.thread_id,
            source_archive_id=archive_id,
        )
        if self.thread_id is not None:
            thread = await self.db.get(ConversationThread, self.thread_id)
            if thread:
                thread.is_active = False
                thread.is_archived = True
        await self.db.commit()
        return {"archive_id": archive_id, "thread_id": continuation_id, "message_count": int(count), "token_count": int(tokens)}
    
    async def _broadcast_compression_status(self, status: str, tokens_freed: int = 0, message_count: int = 0):
        """广播压缩状态到前端"""
        try:
            from app.api.websocket import manager
            # 广播给该用户的所有连接
            message = {
                "type": "compression_status",
                "data": {
                    "status": status,  # "started" or "completed"
                    "tokens_freed": tokens_freed,
                    "message_count": message_count,
                }
            }
            # 广播给所有连接（前端会根据 user_id 过滤）
            await manager.broadcast(message)
        except Exception as e:
            logger.debug(f"Failed to broadcast compression status: {e}")
    
    async def _auto_cleanup(self):
        """Expire only active, unarchived chat after the explicit retention window."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.ACTIVE_HISTORY_RETENTION_DAYS)
        await self.db.execute(
            delete(ConversationHistory).where(
                *self._history_conditions(),
                ConversationHistory.created_at < cutoff,
            )
        )
        
        action_query = select(func.count(ActionHistory.id)).where(
            ActionHistory.user_id == self.user_id,
            ActionHistory.project_id.is_(None) if self.project_id is None else ActionHistory.project_id == self.project_id,
            self._thread_condition(ActionHistory.thread_id),
        )
        
        action_count = await self.db.execute(action_query)
        action_total = action_count.scalar() or 0
        
        # 增加阈值到 500 条
        if action_total > 500:
            excess = action_total - 500
            oldest_query = select(ActionHistory.id).where(
                ActionHistory.user_id == self.user_id,
                ActionHistory.project_id.is_(None) if self.project_id is None else ActionHistory.project_id == self.project_id,
                self._thread_condition(ActionHistory.thread_id),
            )
            oldest_query = oldest_query.order_by(ActionHistory.created_at.asc()).limit(excess)
            
            oldest = await self.db.execute(oldest_query)
            old_ids = [row[0] for row in oldest.all()]
            if old_ids:
                await self.db.execute(
                    delete(ActionHistory).where(ActionHistory.id.in_(old_ids))
                )
                logger.info(f"Auto-cleaned {len(old_ids)} old action records")
        
        await self.db.flush()
    
    def _summarize_result(self, result: Dict) -> str:
        """简化结果用于上下文"""
        if not result:
            return "无结果"
        
        # 扫描结果
        if "open_ports" in result:
            ports = result.get("open_ports", [])
            return f"发现 {len(ports)} 个开放端口"
        
        if "vulnerabilities" in result:
            vulns = result.get("vulnerabilities", [])
            return f"发现 {len(vulns)} 个漏洞"
        
        if "compliance_score" in result:
            score = result.get("compliance_score")
            return f"合规评分: {score} 分"
        
        # 项目操作结果
        if "project_id" in result:
            return f"项目ID: {result['project_id']}"
        
        # 默认返回前 100 字符
        return str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
    
    def _estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数（CJK 字符约 1.5 token/字，ASCII 约 0.25 token/字符）"""
        cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f' or '\uff00' <= c <= '\uffef')
        ascii_count = len(text) - cjk_count
        return int(cjk_count * 1.5 + ascii_count * 0.25)
    
    # ==================== 归档管理 ====================
    
    async def archive_conversations(self, title: str = None) -> Optional[int]:
        """
        归档当前对话历史，生成结构化交接摘要
        
        归档目的：当上下文到达上限时，将当前工作状态保存为交接摘要，
        让新线程能接续未完成的任务。
        
        Args:
            title: 归档标题（可选，默认自动生成）
        
        Returns:
            归档 ID
        """
        return await self.create_archive_placeholder(title)
    
    async def create_archive_placeholder(self, title: str = None) -> Optional[int]:
        """
        创建归档记录并逻辑归档原始对话（同步部分）
        
        用于异步归档流程的第一步：立即返回 archive_id，后台再生成摘要。
        
        Returns:
            归档 ID
        """
        query = select(ConversationHistory).where(*self._history_conditions()).order_by(
            ConversationHistory.created_at.asc(),
            ConversationHistory.id.asc(),
        )
        
        result = await self.db.execute(query)
        histories = result.scalars().all()
        
        if not histories:
            return None
        
        # 计算统计信息
        total_tokens = sum(h.tokens_used or 0 for h in histories)
        message_count = len(histories)
        
        # 生成简单标题
        if not title:
            title = f"对话归档 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
        
        # 创建归档占位记录（无摘要）
        archive = ConversationArchive(
            user_id=self.user_id,
            project_id=self.project_id,
            thread_id=self.thread_id,
            title=title,
            summary="",
            message_count=message_count,
            token_count=total_tokens,
            status="queued",
            source_message_ids=[history.id for history in histories],
            related_refs=self._collect_message_refs(histories),
        )
        self.db.add(archive)
        await self.db.flush()
        
        # Preserve the full source transcript. Active history queries exclude it.
        history_ids = [h.id for h in histories]
        if history_ids:
            await self.db.execute(
                update(ConversationHistory)
                .where(ConversationHistory.id.in_(history_ids))
                .values(archive_id=archive.id, archived_at=datetime.now(timezone.utc))
            )
        
        await self.db.commit()
        logger.info("Queued archive %s with %s source messages", archive.id, message_count)
        
        return archive.id
    
    async def generate_archive_summary(self, archive_id: int):
        """
        异步生成归档摘要（后台任务调用）
        
        Args:
            archive_id: 归档 ID
        """
        return await self._generate_archive_summary_from_sources(archive_id)

    @staticmethod
    def _collect_message_refs(histories: List[ConversationHistory]) -> Dict[str, List[int]]:
        refs = {"task_ids": [], "scan_task_ids": [], "finding_ids": [], "evidence_ids": []}
        key_map = {
            "task_id": "task_ids",
            "scan_task_id": "scan_task_ids",
            "finding_id": "finding_ids",
            "evidence_id": "evidence_ids",
        }

        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    target = key_map.get(str(key))
                    if target and isinstance(item, int) and item not in refs[target]:
                        refs[target].append(item)
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        for history in histories:
            collect(history.context_snapshot or {})
        return {key: value for key, value in refs.items() if value}

    @staticmethod
    def _redact_summary_text(value: str) -> str:
        value = re.sub(
            r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|private[_-]?key|key[_-]?file)\b\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]",
            value or "",
        )
        return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)

    @staticmethod
    def _format_messages_for_summary(histories: List[ConversationHistory], limit: int = 80) -> str:
        selected = histories[-limit:]
        return "\n".join(
            f"{'用户' if history.role == 'user' else '助手'}: {ContextManager._redact_summary_text(history.content)}"
            for history in selected
        )

    async def _generate_archive_summary_from_sources(self, archive_id: int) -> bool:
        archive = (await self.db.execute(
            select(ConversationArchive).where(
                ConversationArchive.id == archive_id,
                ConversationArchive.user_id == self.user_id,
                ConversationArchive.project_id.is_(None) if self.project_id is None else ConversationArchive.project_id == self.project_id,
            )
        )).scalar_one_or_none()
        if not archive:
            return False
        if archive.legacy_summary_only:
            archive.status = "failed"
            archive.error_message = "历史归档没有保留原始对话，无法重新生成摘要。"
            await self.db.commit()
            return False

        histories = list((await self.db.execute(
            select(ConversationHistory)
            .where(
                ConversationHistory.archive_id == archive.id,
                ConversationHistory.user_id == self.user_id,
                ConversationHistory.project_id.is_(None) if self.project_id is None else ConversationHistory.project_id == self.project_id,
            )
            .order_by(ConversationHistory.created_at.asc(), ConversationHistory.id.asc())
        )).scalars().all())
        if not histories:
            archive.status = "failed"
            archive.error_message = "归档原始对话不存在，未生成摘要。"
            await self.db.commit()
            return False

        try:
            from app.services.llm_service import llm_service

            response = await llm_service.chat_with_fallback(
                db=self.db,
                user_id=self.user_id,
                messages=[
                    {
                        "role": "system",
                        "content": """你是任务交接摘要助手。仅根据提供的原始对话生成 JSON：
{"summary":"一句话状态","completed_tasks":[{"task":"任务","result":"结果"}],"current_task":{"task":"任务","progress":"进度"},"interrupt_point":"下一步","key_findings":["发现"]}
不要补造事实；completed_tasks 和 key_findings 最多 5 项；无进行中任务时 current_task 为 null；不得输出密码、令牌、密钥或其他凭据。""",
                    },
                    {"role": "user", "content": self._format_messages_for_summary(histories)},
                ],
                task_type="chat",
                timeout=60.0,
                response_model=ArchiveSummaryContract,
            )
            parsed = response.get("validated")
            if not parsed:
                content = re.sub(r"<think>.*?</think>", "", response.get("content", ""), flags=re.DOTALL).strip()
                match = re.search(r"\{[\s\S]*\}", content)
                parsed = json.loads(match.group()) if match else {}
            summary = self._redact_summary_text(str(parsed.get("summary") or "").strip())
            if not summary:
                raise ValueError("摘要服务未返回有效摘要")
        except Exception as exc:
            archive.status = "failed"
            archive.error_message = f"摘要生成失败：{str(exc)[:500]}"
            archive.lease_owner = None
            archive.lease_expires_at = None
            await self.db.commit()
            logger.warning("Archive %s summary failed: %s", archive_id, exc)
            return False

        archive.summary = summary
        archive.completed_tasks = redact_sensitive(parsed.get("completed_tasks") or [])[:5]
        archive.current_task = redact_sensitive(parsed.get("current_task"))
        archive.interrupt_point = self._redact_summary_text(str(parsed.get("interrupt_point") or ""))
        archive.key_findings = [self._redact_summary_text(str(item)) for item in (parsed.get("key_findings") or [])[:5]]
        archive.status = "completed"
        archive.error_message = None
        archive.summary_generated_at = datetime.now(timezone.utc)
        archive.lease_owner = None
        archive.lease_expires_at = None
        await self.db.commit()
        return True

    async def generate_conversation_summary(self, summary_id: int) -> bool:
        summary = (await self.db.execute(
            select(ConversationSummary).where(
                ConversationSummary.id == summary_id,
                ConversationSummary.user_id == self.user_id,
            )
        )).scalar_one_or_none()
        if not summary:
            return False
        histories = list((await self.db.execute(
            select(ConversationHistory)
            .where(
                ConversationHistory.user_id == summary.user_id,
                ConversationHistory.project_id.is_(None) if self.project_id is None else ConversationHistory.project_id == self.project_id,
                ConversationHistory.id >= summary.source_start_message_id,
                ConversationHistory.id <= summary.source_end_message_id,
                ConversationHistory.archive_id.is_(None),
            )
            .order_by(ConversationHistory.id.asc())
        )).scalars().all())
        if len(histories) != summary.message_count:
            summary.status = "failed"
            summary.error_message = "分段原文已变化，未生成摘要。"
            summary.lease_owner = None
            summary.lease_expires_at = None
            await self.db.commit()
            return False
        try:
            from app.services.llm_service import llm_service

            response = await llm_service.chat_with_fallback(
                db=self.db,
                user_id=self.user_id,
                messages=[
                    {"role": "system", "content": "将以下同一线程的原始对话压缩为不超过 500 字的中文事实摘要。不得补造事实，且不得保留密码、令牌或密钥。"},
                    {"role": "user", "content": self._format_messages_for_summary(histories, limit=self.SUMMARY_SEGMENT_MESSAGES)},
                ],
                task_type="chat",
                timeout=60.0,
            )
            content = self._redact_summary_text(str(response.get("content") or "").strip())
            if not content:
                raise ValueError("摘要服务未返回内容")
        except Exception as exc:
            summary.status = "failed"
            summary.error_message = f"分段摘要失败：{str(exc)[:500]}"
            summary.lease_owner = None
            summary.lease_expires_at = None
            await self.db.commit()
            return False

        summary.summary = content[:4000]
        summary.status = "completed"
        summary.error_message = None
        summary.completed_at = datetime.now(timezone.utc)
        summary.lease_owner = None
        summary.lease_expires_at = None
        await self.db.commit()
        await self._broadcast_compression_status("completed", summary.token_count, summary.message_count)
        return True

    async def list_archives(self, limit: int = 20) -> List[Dict]:
        """列出用户的归档"""
        query = select(ConversationArchive).where(ConversationArchive.user_id == self.user_id)
        if self.project_id:
            query = query.where(ConversationArchive.project_id == self.project_id)
        query = query.order_by(ConversationArchive.archived_at.desc()).limit(limit)
        
        result = await self.db.execute(query)
        archives = result.scalars().all()
        
        return [
            {
                "id": a.id,
                "title": a.title,
                "summary": a.summary,
                "message_count": a.message_count,
                "token_count": a.token_count,
                "completed_tasks": a.completed_tasks or [],
                "current_task": a.current_task,
                "interrupt_point": a.interrupt_point or "",
                "key_findings": a.key_findings or [],
                "thread_id": a.thread_id,
                "status": a.status,
                "error_message": a.error_message,
                "legacy_summary_only": bool(a.legacy_summary_only),
                "has_raw_messages": not bool(a.legacy_summary_only),
                "archived_at": a.archived_at.isoformat() if a.archived_at else None,
            }
            for a in archives
        ]
    
    async def delete_archive(self, archive_id: int, *, permanent: bool = False) -> bool:
        """Permanently remove an archive only after explicit confirmation."""
        if not permanent:
            raise ValueError("永久删除归档必须明确确认")
        query = select(ConversationArchive).where(
            ConversationArchive.id == archive_id,
            ConversationArchive.user_id == self.user_id,
        )
        if self.project_id is None:
            query = query.where(ConversationArchive.project_id.is_(None))
        else:
            query = query.where(ConversationArchive.project_id == self.project_id)
        archive = (await self.db.execute(query)).scalar_one_or_none()
        if not archive:
            return False

        source_ids = list(archive.source_message_ids or [])
        if source_ids:
            await self.db.execute(delete(ConversationSummary).where(
                ConversationSummary.user_id == self.user_id,
                ConversationSummary.source_start_message_id <= max(source_ids),
                ConversationSummary.source_end_message_id >= min(source_ids),
            ))
        await self.db.execute(update(ConversationThread).where(
            ConversationThread.source_archive_id == archive.id
        ).values(source_archive_id=None))
        await self.db.execute(delete(ConversationHistory).where(ConversationHistory.archive_id == archive.id))
        await self.db.delete(archive)
        await self.db.commit()
        return True
    
    async def get_archive(self, archive_id: int) -> Optional[Dict]:
        """获取单个归档的完整信息"""
        query = select(ConversationArchive).where(
            ConversationArchive.id == archive_id,
            ConversationArchive.user_id == self.user_id
        )
        if self.project_id is not None:
            query = query.where(ConversationArchive.project_id == self.project_id)
        result = await self.db.execute(
            query
        )
        a = result.scalar_one_or_none()
        if not a:
            return None
        
        return {
            "id": a.id,
            "title": a.title,
            "summary": a.summary,
            "message_count": a.message_count,
            "token_count": a.token_count,
            "completed_tasks": a.completed_tasks or [],
            "current_task": a.current_task,
            "interrupt_point": a.interrupt_point or "",
            "key_findings": a.key_findings or [],
            "thread_id": a.thread_id,
            "status": a.status,
            "error_message": a.error_message,
            "legacy_summary_only": bool(a.legacy_summary_only),
            "related_refs": a.related_refs or {},
            "messages": [
                {
                    "id": history.id,
                    "role": history.role,
                    "content": history.content,
                    "created_at": history.created_at.isoformat() if history.created_at else None,
                }
                for history in (await self.db.execute(
                    select(ConversationHistory)
                    .where(ConversationHistory.archive_id == a.id)
                    .order_by(ConversationHistory.created_at.asc(), ConversationHistory.id.asc())
                )).scalars().all()
            ],
            "archived_at": a.archived_at.isoformat() if a.archived_at else None,
        }

    async def retry_archive(self, archive_id: int) -> bool:
        query = select(ConversationArchive).where(
            ConversationArchive.id == archive_id,
            ConversationArchive.user_id == self.user_id,
        )
        query = query.where(ConversationArchive.project_id.is_(None) if self.project_id is None else ConversationArchive.project_id == self.project_id)
        archive = (await self.db.execute(query)).scalar_one_or_none()
        if not archive or archive.legacy_summary_only:
            return False
        archive.status = "queued"
        archive.error_message = None
        archive.lease_owner = None
        archive.lease_expires_at = None
        await self.db.commit()
        return True

    async def get_thread_handoff_summary(self) -> str:
        """Only expose a source archive for this thread, never unrelated project history."""
        if self.thread_id is None:
            return ""
        thread = (await self.db.execute(select(ConversationThread).where(
            ConversationThread.id == self.thread_id,
            ConversationThread.user_id == self.user_id,
        ))).scalar_one_or_none()
        if not thread:
            return ""
        query = select(ConversationArchive).where(
            ConversationArchive.user_id == self.user_id,
        )
        if thread.source_archive_id:
            query = query.where(ConversationArchive.id == thread.source_archive_id)
        else:
            query = query.where(ConversationArchive.thread_id == thread.id)
        archive = (await self.db.execute(query.order_by(ConversationArchive.archived_at.desc()).limit(1))).scalar_one_or_none()
        return archive.summary if archive and archive.summary else ""
    
    # ==================== 线程管理 ====================
    
    async def create_thread(self, title: str = None, parent_thread_id: int = None, source_archive_id: int = None) -> int:
        """
        创建新的对话线程
        
        Args:
            title: 线程标题
            parent_thread_id: 父线程 ID（用于接续上下文）
        
        Returns:
            线程 ID
        """
        thread = ConversationThread(
            user_id=self.user_id,
            project_id=self.project_id,
            title=title or f"对话 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
            parent_thread_id=parent_thread_id,
            source_archive_id=source_archive_id,
            is_active=True,
        )
        self.db.add(thread)
        await self.db.flush()
        await self.db.commit()
        
        logger.info(f"Created thread {thread.id} with parent {parent_thread_id}")
        return thread.id
    
    async def list_threads(self, limit: int = 20) -> List[Dict]:
        """列出用户的线程"""
        query = select(ConversationThread).where(
            ConversationThread.user_id == self.user_id,
            ConversationThread.deleted_at.is_(None),
        )
        if self.project_id is not None:
            query = query.where(ConversationThread.project_id == self.project_id)
        result = await self.db.execute(
            query
            .order_by(ConversationThread.updated_at.desc())
            .limit(limit)
        )
        threads = result.scalars().all()
        
        return [
            {
                "id": t.id,
                "title": t.title,
                "parent_thread_id": t.parent_thread_id,
                "source_archive_id": t.source_archive_id,
                "is_active": t.is_active,
                "is_archived": t.is_archived,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in threads
        ]
    
    async def get_thread(self, thread_id: int) -> Optional[Dict]:
        """获取线程详情"""
        query = select(ConversationThread).where(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == self.user_id,
            ConversationThread.deleted_at.is_(None),
        )
        if self.project_id is not None:
            query = query.where(ConversationThread.project_id == self.project_id)
        result = await self.db.execute(
            query
        )
        thread = result.scalar_one_or_none()
        
        if not thread:
            return None
        
        return {
            "id": thread.id,
            "title": thread.title,
            "parent_thread_id": thread.parent_thread_id,
            "source_archive_id": thread.source_archive_id,
            "is_active": thread.is_active,
            "is_archived": thread.is_archived,
            "created_at": thread.created_at.isoformat() if thread.created_at else None,
            "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
        }
    
    async def delete_thread(self, thread_id: int) -> bool:
        """Soft-delete a thread without destroying its archive or transcripts."""
        query = update(ConversationThread).where(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == self.user_id,
            ConversationThread.deleted_at.is_(None),
        )
        if self.project_id is not None:
            query = query.where(ConversationThread.project_id == self.project_id)
        result = await self.db.execute(query.values(is_active=False, deleted_at=datetime.now(timezone.utc)))
        await self.db.commit()
        return result.rowcount > 0
    
    async def continue_from_thread(self, thread_id: int) -> Optional[Dict]:
        """
        从指定线程接续上下文
        
        Returns:
            线程的对话历史和摘要
        """
        thread = await self.get_thread(thread_id)
        if not thread:
            return None
        
        # 获取该线程的对话历史
        history_result = await self.db.execute(
            select(ConversationHistory)
            .where(
                ConversationHistory.thread_id == thread_id,
                ConversationHistory.user_id == self.user_id,
                ConversationHistory.archive_id.is_(None),
            )
            .order_by(ConversationHistory.created_at.asc(), ConversationHistory.id.asc())
        )
        histories = history_result.scalars().all()
        
        # 构建对话历史
        conversation_history = [
            {
                "role": h.role,
                "content": h.content,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in histories
        ]
        
        archive_query = select(ConversationArchive).where(
            ConversationArchive.user_id == self.user_id,
            ConversationArchive.status == "completed",
        )
        if thread.get("source_archive_id"):
            archive_query = archive_query.where(ConversationArchive.id == thread["source_archive_id"])
        else:
            archive_query = archive_query.where(ConversationArchive.thread_id == thread_id)
        archive_result = await self.db.execute(archive_query.order_by(ConversationArchive.archived_at.desc()).limit(1))
        archive = archive_result.scalar_one_or_none()
        
        return {
            "thread": thread,
            "conversation_history": conversation_history,
            "archive_summary": archive.summary if archive else None,
            "message_count": len(histories),
        }

    async def continue_from_archive(self, archive_id: int) -> Optional[Dict]:
        query = select(ConversationArchive).where(
            ConversationArchive.id == archive_id,
            ConversationArchive.user_id == self.user_id,
            ConversationArchive.status == "completed",
        )
        query = query.where(ConversationArchive.project_id.is_(None) if self.project_id is None else ConversationArchive.project_id == self.project_id)
        archive = (await self.db.execute(query)).scalar_one_or_none()
        if not archive:
            return None
        thread_id = await self.create_thread(
            title=f"接续: {archive.title}",
            parent_thread_id=archive.thread_id,
            source_archive_id=archive.id,
        )
        return {"thread_id": thread_id, "archive_id": archive.id, "summary": archive.summary}


# 全局单例工厂函数
def get_context_manager(db: AsyncSession, user_id: int, project_id: int = None, thread_id: int = None) -> ContextManager:
    """获取上下文管理器实例"""
    return ContextManager(db, user_id, project_id, thread_id)
