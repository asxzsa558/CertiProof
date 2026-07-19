"""Track the highest issued report version per project.

Revision ID: 023
Revises: 022
Create Date: 2026-07-19
"""

import sqlalchemy as sa
from alembic import op


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("report_version_counter", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("projects", "report_version_counter")
