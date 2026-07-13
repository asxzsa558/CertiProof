import asyncio
import importlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType
from app.orchestrator.orchestrator import Orchestrator

orchestrator_module = importlib.import_module("app.orchestrator.orchestrator")


def test_stop_request_wins_over_a_late_tool_result(monkeypatch):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            task = ScanTask(
                project_id=1,
                task_type=ScanTaskType.FULL,
                status=ScanTaskStatus.RUNNING,
                orchestrator_task_id="late-stop",
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)

        runner = Orchestrator()

        async def complete_after_stop(**_kwargs):
            runner.task_stop_flags["late-stop"] = True
            runner.task_status["late-stop"] = "stopped"
            return {"results": [], "success_count": 0, "failed_count": 0}

        monkeypatch.setattr(orchestrator_module, "AsyncSessionLocal", session_factory)
        monkeypatch.setattr(runner.execution_engine, "execute_plan", complete_after_stop)
        await runner._execute_plan_async(
            task_id="late-stop",
            plan=[{"capability": "scan_ports", "parameters": {"target": "203.0.113.10"}}],
            user_id=1,
            project_id=1,
            db=None,
            context_manager=None,
            scan_task_id=task.id,
        )

        async with session_factory() as db:
            persisted = (await db.execute(select(ScanTask).where(ScanTask.id == task.id))).scalar_one()
            assert persisted.status == ScanTaskStatus.CANCELLED
            assert persisted.control_state == "cancelled"
            assert (persisted.result_summary or {}).get("result_description") == "任务已停止"

        await engine.dispose()

    asyncio.run(run())
