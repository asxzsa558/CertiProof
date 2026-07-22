"""Add independent Dengbao and Miping assessment scopes.

Revision ID: 026
Revises: 025
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op


revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_templates",
        sa.Column("assessment_type_code", sa.String(50), nullable=False, server_default="dengbao"),
    )
    op.create_index("ix_flow_templates_assessment_type_code", "flow_templates", ["assessment_type_code"])
    op.add_column(
        "assessments",
        sa.Column("assessment_type_code", sa.String(50), nullable=False, server_default="dengbao"),
    )
    op.create_index("ix_assessments_assessment_type_code", "assessments", ["assessment_type_code"])
    op.add_column(
        "scan_tasks",
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE")),
    )
    op.create_index("ix_scan_tasks_assessment_id", "scan_tasks", ["assessment_id"])
    op.add_column(
        "findings",
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE")),
    )
    op.create_index("ix_findings_assessment_id", "findings", ["assessment_id"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("""
            UPDATE scan_tasks AS scan
            SET assessment_id = (
                SELECT id FROM assessments
                WHERE project_id = scan.project_id AND assessment_type_code = 'dengbao'
                ORDER BY id DESC LIMIT 1
            )
            WHERE scan.assessment_id IS NULL
              AND scan.parameters ->> 'source' = 'assessment_task'
        """))
        op.execute(sa.text("""
            UPDATE findings AS finding
            SET assessment_id = COALESCE(
                (SELECT assessment_id FROM scan_tasks WHERE id = finding.scan_task_id),
                (SELECT assessment_id FROM document_analysis_runs WHERE id = finding.document_run_id),
                (SELECT id FROM assessments WHERE project_id = finding.project_id
                 AND assessment_type_code = 'dengbao' ORDER BY id DESC LIMIT 1)
            )
            WHERE finding.assessment_id IS NULL
              AND finding.source_type IN ('document', 'technical')
        """))


def downgrade() -> None:
    op.drop_index("ix_findings_assessment_id", table_name="findings")
    op.drop_column("findings", "assessment_id")
    op.drop_index("ix_scan_tasks_assessment_id", table_name="scan_tasks")
    op.drop_column("scan_tasks", "assessment_id")
    op.drop_index("ix_assessments_assessment_type_code", table_name="assessments")
    op.drop_column("assessments", "assessment_type_code")
    op.drop_index("ix_flow_templates_assessment_type_code", table_name="flow_templates")
    op.drop_column("flow_templates", "assessment_type_code")
