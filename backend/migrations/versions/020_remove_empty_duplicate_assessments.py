"""Remove empty duplicate assessment instances.

Revision ID: 020
Revises: 019
Create Date: 2026-07-18
"""

from alembic import op


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


STALE_ASSESSMENTS = """
    SELECT id
    FROM (
        SELECT
            assessment.*,
            row_number() OVER (
                PARTITION BY project_id
                ORDER BY
                    CASE status
                        WHEN 'completed' THEN 5
                        WHEN 'in_progress' THEN 4
                        WHEN 'paused' THEN 3
                        WHEN 'failed' THEN 2
                        ELSE 1
                    END DESC,
                    progress DESC,
                    created_at DESC,
                    id DESC
            ) AS keep_rank
        FROM assessments AS assessment
    ) AS ranked
    WHERE keep_rank > 1
      AND status = 'not_started'
      AND COALESCE(progress, 0) = 0
      AND started_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM document_files WHERE document_files.assessment_id = ranked.id
      )
      AND NOT EXISTS (
          SELECT 1 FROM document_analysis_runs WHERE document_analysis_runs.assessment_id = ranked.id
      )
      AND NOT EXISTS (
          SELECT 1 FROM verification_runs WHERE verification_runs.assessment_id = ranked.id
      )
      AND NOT EXISTS (
          SELECT 1 FROM report_artifacts WHERE report_artifacts.assessment_id = ranked.id
      )
"""


def upgrade() -> None:
    op.execute(f"DELETE FROM flow_events WHERE assessment_id IN ({STALE_ASSESSMENTS})")
    op.execute(
        f"DELETE FROM task_instances WHERE phase_id IN "
        f"(SELECT id FROM phase_instances WHERE assessment_id IN ({STALE_ASSESSMENTS}))"
    )
    op.execute(f"DELETE FROM phase_instances WHERE assessment_id IN ({STALE_ASSESSMENTS})")
    op.execute(f"DELETE FROM assessments WHERE id IN ({STALE_ASSESSMENTS})")


def downgrade() -> None:
    pass
