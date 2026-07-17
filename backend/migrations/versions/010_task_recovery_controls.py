"""Add durable heartbeats and cancellation state for long tasks.

Revision ID: 010
Revises: 009
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    document_columns = _columns(bind, "document_analysis_runs")
    additions = {
        "lease_owner": sa.Column("lease_owner", sa.String(length=128), nullable=True),
        "lease_expires_at": sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        "heartbeat_at": sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        "cancel_requested_at": sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        "attempt_count": sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    }
    for name, column in additions.items():
        if name not in document_columns:
            op.add_column("document_analysis_runs", column)

    document_indexes = _indexes(bind, "document_analysis_runs")
    for column in ("lease_owner", "lease_expires_at", "heartbeat_at"):
        name = f"ix_document_analysis_runs_{column}"
        if name not in document_indexes:
            op.create_index(name, "document_analysis_runs", [column])

    task_columns = _columns(bind, "task_instances")
    for name in ("heartbeat_at", "cancel_requested_at"):
        if name not in task_columns:
            op.add_column("task_instances", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    task_indexes = _indexes(bind, "task_instances")
    if "ix_task_instances_heartbeat_at" not in task_indexes:
        op.create_index("ix_task_instances_heartbeat_at", "task_instances", ["heartbeat_at"])


def downgrade() -> None:
    bind = op.get_bind()
    task_indexes = _indexes(bind, "task_instances")
    if "ix_task_instances_heartbeat_at" in task_indexes:
        op.drop_index("ix_task_instances_heartbeat_at", table_name="task_instances")
    task_columns = _columns(bind, "task_instances")
    for name in ("cancel_requested_at", "heartbeat_at"):
        if name in task_columns:
            op.drop_column("task_instances", name)

    document_indexes = _indexes(bind, "document_analysis_runs")
    for column in ("heartbeat_at", "lease_expires_at", "lease_owner"):
        name = f"ix_document_analysis_runs_{column}"
        if name in document_indexes:
            op.drop_index(name, table_name="document_analysis_runs")
    document_columns = _columns(bind, "document_analysis_runs")
    for name in ("attempt_count", "cancel_requested_at", "heartbeat_at", "lease_expires_at", "lease_owner"):
        if name in document_columns:
            op.drop_column("document_analysis_runs", name)
