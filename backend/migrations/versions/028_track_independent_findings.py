"""Track independent findings with precise asset provenance.

Revision ID: 028
Revises: 027
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from alembic import op


revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("asset_id", sa.Integer(), nullable=True))
    op.add_column("findings", sa.Column("source_channel", sa.String(length=24), nullable=True))
    op.add_column("findings", sa.Column("origin_finding_id", sa.Integer(), nullable=True))
    op.add_column("findings", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("findings", sa.Column("occurrence_count", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_findings_asset_id", "findings", "assets", ["asset_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_findings_origin_finding_id", "findings", "findings", ["origin_finding_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_findings_asset_id", "findings", ["asset_id"])
    op.create_index("ix_findings_source_channel", "findings", ["source_channel"])
    op.create_index("ix_findings_origin_finding_id", "findings", ["origin_finding_id"])
    op.create_index("ix_findings_last_seen_at", "findings", ["last_seen_at"])
    op.execute("UPDATE findings f SET asset_id = s.asset_id FROM scan_tasks s WHERE f.scan_task_id = s.id AND f.asset_id IS NULL AND s.asset_id IS NOT NULL")
    op.execute("UPDATE findings f SET asset_id = a.id FROM assets a WHERE f.asset_id IS NULL AND a.project_id = f.project_id AND LOWER(TRIM(a.value)) = LOWER(TRIM(f.scope_key))")
    op.execute("UPDATE findings SET source_channel = CASE WHEN assessment_id IS NULL THEN 'independent' ELSE 'assessment' END")
    op.execute("UPDATE findings SET occurrence_count = 1, last_seen_at = COALESCE(updated_at, created_at)")
    op.alter_column("findings", "source_channel", nullable=False, server_default="assessment")
    op.alter_column("findings", "occurrence_count", nullable=False, server_default="1")


def downgrade() -> None:
    op.drop_index("ix_findings_last_seen_at", table_name="findings")
    op.drop_index("ix_findings_origin_finding_id", table_name="findings")
    op.drop_index("ix_findings_source_channel", table_name="findings")
    op.drop_index("ix_findings_asset_id", table_name="findings")
    op.drop_constraint("fk_findings_origin_finding_id", "findings", type_="foreignkey")
    op.drop_constraint("fk_findings_asset_id", "findings", type_="foreignkey")
    op.drop_column("findings", "occurrence_count")
    op.drop_column("findings", "last_seen_at")
    op.drop_column("findings", "origin_finding_id")
    op.drop_column("findings", "source_channel")
    op.drop_column("findings", "asset_id")
