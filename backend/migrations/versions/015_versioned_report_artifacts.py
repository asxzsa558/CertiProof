"""Persist immutable HTML report artifacts.

Revision ID: 015
Revises: 014
Create Date: 2026-07-17
"""

import sqlalchemy as sa
from alembic import op


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="current", nullable=False),
        sa.Column("html_path", sa.String(length=1000), nullable=False),
        sa.Column("html_sha256", sa.String(length=64), nullable=False),
        sa.Column("html_size", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("generated_by", sa.Integer(), nullable=True),
        sa.Column("stale_reason", sa.Text(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task_instances.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version", name="uq_report_artifact_project_version"),
    )
    op.create_index("ix_report_artifacts_project_id", "report_artifacts", ["project_id"])
    op.create_index("ix_report_artifacts_assessment_id", "report_artifacts", ["assessment_id"])
    op.create_index("ix_report_artifacts_task_id", "report_artifacts", ["task_id"])
    op.create_index("ix_report_artifacts_status", "report_artifacts", ["status"])


def downgrade() -> None:
    op.drop_table("report_artifacts")
