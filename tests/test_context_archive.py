import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from fastapi import HTTPException

import app.models  # noqa: F401
from app.api import projects as projects_api
from app.core.database import Base
from app.models.context import ActionHistory, ConversationArchive, ConversationHistory, ConversationSummary, ConversationThread
from app.models.project import ProjectStatus
from app.services.context_manager import ContextManager


def test_archive_keeps_raw_messages_and_thread_scope_isolated():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add_all([
                ConversationHistory(user_id=1, project_id=1, thread_id=None, role="user", content="默认线程", tokens_used=4),
                ConversationHistory(user_id=1, project_id=1, thread_id=9, role="user", content="独立线程", tokens_used=4),
                ActionHistory(user_id=1, project_id=1, thread_id=None, action_type="default", parameters={}),
                ActionHistory(user_id=1, project_id=1, thread_id=9, action_type="isolated", parameters={}),
            ])
            await db.commit()

            default_context = ContextManager(db, user_id=1, project_id=1, thread_id=None)
            thread_context = ContextManager(db, user_id=1, project_id=1, thread_id=9)
            assert [item["content"] for item in await default_context._get_conversation_history()] == ["默认线程"]
            assert [item["content"] for item in await thread_context._get_conversation_history()] == ["独立线程"]
            assert [item["action_type"] for item in await default_context._get_action_history()] == ["default"]
            assert [item["action_type"] for item in await thread_context._get_action_history()] == ["isolated"]

            archive_id = await default_context.create_archive_placeholder("默认线程归档")
            archive = (await db.execute(select(ConversationArchive).where(ConversationArchive.id == archive_id))).scalar_one()
            raw_messages = list((await db.execute(
                select(ConversationHistory).where(ConversationHistory.archive_id == archive_id)
            )).scalars().all())
            assert archive.status == "queued"
            assert [message.content for message in raw_messages] == ["默认线程"]
            assert await default_context._get_conversation_history() == []
            assert [item["content"] for item in await thread_context._get_conversation_history()] == ["独立线程"]

            archive.status = "completed"
            archive.summary = "可接续"
            await db.commit()
            continued = await default_context.continue_from_archive(archive_id)
            assert continued and continued["archive_id"] == archive_id

        await engine.dispose()

    asyncio.run(run())


def test_conversation_history_uses_id_to_order_same_timestamp_pairs():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        created_at = datetime.now(timezone.utc)
        async with session_factory() as db:
            db.add_all([
                ConversationHistory(user_id=1, project_id=1, role="user", content="问题", created_at=created_at),
                ConversationHistory(user_id=1, project_id=1, role="assistant", content="回答", created_at=created_at),
            ])
            await db.commit()
            history = await ContextManager(db, user_id=1, project_id=1)._get_conversation_history()
            assert [item["content"] for item in history] == ["问题", "回答"]

        await engine.dispose()

    asyncio.run(run())


def test_archived_project_blocks_mutations_but_keeps_read_access(monkeypatch):
    class Result:
        def scalar_one_or_none(self):
            return project

    class Db:
        async def execute(self, _query):
            return Result()

    class Project:
        id = 1
        organization_id = None
        user_id = 1
        status = ProjectStatus.ARCHIVED

    project = Project()

    async def run():
        assert await projects_api.get_project_for_user(Db(), 1, 1, "project:read") is project
        try:
            await projects_api.get_project_for_user(Db(), 1, 1, "scan:execute")
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("archived project accepted a mutation")

    asyncio.run(run())


def test_compression_queues_a_source_backed_segment_without_deleting_messages():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add_all([
                ConversationHistory(user_id=1, project_id=1, thread_id=None, role="user", content=f"消息 {index}", tokens_used=10)
                for index in range(40)
            ])
            await db.commit()
            context = ContextManager(db, user_id=1, project_id=1, thread_id=None)
            await context._compress_conversation_if_needed()
            segment = (await db.execute(select(ConversationSummary))).scalar_one()
            message_count = (await db.execute(select(ConversationHistory))).scalars().all()
            assert segment.status == "queued"
            assert segment.message_count == 40
            assert len(message_count) == 40

        await engine.dispose()

    asyncio.run(run())


def test_long_thread_rolls_over_without_deleting_raw_messages():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as db:
            db.add_all([
                ConversationHistory(user_id=1, project_id=1, role="user" if index % 2 == 0 else "assistant", content=f"归档测试消息 {index}", tokens_used=10)
                for index in range(ContextManager.AUTO_ROLLOVER_MESSAGES)
            ])
            await db.commit()
            context = ContextManager(db, user_id=1, project_id=1)
            rollover = await context.maybe_auto_rollover()
            assert rollover and rollover["thread_id"]
            archive = await db.get(ConversationArchive, rollover["archive_id"])
            assert archive.message_count == ContextManager.AUTO_ROLLOVER_MESSAGES
            assert len((await db.execute(select(ConversationHistory).where(ConversationHistory.archive_id == archive.id))).scalars().all()) == ContextManager.AUTO_ROLLOVER_MESSAGES
            thread = await db.get(ConversationThread, rollover["thread_id"])
            assert thread.source_archive_id == archive.id
            recalled = await ContextManager(db, user_id=1, project_id=1).recall_archived_messages("归档测试消息")
            assert recalled and recalled[0]["archive_id"] == archive.id
        await engine.dispose()

    asyncio.run(run())


def test_auto_cleanup_accepts_timezone_aware_history_timestamps():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add(ConversationHistory(
                user_id=1,
                project_id=1,
                role="user",
                content="历史消息",
                created_at=datetime.now(timezone.utc) - timedelta(days=91),
            ))
            await db.commit()
            await ContextManager(db, user_id=1, project_id=1)._auto_cleanup()
            await db.commit()
            assert (await db.execute(select(ConversationHistory))).scalars().all() == []

        await engine.dispose()

    asyncio.run(run())
