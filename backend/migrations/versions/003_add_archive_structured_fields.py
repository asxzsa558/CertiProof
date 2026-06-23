"""add archive structured fields

Revision ID: 003
Revises: 002
Create Date: 2026-06-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 给 conversation_archives 添加结构化交接字段
    op.add_column('conversation_archives', sa.Column('completed_tasks', sa.JSON(), nullable=True))
    op.add_column('conversation_archives', sa.Column('current_task', sa.JSON(), nullable=True))
    op.add_column('conversation_archives', sa.Column('interrupt_point', sa.Text(), nullable=True))
    op.add_column('conversation_archives', sa.Column('key_findings', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversation_archives', 'key_findings')
    op.drop_column('conversation_archives', 'interrupt_point')
    op.drop_column('conversation_archives', 'current_task')
    op.drop_column('conversation_archives', 'completed_tasks')
