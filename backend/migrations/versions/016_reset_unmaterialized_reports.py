"""Reset report tasks that claim completion without a persisted artifact.

Revision ID: 016
Revises: 015
Create Date: 2026-07-17
"""

from alembic import op


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE task_instances AS task
        SET status = 'todo',
            result = NULL,
            started_at = NULL,
            completed_at = NULL
        FROM phase_instances AS phase
        WHERE task.phase_id = phase.id
          AND task.task_type = 'html_report'
          AND NOT EXISTS (
              SELECT 1 FROM report_artifacts artifact
              WHERE artifact.assessment_id = phase.assessment_id
          )
    """)


def downgrade() -> None:
    pass
