"""
系统配置 API - 提供配置的查看和修改
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Any, Dict

from app.core.database import get_db
from app.core.rbac import require_org_permission
from app.core.security import get_current_user
from app.models.user import User
from app.services.config_service import get_config_service
from app.services.llm_service import llm_service
from app.services.audit import record_audit_event

router = APIRouter(prefix="/config", tags=["System Config"])


class ConfigUpdateRequest(BaseModel):
    updates: Dict[str, Any]


async def require_config_access(
    db: AsyncSession,
    current_user: User,
    organization_id: int | None,
):
    if organization_id is None:
        raise HTTPException(status_code=400, detail="X-Org-Id header is required")
    return await require_org_permission(db, organization_id, current_user, "system:config")


@router.get("/")
async def get_all_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    organization_id: int | None = Header(default=None, alias="X-Org-Id"),
):
    """获取所有配置（按 category 分组）"""
    await require_config_access(db, current_user, organization_id)
    service = get_config_service(db)
    await service.init_defaults()
    return await service.get_all()


@router.get("/meta")
async def get_config_meta(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    organization_id: int | None = Header(default=None, alias="X-Org-Id"),
):
    """获取配置的元信息（描述、默认值等）"""
    await require_config_access(db, current_user, organization_id)
    service = get_config_service(db)
    return await service.get_meta()


@router.get("/runtime-status")
async def get_runtime_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    organization_id: int | None = Header(default=None, alias="X-Org-Id"),
):
    await require_config_access(db, current_user, organization_id)
    return await llm_service.runtime_status(db)


@router.put("/")
async def update_config(
    req: ConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    organization_id: int | None = Header(default=None, alias="X-Org-Id"),
):
    """批量更新配置"""
    await require_config_access(db, current_user, organization_id)
    service = get_config_service(db)
    try:
        validated = service.validate_updates(req.updates)
        previous = {key: await service.get(key) for key in validated}
        updated = await service.update_batch(validated)
        await record_audit_event(
            db,
            event_type="system_config.updated",
            resource_type="system_config",
            resource_id="deployment",
            actor_user_id=current_user.id,
            organization_id=organization_id,
            details={"keys": sorted(updated), "previous": previous, "updated": updated},
        )
        return {"message": f"Updated {len(updated)} configs", "updated": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{key}")
async def get_config_by_key(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    organization_id: int | None = Header(default=None, alias="X-Org-Id"),
):
    """获取单个配置"""
    await require_config_access(db, current_user, organization_id)
    service = get_config_service(db)
    if key not in await service.get_meta():
        raise HTTPException(status_code=404, detail="Unknown config key")
    value = await service.get(key)
    return {"key": key, "value": value}
