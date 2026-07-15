"""Stop treating incomplete tool runs as security findings.

Revision ID: 005
Revises: 004
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if not {"findings", "remediation_tickets"}.issubset(tables):
        return
    params = {"name": "自动化技术检测", "pattern": "%检测未完成（不代表通过）%"}
    op.get_bind().execute(sa.text("""
        UPDATE remediation_tickets
        SET status = 'CLOSED',
            resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP),
            resolution_notes = COALESCE(resolution_notes, '检测未完成仅表示覆盖不足，不作为安全风险。')
        WHERE finding_id IN (
            SELECT id FROM findings WHERE clause_name = :name AND description LIKE :pattern
        )
    """), params)
    op.get_bind().execute(sa.text("""
        UPDATE findings
        SET status = 'RESOLVED',
            resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE clause_name = :name AND description LIKE :pattern
    """), params)


def downgrade() -> None:
    # Historical false findings must not be reopened.
    pass
