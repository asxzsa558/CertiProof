"""Recount scan findings after removing incomplete runs from risk data.

Revision ID: 006
Revises: 005
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not {"findings", "scan_tasks"}.issubset(sa.inspect(op.get_bind()).get_table_names()):
        return
    visible = "NOT (f.clause_name = '自动化技术检测' AND f.description LIKE '%检测未完成（不代表通过）%')"
    op.execute(sa.text(f"""
        UPDATE scan_tasks AS s SET
            findings_count = (SELECT COUNT(*) FROM findings f WHERE f.scan_task_id = s.id AND {visible}),
            high_severity_count = (SELECT COUNT(*) FROM findings f WHERE f.scan_task_id = s.id AND {visible} AND f.severity IN ('CRITICAL', 'HIGH')),
            medium_severity_count = (SELECT COUNT(*) FROM findings f WHERE f.scan_task_id = s.id AND {visible} AND f.severity = 'MEDIUM'),
            low_severity_count = (SELECT COUNT(*) FROM findings f WHERE f.scan_task_id = s.id AND {visible} AND f.severity IN ('LOW', 'INFO'))
    """))


def downgrade() -> None:
    pass
