#!/usr/bin/env python3
"""Dependency-light checks for security boundary helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_redaction() -> None:
    redaction = load_module(ROOT / "backend/app/core/redaction.py", "redaction_check")
    payload = {
        "target": "10.0.0.1",
        "ssh_password": "secret",
        "nested": {"api_key": "key", "port": 22},
        "items": [{"credential": "token"}],
    }
    clean = redaction.redact_sensitive(payload)
    assert clean["target"] == "10.0.0.1"
    assert clean["ssh_password"] == redaction.REDACTED
    assert clean["nested"]["api_key"] == redaction.REDACTED
    assert clean["items"][0]["credential"] == redaction.REDACTED


def assert_source_guards() -> None:
    ai_engine = (ROOT / "backend/app/services/ai_engine.py").read_text(encoding="utf-8")
    assert "def _validate_step" in ai_engine
    assert "Dropped unknown parameter" in ai_engine
    assert "redact_sensitive(plan)" in ai_engine
    assert "Raw LLM content received (length=%d)" in ai_engine

    execution_engine = (ROOT / "backend/app/services/execution_engine.py").read_text(encoding="utf-8")
    assert "safe_parameters = redact_sensitive(parameters)" in execution_engine
    assert "parameters=redact_sensitive(parameters)" in execution_engine
    assert "async def _project_for_user_id" in execution_engine
    assert "Project.id == project_id, Project.user_id == user_id" not in execution_engine
    assert "Project.id == pid, Project.user_id == user_id" not in execution_engine

    config = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
    assert "def validate_runtime_security" in config
    assert "SECRET_KEY must be set to a strong non-default value" in config
    assert "DEBUG must be false in production" in config
    assert 'TASK_EXECUTION_MODE: str = "inline"' in config
    assert "TASK_WORKER_POLL_SECONDS" in config
    assert "TASK_LEASE_MINUTES" in config
    assert "MONITORING_WORKER_BATCH_SIZE" in config

    scan_service = (ROOT / "backend/app/services/scan_service.py").read_text(encoding="utf-8")
    assert "Project.user_id == user_id" not in scan_service
    assert "ScanTask.project_id == project_id" in scan_service
    assert "user_id = parameters.get(\"user_id\") or project.owner_id or project.user_id" in scan_service
    scans_api = (ROOT / "backend/app/api/scans.py").read_text(encoding="utf-8")
    assert "BackgroundTasks" not in scans_api
    assert "orchestrator.start_async_plan" in scans_api

    chat_api = (ROOT / "backend/app/api/chat.py").read_text(encoding="utf-8")
    assert "async def _can_read_task_payload" in chat_api
    assert "await _can_read_task_payload(task, db, current_user)" in chat_api
    assert "await _can_read_task_payload(progress, db, current_user)" in chat_api
    assert "project_id: Optional[int] = None" in chat_api
    assert "ContextManager(db, current_user.id, project_id=req.project_id, thread_id=req.thread_id)" in chat_api

    orchestrator = (ROOT / "backend/app/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    assert "async def recover_incomplete_scan_tasks" in orchestrator
    assert "update(ScanTask)" in orchestrator
    assert "lease_owner=self.worker_id" in orchestrator
    assert "lease_expires_at=now + timedelta(minutes=settings.TASK_LEASE_MINUTES)" in orchestrator
    scan_task_model = (ROOT / "backend/app/models/scan_task.py").read_text(encoding="utf-8")
    assert "lease_owner" in scan_task_model
    assert "lease_expires_at" in scan_task_model
    main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    assert 'settings.TASK_EXECUTION_MODE == "inline"' in main
    assert "await orchestrator.recover_incomplete_scan_tasks(db)" in main
    worker = (ROOT / "backend/app/worker.py").read_text(encoding="utf-8")
    assert "async def run_worker" in worker
    assert "await orchestrator.recover_incomplete_scan_tasks(db)" in worker
    assert "run_due_scheduled_scans" in worker
    tasks_api = (ROOT / "backend/app/api/tasks.py").read_text(encoding="utf-8")
    assert 'lease_owner = "paused"' in tasks_api
    assert 'lease_owner = "resumed"' in tasks_api
    assert "ScanTaskStatus.PENDING" in tasks_api
    monitoring_api = (ROOT / "backend/app/api/monitoring.py").read_text(encoding="utf-8")
    assert "TODO: Generate findings from scan results" not in monitoring_api
    assert "TODO: Implement change detection" not in monitoring_api
    assert "created_findings = []" in monitoring_api
    assert "changes_detected=changes[\"changes_detected\"]" in monitoring_api
    assert "async def run_due_scheduled_scans" in monitoring_api
    assert "update(ScheduledScan)" in monitoring_api

    context_manager = (ROOT / "backend/app/services/context_manager.py").read_text(encoding="utf-8")
    assert "ConversationHistory.project_id == self.project_id" in context_manager
    assert "ConversationThread.project_id == self.project_id" in context_manager


def main() -> int:
    assert_redaction()
    assert_source_guards()
    print("security boundary check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
