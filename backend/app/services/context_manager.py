"""
上下文管理器 - 管理对话历史、操作历史、结果缓存、项目记忆、用户记忆
参考 Claude Code 的多层记忆系统设计
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from app.models.context import (
    ConversationHistory,
    ActionHistory,
    ResultCache,
    ProjectMemory,
    UserMemory,
)

logger = logging.getLogger(__name__)


class ContextManager:
    """统一的上下文管理器"""
    
    # 上下文 token 限制
    MAX_CONVERSATION_TOKENS = 50000  # 对话历史最大 token 数
    MAX_ACTION_HISTORY = 50  # 最大操作历史记录数
    MAX_CACHE_ENTRIES = 100  # 最大缓存条目数
    
    def __init__(self, db: AsyncSession, user_id: int, project_id: int = None):
        self.db = db
        self.user_id = user_id
        self.project_id = project_id
    
    async def build_context(self) -> Dict:
        """
        构建完整上下文
        
        Returns:
            {
                "conversation_history": [...],
                "action_history": [...],
                "result_cache": {...},
                "project_memory": [...],
                "user_memory": [...],
                "current_project": {...},
                "project_assets": [...],
            }
        """
        context = {
            "conversation_history": await self._get_conversation_history(),
            "action_history": await self._get_action_history(),
            "result_cache": await self._get_result_cache(),
            "project_memory": await self._get_project_memory(),
            "user_memory": await self._get_user_memory(),
            "current_project": await self._get_current_project(),
            "project_assets": await self._get_project_assets(),
        }
        
        return context
    
    async def _get_conversation_history(self, limit: int = 20) -> List[Dict]:
        """获取最近的对话历史"""
        result = await self.db.execute(
            select(ConversationHistory)
            .where(ConversationHistory.user_id == self.user_id)
            .order_by(ConversationHistory.created_at.desc())
            .limit(limit)
        )
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
            parameters=parameters,
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
        result = await self.db.execute(
            select(ResultCache).where(
                ResultCache.user_id == self.user_id,
                ResultCache.cache_key == cache_key,
            )
        )
        existing = result.scalar_one_or_none()
        
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
        result = await self.db.execute(
            select(ResultCache).where(
                ResultCache.user_id == self.user_id,
                ResultCache.cache_key == cache_key,
                (ResultCache.expires_at > datetime.utcnow()) | (ResultCache.expires_at == None),
            )
        )
        cache = result.scalar_one_or_none()
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
            .order_by(ConversationHistory.created_at.desc())
        )
        histories = result.scalars().all()
        
        total_tokens = sum(h.tokens_used or 0 for h in histories)
        
        if total_tokens <= self.MAX_CONVERSATION_TOKENS:
            return
        
        logger.info(f"Conversation history exceeds limit ({total_tokens} tokens), compressing...")
        
        old_histories = histories[-50:] if len(histories) >= 50 else histories[:-20]
        if not old_histories:
            return
        
        old_histories = sorted(old_histories, key=lambda h: h.created_at)
        
        conversation_text = "\n".join(
            f"{'用户' if h.role == 'user' else '助手'}: {h.content}"
            for h in old_histories
        )
        
        try:
            from app.services.llm_service import llm_service
            
            summary_response = await llm_service.chat_with_fallback(
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
            )
            summary = summary_response.get("content", "")
        except Exception as e:
            logger.warning(f"LLM summarization failed, using simple truncation: {e}")
            summary = f"[历史对话摘要] 共 {len(old_histories)} 条对话，涉及{len(set(h.role for h in old_histories))}个角色。"
        
        if not summary:
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
        
        old_ids = [h.id for h in old_histories]
        if old_ids:
            await self.db.execute(
                delete(ConversationHistory).where(ConversationHistory.id.in_(old_ids))
            )
            await self.db.flush()
            logger.info(f"Compressed {len(old_ids)} old conversation records")
    
    async def _auto_cleanup(self):
        """自动清理过旧的历史记录"""
        conv_count = await self.db.execute(
            select(func.count(ConversationHistory.id))
            .where(ConversationHistory.user_id == self.user_id)
        )
        conv_total = conv_count.scalar() or 0
        
        if conv_total > 200:
            excess = conv_total - 200
            oldest = await self.db.execute(
                select(ConversationHistory.id)
                .where(ConversationHistory.user_id == self.user_id)
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
        
        if action_total > 100:
            excess = action_total - 100
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
        """估算文本的 token 数（简单估算：1 token ≈ 4 字符）"""
        return len(text) // 4


# 全局单例工厂函数
def get_context_manager(db: AsyncSession, user_id: int, project_id: int = None) -> ContextManager:
    """获取上下文管理器实例"""
    return ContextManager(db, user_id, project_id)
