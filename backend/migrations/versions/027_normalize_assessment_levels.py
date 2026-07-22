"""Normalize per-assessment levels.

Revision ID: 027
Revises: 026
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op


revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE project_assessments AS pa
        SET level = CASE WHEN EXISTS (
            SELECT 1
            FROM assessment_types AS type
            JOIN assessments AS assessment
              ON assessment.project_id = pa.project_id
             AND assessment.assessment_type_code = type.code
            WHERE type.id = pa.assessment_type_id
              AND assessment.assessment_level = 2
        ) THEN '二级' ELSE '三级' END
        WHERE EXISTS (
            SELECT 1
            FROM assessment_types AS type
            JOIN assessments AS assessment
              ON assessment.project_id = pa.project_id
             AND assessment.assessment_type_code = type.code
            WHERE type.id = pa.assessment_type_id
        )
    """))


def downgrade() -> None:
    pass
