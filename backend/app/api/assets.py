import asyncio
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, case, func, or_, select
from typing import List, Optional
import secrets
from datetime import datetime
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset, AssetType, VerificationStatus
from app.models.finding import Finding, FindingStatus
from app.models.scan_task import ScanTask
from app.schemas.asset import AssetCreate, AssetResponse, AssetListResponse, AssetScopeConfirmation, AssetVerify

router = APIRouter(prefix="/projects/{project_id}/assets", tags=["Assets"])
inventory_router = APIRouter(prefix="/assets", tags=["Assets"])


def _enum_value(value):
    return getattr(value, "value", value)


def _observed_services(summary):
    """Extract observed open services from normalized scan results."""
    services = []
    seen = set()

    def visit(value, depth=0):
        if depth > 5 or not value:
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        for port in value.get("open_ports") or []:
            if not isinstance(port, dict) or port.get("state") not in (None, "open"):
                continue
            number = port.get("port")
            if number in (None, ""):
                continue
            protocol = str(port.get("protocol") or "tcp").lower()
            service = str(port.get("service") or port.get("name") or "").strip()
            key = f"{number}/{protocol}"
            if key not in seen:
                seen.add(key)
                services.append({"id": key, "label": key, "service": service or None})
        for key in ("data", "result", "results", "scan_results"):
            visit(value.get(key), depth + 1)

    visit(summary)
    return services[:6]


