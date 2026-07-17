"""Reconcile scan control state after assessment task execution.

Revision ID: 017
Revises: 016
Create Date: 2026-07-17
"""

from alembic import op


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE scan_tasks
        SET status = 'FAILED',
            control_state = 'failed',
            completed_at = COALESCE(completed_at, now()),
            error_message = COALESCE(error_message, '历史任务缺少执行计划和租约，已终止，必要时请重新发起检测')
        WHERE status::text = 'RUNNING'
          AND orchestrator_task_id IS NULL
          AND started_at IS NULL
          AND lease_owner IS NULL
          AND created_at < now() - INTERVAL '1 day'
    """)
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


def downgrade() -> None:
    pass
