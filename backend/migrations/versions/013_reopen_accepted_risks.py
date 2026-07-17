"""Return accepted-risk shortcuts to the real remediation workflow.

Revision ID: 013
Revises: 012
Create Date: 2026-07-16
"""

from alembic import op


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE findings SET status = 'open', resolved_at = NULL WHERE status = 'accepted_risk'")


def downgrade() -> None:
    pass
