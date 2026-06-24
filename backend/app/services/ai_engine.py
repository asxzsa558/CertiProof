"""
AI 决策引擎 - 使用 LLM 理解用户需求，生成执行计划
参考 Claude Code 的设计，让 AI 自己理解用户需求，决定调用哪些能力
"""

import json
import logging
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_service import llm_service
from app.services.capability_registry import capability_registry

logger = logging.getLogger(__name__)


# AI 决策系统提示（精简版）
AI_DECISION_SYSTEM_PROMPT = """你是 VeriSure 智能合规验证助手。理解用户需求，调用能力完成任务。

## 能力列表
{capabilities}

## 上下文
- 项目: {current_project}
- 资产: {project_assets}{archive_context}

## 规则
1. 回顾性词语（"之前"、"刚才"、"上次"）→ 用 view_* 查缓存，不要重新扫描
2. 缺少必填参数 → 用 chat 询问，不要自动填充
3. 扫描目标 → 优先使用项目资产，支持 IP/域名
4. 纯对话 → 用 chat 直接回复
5. 如果有归档上下文，了解之前的工作进度，用户可能在接续之前的任务

## 输出格式
返回 JSON：
```json
{{"plan": [{{"capability": "能力名", "parameters": {{参数}}}}], "response": "回复"}}
```

## 示例
用户: "扫描端口" → {{"plan": [{{"capability": "scan_ports", "parameters": {{"target": "项目资产"}}}}]}}
用户: "之前扫了什么" → {{"plan": [{{"capability": "view_open_ports", "parameters": {{}}}}]}}
用户: "创建项目"（无名称）→ {{"plan": [{{"capability": "chat", "parameters": {{"message": "请提供项目名称"}}}}]}}
用户: "继续"（有归档上下文）→ 根据归档的中断点继续执行
"""


