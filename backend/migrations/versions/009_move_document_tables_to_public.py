"""Move document tables out of the Apache AGE catalog schema.

Revision ID: 009
Revises: 008
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


DOCUMENT_TABLES = (
    "knowledge_graph_revisions",
    "document_analysis_runs",
    "document_files",
    "document_run_files",
    "document_blocks",
    "document_control_results",
    "document_evidence_links",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in DOCUMENT_TABLES:
        exists = bind.execute(
            sa.text("SELECT to_regclass(:name)"),
            {"name": f"ag_catalog.{table}"},
        ).scalar()
        if exists:
            op.execute(f'ALTER TABLE ag_catalog."{table}" SET SCHEMA public')
    op.execute('SET search_path = public, ag_catalog, "$user"')


def downgrade() -> None:
    pass
