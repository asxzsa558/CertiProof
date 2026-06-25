from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from app.core.config import settings

# Use SQLite for development
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def _migrate_evidences_table(conn):
    """迁移 evidences 表，添加缺失的字段"""
    # 检查表是否存在
    if "postgresql" in settings.DATABASE_URL:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'evidences'
        )
        """
    else:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM sqlite_master 
            WHERE type='table' AND name='evidences'
        )
        """
    
    result = await conn.execute(text(check_table_sql))
    table_exists = result.scalar()
    
    if not table_exists:
        return  # 表不存在，让 create_all 创建
    
    # 检查各字段是否存在并添加
    columns_to_add = [
        ("questionnaire_record_id", "INTEGER"),
        ("project_id", "INTEGER"),
        ("file_name", "VARCHAR(255)"),
        ("file_size", "INTEGER"),
        ("mime_type", "VARCHAR(100)"),
        ("description", "TEXT"),
        ("clause_id", "VARCHAR(50)"),
        ("uploaded_by", "INTEGER"),
    ]
    
    for col_name, col_type in columns_to_add:
        if "postgresql" in settings.DATABASE_URL:
            check_col_sql = f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'evidences' 
                AND column_name = '{col_name}'
            )
            """
        else:
            check_col_sql = f"PRAGMA table_info(evidences)"
        
        result = await conn.execute(text(check_col_sql))
        
        if "postgresql" in settings.DATABASE_URL:
            col_exists = result.scalar()
        else:
            # SQLite: 需要获取所有列名
            rows = result.fetchall()
            col_exists = any(row[1] == col_name for row in rows)
        
        if not col_exists:
            # 添加列（finding_id 改为可空）
            if col_name == "finding_id":
                alter_sql = f"ALTER TABLE evidences ALTER COLUMN {col_name} DROP NOT NULL"
            else:
                alter_sql = f"ALTER TABLE evidences ADD COLUMN {col_name} {col_type}"
            try:
                await conn.execute(text(alter_sql))
            except Exception:
                pass  # 列可能已存在


async def _migrate_questionnaire_records_table(conn):
    """迁移 questionnaire_records 表"""
    # 检查表是否存在
    if "postgresql" in settings.DATABASE_URL:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'questionnaire_records'
        )
        """
    else:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM sqlite_master 
            WHERE type='table' AND name='questionnaire_records'
        )
        """
    
    result = await conn.execute(text(check_table_sql))
    table_exists = result.scalar()
    
    if not table_exists:
        return  # 表不存在，让 create_all 创建


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        # 创建新表
        await conn.run_sync(Base.metadata.create_all)
        
        # 迁移已存在的表
        await _migrate_evidences_table(conn)
        await _migrate_questionnaire_records_table(conn)
