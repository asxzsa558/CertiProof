"""
LLM Service - VeriSure
Unified LLM interface with multi-provider support and fallback strategy.
"""

import asyncio
import json
import logging
import re
from typing import Optional, List, Dict, Any, Callable, Type, Literal
from datetime import datetime
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.model_config import InferenceRuntime, ModelProvider, ModelConfig, ModelUsage, ProviderType
from app.core.config import settings
from app.core.secret_box import decrypt_secret
from app.services.config_service import get_config_service
from app.services.runtime_resources import gpu_available, runtime_status as resource_runtime_status

logger = logging.getLogger(__name__)


class ModelHealthContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


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

    @staticmethod
    def _build_chat_payload(messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        """Translate the shared generation options to Ollama's native API."""
        options = dict(kwargs.pop("options", {}) or {})
        aliases = {
            "max_tokens": "num_predict",
            "max_completion_tokens": "num_predict",
            "temperature": "temperature",
            "top_p": "top_p",
            "top_k": "top_k",
            "seed": "seed",
            "stop": "stop",
            "repeat_penalty": "repeat_penalty",
            "num_ctx": "num_ctx",
        }
        for source, target in aliases.items():
            value = kwargs.pop(source, None)
            if value is not None:
                options[target] = value

        response_format = kwargs.pop("response_format", None)
        output_format = kwargs.pop("format", None)
        if isinstance(response_format, dict):
            if response_format.get("type") == "json_object":
                output_format = "json"
            elif response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema") or {}
                output_format = json_schema.get("schema") or json_schema

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "think": kwargs.pop("think", settings.OLLAMA_THINK),
            "keep_alive": kwargs.pop("keep_alive", settings.OLLAMA_KEEP_ALIVE),
        }
        if options:
            payload["options"] = options
        if output_format:
            payload["format"] = output_format
        for key in ("tools", "logprobs", "top_logprobs"):
            value = kwargs.pop(key, None)
            if value is not None:
                payload[key] = value
        return payload

    async def chat(self, messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        try:
            import httpx

            api_base = (self.api_base or "http://localhost:11434").rstrip("/")

            # 合并分层 system 消息
            processed = self._merge_layered_messages(messages)

            payload = self._build_chat_payload(processed, model_name, **kwargs)
            async with httpx.AsyncClient(timeout=settings.OLLAMA_REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{api_base}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                message = data.get("message") or {}
                content = message.get("content") or ""

                return {
                    "content": content,
                    "thinking_only": not content.strip() and bool(str(message.get("thinking") or "").strip()),
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
            api_base = (self.api_base or "http://localhost:11434").rstrip("/")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{api_base}/api/tags")
                if response.status_code != 200:
                    return False
                if not model_name:
                    return True
                installed = {
                    str(item.get("name") or item.get("model") or "")
                    for item in response.json().get("models", [])
                }
                return model_name in installed
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
        self._model_active = 0
        self._model_condition = asyncio.Condition()

    @staticmethod
    def _provider_runtime(provider: ModelProvider) -> str:
        if provider.provider_type == ProviderType.OLLAMA:
            return InferenceRuntime.OLLAMA.value
        return getattr(provider, "runtime_kind", None) or InferenceRuntime.CLOUD.value

    @staticmethod
    def runtime_preference(policy: str) -> List[str]:
        if policy == "auto":
            primary = InferenceRuntime.VLLM.value if gpu_available() else InferenceRuntime.CLOUD.value
        elif policy == "local":
            primary = InferenceRuntime.VLLM.value if gpu_available() else InferenceRuntime.LLAMA_CPP.value
        else:
            primary = policy
        fallback = ["cloud", "vllm", "llama_cpp", "ollama"]
        return [primary, *(item for item in fallback if item != primary)]

    async def _rank_models_for_runtime(
        self,
        db: AsyncSession,
        models: List[ModelConfig],
    ) -> List[ModelConfig]:
        if not models:
            return []
        providers = (await db.execute(select(ModelProvider).where(
            ModelProvider.id.in_({model.provider_id for model in models}),
            ModelProvider.is_active.is_(True),
        ))).scalars().all()
        runtime_by_provider = {provider.id: self._provider_runtime(provider) for provider in providers}
        policy = await get_config_service(db).get("runtime.model_policy", settings.LLM_RUNTIME_POLICY)
        preference = {runtime: index for index, runtime in enumerate(self.runtime_preference(policy))}
        return sorted(
            (model for model in models if model.provider_id in runtime_by_provider),
            key=lambda model: (
                preference.get(runtime_by_provider[model.provider_id], len(preference)),
                not bool(model.is_default),
                model.priority,
                model.id,
            ),
        )

    @asynccontextmanager
    async def _model_slot(self, limit: int):
        async with self._model_condition:
            await self._model_condition.wait_for(lambda: self._model_active < max(1, limit))
            self._model_active += 1
        try:
            yield
        finally:
            async with self._model_condition:
                self._model_active -= 1
                self._model_condition.notify_all()

    def _get_provider(self, provider: ModelProvider) -> BaseProvider:
        """Get or create provider adapter"""
        cache_key = f"{provider.id}_{provider.provider_type.value}"
        
        if cache_key not in self.providers:
            api_key = decrypt_secret(provider.api_key)
            if not api_key and self._provider_runtime(provider) in {
                InferenceRuntime.VLLM.value,
                InferenceRuntime.LLAMA_CPP.value,
            }:
                api_key = "local"
            if provider.provider_type == ProviderType.OPENAI:
                self.providers[cache_key] = OpenAIProvider(api_key, provider.api_base)
            elif provider.provider_type == ProviderType.ANTHROPIC:
                self.providers[cache_key] = AnthropicProvider(api_key, provider.api_base)
            elif provider.provider_type == ProviderType.OLLAMA:
                self.providers[cache_key] = OllamaProvider(api_key, provider.api_base)
            elif provider.provider_type == ProviderType.AZURE:
                # Azure uses OpenAI SDK with different base URL
                self.providers[cache_key] = OpenAIProvider(api_key, provider.api_base)
            elif provider.provider_type == ProviderType.CUSTOM:
                # Custom providers use OpenAI-compatible API
                self.providers[cache_key] = OpenAIProvider(api_key, provider.api_base)
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
        """Get the highest-ranked model for the active deployment policy."""
        result = await db.execute(
            select(ModelConfig)
            .where(ModelConfig.is_active == True)
            .order_by(ModelConfig.priority, ModelConfig.id)
        )
        models = await self._rank_models_for_runtime(db, list(result.scalars().all()))
        return models[0] if models else None
    
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
        response_validator: Optional[Callable[[Dict[str, Any]], Any]] = None,
        response_model: Optional[Type[BaseModel]] = None,
        business_validator: Optional[Callable[[BaseModel], None]] = None,
        max_attempts_per_model: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send chat request with automatic fallback to backup models.
        
        Args:
            timeout: 整体超时时间（秒），默认 60 秒
        """
        models = await self._candidate_models(db, task_type)
        structured_schema = response_model.model_json_schema() if response_model else None
        validator = response_validator
        if response_model:
            messages = self._with_schema_instruction(messages, structured_schema)
            validator = self._structured_validator(response_model, business_validator, response_validator)
        attempts = max_attempts_per_model or (3 if response_model else 1)
        providers = (await db.execute(
            select(ModelProvider).where(
                ModelProvider.id.in_({model.provider_id for model in models}),
                ModelProvider.is_active.is_(True),
            )
        )).scalars().all() if models else []
        local_cpu_runtime = any(
            self._provider_runtime(provider) in {InferenceRuntime.OLLAMA.value, InferenceRuntime.LLAMA_CPP.value}
            for provider in providers
        )
        resources = await resource_runtime_status(db)
        retry_timeout = timeout * attempts if response_model else timeout
        effective_timeout = (
            max(retry_timeout, settings.OLLAMA_REQUEST_TIMEOUT_SECONDS)
            if local_cpu_runtime
            else retry_timeout
        )
        try:
            async with self._model_slot(resources["limits"]["model"]):
                return await asyncio.wait_for(
                    self._chat_with_fallback_impl(
                        db,
                        user_id,
                        messages,
                        task_type,
                        models=models,
                        response_validator=validator,
                        max_attempts_per_model=attempts,
                        structured_schema=structured_schema,
                        structured_name=response_model.__name__ if response_model else None,
                        **kwargs,
                    ),
                    timeout=effective_timeout,
                )
        except asyncio.TimeoutError:
            logger.error(f"LLM call timed out after {effective_timeout}s")
            raise ValueError(f"LLM call timed out after {effective_timeout}s")

    @staticmethod
    def _with_schema_instruction(messages: List[Dict], schema: Dict[str, Any]) -> List[Dict]:
        instruction = (
            "\n\n只返回一个符合以下 JSON Schema 的 JSON 对象，不得输出 Markdown、解释或思考过程：\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
        result = [dict(message) for message in messages]
        for message in result:
            if message.get("role") != "system":
                continue
            content = message.get("content")
            if isinstance(content, dict) and "stable" in content:
                message["content"] = {**content, "variable": str(content.get("variable") or "") + instruction}
            else:
                message["content"] = str(content or "") + instruction
            return result
        return [{"role": "system", "content": instruction.strip()}, *result]

    def _structured_validator(
        self,
        response_model: Type[BaseModel],
        business_validator: Optional[Callable[[BaseModel], None]],
        response_validator: Optional[Callable[[Dict[str, Any]], Any]],
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        def validate(response: Dict[str, Any]) -> Dict[str, Any]:
            if response.get("thinking_only"):
                raise ValueError("模型只返回了思考过程，没有最终答案")
            if response.get("finish_reason") in {"length", "max_tokens"}:
                raise ValueError("模型输出达到长度上限，JSON 不完整")
            payload = self._extract_json_value(str(response.get("content") or ""))
            validated = response_model.model_validate(payload)
            if business_validator:
                business_validator(validated)
            if response_validator:
                response_validator(response)
            return validated.model_dump(mode="json")

        return validate

    @staticmethod
    def _extract_json_value(content: str) -> Any:
        text = re.sub(r"<think>[\s\S]*?</think>", "", content or "", flags=re.I).strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
        if not text:
            raise ValueError("模型没有返回最终 JSON 内容")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for index, char in enumerate(text):
                if char not in "[{":
                    continue
                try:
                    value, _ = decoder.raw_decode(text[index:])
                    return value
                except json.JSONDecodeError:
                    continue
        raise ValueError("模型未返回有效 JSON")

    @staticmethod
    def _structured_response_format(
        provider_type: ProviderType,
        schema: Dict[str, Any],
        name: str,
        attempt: int = 1,
    ) -> Optional[Dict[str, Any]]:
        if provider_type == ProviderType.ANTHROPIC:
            return None
        if provider_type in {ProviderType.CUSTOM, ProviderType.AZURE} or (
            provider_type == ProviderType.OPENAI and attempt > 1
        ):
            return {"type": "json_object"}
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64] or "structured_response"
        return {
            "type": "json_schema",
            "json_schema": {"name": safe_name, "strict": True, "schema": schema},
        }

    @staticmethod
    def _validation_error_detail(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return "；".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'response'}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )[:300]
        return re.sub(r"\s+", " ", str(exc)).strip()[:300]

    async def _candidate_models(self, db: AsyncSession, task_type: str) -> List[ModelConfig]:
        models = await self.get_available_models(db, task_type)
        if not models and task_type != "chat":
            models = await self.get_available_models(db, "chat")
        return await self._rank_models_for_runtime(db, models or await self.get_available_models(db))

    async def runtime_status(self, db: AsyncSession) -> Dict[str, Any]:
        resources = await resource_runtime_status(db)
        models = await self._candidate_models(db, "chat")
        selected = models[0] if models else None
        provider = (await db.execute(select(ModelProvider).where(
            ModelProvider.id == selected.provider_id
        ))).scalar_one_or_none() if selected else None
        policy = await get_config_service(db).get("runtime.model_policy", settings.LLM_RUNTIME_POLICY)
        return {
            **resources,
            "model_policy": policy,
            "model_preference": self.runtime_preference(policy),
            "selected_runtime": self._provider_runtime(provider) if provider else None,
            "selected_model": selected.model_name if selected else None,
            "selected_provider": provider.name if provider else None,
            "model_ready": bool(selected and provider),
            "active_model_calls": self._model_active,
        }

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
        models: Optional[List[ModelConfig]] = None,
        response_validator: Optional[Callable[[Dict[str, Any]], Any]] = None,
        max_attempts_per_model: int = 1,
        structured_schema: Optional[Dict[str, Any]] = None,
        structured_name: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Internal implementation of chat_with_fallback"""
        models = models if models is not None else await self._candidate_models(db, task_type)
        
        if not models:
            raise ValueError("No available models for this task type")
        
        errors = []
        for model_config in models:
            result = await db.execute(
                select(ModelProvider).where(ModelProvider.id == model_config.provider_id)
            )
            provider = result.scalar_one_or_none()
            if not provider or not provider.is_active:
                continue

            adapter = self._get_provider(provider)
            attempt_messages = messages
            for attempt in range(1, max(1, max_attempts_per_model) + 1):
                try:
                    call_kwargs = dict(kwargs)
                    if structured_schema:
                        response_format = self._structured_response_format(
                            provider.provider_type,
                            structured_schema,
                            structured_name or "structured_response",
                            attempt,
                        )
                        if response_format:
                            call_kwargs["response_format"] = response_format
                        else:
                            call_kwargs.pop("response_format", None)
                    response = await adapter.chat(attempt_messages, model_config.model_name, **call_kwargs)

                    await self.record_usage(
                        db=db,
                        user_id=user_id,
                        model_config_id=model_config.id,
                        prompt_tokens=response["usage"]["prompt_tokens"],
                        completion_tokens=response["usage"]["completion_tokens"],
                        task_type=task_type,
                    )
                    validated = response_validator(response) if response_validator else None
                    if validated is not None:
                        response["validated"] = validated

                    response["model_config_id"] = model_config.id
                    response["model_name"] = model_config.model_name
                    response["display_name"] = model_config.display_name
                    response["fallback_used"] = model_config != models[0]
                    response["attempt"] = attempt
                    return response
                except Exception as exc:
                    error_detail = self._validation_error_detail(exc)
                    error = f"{model_config.display_name} 第 {attempt} 次：{error_detail}"
                    errors.append(error)
                    logger.warning("Structured/model call failed: %s", error)
                    if attempt < max_attempts_per_model:
                        attempt_messages = [
                            *messages,
                            {
                                "role": "user",
                                "content": f"上一次输出未通过校验：{error_detail}。请重新生成，只返回符合要求的 JSON。",
                            },
                        ]

        detail = "；".join(errors[-6:]) if errors else "没有可用模型"
        raise ValueError(f"所有模型均未生成有效结果：{detail}")
    
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
            schema = ModelHealthContract.model_json_schema()
            messages = self._with_schema_instruction(
                [{"role": "user", "content": "返回 status 为 ok 的结构化结果。"}],
                schema,
            )
            validator = self._structured_validator(ModelHealthContract, None, None)
            last_error = None
            for attempt in range(1, 4):
                try:
                    kwargs = {"temperature": 0, "max_tokens": 512}
                    response_format = self._structured_response_format(
                        provider.provider_type,
                        schema,
                        ModelHealthContract.__name__,
                        attempt,
                    )
                    if response_format:
                        kwargs["response_format"] = response_format
                    response = await adapter.chat(messages, model_config.model_name, **kwargs)
                    validator(response)
                    break
                except Exception as exc:
                    last_error = exc
            else:
                raise ValueError(f"模型连续 3 次未通过结构化输出测试：{last_error}")
            return {
                "success": True,
                "model_name": model_config.model_name,
                "provider": provider.name,
                "capability": "chat",
                "json_mode": True,
                "attempt": attempt,
                "thinking_disabled": not settings.OLLAMA_THINK if provider.provider_type == ProviderType.OLLAMA else None,
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
