"""Restore reports invalidated only by ad-hoc scans.

Revision ID: 021
Revises: 020
Create Date: 2026-07-18
"""

from alembic import op


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


ELIGIBLE_REPORTS = """
    SELECT artifact.id
    FROM report_artifacts AS artifact
    WHERE artifact.status = 'stale'
      AND artifact.stale_reason IN ('已发起新的安全检测', '定时安全检测已产生新数据')
      AND NOT EXISTS (
          SELECT 1
          FROM report_artifacts AS current_artifact
          WHERE current_artifact.project_id = artifact.project_id
            AND current_artifact.status = 'current'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM phase_instances AS phase
          WHERE phase.assessment_id = artifact.assessment_id
            AND phase.phase_id <> 'report'
            AND phase.status <> 'completed'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM task_instances AS task
          JOIN phase_instances AS phase ON phase.id = task.phase_id
          WHERE phase.assessment_id = artifact.assessment_id
            AND phase.phase_id <> 'report'
            AND task.completed_at > artifact.created_at
      )
      AND artifact.version = (
          SELECT max(latest.version)
          FROM report_artifacts AS latest
          WHERE latest.project_id = artifact.project_id
      )
"""


def upgrade() -> None:
    op.execute(f"""
        CREATE TEMPORARY TABLE restored_ad_hoc_reports
        ON COMMIT DROP
        AS {ELIGIBLE_REPORTS}
    """)
    op.execute("""
        UPDATE report_artifacts
        SET status = 'current',
            stale_reason = NULL,
            invalidated_at = NULL
        WHERE id IN (SELECT id FROM restored_ad_hoc_reports)
    """)
    op.execute("""
        UPDATE task_instances AS task
        SET status = 'completed',
            result = jsonb_build_object(
                'status', 'completed',
                'format', 'html',
                'artifact', jsonb_build_object(
                    'id', artifact.id,
                    'version', artifact.version,
                    'status', 'current'
                ),
                'summary', artifact.snapshot::jsonb -> 'summary'
            ),
            started_at = COALESCE(task.started_at, artifact.created_at),
            completed_at = COALESCE(task.completed_at, artifact.created_at)
        FROM report_artifacts AS artifact
        WHERE task.id = artifact.task_id
          AND artifact.id IN (SELECT id FROM restored_ad_hoc_reports)
    """)
    op.execute("""
        UPDATE phase_instances AS phase
        SET status = 'completed',
            progress = 100,
            completed_tasks = phase.total_tasks,
            started_at = COALESCE(phase.started_at, artifact.created_at),
            completed_at = COALESCE(phase.completed_at, artifact.created_at)
        FROM report_artifacts AS artifact
        WHERE phase.assessment_id = artifact.assessment_id
          AND phase.phase_id = 'report'
          AND artifact.id IN (SELECT id FROM restored_ad_hoc_reports)
    """)
    op.execute("""
        UPDATE assessments AS assessment
        SET status = 'completed',
            progress = 100,
            completed_phases = assessment.total_phases,
            completed_at = COALESCE(assessment.completed_at, artifact.created_at)
        FROM report_artifacts AS artifact
        WHERE assessment.id = artifact.assessment_id
          AND artifact.id IN (SELECT id FROM restored_ad_hoc_reports)
    """)
    op.execute("""
        UPDATE projects AS project
        SET compliance_score = COALESCE(
            NULLIF(artifact.snapshot::jsonb -> 'score_metrics' ->> 'score', '')::double precision,
            NULLIF(artifact.snapshot::jsonb -> 'project' ->> 'compliance_score', '')::double precision
        )
        FROM report_artifacts AS artifact
        WHERE project.id = artifact.project_id
          AND artifact.id IN (SELECT id FROM restored_ad_hoc_reports)
    """)


def downgrade() -> None:
    pass
