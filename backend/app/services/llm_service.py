"""
LLM Service - VeriSure
Unified LLM interface with multi-provider support and fallback strategy.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
from abc import ABC, abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.model_config import ModelProvider, ModelConfig, ModelUsage, ProviderType
from app.core.config import settings

logger = logging.getLogger(__name__)


# --- Provider Adapters ---

class BaseProvider(ABC):
    """Base class for LLM providers"""
    
    def __init__(self, api_key: str, api_base: Optional[str] = None):
        self.api_key = api_key
        self.api_base = api_base
    
    @abstractmethod
    async def chat(self, messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        """Send chat completion request"""
        pass
    
    @abstractmethod
    async def test_connection(self, model_name: str = None) -> bool:
        """Test if the provider connection works"""
        pass

    async def embed(self, inputs: List[str], model_name: str, dimensions: int) -> List[List[float]]:
        raise ValueError("This provider does not support embeddings")


class OpenAIProvider(BaseProvider):
    """OpenAI API adapter - 自动 prompt cache (无 cache_control, OpenAI 自动处理)"""

    async def chat(self, messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.openai.com/v1",
                timeout=120.0,
                max_retries=2
            )

            # 合并分层 system 消息（OpenAI 自动 cache，>1024 tokens 自动启用）
            processed_messages = self._merge_layered_messages(messages)

            response = await client.chat.completions.create(
                model=model_name,
                messages=processed_messages,
                **kwargs
            )

            # 提取 OpenAI 自己的 cache 命中信息（如果 SDK 支持）
            usage = response.usage
            cached_tokens = getattr(usage, 'cached_tokens', 0) or 0

            return {
                "content": response.choices[0].message.content,
                "finish_reason": response.choices[0].finish_reason,
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "cached_tokens": cached_tokens,
                },
                "cache_hit": cached_tokens > 0,
                "model": response.model,
                "provider": "openai"
            }
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    def _merge_layered_messages(self, messages: List[Dict]) -> List[Dict]:
        """合并 stable + variable 为单个 system 消息（OpenAI 不支持分层）"""
        result = []
        for msg in messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, dict) and "stable" in content:
                    # 合并 stable + variable
                    merged = content.get("stable", "") + "\n\n" + content.get("variable", "")
                    result.append({"role": "system", "content": merged})
                else:
                    result.append(msg)
            else:
                result.append(msg)
        return result
    
    async def test_connection(self, model_name: str = None) -> bool:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
                timeout=30.0,
                max_retries=1
            )
            await client.models.list()
            return True
        except Exception as e:
            logger.error(f"OpenAI connection test failed: {e}")
            return False

    async def embed(self, inputs: List[str], model_name: str, dimensions: int) -> List[List[float]]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.api_key or "local",
            base_url=self.api_base or "https://api.openai.com/v1",
            timeout=120.0,
            max_retries=2,
        )
        response = await client.embeddings.create(model=model_name, input=inputs, dimensions=dimensions)
        return [list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]


class AnthropicProvider(BaseProvider):
    """Anthropic Claude API adapter - 支持 prompt cache"""

    async def chat(self, messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.anthropic.com"
            )

            # Convert OpenAI format to Anthropic format
            system_blocks = None
            chat_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    content = msg["content"]
                    # 支持分层结构 {"stable": "...", "variable": "..."}
                    if isinstance(content, dict) and "stable" in content:
                        system_blocks = self._build_cached_system_blocks(content)
                    else:
                        system_blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
                else:
                    chat_messages.append(msg)

            response = await client.messages.create(
                model=model_name,
                messages=chat_messages,
                system=system_blocks or "",
                max_tokens=kwargs.get("max_tokens", 4096),
                **{k: v for k, v in kwargs.items() if k != "max_tokens"}
            )

            # 提取 cache 命中信息
            usage = response.usage
            cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
            cache_creation = getattr(usage, 'cache_creation_input_tokens', 0) or 0

            return {
                "content": response.content[0].text,
                "finish_reason": getattr(response, "stop_reason", None),
                "usage": {
                    "prompt_tokens": usage.input_tokens,
                    "completion_tokens": usage.output_tokens,
                    "total_tokens": usage.input_tokens + usage.output_tokens,
                    "cache_read_tokens": cache_read,
                    "cache_creation_tokens": cache_creation,
                },
                "cache_hit": cache_read > 0,
                "model": response.model,
                "provider": "anthropic"
            }
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise

    def _build_cached_system_blocks(self, content: Dict) -> List[Dict]:
        """
        构建带 cache_control 的 system blocks

        Layer 1 (stable) → 加 cache_control: ephemeral
        Layer 2 (variable) → 不缓存
        """
        blocks = []

        stable = content.get("stable", "")
        variable = content.get("variable", "")

        # Stable layer — 标记为可缓存（Anthropic 要求 >= 1024 tokens）
        if stable and len(stable) >= 100:  # 保守估计 100 字符 ≈ 50 tokens
            blocks.append({
                "type": "text",
                "text": stable,
                "cache_control": {"type": "ephemeral"}
            })
        elif stable:
            blocks.append({"type": "text", "text": stable})

        # Variable layer — 不缓存
        if variable:
            blocks.append({"type": "text", "text": variable})

        return blocks
    
    async def test_connection(self, model_name: str = None) -> bool:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.anthropic.com"
            )
            await client.messages.create(
                model=model_name or "claude-3-haiku-20240307",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=10
            )
            return True
        except Exception as e:
            logger.error(f"Anthropic connection test failed: {e}")
            return False


class OllamaProvider(BaseProvider):
    """Ollama local LLM adapter - 本地推理无 cache"""

    async def chat(self, messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        try:
            import httpx

            api_base = self.api_base or "http://localhost:11434"

            # 合并分层 system 消息
            processed = self._merge_layered_messages(messages)

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{api_base}/api/chat",
                    json={
                        "model": model_name,
                        "messages": processed,
                        "stream": False,
                        **kwargs
                    }
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "content": data["message"]["content"],
                    "finish_reason": data.get("done_reason"),
                    "usage": {
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "completion_tokens": data.get("eval_count", 0),
                        "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                    },
                    "cache_hit": False,
                    "model": model_name,
                    "provider": "ollama"
                }
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            raise

    def _merge_layered_messages(self, messages: List[Dict]) -> List[Dict]:
        """合并分层 system 消息为字符串"""
        result = []
        for msg in messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, dict) and "stable" in content:
                    merged = content.get("stable", "") + "\n\n" + content.get("variable", "")
                    result.append({"role": "system", "content": merged})
                else:
                    result.append(msg)
            else:
                result.append(msg)
        return result

    async def test_connection(self, model_name: str = None) -> bool:
        try:
            import httpx
            api_base = self.api_base or "http://localhost:11434"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{api_base}/api/tags")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama connection test failed: {e}")
            return False

    async def embed(self, inputs: List[str], model_name: str, dimensions: int) -> List[List[float]]:
        import httpx

        api_base = (self.api_base or "http://localhost:11434").rstrip("/")
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{api_base}/api/embed",
                json={"model": model_name, "input": inputs, "dimensions": dimensions, "truncate": True},
            )
            response.raise_for_status()
            return response.json().get("embeddings") or []


# --- LLM Service ---

class LLMService:
    """Unified LLM service with multi-provider support"""
    
    def __init__(self):
        self.providers: Dict[str, BaseProvider] = {}
    
    def _get_provider(self, provider: ModelProvider) -> BaseProvider:
        """Get or create provider adapter"""
        cache_key = f"{provider.id}_{provider.provider_type.value}"
        
        if cache_key not in self.providers:
            if provider.provider_type == ProviderType.OPENAI:
                self.providers[cache_key] = OpenAIProvider(provider.api_key, provider.api_base)
            elif provider.provider_type == ProviderType.ANTHROPIC:
                self.providers[cache_key] = AnthropicProvider(provider.api_key, provider.api_base)
            elif provider.provider_type == ProviderType.OLLAMA:
                self.providers[cache_key] = OllamaProvider(provider.api_key or "", provider.api_base)
            elif provider.provider_type == ProviderType.AZURE:
                # Azure uses OpenAI SDK with different base URL
                self.providers[cache_key] = OpenAIProvider(provider.api_key, provider.api_base)
            elif provider.provider_type == ProviderType.CUSTOM:
                # Custom providers use OpenAI-compatible API
                self.providers[cache_key] = OpenAIProvider(provider.api_key, provider.api_base)
            else:
                raise ValueError(f"Unknown provider type: {provider.provider_type}")
        
        return self.providers[cache_key]
    
    async def get_model_config(self, db: AsyncSession, model_id: int) -> Optional[ModelConfig]:
        """Get model configuration by ID"""
        result = await db.execute(
            select(ModelConfig).where(ModelConfig.id == model_id, ModelConfig.is_active == True)
        )
        return result.scalar_one_or_none()
    
    async def get_default_model(self, db: AsyncSession) -> Optional[ModelConfig]:
        """Get default model configuration"""
        result = await db.execute(
            select(ModelConfig)
            .where(ModelConfig.is_default == True, ModelConfig.is_active == True)
            .order_by(ModelConfig.priority)
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def get_available_models(
        self, 
        db: AsyncSession, 
        task_type: Optional[str] = None
    ) -> List[ModelConfig]:
        """Get list of available models, optionally filtered by capability"""
        result = await db.execute(
            select(ModelConfig)
            .where(ModelConfig.is_active == True)
            .order_by(ModelConfig.priority)
        )
        models = result.scalars().all()
        
        if task_type:
            models = [m for m in models if m.capabilities and task_type in m.capabilities]
        
        return models
    
    async def chat(
        self,
        db: AsyncSession,
        user_id: int,
        messages: List[Dict],
        model_id: Optional[int] = None,
        task_type: str = "chat",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send chat request using specified or default model
        """
        # Get model config
        if model_id:
            model_config = await self.get_model_config(db, model_id)
            if not model_config:
                raise ValueError(f"Model {model_id} not found or inactive")
        else:
            model_config = await self.get_default_model(db)
            if not model_config:
                raise ValueError("No default model configured")
        
        # Get provider
        result = await db.execute(
            select(ModelProvider).where(ModelProvider.id == model_config.provider_id)
        )
        provider = result.scalar_one_or_none()
        if not provider or not provider.is_active:
            raise ValueError(f"Provider for model {model_config.model_name} not available")
        
        # Call provider
        adapter = self._get_provider(provider)
        try:
            response = await adapter.chat(messages, model_config.model_name, **kwargs)
            
            # Record usage
            await self.record_usage(
                db=db,
                user_id=user_id,
                model_config_id=model_config.id,
                prompt_tokens=response["usage"]["prompt_tokens"],
                completion_tokens=response["usage"]["completion_tokens"],
                task_type=task_type,
            )
            
            response["model_config_id"] = model_config.id
            response["model_name"] = model_config.model_name
            response["display_name"] = model_config.display_name
            
            return response
            
        except Exception as e:
            logger.error(f"Chat request failed: {e}")
            raise
    
    async def chat_with_fallback(
        self,
        db: AsyncSession,
        user_id: int,
        messages: List[Dict],
        task_type: str = "chat",
        timeout: float = 60.0,
        response_validator: Optional[Callable[[Dict[str, Any]], None]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send chat request with automatic fallback to backup models.
        
        Args:
            timeout: 整体超时时间（秒），默认 60 秒
        """
        try:
            return await asyncio.wait_for(
                self._chat_with_fallback_impl(
                    db,
                    user_id,
                    messages,
                    task_type,
                    response_validator=response_validator,
                    **kwargs,
                ),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"LLM call timed out after {timeout}s")
            raise ValueError(f"LLM call timed out after {timeout}s")

    async def embed_with_fallback(
        self,
        db: AsyncSession,
        inputs: List[str],
        dimensions: int,
        timeout: float = 180.0,
        input_type: str = "passage",
    ) -> Dict[str, Any]:
        if not inputs:
            return {"embeddings": [], "model": None}

        async def execute():
            models = await self.get_available_models(db, "embedding")
            errors = []
            for model_config in models:
                provider = (await db.execute(
                    select(ModelProvider).where(
                        ModelProvider.id == model_config.provider_id,
                        ModelProvider.is_active.is_(True),
                    )
                )).scalar_one_or_none()
                if not provider:
                    continue
                try:
                    vectors = await self._get_provider(provider).embed(inputs, model_config.model_name, dimensions)
                    if len(vectors) != len(inputs) or any(len(vector) != dimensions for vector in vectors):
                        raise ValueError(f"向量维度必须为 {dimensions}，模型返回结果不匹配")
                    return {
                        "embeddings": vectors,
                        "model": model_config.model_name,
                        "model_config_id": model_config.id,
                        "provider": provider.name,
                    }
                except Exception as exc:
                    errors.append(f"{model_config.display_name}: {exc}")
            try:
                import httpx

                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{settings.EMBEDDING_SERVER_URL}/embed",
                        json={
                            "inputs": inputs,
                            "input_type": input_type,
                            "dimensions": dimensions,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                vectors = payload.get("embeddings") or []
                if len(vectors) != len(inputs) or any(len(vector) != dimensions for vector in vectors):
                    raise ValueError(f"本地向量服务返回结果不是 {dimensions} 维")
                return {
                    "embeddings": vectors,
                    "model": payload.get("model") or settings.DOCUMENT_EMBEDDING_MODEL,
                    "model_config_id": None,
                    "provider": payload.get("runtime") or "local",
                }
            except Exception as exc:
                errors.append(f"本地向量服务: {exc}")
            raise ValueError("全部向量模型不可用：" + "；".join(errors))

        try:
            return await asyncio.wait_for(execute(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ValueError(f"向量模型调用超过 {timeout:.0f} 秒") from exc
    
    async def _chat_with_fallback_impl(
        self,
        db: AsyncSession,
        user_id: int,
        messages: List[Dict],
        task_type: str = "chat",
        response_validator: Optional[Callable[[Dict[str, Any]], None]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Internal implementation of chat_with_fallback"""
        models = await self.get_available_models(db, task_type)
        if not models and task_type != "chat":
            models = await self.get_available_models(db, "chat")
        if not models:
            models = await self.get_available_models(db)
        
        if not models:
            raise ValueError("No available models for this task type")
        
        last_error = None
        for model_config in models:
            try:
                result = await db.execute(
                    select(ModelProvider).where(ModelProvider.id == model_config.provider_id)
                )
                provider = result.scalar_one_or_none()
                
                if not provider or not provider.is_active:
                    continue
                
                adapter = self._get_provider(provider)
                response = await adapter.chat(messages, model_config.model_name, **kwargs)
                
                # Record usage
                await self.record_usage(
                    db=db,
                    user_id=user_id,
                    model_config_id=model_config.id,
                    prompt_tokens=response["usage"]["prompt_tokens"],
                    completion_tokens=response["usage"]["completion_tokens"],
                    task_type=task_type,
                )
                if response_validator:
                    response_validator(response)
                
                response["model_config_id"] = model_config.id
                response["model_name"] = model_config.model_name
                response["display_name"] = model_config.display_name
                response["fallback_used"] = model_config != models[0]
                
                return response
                
            except Exception as e:
                logger.warning(f"Model {model_config.model_name} failed: {e}, trying next...")
                last_error = e
                continue
        
        raise ValueError(f"All models failed. Last error: {last_error}")
    
    async def record_usage(
        self,
        db: AsyncSession,
        user_id: int,
        model_config_id: int,
        prompt_tokens: int,
        completion_tokens: int,
        task_type: str = "chat",
    ):
        """Record model usage for analytics"""
        usage = ModelUsage(
            user_id=user_id,
            model_config_id=model_config_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            task_type=task_type
        )
        db.add(usage)
        await db.commit()
    
    async def test_model(self, db: AsyncSession, model_id: int) -> Dict[str, Any]:
        """Test if a model is accessible"""
        model_config = await self.get_model_config(db, model_id)
        if not model_config:
            return {"success": False, "error": "Model not found"}
        
        result = await db.execute(
            select(ModelProvider).where(ModelProvider.id == model_config.provider_id)
        )
        provider = result.scalar_one_or_none()
        
        if not provider:
            return {"success": False, "error": "Provider not found"}
        
        adapter = self._get_provider(provider)
        try:
            if "embedding" in (model_config.capabilities or []):
                vectors = await adapter.embed(
                    ["CertiProof 文档语义检索连通性测试"],
                    model_config.model_name,
                    settings.DOCUMENT_EMBEDDING_DIMENSION,
                )
                if len(vectors) != 1 or len(vectors[0]) != settings.DOCUMENT_EMBEDDING_DIMENSION:
                    raise ValueError(
                        f"向量模型必须返回 {settings.DOCUMENT_EMBEDDING_DIMENSION} 维向量"
                    )
                return {
                    "success": True,
                    "model_name": model_config.model_name,
                    "provider": provider.name,
                    "capability": "embedding",
                    "dimensions": len(vectors[0]),
                }
            success = await adapter.test_connection(model_name=model_config.model_name)
            if not success:
                return {
                    "success": False,
                    "error": "Connection failed. Please check API Key and API Base URL.",
                    "model_name": model_config.model_name,
                    "provider": provider.name
                }
            return {
                "success": True,
                "model_name": model_config.model_name,
                "provider": provider.name
            }
        except Exception as e:
            logger.error(f"Model test failed: {e}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}",
                "model_name": model_config.model_name,
                "provider": provider.name
            }


# Singleton instance
llm_service = LLMService()
