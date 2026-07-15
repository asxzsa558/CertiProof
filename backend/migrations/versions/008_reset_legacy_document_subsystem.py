"""Remove legacy document-analysis data before the new pipeline is used.

Revision ID: 008
Revises: 007
Create Date: 2026-07-15
"""

import os
import re
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def _remove_uploads(paths: list[str]) -> None:
    root = Path(os.getenv("UPLOAD_DIR", "/app/uploads")).resolve()
    for value in paths:
        if not value:
            continue
        candidate = Path(value)
        candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            candidate.unlink()


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"task_instances", "findings", "evidences"}.issubset(tables):
        return

    legacy_paths = list(bind.execute(sa.text("""
        SELECT file_path FROM evidences
        WHERE UPPER(CAST(evidence_type AS VARCHAR)) IN ('DOCUMENT', 'POLICY', 'RECORD')
    """)).scalars())
    if "document_files" in tables:
        legacy_paths.extend(bind.execute(sa.text("SELECT storage_path FROM document_files")).scalars())
    _remove_uploads(legacy_paths)

    bind.execute(sa.text("""
        DELETE FROM remediation_tickets
        WHERE finding_id IN (
            SELECT id FROM findings
            WHERE clause_id LIKE 'DOC-TASK-%' OR document_run_id IS NOT NULL
        )
    """))
    bind.execute(sa.text("""
        DELETE FROM evidences
        WHERE finding_id IN (
            SELECT id FROM findings
            WHERE clause_id LIKE 'DOC-TASK-%' OR document_run_id IS NOT NULL
        )
        OR UPPER(CAST(evidence_type AS VARCHAR)) IN ('DOCUMENT', 'POLICY', 'RECORD')
    """))
    bind.execute(sa.text("""
        DELETE FROM findings
        WHERE clause_id LIKE 'DOC-TASK-%' OR document_run_id IS NOT NULL
    """))

    if "document_files" in tables:
        bind.execute(sa.text("DELETE FROM document_files"))
    if "document_analysis_runs" in tables:
        bind.execute(sa.text("DELETE FROM document_analysis_runs"))

    bind.execute(sa.text("""
        DELETE FROM flow_events
        WHERE task_id IN (SELECT id FROM task_instances WHERE task_type = 'doc_review')
    """))
    bind.execute(sa.text("""
        UPDATE task_instances
        SET status = 'todo', result = NULL, evidence_ids = NULL,
            started_at = NULL, completed_at = NULL,
            lease_owner = NULL, lease_expires_at = NULL
        WHERE task_type = 'doc_review'
    """))

    if bind.dialect.name == "postgresql":
        graph = os.getenv("GRAPH_NAME", "certiproof")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,62}", graph):
            raise ValueError("Invalid GRAPH_NAME")
        op.execute("LOAD 'age'")
        op.execute('SET search_path = ag_catalog, "$user", public')
        for label in ("Project", "Assessment", "Run", "Document", "Page", "Section", "Block"):
            op.execute(sa.text(
                f"SELECT * FROM cypher('{graph}', $$ "
                f"MATCH (n:{label}) DETACH DELETE n RETURN count(n) "
                "$$) AS (deleted agtype)"
            ))


def downgrade() -> None:
    pass
