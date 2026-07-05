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


async def _migrate_projects_table(conn):
    """迁移 projects 表，添加 organization_id, system_name, owner_id 字段"""
    if "postgresql" in settings.DATABASE_URL:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'projects'
        )
        """
    else:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM sqlite_master 
            WHERE type='table' AND name='projects'
        )
        """
    
    result = await conn.execute(text(check_table_sql))
    table_exists = result.scalar()
    
    if not table_exists:
        return
    
    columns_to_add = [
        ("organization_id", "INTEGER"),
        ("system_name", "VARCHAR(500)"),
        ("owner_id", "INTEGER"),
    ]
    
    for col_name, col_type in columns_to_add:
        if "postgresql" in settings.DATABASE_URL:
            check_col_sql = f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'projects' 
                AND column_name = '{col_name}'
            )
            """
            result = await conn.execute(text(check_col_sql))
            col_exists = result.scalar()
        else:
            check_col_sql = f"PRAGMA table_info(projects)"
            result = await conn.execute(text(check_col_sql))
            rows = result.fetchall()
            col_exists = any(row[1] == col_name for row in rows)
        
        if not col_exists:
            alter_sql = f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}"
            try:
                await conn.execute(text(alter_sql))
            except Exception:
                pass


async def _migrate_organization_members_table(conn):
    """迁移 organization_members 表，支持自定义角色绑定。"""
    if "postgresql" in settings.DATABASE_URL:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = 'organization_members'
        )
        """
    else:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM sqlite_master
            WHERE type='table' AND name='organization_members'
        )
        """

    result = await conn.execute(text(check_table_sql))
    if not result.scalar():
        return

    if "postgresql" in settings.DATABASE_URL:
        result = await conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'organization_members'
                AND column_name = 'custom_role_id'
            )
        """))
        col_exists = result.scalar()
    else:
        result = await conn.execute(text("PRAGMA table_info(organization_members)"))
        col_exists = any(row[1] == "custom_role_id" for row in result.fetchall())

    if not col_exists:
        try:
            await conn.execute(text("ALTER TABLE organization_members ADD COLUMN custom_role_id INTEGER"))
        except Exception:
            pass


async def _migrate_scan_tasks_table(conn):
    """迁移 scan_tasks 表，补齐 AI 编排任务持久化字段。"""
    if "postgresql" in settings.DATABASE_URL:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = 'scan_tasks'
        )
        """
    else:
        check_table_sql = """
        SELECT EXISTS (
            SELECT FROM sqlite_master
            WHERE type='table' AND name='scan_tasks'
        )
        """

    result = await conn.execute(text(check_table_sql))
    if not result.scalar():
        return

    columns_to_add = [
        ("orchestrator_task_id", "VARCHAR(64)"),
        ("progress", "JSONB" if "postgresql" in settings.DATABASE_URL else "JSON"),
        ("result_summary", "JSONB" if "postgresql" in settings.DATABASE_URL else "JSON"),
        ("lease_owner", "VARCHAR(128)"),
        ("lease_expires_at", "TIMESTAMP"),
    ]

    for col_name, col_type in columns_to_add:
        if "postgresql" in settings.DATABASE_URL:
            result = await conn.execute(text(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = 'scan_tasks'
                    AND column_name = '{col_name}'
                )
            """))
            col_exists = result.scalar()
        else:
            result = await conn.execute(text("PRAGMA table_info(scan_tasks)"))
            col_exists = any(row[1] == col_name for row in result.fetchall())

        if not col_exists:
            try:
                await conn.execute(text(f"ALTER TABLE scan_tasks ADD COLUMN {col_name} {col_type}"))
            except Exception:
                pass


