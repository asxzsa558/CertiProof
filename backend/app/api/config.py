"""
系统配置 API - 提供配置的查看和修改
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Any, Dict

from app.core.database import get_db
from app.core.rbac import require_any_org_permission
from app.core.security import get_current_user
from app.models.user import User
from app.services.config_service import ConfigService, get_config_service
from app.services.llm_service import llm_service

router = APIRouter(prefix="/config", tags=["System Config"])


class ConfigUpdateRequest(BaseModel):
    updates: Dict[str, Any]


@router.get("/")
async def get_all_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有配置（按 category 分组）"""
    await require_any_org_permission(db, current_user, "system:config")
    service = get_config_service(db)
    await service.init_defaults()
    return await service.get_all()


@router.get("/meta")
async def get_config_meta(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取配置的元信息（描述、默认值等）"""
    await require_any_org_permission(db, current_user, "system:config")
    service = get_config_service(db)
    return await service.get_meta()


@router.get("/runtime-status")
async def get_runtime_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_any_org_permission(db, current_user, "system:config")
    return await llm_service.runtime_status(db)


@router.put("/")
async def update_config(
    req: ConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量更新配置"""
    await require_any_org_permission(db, current_user, "system:config")
    service = get_config_service(db)
    try:
        count = await service.update_batch(req.updates)
        return {"message": f"Updated {count} configs", "updated": req.updates}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{key}")
async def get_config_by_key(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单个配置"""
    await require_any_org_permission(db, current_user, "system:config")
    service = get_config_service(db)
    value = await service.get(key)
    return {"key": key, "value": value}
