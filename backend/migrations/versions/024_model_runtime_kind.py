"""Classify cloud and local inference runtimes.

Revision ID: 024
Revises: 023
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from alembic import op


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_providers",
        sa.Column("runtime_kind", sa.String(length=20), nullable=False, server_default="cloud"),
    )
    op.execute("UPDATE model_providers SET runtime_kind = 'ollama' WHERE provider_type::text = 'OLLAMA'")


def downgrade() -> None:
    op.drop_column("model_providers", "runtime_kind")
