"""Invalidate reports generated before failed checks affected the score.

Revision ID: 019
Revises: 018
Create Date: 2026-07-18
"""

from alembic import op


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE report_artifacts
        SET status = 'stale',
            stale_reason = '评分规则已更新，失败和无法验证项现按 0 分计入，请重新生成报告',
            invalidated_at = now()
        WHERE status = 'current'
    """)
    op.execute("""
        UPDATE task_instances AS task
        SET status = 'todo', result = NULL, started_at = NULL, completed_at = NULL
        FROM phase_instances AS phase
        WHERE task.phase_id = phase.id
          AND task.task_type = 'html_report'
          AND EXISTS (
              SELECT 1 FROM report_artifacts artifact
              WHERE artifact.task_id = task.id AND artifact.status = 'stale'
          )
    """)


def downgrade() -> None:
    pass
