import asyncio

from app import worker


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return None


class _ActiveTask:
    def done(self):
        return False


async def _runtime_status(_db):
    return {
        "pressure": {"paused": False, "reasons": []},
        "limits": {"interactive": 5, "document": 2, "assessment": 4, "verification": 2},
    }


def test_interactive_worker_only_claims_available_capacity(monkeypatch):
    from app.services import runtime_resources

    claimed_limits = []

    async def recover(_db, limit):
        claimed_limits.append(limit)
        return limit

    monkeypatch.setattr(worker, "AsyncSessionLocal", _SessionContext)
    monkeypatch.setattr(runtime_resources, "runtime_status", _runtime_status)
    monkeypatch.setattr(worker.settings, "INTERACTIVE_SCAN_MAX_CONCURRENT", 5)
    monkeypatch.setattr(worker.orchestrator, "active_tasks", {str(index): _ActiveTask() for index in range(3)})
    monkeypatch.setattr(worker.orchestrator, "recover_incomplete_scan_tasks", recover)

    assert asyncio.run(worker._run_role_once("interactive")) == 2
    assert claimed_limits == [2]


def test_document_worker_does_not_run_other_queues(monkeypatch):
    from app.services import document_pipeline, runtime_resources

    async def process(_db, limit):
        assert limit == 2
        return 3

    monkeypatch.setattr(worker, "AsyncSessionLocal", _SessionContext)
    monkeypatch.setattr(runtime_resources, "runtime_status", _runtime_status)
    monkeypatch.setattr(document_pipeline, "process_pending_document_runs", process)

    assert asyncio.run(worker._run_role_once("document")) == 3
