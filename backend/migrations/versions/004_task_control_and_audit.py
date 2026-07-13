"""Add durable task control and operational audit records.

Revision ID: 004
Revises: 003
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns(name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(name)}


def _indexes(name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(name)}


def upgrade() -> None:
    # A development build briefly placed these task-only fields on archives.
    # They are unused there and must not become part of the public archive model.
    if _table_exists("conversation_archives"):
        archive_columns = _columns("conversation_archives")
        for column in ("cancel_requested_at", "paused_at", "checkpoint", "control_state"):
            if column in archive_columns:
                op.drop_column("conversation_archives", column)

    if _table_exists("scan_tasks"):
        columns = _columns("scan_tasks")
        if "control_state" not in columns:
            op.add_column("scan_tasks", sa.Column("control_state", sa.String(length=24), nullable=False, server_default="running"))
        if "checkpoint" not in columns:
            op.add_column("scan_tasks", sa.Column("checkpoint", sa.JSON(), nullable=True))
        if "paused_at" not in columns:
            op.add_column("scan_tasks", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
        if "cancel_requested_at" not in columns:
            op.add_column("scan_tasks", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
        indexes = _indexes("scan_tasks")
        if "ix_scan_tasks_control_state" not in indexes:
            op.create_index("ix_scan_tasks_control_state", "scan_tasks", ["control_state"])

    if not _table_exists("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("resource_type", sa.String(length=80), nullable=False),
            sa.Column("resource_id", sa.String(length=80), nullable=True),
            sa.Column("outcome", sa.String(length=20), nullable=False, server_default="success"),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    indexes = _indexes("audit_events")
    for name, columns in (
        ("ix_audit_events_organization_id", ["organization_id"]),
        ("ix_audit_events_project_id", ["project_id"]),
        ("ix_audit_events_actor_user_id", ["actor_user_id"]),
        ("ix_audit_events_event_type", ["event_type"]),
        ("ix_audit_events_resource_id", ["resource_id"]),
        ("ix_audit_events_outcome", ["outcome"]),
        ("ix_audit_events_created_at", ["created_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "audit_events", columns)


def downgrade() -> None:
    if _table_exists("audit_events"):
        op.drop_table("audit_events")
    if _table_exists("scan_tasks"):
        indexes = _indexes("scan_tasks")
        if "ix_scan_tasks_control_state" in indexes:
            op.drop_index("ix_scan_tasks_control_state", table_name="scan_tasks")
        columns = _columns("scan_tasks")
        for column in ("cancel_requested_at", "paused_at", "checkpoint", "control_state"):
            if column in columns:
                op.drop_column("scan_tasks", column)
