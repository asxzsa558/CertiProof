"""Keep project compliance scores at the same precision as assessment scores.

Revision ID: 018
Revises: 017
Create Date: 2026-07-18
"""

import sqlalchemy as sa
from alembic import op


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "projects",
        "compliance_score",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=True,
        postgresql_using="compliance_score::double precision",
    )


def downgrade() -> None:
    op.alter_column(
        "projects",
        "compliance_score",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="round(compliance_score)::integer",
    )
