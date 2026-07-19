"""Clear ineffective custom roles from organization administrators.

Revision ID: 022
Revises: 021
Create Date: 2026-07-18
"""

from alembic import op


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE organization_members
        SET custom_role_id = NULL
        WHERE role = 'admin'
          AND custom_role_id IS NOT NULL
    """)


def downgrade() -> None:
    pass
