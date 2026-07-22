"""Add remote scan nodes and leased executions.

Revision ID: 025
Revises: 024
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op


revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("location", sa.String(160)),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_cidrs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("project_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enrollment_token_hash", sa.String(64)),
        sa.Column("enrollment_expires_at", sa.DateTime(timezone=True)),
        sa.Column("node_token_hash", sa.String(64)),
        sa.Column("enrolled_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("runtime_info", sa.JSON()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_scan_nodes_organization_id", "scan_nodes", ["organization_id"])
    op.create_index("ix_scan_nodes_last_seen_at", "scan_nodes", ["last_seen_at"])
    op.create_table(
        "remote_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_node_id", sa.Integer(), sa.ForeignKey("scan_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("target", sa.String(500), nullable=False),
        sa.Column("payload_envelope", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("control_state", sa.String(24), nullable=False, server_default="active"),
        sa.Column("progress", sa.JSON()),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for column in ("scan_node_id", "organization_id", "project_id", "capability", "status", "lease_expires_at", "created_at"):
        op.create_index(f"ix_remote_executions_{column}", "remote_executions", [column])


def downgrade() -> None:
    op.drop_table("remote_executions")
    op.drop_table("scan_nodes")
