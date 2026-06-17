"""
LLM Service - CertiProof
Unified LLM interface with multi-provider support and fallback strategy.
"""

import logging
from typing import Optional, List, Dict, Any
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
    async def test_connection(self) -> bool:
        """Test if the provider connection works"""
        pass


class OpenAIProvider(BaseProvider):
    """OpenAI API adapter"""
    
    async def chat(self, messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        try:
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.openai.com/v1"
            )
            
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                **kwargs
            )
            
            return {
                "content": response.choices[0].message.content,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                "model": response.model,
                "provider": "openai"
            }
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    async def test_connection(self) -> bool:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.api_base)
            await client.models.list()
            return True
        except Exception as e:
            logger.error(f"OpenAI connection test failed: {e}")
            return False


class AnthropicProvider(BaseProvider):
    """Anthropic Claude API adapter"""
    
    async def chat(self, messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        try:
            from anthropic import AsyncAnthropic
            
            client = AsyncAnthropic(api_key=self.api_key)
            
            # Convert OpenAI format to Anthropic format
            system_msg = None
            chat_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_msg = msg["content"]
                else:
                    chat_messages.append(msg)
            
            response = await client.messages.create(
                model=model_name,
                messages=chat_messages,
                system=system_msg or "",
                max_tokens=kwargs.get("max_tokens", 4096),
                **{k: v for k, v in kwargs.items() if k != "max_tokens"}
            )
            
            return {
                "content": response.content[0].text,
                "usage": {
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                },
                "model": response.model,
                "provider": "anthropic"
            }
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise
    
    async def test_connection(self) -> bool:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self.api_key)
            await client.messages.create(
                model="claude-3-haiku-20240307",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=10
            )
            return True
        except Exception as e:
            logger.error(f"Anthropic connection test failed: {e}")
            return False


class OllamaProvider(BaseProvider):
    """Ollama local LLM adapter"""
    
    async def chat(self, messages: List[Dict], model_name: str, **kwargs) -> Dict[str, Any]:
        try:
            import httpx
            
            api_base = self.api_base or "http://localhost:11434"
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{api_base}/api/chat",
                    json={
                        "model": model_name,
                        "messages": messages,
                        "stream": False,
                        **kwargs
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                return {
                    "content": data["message"]["content"],
                    "usage": {
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "completion_tokens": data.get("eval_count", 0),
                        "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                    },
                    "model": model_name,
                    "provider": "ollama"
                }
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            raise
    
    async def test_connection(self) -> bool:
        try:
            import httpx
            api_base = self.api_base or "http://localhost:11434"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{api_base}/api/tags")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama connection test failed: {e}")
            return False


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
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send chat request with automatic fallback to backup models
        """
        models = await self.get_available_models(db, task_type)
        
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
        success = await adapter.test_connection()
        
        return {
            "success": success,
            "model_name": model_config.model_name,
            "provider": provider.name
        }


# Singleton instance
llm_service = LLMService()
