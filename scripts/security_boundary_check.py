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

    config = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
    assert "def validate_runtime_security" in config
    assert "SECRET_KEY must be set to a strong non-default value" in config
    assert "DEBUG must be false in production" in config

    scan_service = (ROOT / "backend/app/services/scan_service.py").read_text(encoding="utf-8")
    assert "Project.user_id == user_id" not in scan_service
    assert "ScanTask.project_id == project_id" in scan_service

    chat_api = (ROOT / "backend/app/api/chat.py").read_text(encoding="utf-8")
    assert "async def _can_read_task_payload" in chat_api
    assert "await _can_read_task_payload(task, db, current_user)" in chat_api
    assert "await _can_read_task_payload(progress, db, current_user)" in chat_api

    orchestrator = (ROOT / "backend/app/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    assert "async def recover_incomplete_scan_tasks" in orchestrator
    assert "single-process recovery only" in orchestrator
    main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    assert "await orchestrator.recover_incomplete_scan_tasks(db)" in main


def main() -> int:
    assert_redaction()
    assert_source_guards()
    print("security boundary check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
