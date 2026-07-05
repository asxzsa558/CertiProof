"""
上下文管理器 - 管理对话历史、操作历史、结果缓存、项目记忆、用户记忆
参考 Claude Code 的多层记忆系统设计
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
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
)
from app.core.redaction import redact_sensitive

logger = logging.getLogger(__name__)


class ContextManager:
    """统一的上下文管理器"""
    
    # 上下文 token 限制
    MAX_CONVERSATION_TOKENS = 200000  # 对话历史最大 token 数（增加到 200k）
    HARD_TOKEN_LIMIT = 500000  # 硬限制，超过则强制归档（增加到 500k）
    MAX_ACTION_HISTORY = 200  # 最大操作历史记录数（增加到 200）
    MAX_CACHE_ENTRIES = 100  # 最大缓存条目数
    
    def __init__(self, db: AsyncSession, user_id: int, project_id: int = None, thread_id: int = None):
        self.db = db
        self.user_id = user_id
        self.project_id = project_id
        self.thread_id = thread_id
    
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
            "project_archives_summary": await self.get_project_archives_summary(),
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
        # 每轮 = 1 user + 1 assistant = 2 messages
        messages = await self._get_conversation_history(limit=turns * 2)
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
                .where(Assessment.project_id == self.project_id)
                .order_by(Assessment.created_at.desc())
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
        query = select(ConversationHistory).where(ConversationHistory.user_id == self.user_id)
        
        # 按项目过滤
        if self.project_id is not None:
            query = query.where(ConversationHistory.project_id == self.project_id)
        
        # 如果有 thread_id，按线程过滤
        if self.thread_id:
            query = query.where(ConversationHistory.thread_id == self.thread_id)
        
        query = query.order_by(ConversationHistory.created_at.desc()).limit(limit)
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
        query = select(ActionHistory).where(ActionHistory.user_id == self.user_id)
        
        if self.project_id:
            query = query.where(ActionHistory.project_id == self.project_id)
        
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
        
        result = await self.db.execute(
            select(Project).where(Project.id == self.project_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            return None
        
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "compliance_level": project.compliance_level.value if project.compliance_level else None,
            "compliance_score": project.compliance_score,
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
            action_type=action_type,
            parameters=redact_sensitive(parameters),
            result=result,
            status=status,
            completed_at=datetime.utcnow() if status in ["success", "failed"] else None,
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
            existing.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        else:
            # 创建新缓存
            cache = ResultCache(
                user_id=self.user_id,
                project_id=self.project_id,
                cache_key=cache_key,
                result_data=result_data,
                expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
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
            (ResultCache.expires_at > datetime.utcnow()) | (ResultCache.expires_at == None),
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
                ResultCache.expires_at < datetime.utcnow()
            )
        )
        await self.db.flush()
    
    async def _compress_conversation_if_needed(self):
        """如果对话历史过长，进行压缩"""
        result = await self.db.execute(
            select(ConversationHistory)
            .where(ConversationHistory.user_id == self.user_id)
            .where(ConversationHistory.project_id == self.project_id)
            .order_by(ConversationHistory.created_at.desc())
        )
        histories = result.scalars().all()
        
        total_tokens = sum(h.tokens_used or 0 for h in histories)
        
        if total_tokens <= self.MAX_CONVERSATION_TOKENS:
            return
        
        logger.info(f"Conversation history exceeds limit ({total_tokens} tokens), compressing...")
        
        # 广播压缩开始
        await self._broadcast_compression_status("started", total_tokens)
        
        old_histories = histories[-50:] if len(histories) >= 50 else histories[:-20]
        if not old_histories:
            await self._broadcast_compression_status("completed", 0)
            return
        
        old_histories = sorted(old_histories, key=lambda h: h.created_at)
        
        conversation_text = "\n".join(
            f"{'用户' if h.role == 'user' else '助手'}: {h.content}"
            for h in old_histories
        )
        
        try:
            from app.services.llm_service import llm_service
            import asyncio
            
            summary_response = await asyncio.wait_for(
                llm_service.chat_with_fallback(
                    db=self.db,
                    user_id=self.user_id,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一个对话摘要助手。请将以下对话历史压缩为简洁的摘要，保留关键信息（用户需求、执行的操作、重要结果）。用中文输出，控制在 500 字以内。"
                        },
                        {
                            "role": "user",
                            "content": f"请压缩以下对话历史：\n\n{conversation_text}"
                        }
                    ],
                    task_type="chat",
                ),
                timeout=30.0
            )
            summary = summary_response.get("content", "")
        except asyncio.TimeoutError:
            logger.warning("LLM summarization timed out (30s), using fallback")
            summary = f"[历史对话摘要] 共 {len(old_histories)} 条对话，涉及{len(set(h.role for h in old_histories))}个角色。"
        except Exception as e:
            logger.warning(f"LLM summarization failed, using simple truncation: {e}")
            summary = f"[历史对话摘要] 共 {len(old_histories)} 条对话，涉及{len(set(h.role for h in old_histories))}个角色。"
        
        if not summary:
            await self._broadcast_compression_status("completed", 0)
            return
        
        if self.project_id:
            await self.add_project_memory(
                memory_type="conversation_summary",
                content=summary,
                extra_data={
                    "compressed_at": datetime.utcnow().isoformat(),
                    "message_count": len(old_histories),
                    "tokens_freed": sum(h.tokens_used or 0 for h in old_histories),
                }
            )
        else:
            await self.add_user_memory(
                memory_type="conversation_summary",
                content=summary,
                extra_data={
                    "compressed_at": datetime.utcnow().isoformat(),
                    "message_count": len(old_histories),
                    "tokens_freed": sum(h.tokens_used or 0 for h in old_histories),
                }
            )
        
        old_ids = [h.id for h in old_histories]
        if old_ids:
            await self.db.execute(
                delete(ConversationHistory).where(ConversationHistory.id.in_(old_ids))
            )
            await self.db.flush()
        
        # 广播压缩完成
        tokens_freed = sum(h.tokens_used or 0 for h in old_histories)
        await self._broadcast_compression_status("completed", tokens_freed, len(old_histories))
        
        logger.info(f"Compressed {len(old_ids)} old conversation records")
    
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
        """自动清理过旧的历史记录"""
        conv_count = await self.db.execute(
            select(func.count(ConversationHistory.id))
            .where(ConversationHistory.user_id == self.user_id)
            .where(ConversationHistory.project_id == self.project_id)
        )
        conv_total = conv_count.scalar() or 0
        
        # 增加阈值到 1000 条，避免过度删除
        if conv_total > 1000:
            excess = conv_total - 1000
            oldest = await self.db.execute(
                select(ConversationHistory.id)
                .where(ConversationHistory.user_id == self.user_id)
                .where(ConversationHistory.project_id == self.project_id)
                .order_by(ConversationHistory.created_at.asc())
                .limit(excess)
            )
            old_ids = [row[0] for row in oldest.all()]
            if old_ids:
                await self.db.execute(
                    delete(ConversationHistory).where(ConversationHistory.id.in_(old_ids))
                )
                logger.info(f"Auto-cleaned {len(old_ids)} old conversation records")
        
        action_query = select(func.count(ActionHistory.id)).where(ActionHistory.user_id == self.user_id)
        if self.project_id:
            action_query = action_query.where(ActionHistory.project_id == self.project_id)
        
        action_count = await self.db.execute(action_query)
        action_total = action_count.scalar() or 0
        
        # 增加阈值到 500 条
        if action_total > 500:
            excess = action_total - 500
            oldest_query = select(ActionHistory.id).where(ActionHistory.user_id == self.user_id)
            if self.project_id:
                oldest_query = oldest_query.where(ActionHistory.project_id == self.project_id)
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
        # 获取当前线程（如果有）的对话历史
        query = select(ConversationHistory).where(ConversationHistory.user_id == self.user_id)
        if self.thread_id:
            query = query.where(ConversationHistory.thread_id == self.thread_id)
        query = query.order_by(ConversationHistory.created_at.asc())
        
        result = await self.db.execute(query)
        histories = result.scalars().all()
        
        if not histories:
            return None
        
        # 获取操作历史（用于提取任务状态）
        action_query = select(ActionHistory).where(ActionHistory.user_id == self.user_id)
        if self.project_id:
            action_query = action_query.where(ActionHistory.project_id == self.project_id)
        action_query = action_query.order_by(ActionHistory.created_at.desc()).limit(50)
        
        action_result = await self.db.execute(action_query)
        actions = action_result.scalars().all()
        
        # 计算统计信息
        total_tokens = sum(h.tokens_used or 0 for h in histories)
        message_count = len(histories)
        
        # 构建 LLM 输入：对话历史 + 操作历史
        conversation_text = "\n".join(
            f"{'用户' if h.role == 'user' else '助手'}: {h.content}"
            for h in histories[-30:]  # 只取最近 30 条，避免过长
        )
        
        actions_text = "\n".join(
            f"- {a.action_type}: {a.status} ({self._summarize_result(a.result)})"
            for a in actions[:20]
        ) if actions else "无操作记录"
        
        # 用 LLM 生成结构化交接摘要
        completed_tasks = []
        current_task = None
        interrupt_point = ""
        key_findings = []
        summary = ""
        
        try:
            from app.services.llm_service import llm_service
            import asyncio
            
            llm_response = await asyncio.wait_for(
                llm_service.chat_with_fallback(
                    db=self.db,
                    user_id=self.user_id,
                    messages=[
                        {
                            "role": "system",
                            "content": """你是一个任务交接摘要助手。根据对话历史，生成简洁的交接摘要，让新线程能接续工作。

