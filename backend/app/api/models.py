"""
Model Configuration API - VeriSure
API endpoints for managing LLM providers and models.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.model_config import ModelProvider, ModelConfig, ModelUsage
from app.schemas.model_config import (
    ModelProviderCreate,
    ModelProviderUpdate,
    ModelProviderResponse,
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
    ModelConfigWithProvider,
    ModelUsageResponse,
    ModelUsageSummary,
    AvailableModel,
)
from app.services.llm_service import llm_service

router = APIRouter(prefix="/models", tags=["Model Configuration"])


# --- Provider Endpoints ---

@router.post("/providers", response_model=ModelProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_provider(
    provider_data: ModelProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new model provider"""
    provider = ModelProvider(
        name=provider_data.name,
        provider_type=provider_data.provider_type,
        api_key=provider_data.api_key,
        api_base=provider_data.api_base,
        is_active=True,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.get("/providers", response_model=List[ModelProviderResponse])
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all model providers"""
    result = await db.execute(
        select(ModelProvider).order_by(ModelProvider.created_at.desc())
    )
    return result.scalars().all()


@router.put("/providers/{provider_id}", response_model=ModelProviderResponse)
async def update_provider(
    provider_id: int,
    provider_data: ModelProviderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a model provider"""
    result = await db.execute(
        select(ModelProvider).where(ModelProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    if provider_data.name is not None:
        provider.name = provider_data.name
    if provider_data.api_key is not None:
        provider.api_key = provider_data.api_key
    if provider_data.api_base is not None:
        provider.api_base = provider_data.api_base
    if provider_data.is_active is not None:
        provider.is_active = provider_data.is_active
    
    await db.commit()
    await db.refresh(provider)
    return provider


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a model provider"""
    result = await db.execute(
        select(ModelProvider).where(ModelProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    await db.delete(provider)
    await db.commit()
    return None


# --- Model Config Endpoints ---

@router.post("/configs", response_model=ModelConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_model_config(
    config_data: ModelConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new model configuration"""
    # Verify provider exists
    result = await db.execute(
        select(ModelProvider).where(ModelProvider.id == config_data.provider_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Provider not found")
    
    # If this is set as default, unset other defaults
    if config_data.is_default:
        await db.execute(
            select(ModelConfig).where(ModelConfig.is_default == True)
        )
        result = await db.execute(
            select(ModelConfig).where(ModelConfig.is_default == True)
        )
        for existing in result.scalars().all():
            existing.is_default = False
    
    config = ModelConfig(
        provider_id=config_data.provider_id,
        model_name=config_data.model_name,
        display_name=config_data.display_name,
        capabilities=config_data.capabilities,
        max_tokens=config_data.max_tokens,
        is_default=config_data.is_default,
        priority=config_data.priority,
        is_active=True,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.get("/configs", response_model=List[ModelConfigWithProvider])
async def list_model_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all model configurations with provider info"""
    result = await db.execute(
        select(ModelConfig)
        .order_by(ModelConfig.priority, ModelConfig.created_at.desc())
    )
    configs = result.scalars().all()
    
    # Attach provider info
    response = []
    for config in configs:
        result = await db.execute(
            select(ModelProvider).where(ModelProvider.id == config.provider_id)
        )
        provider = result.scalar_one_or_none()
        config_dict = ModelConfigResponse.model_validate(config).model_dump()
        config_dict["provider"] = ModelProviderResponse.model_validate(provider).model_dump()
        response.append(config_dict)
    
    return response


@router.put("/configs/{config_id}", response_model=ModelConfigResponse)
async def update_model_config(
    config_id: int,
    config_data: ModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a model configuration"""
    result = await db.execute(
        select(ModelConfig).where(ModelConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Model config not found")
    
    # If setting as default, unset other defaults
    if config_data.is_default:
        result = await db.execute(
            select(ModelConfig).where(
                ModelConfig.is_default == True,
                ModelConfig.id != config_id
            )
        )
        for existing in result.scalars().all():
            existing.is_default = False
    
    if config_data.display_name is not None:
        config.display_name = config_data.display_name
    if config_data.capabilities is not None:
        config.capabilities = config_data.capabilities
    if config_data.max_tokens is not None:
        config.max_tokens = config_data.max_tokens
    if config_data.is_default is not None:
        config.is_default = config_data.is_default
    if config_data.priority is not None:
        config.priority = config_data.priority
    if config_data.is_active is not None:
        config.is_active = config_data.is_active
    
    await db.commit()
    await db.refresh(config)
    return config


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a model configuration"""
    result = await db.execute(
        select(ModelConfig).where(ModelConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Model config not found")
    
    await db.delete(config)
    await db.commit()
    return None


@router.post("/configs/{config_id}/test")
async def test_model_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test if a model configuration is accessible"""
    result = await llm_service.test_model(db, config_id)
    return result


# --- Available Models Endpoint ---

@router.get("/available", response_model=List[AvailableModel])
async def get_available_models(
    task_type: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get list of available models for selection"""
    models = await llm_service.get_available_models(db, task_type)
    
    response = []
    for model in models:
        result = await db.execute(
            select(ModelProvider).where(ModelProvider.id == model.provider_id)
        )
        provider = result.scalar_one_or_none()
        
        response.append(AvailableModel(
            id=model.id,
            model_name=model.model_name,
            display_name=model.display_name,
            provider_name=provider.name if provider else "Unknown",
            capabilities=model.capabilities,
            is_default=model.is_default,
        ))
    
    return response


# --- Usage Statistics ---

@router.get("/usage", response_model=List[ModelUsageSummary])
async def get_usage_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get usage statistics grouped by model"""
    result = await db.execute(
        select(
            ModelConfig.model_name,
            ModelConfig.display_name,
            func.count(ModelUsage.id).label("total_calls"),
            func.sum(ModelUsage.prompt_tokens).label("total_prompt_tokens"),
            func.sum(ModelUsage.completion_tokens).label("total_completion_tokens"),
        )
        .join(ModelUsage, ModelUsage.model_config_id == ModelConfig.id)
        .group_by(ModelConfig.id, ModelConfig.model_name, ModelConfig.display_name)
        .order_by(func.count(ModelUsage.id).desc())
    )
    
    return [
        ModelUsageSummary(
            model_name=row.model_name,
            display_name=row.display_name,
            total_calls=row.total_calls,
            total_prompt_tokens=row.total_prompt_tokens or 0,
            total_completion_tokens=row.total_completion_tokens or 0,
        )
        for row in result
    ]
