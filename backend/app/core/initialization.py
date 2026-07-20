"""
Initialize default model configuration from environment variables.
This script runs on application startup to ensure at least one model is configured.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.model_config import InferenceRuntime, ModelProvider, ModelConfig, ProviderType
from app.core.config import settings
from app.core.secret_box import encrypt_secret

logger = logging.getLogger(__name__)


async def initialize_default_models(db: AsyncSession):
    """
    Initialize default model provider and configuration from environment variables.
    This ensures the system has at least one model configured on first startup.
    """
    try:
        providers = (await db.execute(select(ModelProvider))).scalars().all()
        plaintext_keys = [provider for provider in providers if provider.api_key and not provider.api_key.startswith("enc:")]
        for provider in plaintext_keys:
            provider.api_key = encrypt_secret(provider.api_key)
        if plaintext_keys:
            await db.commit()
            logger.info("Encrypted %d existing model provider key(s)", len(plaintext_keys))

        await _initialize_local_runtime(
            db, "vLLM (managed)", InferenceRuntime.VLLM,
            settings.VLLM_API_BASE, settings.VLLM_MODEL,
        )
        await _initialize_local_runtime(
            db, "llama.cpp (managed)", InferenceRuntime.LLAMA_CPP,
            settings.LLAMA_CPP_API_BASE, settings.LLAMA_CPP_MODEL,
        )
        if settings.OPENAI_API_KEY:
            await _initialize_cloud_runtime(db)
        elif not providers and not settings.VLLM_MODEL and not settings.LLAMA_CPP_MODEL:
            logger.warning("No model provider configured; add a cloud or local runtime before using AI features")
        
    except Exception as e:
        logger.error(f"Failed to initialize default models: {e}")
        await db.rollback()
        raise


async def _initialize_local_runtime(
    db: AsyncSession,
    name: str,
    runtime: InferenceRuntime,
    api_base: str,
    model_name: str,
) -> None:
    if not model_name:
        return
    provider = (await db.execute(select(ModelProvider).where(
        ModelProvider.name == name
    ))).scalar_one_or_none()
    if provider is None:
        provider = ModelProvider(
            name=name,
            provider_type=ProviderType.CUSTOM,
            api_key=encrypt_secret("local"),
            api_base=api_base,
            runtime_kind=runtime.value,
            is_active=True,
        )
        db.add(provider)
        await db.flush()
    else:
        provider.api_base = api_base
        provider.runtime_kind = runtime.value
        provider.is_active = True
    model = (await db.execute(select(ModelConfig).where(
        ModelConfig.provider_id == provider.id,
        ModelConfig.model_name == model_name,
    ))).scalar_one_or_none()
    if model is None:
        db.add(ModelConfig(
            provider_id=provider.id,
            model_name=model_name,
            display_name=f"{model_name} ({runtime.value})",
            capabilities=["chat", "code"],
            max_tokens=4096,
            is_default=False,
            priority=10,
            is_active=True,
        ))
    await db.commit()


async def _initialize_cloud_runtime(db: AsyncSession) -> None:
    provider = (await db.execute(select(ModelProvider).where(
        ModelProvider.provider_type == ProviderType.OPENAI
    ).limit(1))).scalar_one_or_none()
    if provider is None:
        provider = ModelProvider(
            name="OpenAI (managed)",
            provider_type=ProviderType.OPENAI,
            runtime_kind=InferenceRuntime.CLOUD.value,
            is_active=True,
        )
        db.add(provider)
        await db.flush()
    provider.api_key = encrypt_secret(settings.OPENAI_API_KEY)
    provider.api_base = settings.OPENAI_API_BASE
    provider.runtime_kind = InferenceRuntime.CLOUD.value
    provider.is_active = True
    model = (await db.execute(select(ModelConfig).where(
        ModelConfig.provider_id == provider.id,
        ModelConfig.model_name == settings.OPENAI_MODEL,
    ))).scalar_one_or_none()
    if model is None:
        db.add(ModelConfig(
            provider_id=provider.id,
            model_name=settings.OPENAI_MODEL,
            display_name=settings.OPENAI_MODEL,
            capabilities=["chat", "vision", "code"],
            max_tokens=4096,
            is_default=True,
            priority=1,
            is_active=True,
        ))
    await db.commit()
