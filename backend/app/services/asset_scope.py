"""Shared project-asset scope checks for every network tool entry point."""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset


def target_identity(value: str) -> str:
    """Return the host identity used to match an entered URL/IP to an asset."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"//{raw}", scheme="scan")
    return (parsed.hostname or raw.split("/", 1)[0]).strip("[]").lower().rstrip(".")


async def list_scannable_assets(db: AsyncSession, project_id: int) -> list[Asset]:
    """Return active assets owned by the project.

    Project membership and an asset's project_id are the execution boundary.
    Verification describes ownership confidence; it must not make a project
    operator unable to run a permitted assessment against their own inventory.
    """
    result = await db.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.is_active.is_(True),
        ).order_by(Asset.created_at.asc())
    )
    return list(result.scalars().all())


async def require_scannable_target(db: AsyncSession, project_id: int, target: str) -> Asset:
    identity = target_identity(target)
    assets = await list_scannable_assets(db, project_id)
    asset = next((item for item in assets if target_identity(item.value) == identity), None)
    if asset:
        return asset
    raise ValueError("目标不在当前项目的启用资产范围内，请先将该资产添加到当前项目")


async def scope_plan_to_project_assets(db: AsyncSession, project_id: int, plan: list[dict]) -> list[dict]:
    """Reject direct targets outside the current project's confirmed asset scope."""
    for step in plan:
        parameters = step.get("parameters") if isinstance(step, dict) else None
        if not isinstance(parameters, dict):
            continue
        targets = []
        if parameters.get("target"):
            targets.append(str(parameters["target"]))
        if isinstance(parameters.get("targets"), list):
            targets.extend(str(target) for target in parameters["targets"])
        for target in targets:
            if target in {"项目资产", "全部项目资产", "所有项目资产", "项目中的资产"}:
                continue
            await require_scannable_target(db, project_id, target)
    return plan
