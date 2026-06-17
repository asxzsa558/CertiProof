"""
Initialize default model configuration from environment variables.
This script runs on application startup to ensure at least one model is configured.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.model_config import ModelProvider, ModelConfig, ProviderType
from app.core.config import settings

logger = logging.getLogger(__name__)


async def initialize_default_models(db: AsyncSession):
    """
    Initialize default model provider and configuration from environment variables.
    This ensures the system has at least one model configured on first startup.
    """
    try:
        # Check if any providers already exist
        result = await db.execute(select(ModelProvider).limit(1))
        if result.scalar_one_or_none():
            logger.info("Model providers already exist, skipping initialization")
            return
        
        # Check if OpenAI API key is configured
        if not settings.OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not configured, no default model will be created")
            logger.info("Please configure model providers through the API or environment variables")
            return
        
        logger.info("Initializing default OpenAI model configuration...")
        
        # Create OpenAI provider
        provider = ModelProvider(
            name="OpenAI",
            provider_type=ProviderType.OPENAI,
            api_key=settings.OPENAI_API_KEY,
            api_base=settings.OPENAI_API_BASE,
            is_active=True,
        )
        db.add(provider)
        await db.flush()
        
        # Create default model configurations
        models = [
            {
                "model_name": "gpt-4-turbo-preview",
                "display_name": "GPT-4 Turbo",
                "capabilities": ["chat", "vision", "code"],
                "max_tokens": 4096,
                "is_default": True,
                "priority": 1,
            },
            {
                "model_name": "gpt-4",
                "display_name": "GPT-4",
                "capabilities": ["chat", "vision", "code"],
                "max_tokens": 4096,
                "is_default": False,
                "priority": 2,
            },
            {
                "model_name": "gpt-3.5-turbo",
                "display_name": "GPT-3.5 Turbo",
                "capabilities": ["chat", "code"],
                "max_tokens": 4096,
                "is_default": False,
                "priority": 3,
            },
        ]
        
        for model_data in models:
            model = ModelConfig(
                provider_id=provider.id,
                **model_data
            )
            db.add(model)
        
        await db.commit()
        logger.info(f"Successfully initialized {len(models)} default OpenAI models")
        
    except Exception as e:
        logger.error(f"Failed to initialize default models: {e}")
        await db.rollback()
        raise
