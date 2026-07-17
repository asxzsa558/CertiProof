"""Make durable scan control state agree with the task lifecycle.

Revision ID: 014
Revises: 013
Create Date: 2026-07-17
"""

from alembic import op


revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE scan_tasks
        SET control_state = CASE status::text
            WHEN 'COMPLETED' THEN 'completed'
            WHEN 'FAILED' THEN 'failed'
            WHEN 'CANCELLED' THEN 'cancelled'
            WHEN 'PENDING' THEN CASE WHEN control_state = 'paused' THEN 'paused' ELSE 'queued' END
            WHEN 'RUNNING' THEN CASE WHEN control_state = 'paused' THEN 'paused' ELSE 'running' END
            ELSE control_state
        END
    """)
    op.alter_column("scan_tasks", "control_state", server_default="queued")


def downgrade() -> None:
    op.alter_column("scan_tasks", "control_state", server_default="running")
