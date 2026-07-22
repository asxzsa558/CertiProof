import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.asset import Asset, AssetType
from app.models.finding import Finding, FindingStatus
from app.models.organization import Organization
from app.models.project import Project
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy
from app.models.user import User
from app.services.independent_finding_tracker import sync_independent_findings


def test_independent_findings_are_deduplicated_and_only_reliable_clean_runs_close_them():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            user = User(email="tracking@example.test", username="tracking", hashed_password="test")
            organization = Organization(name="Tracking", code="tracking")
            db.add_all([user, organization])
            await db.flush()
            project = Project(user_id=user.id, organization_id=organization.id, name="Tracking")
            db.add(project)
            await db.flush()
            asset = Asset(project_id=project.id, asset_type=AssetType.IP, value="192.0.2.20", is_active=True)
            db.add(asset)
            await db.flush()

            async def track(execution):
                task = ScanTask(
                    project_id=project.id,
                    asset_id=asset.id,
                    task_type=ScanTaskType.TARGETED,
                    status=ScanTaskStatus.COMPLETED,
                    triggered_by=TriggeredBy.MANUAL,
                    parameters={"source": "interactive"},
                )
                db.add(task)
                await db.flush()
                result = await sync_independent_findings(db, task, [execution], actor_id=user.id)
                await db.flush()
                return result

            risky = {
                "capability": "scan_ports",
                "target": asset.value,
                "status": "success",
                "result": {"reachable": True, "scan_completed": True, "open_ports": [{"port": 3306, "protocol": "tcp"}]},
            }
            first = await track(risky)
            second = await track(risky)
            findings = list((await db.execute(select(Finding))).scalars().all())
            assert first["tracked"] == second["tracked"] == 1
            assert len(findings) == 1
            assert findings[0].asset_id == asset.id
            assert findings[0].occurrence_count == 2
            assert findings[0].status == FindingStatus.OPEN

            failed = await track({
                "capability": "scan_ports",
                "target": asset.value,
                "status": "warning",
                "error": "probe timeout",
                "result": {"reachable": False, "scan_completed": False},
            })
            assert failed == {"tracked": 0, "resolved": 0, "finding_ids": []}
            assert (await db.get(Finding, findings[0].id)).status == FindingStatus.OPEN

            clean = await track({
                "capability": "scan_ports",
                "target": asset.value,
                "status": "success",
                "result": {"reachable": True, "scan_completed": True, "open_ports": []},
            })
            assert clean["resolved"] == 1
            assert (await db.get(Finding, findings[0].id)).status == FindingStatus.FIXED

            await track({
                "capability": "full_compliance_scan",
                "target": asset.value,
                "status": "success",
                "result": {
                    "scan_completed": True,
                    "sub_results": [
                        {"capability": "scan_ports", "status": "success", "data": {"scan_completed": True, "reachable": True, "open_ports": [{"port": 3306, "protocol": "tcp"}]}},
                        {"capability": "scan_vulnerabilities", "status": "success", "data": {"scan_completed": True, "reachable": True, "findings": [{"id": "CVE-DEMO", "name": "Demo finding", "severity": "high"}]}},
                    ],
                },
            })
            source_keys = set((await db.execute(select(Finding.source_key))).scalars().all())
            assert source_keys == {"scan_ports", "scan_vulnerabilities"}

        await engine.dispose()

    asyncio.run(run())
