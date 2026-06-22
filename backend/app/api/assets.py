from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import secrets
from datetime import datetime
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset, VerificationStatus
from app.schemas.asset import AssetCreate, AssetResponse, AssetListResponse, AssetVerify

router = APIRouter(prefix="/projects/{project_id}/assets", tags=["Assets"])


@router.post("/", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    project_id: int,
    asset_data: AssetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project exists and belongs to user
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
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
    
    return asset


@router.get("/", response_model=List[AssetListResponse])
async def list_assets(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project exists and belongs to user
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
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
    # Verify project exists and belongs to user
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
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
    # Verify project exists and belongs to user
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
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
        except ImportError:
            asset.verification_status = VerificationStatus.VERIFIED
            asset.verification_method = verify_data.verification_method
            asset.verified_at = datetime.utcnow()
        except Exception:
            asset.verification_status = VerificationStatus.FAILED
    else:
        asset.verification_status = VerificationStatus.VERIFIED
        asset.verification_method = verify_data.verification_method
        asset.verified_at = datetime.utcnow()
    
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
    # Verify project exists and belongs to user
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.project_id == project_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )
    
    await db.delete(asset)
    await db.commit()
    return None
