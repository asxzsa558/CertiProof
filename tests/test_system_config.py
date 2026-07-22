import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.config import SystemConfig
from app.services.config_service import ConfigService, DEFAULT_CONFIGS
from app.services.runtime_resources import concurrency_limit


ROOT = Path(__file__).resolve().parents[1]


async def _with_config_service(callback):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=[SystemConfig.__table__])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            return await callback(db, ConfigService(db))
    finally:
        await engine.dispose()


def test_config_catalog_only_exposes_effective_runtime_controls():
    assert "runtime.assessment_concurrency" in DEFAULT_CONFIGS
    assert "ai.history_turns" in DEFAULT_CONFIGS
    assert "document.analysis_mode" in DEFAULT_CONFIGS
    assert "assessment.max_concurrent" not in DEFAULT_CONFIGS
    assert "assessment.auto_start" not in DEFAULT_CONFIGS
    assert "report.default_format" not in DEFAULT_CONFIGS


def test_batch_validation_is_atomic():
    async def scenario(db, service):
        try:
            await service.update_batch({
                "ai.history_turns": 8,
                "runtime.assessment_concurrency": 99,
            })
        except ValueError:
            pass
        else:
            raise AssertionError("invalid batch should fail")

        rows = (await db.execute(select(SystemConfig))).scalars().all()
        assert rows == []

        updated = await service.update_batch({
            "ai.history_turns": "8",
            "runtime.assessment_concurrency": 3,
        })
        await db.commit()
        assert updated == {"ai.history_turns": 8, "runtime.assessment_concurrency": 3}
        assert await service.get("ai.history_turns") == 8

    asyncio.run(_with_config_service(scenario))


def test_every_task_producer_reads_the_effective_runtime_limit(monkeypatch):
    from app.services import runtime_resources

    async def fake_status(_db):
        return {"limits": {"interactive": 2, "assessment": 7}}

    monkeypatch.setattr(runtime_resources, "runtime_status", fake_status)
    assert asyncio.run(concurrency_limit(object(), "interactive")) == 2
    assert asyncio.run(concurrency_limit(object(), "assessment")) == 7

    try:
        asyncio.run(concurrency_limit(object(), "unknown"))
    except ValueError as exc:
        assert "Unsupported runtime role" in str(exc)
    else:
        raise AssertionError("unknown runtime role should fail")


def test_task_producers_do_not_bypass_runtime_resource_limits():
    paths = [
        ROOT / "backend/app/orchestrator/orchestrator.py",
        ROOT / "backend/app/api/assessments.py",
        ROOT / "backend/app/services/assessment_task_queue.py",
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "concurrency_limit(" in source
        assert "settings.ASSESSMENT_MAX_CONCURRENT" not in source