class AIEngine:
    """AI 决策引擎"""
    
    def __init__(self):
        self.llm_service = llm_service
        self.registry = capability_registry
    
    async def decide(
        self,
        user_input: str,
        context: Dict,
        db: AsyncSession,
        user_id: int = None,
    ) -> Dict:
        """
        分析用户需求，生成执行计划
        
        Args:
            user_input: 用户输入
            context: 上下文信息（对话历史、操作历史、结果缓存等）
            db: 数据库会话
            user_id: 用户 ID（可选，用于记录使用情况）
        
        Returns:
            {
                "plan": [
                    {"capability": "能力名称", "parameters": {...}}
                ],
                "response": "给用户的回复"
            }
        """
        try:
            # 构建归档上下文
            archives_summary = context.get("project_archives_summary", "")
            archive_context = ""
            if archives_summary:
                archive_context = f"\n\n## 项目归档上下文（之前中断的工作）\n{archives_summary}"
            
            # 调用 LLM（使用精简 prompt）
            messages = [
                {"role": "system", "content": AI_DECISION_SYSTEM_PROMPT.format(
                    capabilities=self.registry.format_compact_for_prompt(),
                    current_project=self._format_current_project(context.get("current_project")),
                    project_assets=self._format_project_assets(context.get("project_assets", [])),
                    archive_context=archive_context,
                )},
                {"role": "user", "content": user_input},
            ]
            
            # 如果有用户 ID，记录使用情况
            if user_id:
                import asyncio
                try:
                    response = await asyncio.wait_for(
                        self.llm_service.chat_with_fallback(
                            db=db,
                            user_id=user_id,
                            messages=messages,
                            task_type="chat",
                            temperature=0.1,
                            max_tokens=1000,
                        ),
                        timeout=60.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("AI decision LLM timed out (60s)")
                    raise ValueError("AI decision timed out")
            else:
                # 系统调用，不记录使用情况
                import asyncio
                try:
                    response = await asyncio.wait_for(
                        self._call_llm_direct(db, messages),
                        timeout=60.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("AI decision LLM timed out (60s)")
                    raise ValueError("AI decision timed out")
            
            content = response.get("content", "")
            
            # 解析响应
            plan = self._parse_plan(content)
            
            logger.info(f"AI decision: {plan}")
            
            return plan
            
        except Exception as e:
            logger.error(f"AI decision failed: {e}", exc_info=True)
            
            # 降级处理：返回 chat 能力
            return {
                "plan": [{"capability": "chat", "parameters": {"message": "抱歉，我暂时无法理解你的需求。请尝试更明确地描述。"}}],
                "response": "抱歉，我暂时无法理解你的需求。请尝试更明确地描述。",
            }
    
    async def _call_llm_direct(self, db: AsyncSession, messages: List[Dict]) -> Dict:
        """直接调用 LLM，不记录使用情况"""
        from sqlalchemy import select
        from app.models.model_config import ModelProvider, ModelConfig
        
        # 获取默认模型
        result = await db.execute(
            select(ModelConfig).where(
                ModelConfig.is_default == True,
                ModelConfig.is_active == True
            ).limit(1)
        )
        model_config = result.scalar_one_or_none()
        
        if not model_config:
            # 尝试获取任何可用模型
            result = await db.execute(
                select(ModelConfig).where(ModelConfig.is_active == True).limit(1)
            )
            model_config = result.scalar_one_or_none()
        
        if not model_config:
            raise ValueError("No available models")
        
        # 获取 provider
        result = await db.execute(
            select(ModelProvider).where(ModelProvider.id == model_config.provider_id)
        )
        provider = result.scalar_one_or_none()
        
        if not provider or not provider.is_active:
            raise ValueError(f"Provider for model {model_config.model_name} not available")
        
        # 调用 provider
        adapter = self.llm_service._get_provider(provider)
        return await adapter.chat(messages, model_config.model_name, temperature=0.1, max_tokens=1000)
    
    def _build_prompt(self, user_input: str, context: Dict) -> str:
        """构建 prompt（精简版）"""
        return AI_DECISION_SYSTEM_PROMPT.format(
            capabilities=self.registry.format_compact_for_prompt(),
            current_project=self._format_current_project(context.get("current_project")),
            project_assets=self._format_project_assets(context.get("project_assets", [])),
        )
    
    def _format_conversation_history(self, history: List[Dict]) -> str:
        """格式化对话历史"""
        if not history:
            return "（无对话历史）"
        
        lines = []
        for h in history[-10:]:  # 最近 10 条
            role = "用户" if h["role"] == "user" else "助手"
            lines.append(f"{role}: {h['content']}")
        
        return "\n".join(lines)
    
    def _format_action_history(self, history: List[Dict]) -> str:
        """格式化操作历史"""
        if not history:
            return "（无操作历史）"
        
        lines = []
        for a in history[-5:]:  # 最近 5 个操作
            lines.append(f"- {a['action_type']}: {a['result_summary']} ({a['status']})")
        
        return "\n".join(lines)
    
    def _format_cached_results(self, cache: Dict) -> str:
        """格式化缓存结果"""
        if not cache:
            return "（无缓存结果）"
        
        lines = []
        for key, value in list(cache.items())[:5]:  # 最近 5 个缓存
            lines.append(f"- {key}: {self._summarize_result(value)}")
        
        return "\n".join(lines)
    
    def _format_current_project(self, project: Optional[Dict]) -> str:
        """格式化当前项目"""
        if not project:
            return "（未选择项目）"
        
        return f"项目: {project['name']} (ID: {project['id']}, 等保等级: {project.get('compliance_level', '未知')}, 合规分数: {project.get('compliance_score', '未评分')})"
    
    def _format_project_assets(self, assets: List[Dict]) -> str:
        """格式化项目资产列表"""
        if not assets:
            return "（无项目资产）"
        
        lines = []
        for a in assets:
            asset_type = a.get("type", "IP")
            value = a.get("value", "")
            name = a.get("name", "")
            label = f"{name} ({asset_type})" if name else f"{asset_type}"
            lines.append(f"- {label}: {value}")
        
        return "\n".join(lines)
    
    def _format_project_memory(self, memories: List[Dict]) -> str:
        """格式化项目记忆"""
        if not memories:
            return "（无项目记忆）"
        
        lines = []
        for m in memories[:10]:
            memory_type = m.get("memory_type", "")
            content = m.get("content", "")
            lines.append(f"- [{memory_type}] {content}")
        
        return "\n".join(lines)
    
    def _format_user_memory(self, memories: List[Dict]) -> str:
        """格式化用户记忆"""
        if not memories:
            return "（无用户记忆）"
        
        lines = []
        for m in memories[:10]:
            memory_type = m.get("memory_type", "")
            content = m.get("content", "")
            lines.append(f"- [{memory_type}] {content}")
        
        return "\n".join(lines)
    
    def _summarize_result(self, result: Dict) -> str:
        """简化结果用于上下文"""
        if not result:
            return "无结果"
        
        if "open_ports" in result:
            ports = result.get("open_ports", [])
            return f"发现 {len(ports)} 个开放端口"
        
        if "vulnerabilities" in result:
            vulns = result.get("vulnerabilities", [])
            return f"发现 {len(vulns)} 个漏洞"
        
        if "compliance_score" in result:
            score = result.get("compliance_score")
            return f"合规评分: {score} 分"
        
        return str(result)[:50] + "..." if len(str(result)) > 50 else str(result)
    
    def _parse_plan(self, content: str) -> Dict:
        """解析 LLM 返回的计划"""
        import re
        
        logger.info(f"Raw LLM response: {content[:300]}")
        
        # 清理 <think> 标签
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        
        # 尝试直接解析
        try:
            plan = json.loads(content)
            logger.info(f"Parsed plan (direct): {plan}")
            return self._validate_plan(plan)
        except json.JSONDecodeError:
            pass
        
        # 尝试从 markdown 代码块中提取
        if "```json" in content:
            start = content.find("```json") + 7
            # 跳过可能的换行符
            while start < len(content) and content[start] in '\n\r \t':
                start += 1
            end = content.find("```", start)
            if end > start:
                json_str = content[start:end].strip()
                logger.info(f"Extracted JSON from ```json block (length={len(json_str)})")
                # 尝试提取第一个完整的 JSON 对象
                json_obj_match = re.search(r'\{[\s\S]*\}', json_str)
                if json_obj_match:
                    json_str = json_obj_match.group()
                    try:
                        plan = json.loads(json_str)
                        logger.info(f"Parsed plan (```json): {plan}")
                        return self._validate_plan(plan)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse extracted JSON: {e}")
                        pass
        
        # 尝试从普通代码块中提取
        if "```" in content:
            start = content.find("```") + 3
            # 跳过可能的换行符和 "json" 前缀
            while start < len(content) and content[start] in '\n\r \t':
                start += 1
            if content[start:start+4] == 'json':
                start += 4
                while start < len(content) and content[start] in '\n\r \t':
                    start += 1
            end = content.find("```", start)
            if end > start:
                json_str = content[start:end].strip()
                logger.info(f"Extracted JSON from ``` block (length={len(json_str)})")
                # 尝试提取第一个完整的 JSON 对象
                json_obj_match = re.search(r'\{[\s\S]*\}', json_str)
                if json_obj_match:
                    json_str = json_obj_match.group()
                    try:
                        plan = json.loads(json_str)
                        logger.info(f"Parsed plan (```): {plan}")
                        return self._validate_plan(plan)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse extracted JSON: {e}")
                        pass
        
        # 尝试提取 JSON 对象（即使不在代码块中）
        json_match = re.search(r'\{[\s\S]*"plan"[\s\S]*\}', content)
        if json_match:
            try:
                plan = json.loads(json_match.group())
                logger.info(f"Parsed plan (regex): {plan}")
                return self._validate_plan(plan)
            except json.JSONDecodeError:
                pass
        
        # 解析失败，返回默认
        logger.warning(f"Failed to parse AI plan: {content[:200]}")
        return {
            "plan": [{"capability": "chat", "parameters": {"message": content}}],
            "response": content,
        }
    
    def _validate_plan(self, plan: Dict) -> Dict:
        """验证计划格式"""
        if not isinstance(plan, dict):
            return {
                "plan": [{"capability": "chat", "parameters": {"message": "抱歉，我无法理解你的需求。"}}],
                "response": "抱歉，我无法理解你的需求。",
            }
        
        if "plan" not in plan:
            plan["plan"] = []
        
        if "response" not in plan:
            plan["response"] = ""
        
        # 验证每个能力是否存在
        valid_plan = []
        for step in plan["plan"]:
            if isinstance(step, dict) and "capability" in step:
                capability = self.registry.get(step["capability"])
                if capability:
                    valid_plan.append(step)
                else:
                    logger.warning(f"Unknown capability: {step['capability']}")
        
        plan["plan"] = valid_plan
        
        return plan


# 全局单例
ai_engine = AIEngine()