返回 JSON 格式：
{
    "summary": "一句话概括当前工作状态",
    "completed_tasks": [{"task": "已完成的任务名", "result": "关键结果"}],
    "current_task": {"task": "进行中的任务名", "progress": "当前进度"},
    "interrupt_point": "从哪里继续（具体描述）",
    "key_findings": ["关键发现1", "关键发现2"]
}

注意：
- 只保留关键信息，不要冗余描述
- completed_tasks 最多 5 个
- key_findings 最多 5 个
- 如果没有进行中的任务，current_task 为 null"""
                        },
                        {
                            "role": "user",
                            "content": f"对话历史：\n{conversation_text}\n\n操作历史：\n{actions_text}"
                        }
                    ],
                    task_type="chat",
                ),
                timeout=30.0
            )
            
            content = llm_response.get("content", "")
            # 清理 <think> 标签
            import re
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            
            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                parsed = json.loads(json_match.group())
                summary = parsed.get("summary", "")
                completed_tasks = parsed.get("completed_tasks", [])
                current_task = parsed.get("current_task")
                interrupt_point = parsed.get("interrupt_point", "")
                key_findings = parsed.get("key_findings", [])
        except asyncio.TimeoutError:
            logger.warning("LLM archive summary timed out (30s), using fallback")
            # Fallback: 简单截取
            first_msg = histories[0].content[:50] if histories else ""
            last_msg = histories[-1].content[:50] if histories else ""
            summary = f"从「{first_msg}...」到「{last_msg}...」共 {message_count} 条对话"
        except Exception as e:
            logger.warning(f"LLM archive summary failed, using fallback: {e}")
            # Fallback: 简单截取
            first_msg = histories[0].content[:50] if histories else ""
            last_msg = histories[-1].content[:50] if histories else ""
            summary = f"从「{first_msg}...」到「{last_msg}...」共 {message_count} 条对话"
        
        # 生成标题
        if not title:
            title = f"对话归档 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
        
        # 创建归档记录
        archive = ConversationArchive(
            user_id=self.user_id,
            project_id=self.project_id,
            thread_id=self.thread_id,
            title=title,
            summary=summary,
            message_count=message_count,
            token_count=total_tokens,
            completed_tasks=completed_tasks,
            current_task=current_task,
            interrupt_point=interrupt_point,
            key_findings=key_findings,
        )
        self.db.add(archive)
        await self.db.flush()
        
        # 删除已归档的对话历史
        history_ids = [h.id for h in histories]
        if history_ids:
            await self.db.execute(
                delete(ConversationHistory).where(ConversationHistory.id.in_(history_ids))
            )
        
        await self.db.commit()
        logger.info(f"Archived {message_count} conversations with structured summary")
        
        return archive.id
    
    async def create_archive_placeholder(self, title: str = None) -> Optional[int]:
        """
        创建归档占位记录并删除对话历史（同步部分）
        
        用于异步归档流程的第一步：立即返回 archive_id，后台再生成摘要。
        
        Returns:
            归档 ID
        """
        # 获取当前线程（如果有）的对话历史
        query = select(ConversationHistory).where(ConversationHistory.user_id == self.user_id)
        if self.thread_id:
            query = query.where(ConversationHistory.thread_id == self.thread_id)
        query = query.order_by(ConversationHistory.created_at.asc())
        
        result = await self.db.execute(query)
        histories = result.scalars().all()
        
        if not histories:
            return None
        
        # 计算统计信息
        total_tokens = sum(h.tokens_used or 0 for h in histories)
        message_count = len(histories)
        
        # 生成简单标题
        if not title:
            title = f"对话归档 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
        
        # 创建归档占位记录（无摘要）
        archive = ConversationArchive(
            user_id=self.user_id,
            project_id=self.project_id,
            thread_id=self.thread_id,
            title=title,
            summary="",  # 空摘要，稍后由 generate_archive_summary 填充
            message_count=message_count,
            token_count=total_tokens,
        )
        self.db.add(archive)
        await self.db.flush()
        
        # 删除已归档的对话历史
        history_ids = [h.id for h in histories]
        if history_ids:
            await self.db.execute(
                delete(ConversationHistory).where(ConversationHistory.id.in_(history_ids))
            )
        
        await self.db.commit()
        logger.info(f"Created archive placeholder {archive.id} with {message_count} messages")
        
        return archive.id
    
    async def generate_archive_summary(self, archive_id: int):
        """
        异步生成归档摘要（后台任务调用）
        
        Args:
            archive_id: 归档 ID
        """
        # 获取归档记录
        result = await self.db.execute(
            select(ConversationArchive).where(ConversationArchive.id == archive_id)
        )
        archive = result.scalar_one_or_none()
        
        if not archive:
            logger.error(f"Archive {archive_id} not found")
            return
        
        # 获取操作历史（用于提取任务状态）
        action_query = select(ActionHistory).where(ActionHistory.user_id == self.user_id)
        if archive.project_id:
            action_query = action_query.where(ActionHistory.project_id == archive.project_id)
        action_query = action_query.order_by(ActionHistory.created_at.desc()).limit(50)
        
        action_result = await self.db.execute(action_query)
        actions = action_result.scalars().all()
        
        actions_text = "\n".join(
            f"- {a.action_type}: {a.status} ({self._summarize_result(a.result)})"
            for a in actions[:20]
        ) if actions else "无操作记录"
        
        # 构建 LLM 输入
        # 注意：对话历史已被删除，只能从操作历史推断
        conversation_text = f"（对话历史已归档，共 {archive.message_count} 条消息）\n\n操作历史：\n{actions_text}"
        
        # 用 LLM 生成结构化交接摘要
        completed_tasks = []
        current_task = None
        interrupt_point = ""
        key_findings = []
        summary = ""
        
        try:
            from app.services.llm_service import llm_service
            import asyncio
            
            llm_response = await asyncio.wait_for(
                llm_service.chat_with_fallback(
                    db=self.db,
                    user_id=self.user_id,
                    messages=[
                        {
                            "role": "system",
                            "content": """你是一个任务交接摘要助手。根据操作历史，生成简洁的交接摘要，让新线程能接续工作。

