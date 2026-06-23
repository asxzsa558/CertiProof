"""add thread support

Revision ID: 002
Revises: 001
Create Date: 2026-06-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建 conversation_threads 表
    op.create_table(
        'conversation_threads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('parent_thread_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('is_archived', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['parent_thread_id'], ['conversation_threads.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_conversation_threads_id', 'conversation_threads', ['id'])
    op.create_index('ix_conversation_threads_user_id', 'conversation_threads', ['user_id'])
    op.create_index('ix_conversation_threads_project_id', 'conversation_threads', ['project_id'])
    
    # 创建 conversation_archives 表
    op.create_table(
        'conversation_archives',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('thread_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('message_count', sa.Integer(), default=0),
        sa.Column('token_count', sa.Integer(), default=0),
        sa.Column('archived_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['thread_id'], ['conversation_threads.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_conversation_archives_id', 'conversation_archives', ['id'])
    op.create_index('ix_conversation_archives_user_id', 'conversation_archives', ['user_id'])
    op.create_index('ix_conversation_archives_project_id', 'conversation_archives', ['project_id'])
    op.create_index('ix_conversation_archives_thread_id', 'conversation_archives', ['thread_id'])
    
    # 给 conversation_history 添加 thread_id 列
    op.add_column('conversation_history', sa.Column('thread_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_conversation_history_thread_id',
        'conversation_history',
        'conversation_threads',
        ['thread_id'],
        ['id']
    )
    op.create_index('ix_conversation_history_thread_id', 'conversation_history', ['thread_id'])


def downgrade() -> None:
    # 删除 thread_id 相关
    op.drop_index('ix_conversation_history_thread_id', table_name='conversation_history')
    op.drop_constraint('fk_conversation_history_thread_id', 'conversation_history', type_='foreignkey')
    op.drop_column('conversation_history', 'thread_id')
    
    # 删除表
    op.drop_index('ix_conversation_archives_thread_id', table_name='conversation_archives')
    op.drop_index('ix_conversation_archives_project_id', table_name='conversation_archives')
    op.drop_index('ix_conversation_archives_user_id', table_name='conversation_archives')
    op.drop_index('ix_conversation_archives_id', table_name='conversation_archives')
    op.drop_table('conversation_archives')
    
    op.drop_index('ix_conversation_threads_project_id', table_name='conversation_threads')
    op.drop_index('ix_conversation_threads_user_id', table_name='conversation_threads')
    op.drop_index('ix_conversation_threads_id', table_name='conversation_threads')
    op.drop_table('conversation_threads')