async def _seed_assessment_types(conn):
    """种子数据：插入 4 个 AssessmentType"""
    from app.models.assessment_type import AssessmentType
    
    seed_data = [
        {"code": "dengbao", "name": "等保", "description": "网络安全等级保护测评", "icon": "shield", "sort_order": 1},
        {"code": "miping", "name": "密评", "description": "商用密码应用安全性评估", "icon": "lock", "sort_order": 2},
        {"code": "guanji", "name": "关基", "description": "关键信息基础设施安全保护", "icon": "server", "sort_order": 3},
        {"code": "data_security", "name": "数据安全法", "description": "数据安全法合规评估", "icon": "database", "sort_order": 4},
    ]
    
    for item in seed_data:
        if "postgresql" in settings.DATABASE_URL:
            check_sql = f"SELECT EXISTS (SELECT 1 FROM assessment_types WHERE code = '{item['code']}')"
        else:
            check_sql = f"SELECT EXISTS (SELECT 1 FROM assessment_types WHERE code = '{item['code']}')"
        
        result = await conn.execute(text(check_sql))
        exists = result.scalar()
        
        if not exists:
            insert_sql = text("""
                INSERT INTO assessment_types (code, name, description, icon, is_active, sort_order, created_at)
                VALUES (:code, :name, :description, :icon, true, :sort_order, NOW())
            """)
            try:
                await conn.execute(insert_sql, item)
            except Exception:
                pass


async def _migrate_existing_data(conn):
    """数据迁移：为现有用户和项目创建默认组织"""
    from app.models.organization import Organization, OrganizationMember
    
    if "postgresql" in settings.DATABASE_URL:
        check_org_sql = "SELECT EXISTS (SELECT 1 FROM organizations WHERE code = 'DEFAULT')"
    else:
        check_org_sql = "SELECT EXISTS (SELECT 1 FROM organizations WHERE code = 'DEFAULT')"
    
    result = await conn.execute(text(check_org_sql))
    org_exists = result.scalar()
    
    if org_exists:
        return
    
    insert_org_sql = text("""
        INSERT INTO organizations (name, code, description, is_active, created_at, updated_at)
        VALUES ('Default', 'DEFAULT', 'Default organization for existing users', true, NOW(), NOW())
    """)
    try:
        await conn.execute(insert_org_sql)
    except Exception:
        return
    
    if "postgresql" in settings.DATABASE_URL:
        get_org_sql = "SELECT id FROM organizations WHERE code = 'DEFAULT' LIMIT 1"
    else:
        get_org_sql = "SELECT id FROM organizations WHERE code = 'DEFAULT' LIMIT 1"
    
    result = await conn.execute(text(get_org_sql))
    org_id = result.scalar()
    
    if not org_id:
        return
    
    if "postgresql" in settings.DATABASE_URL:
        get_users_sql = "SELECT id FROM users"
    else:
        get_users_sql = "SELECT id FROM users"
    
    result = await conn.execute(text(get_users_sql))
    user_ids = [row[0] for row in result.fetchall()]
    
    for user_id in user_ids:
        insert_member_sql = text("""
            INSERT INTO organization_members (organization_id, user_id, role, joined_at)
            VALUES (:org_id, :user_id, 'admin', NOW())
        """)
        try:
            await conn.execute(insert_member_sql, {"org_id": org_id, "user_id": user_id})
        except Exception:
            pass
    
    if "postgresql" in settings.DATABASE_URL:
        update_projects_sql = f"UPDATE projects SET organization_id = {org_id}, owner_id = user_id WHERE organization_id IS NULL"
    else:
        update_projects_sql = f"UPDATE projects SET organization_id = {org_id}, owner_id = user_id WHERE organization_id IS NULL"
    
    try:
        await conn.execute(text(update_projects_sql))
    except Exception:
        pass


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        # 创建新表
        await conn.run_sync(Base.metadata.create_all)
        
        # 迁移已存在的表
        await _migrate_evidences_table(conn)
        await _migrate_questionnaire_records_table(conn)
        await _migrate_projects_table(conn)
        await _migrate_organization_members_table(conn)
        await _migrate_scan_tasks_table(conn)
        
        # 种子数据
        await _seed_assessment_types(conn)
        
        # 数据迁移
        await _migrate_existing_data(conn)