返回 JSON 格式：
{
    "summary": "一句话概括当前工作状态",
    "completed_tasks": [{"task": "已完成的任务名", "result": "关键结果"}],
    "current_task": {"task": "进行中的任务名", "progress": "当前进度"},
    "interrupt_point": "从哪里继续（具体描述）",
    "key_findings": ["关键发现1", "关键发现2"]
}

注意：
- 只保留关键信息，不要冗余描述
- completed_tasks 最多 5 个
- key_findings 最多 5 个
- 如果没有进行中的任务，current_task 为 null"""
                        },
                        {
                            "role": "user",
                            "content": conversation_text
                        }
                    ],
                    task_type="chat",
                ),
                timeout=30.0
            )
            
            content = llm_response.get("content", "")
            # 清理 <think> 标签
            import re
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            
            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                parsed = json.loads(json_match.group())
                summary = parsed.get("summary", "")
                completed_tasks = parsed.get("completed_tasks", [])
                current_task = parsed.get("current_task")
                interrupt_point = parsed.get("interrupt_point", "")
                key_findings = parsed.get("key_findings", [])
        except asyncio.TimeoutError:
            logger.warning(f"Archive summary LLM timed out (30s) for archive {archive_id}")
            summary = f"归档包含 {archive.message_count} 条对话，请查看操作历史了解详情。"
        except Exception as e:
            logger.warning(f"Archive summary LLM failed for archive {archive_id}: {e}")
            summary = f"归档包含 {archive.message_count} 条对话，请查看操作历史了解详情。"
        
        # 更新归档记录
        archive.summary = summary
        archive.completed_tasks = completed_tasks
        archive.current_task = current_task
        archive.interrupt_point = interrupt_point
        archive.key_findings = key_findings
        
        await self.db.commit()
        logger.info(f"Generated archive summary for archive {archive_id}")
    
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
                "archived_at": a.archived_at.isoformat() if a.archived_at else None,
            }
            for a in archives
        ]
    
    async def delete_archive(self, archive_id: int) -> bool:
        """删除归档"""
        result = await self.db.execute(
            delete(ConversationArchive)
            .where(
                ConversationArchive.id == archive_id,
                ConversationArchive.user_id == self.user_id
            )
        )
        await self.db.commit()
        return result.rowcount > 0
    
    async def get_archive(self, archive_id: int) -> Optional[Dict]:
        """获取单个归档的完整信息"""
        result = await self.db.execute(
            select(ConversationArchive).where(
                ConversationArchive.id == archive_id,
                ConversationArchive.user_id == self.user_id
            )
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
            "archived_at": a.archived_at.isoformat() if a.archived_at else None,
        }
    
    async def get_project_archives_summary(self) -> str:
        """获取项目归档摘要（用于注入 AI 上下文）"""
        if not self.project_id:
            return ""
        
        result = await self.db.execute(
            select(ConversationArchive)
            .where(ConversationArchive.project_id == self.project_id)
            .order_by(ConversationArchive.archived_at.desc())
            .limit(3)
        )
        archives = result.scalars().all()
        
        if not archives:
            return ""
        
        parts = []
        for a in archives:
            lines = [f"【{a.title}】{a.summary}"]
            if a.completed_tasks:
                tasks_str = "; ".join(
                    f"{t.get('task', '')}({t.get('result', '')})" 
                    for t in a.completed_tasks[:3]
                )
                lines.append(f"  已完成: {tasks_str}")
            if a.current_task:
                ct = a.current_task
                lines.append(f"  进行中: {ct.get('task', '')} - {ct.get('progress', '')}")
            if a.interrupt_point:
                lines.append(f"  中断点: {a.interrupt_point}")
            if a.key_findings:
                lines.append(f"  关键发现: {', '.join(a.key_findings[:3])}")
            parts.append("\n".join(lines))
        
        return "\n\n".join(parts)
    
    # ==================== 线程管理 ====================
    
    async def create_thread(self, title: str = None, parent_thread_id: int = None) -> int:
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
            title=title or f"对话 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            parent_thread_id=parent_thread_id,
            is_active=True,
        )
        self.db.add(thread)
        await self.db.flush()
        await self.db.commit()
        
        logger.info(f"Created thread {thread.id} with parent {parent_thread_id}")
        return thread.id
    
    async def list_threads(self, limit: int = 20) -> List[Dict]:
        """列出用户的线程"""
        result = await self.db.execute(
            select(ConversationThread)
            .where(ConversationThread.user_id == self.user_id)
            .order_by(ConversationThread.updated_at.desc())
            .limit(limit)
        )
        threads = result.scalars().all()
        
        return [
            {
                "id": t.id,
                "title": t.title,
                "parent_thread_id": t.parent_thread_id,
                "is_active": t.is_active,
                "is_archived": t.is_archived,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in threads
        ]
    
    async def get_thread(self, thread_id: int) -> Optional[Dict]:
        """获取线程详情"""
        result = await self.db.execute(
            select(ConversationThread)
            .where(
                ConversationThread.id == thread_id,
                ConversationThread.user_id == self.user_id
            )
        )
        thread = result.scalar_one_or_none()
        
        if not thread:
            return None
        
        return {
            "id": thread.id,
            "title": thread.title,
            "parent_thread_id": thread.parent_thread_id,
            "is_active": thread.is_active,
            "is_archived": thread.is_archived,
            "created_at": thread.created_at.isoformat() if thread.created_at else None,
            "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
        }
    
    async def delete_thread(self, thread_id: int) -> bool:
        """删除线程"""
        result = await self.db.execute(
            delete(ConversationThread)
            .where(
                ConversationThread.id == thread_id,
                ConversationThread.user_id == self.user_id
            )
        )
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
                ConversationHistory.user_id == self.user_id
            )
            .order_by(ConversationHistory.created_at.asc())
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
        
        # 获取该线程的归档摘要（如果有）
        archive_result = await self.db.execute(
            select(ConversationArchive)
            .where(
                ConversationArchive.thread_id == thread_id,
                ConversationArchive.user_id == self.user_id
            )
            .order_by(ConversationArchive.archived_at.desc())
            .limit(1)
        )
        archive = archive_result.scalar_one_or_none()
        
        return {
            "thread": thread,
            "conversation_history": conversation_history,
            "archive_summary": archive.summary if archive else None,
            "message_count": len(histories),
        }


# 全局单例工厂函数
def get_context_manager(db: AsyncSession, user_id: int, project_id: int = None, thread_id: int = None) -> ContextManager:
    """获取上下文管理器实例"""
    return ContextManager(db, user_id, project_id, thread_id)