@inventory_router.get("/inventory")
async def get_asset_inventory(
    organization_id: int = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    project_id: Optional[int] = Query(None, ge=1),
    asset_type: Optional[AssetType] = Query(None),
    verification_status: Optional[VerificationStatus] = Query(None),
    search: Optional[str] = Query(None, max_length=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a paged organization-wide asset matrix without per-project requests."""
    from app.api.projects import check_org_member

    await check_org_member(db, organization_id, current_user.id, "asset:read")
    organization_filter = Project.organization_id == organization_id
    filters = [organization_filter]
    if project_id:
        filters.append(Project.id == project_id)
    if asset_type:
        filters.append(Asset.asset_type == asset_type)
    if verification_status:
        filters.append(Asset.verification_status == verification_status)
    if search and search.strip():
        keyword = f"%{search.strip()}%"
        filters.append(or_(
            Asset.value.ilike(keyword),
            Asset.name.ilike(keyword),
            Project.name.ilike(keyword),
            Project.system_name.ilike(keyword),
        ))

    total_result = await db.execute(
        select(func.count(Asset.id))
        .join(Project, Project.id == Asset.project_id)
        .where(*filters)
    )
    total = int(total_result.scalar_one() or 0)
    asset_rows = await db.execute(
        select(Asset, Project)
        .join(Project, Project.id == Asset.project_id)
        .where(*filters)
        .order_by(Project.name.asc(), Asset.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = asset_rows.all()

    summary_result = await db.execute(
        select(
            func.count(Asset.id).label("total"),
            func.coalesce(func.sum(case((
                Asset.verification_status == VerificationStatus.VERIFIED,
                1,
            ), else_=0)), 0).label("verified"),
        )
        .join(Project, Project.id == Asset.project_id)
        .where(organization_filter)
    )
    summary = summary_result.one()
    type_rows = await db.execute(
        select(Asset.asset_type, func.count(Asset.id))
        .join(Project, Project.id == Asset.project_id)
        .where(organization_filter)
        .group_by(Asset.asset_type)
    )
    type_counts = {asset_type.value: 0 for asset_type in AssetType}
    type_counts.update({_enum_value(kind): int(count) for kind, count in type_rows.all()})

    organization_project_ids = select(Project.id).where(organization_filter)
    active_risks = [FindingStatus.OPEN, FindingStatus.IN_PROGRESS]
    at_risk_result = await db.execute(
        select(func.count(func.distinct(ScanTask.asset_id)))
        .select_from(ScanTask)
        .join(Finding, Finding.scan_task_id == ScanTask.id)
        .where(
            ScanTask.project_id.in_(organization_project_ids),
            ScanTask.asset_id.is_not(None),
            Finding.status.in_(active_risks),
            Finding.severity.in_(["critical", "high", "medium"]),
        )
    )
    at_risk = int(at_risk_result.scalar_one() or 0)

    summary_rows = await db.execute(
        select(ScanTask.asset_id, ScanTask.result_summary)
        .where(
            ScanTask.project_id.in_(organization_project_ids),
            ScanTask.asset_id.is_not(None),
            ScanTask.result_summary.is_not(None),
        )
        .order_by(ScanTask.completed_at.desc().nullslast(), ScanTask.id.desc())
    )
    services_by_asset = {}
    for asset_id, result_summary in summary_rows.all():
        if asset_id in services_by_asset:
            continue
        services = _observed_services(result_summary)
        if services:
            services_by_asset[asset_id] = services
    service_count = sum(len(services) for services in services_by_asset.values())

    asset_ids = [asset.id for asset, _ in rows]
    if not asset_ids:
        return {
            "assets": [],
            "summary": {
                "total": int(summary.total or 0),
                "verified": int(summary.verified or 0),
                "at_risk": at_risk,
                "services": service_count,
                "type_counts": type_counts,
            },
            "pagination": {"page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1) // page_size},
        }

    risk_rows = await db.execute(
        select(
            ScanTask.asset_id,
            func.coalesce(func.sum(case((and_(
                Finding.status.in_(active_risks),
                Finding.severity.in_(["critical", "high", "medium"]),
            ), 1), else_=0)), 0).label("risk_count"),
            func.count(Finding.id).label("finding_count"),
        )
        .select_from(ScanTask)
        .outerjoin(Finding, Finding.scan_task_id == ScanTask.id)
        .where(ScanTask.asset_id.in_(asset_ids))
        .group_by(ScanTask.asset_id)
    )
    risk_by_asset = {
        row.asset_id: {"risk_count": int(row.risk_count or 0), "finding_count": int(row.finding_count or 0)}
        for row in risk_rows.all()
        if row.asset_id is not None
    }

    inventory = []
    for asset, project in rows:
        metrics = risk_by_asset.get(asset.id, {})
        inventory.append({
            "id": asset.id,
            "project_id": project.id,
            "project_name": project.name,
            "project_system_name": project.system_name,
            "asset_type": _enum_value(asset.asset_type),
            "value": asset.value,
            "name": asset.name,
            "verification_status": _enum_value(asset.verification_status),
            "is_active": asset.is_active,
            "scope_confirmed_at": asset.scope_confirmed_at.isoformat() if asset.scope_confirmed_at else None,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "risk_count": metrics.get("risk_count", 0),
            "finding_count": metrics.get("finding_count", 0),
            "services": services_by_asset.get(asset.id, []),
        })

    return {
        "assets": inventory,
        "summary": {
            "total": int(summary.total or 0),
            "verified": int(summary.verified or 0),
            "at_risk": at_risk,
            "services": service_count,
            "type_counts": type_counts,
        },
        "pagination": {"page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1) // page_size},
    }


@router.post("/", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    project_id: int,
    asset_data: AssetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project exists and user has access
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, project_id, current_user.id, "asset:create")

    from app.services.change_detection import record_asset_snapshot
    await record_asset_snapshot(db, project_id)

    # Generate verification token
    verification_token = secrets.token_urlsafe(32)
    
    # Create asset
    asset = Asset(
        project_id=project_id,
        asset_type=asset_data.asset_type,
        value=asset_data.value,
        name=asset_data.name,
        verification_token=verification_token,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    await record_asset_snapshot(db, project_id)
    
    return asset


@router.get("/", response_model=List[AssetListResponse])
async def list_assets(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project exists and user has access
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, project_id, current_user.id, "asset:read")
    
    result = await db.execute(
        select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at.desc())
    )
    assets = result.scalars().all()
    return assets


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    project_id: int,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project exists and user has access
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, project_id, current_user.id, "asset:read")
    
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.project_id == project_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )
    
    return asset


@router.post("/{asset_id}/verify", response_model=AssetResponse)
async def verify_asset(
    project_id: int,
    asset_id: int,
    verify_data: AssetVerify,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project exists and user has access
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, project_id, current_user.id, "asset:update")
    
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.project_id == project_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )
    
    if not asset.verification_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Asset has no verification token. Please regenerate.",
        )
    
    if verify_data.verification_method.value == "dns_txt":
        try:
            import dns.resolver
            domain = asset.value if asset.asset_type.value == "domain" else None
            if not domain:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="DNS TXT verification only supports domain assets",
                )
            
            answers = dns.resolver.resolve(domain, "TXT")
            found = False
            for rdata in answers:
                for txt in rdata.strings:
                    if asset.verification_token in txt.decode():
                        found = True
                        break
                if found:
                    break
            
            if found:
                asset.verification_status = VerificationStatus.VERIFIED
                asset.verification_method = verify_data.verification_method
                asset.verified_at = datetime.utcnow()
            else:
                asset.verification_status = VerificationStatus.FAILED
        except ImportError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DNS 验证组件不可用，无法确认资产归属") from exc
        except HTTPException:
            raise
        except Exception:
            asset.verification_status = VerificationStatus.FAILED
    elif verify_data.verification_method.value == "file":
        if asset.asset_type.value != "domain":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件验证仅支持域名资产")
        url = f"https://{asset.value}/.well-known/certiproof-verification-{asset.verification_token}.txt"
        try:
            body = await asyncio.to_thread(lambda: urlopen(url, timeout=8).read(512).decode("utf-8", errors="replace"))
        except URLError:
            asset.verification_status = VerificationStatus.FAILED
        else:
            if asset.verification_token in body:
                asset.verification_status = VerificationStatus.VERIFIED
                asset.verification_method = verify_data.verification_method
                asset.verified_at = datetime.utcnow()
            else:
                asset.verification_status = VerificationStatus.FAILED
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该验证方式不能自动证明资产归属，请使用 DNS/文件验证，或在资产详情中确认已获得扫描授权",
        )
    
    await db.commit()
    await db.refresh(asset)
    
    return asset


@router.post("/{asset_id}/confirm-scope", response_model=AssetResponse)
async def confirm_asset_scope(
    project_id: int,
    asset_id: int,
    confirmation: AssetScopeConfirmation,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record an accountable authorization confirmation when technical proof is unavailable."""
    if not confirmation.confirmed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必须明确确认已获得该资产的扫描授权")
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "asset:update")
    result = await db.execute(select(Asset).where(Asset.id == asset_id, Asset.project_id == project_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    asset.scope_confirmed_by = current_user.id
    asset.scope_confirmed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    project_id: int,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project exists and user has access
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, project_id, current_user.id, "asset:delete")
    
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.project_id == project_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )
    
    from app.services.change_detection import record_asset_snapshot
    await record_asset_snapshot(db, project_id)
    await db.delete(asset)
    await db.commit()
    await record_asset_snapshot(db, project_id)
    return None
