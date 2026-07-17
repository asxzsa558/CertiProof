import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.asset import Asset, AssetType, VerificationStatus
from app.services.asset_scope import list_scannable_assets, scope_plan_to_project_assets, target_identity


def test_target_identity_normalizes_urls_and_hosts():
    assert target_identity("HTTPS://Example.COM:443/admin") == "example.com"
    assert target_identity("121.40.95.31:22") == "121.40.95.31"
    assert target_identity("[2001:db8::1]:443") == "2001:db8::1"


def test_active_project_assets_are_scannable_without_forcing_dns_or_file_verification():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add_all([
                Asset(project_id=7, asset_type=AssetType.IP, value="203.0.113.10", verification_status=VerificationStatus.PENDING),
                Asset(project_id=7, asset_type=AssetType.IP, value="203.0.113.11", verification_status=VerificationStatus.FAILED, is_active=False),
            ])
            await db.commit()
            assert [asset.value for asset in await list_scannable_assets(db, 7)] == ["203.0.113.10"]

        await engine.dispose()

    asyncio.run(run())


def test_out_of_scope_substep_does_not_cancel_valid_project_target():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add(Asset(project_id=7, asset_type=AssetType.IP, value="172.23.0.17"))
            await db.commit()
            plan = await scope_plan_to_project_assets(db, 7, [
                {"capability": "nikto_scan", "parameters": {"target": "139.224.104.187"}},
                {"capability": "nikto_scan", "parameters": {"target": "172.23.0.17"}},
            ])
            assert plan == [{"capability": "nikto_scan", "parameters": {"target": "172.23.0.17"}}]

        await engine.dispose()

    asyncio.run(run())
