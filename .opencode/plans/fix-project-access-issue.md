# 修复项目访问权限问题

## 问题描述

用户报告：除了"我的电商网站"（project_id=5）外，其他所有项目都报错：
- "抱歉，处理请求时出错：Project not found"
- "获取资产列表失败，请检查项目是否存在"

## 根因分析

### 数据库现状
```
项目列表：
- id=5, name=我的电商网站, user_id=1, organization_id=1 ✅ 当前用户是 owner
- id=6, name=测试多资产扫描, user_id=3, organization_id=1 ❌ 当前用户不是 owner
- id=7, name=测试二级项目, user_id=3, organization_id=1 ❌ 当前用户不是 owner
- id=10, name=测试新项目, user_id=2, organization_id=1 ❌ 当前用户不是 owner
- id=13, name=测试系统 - 等保三级测评, user_id=2, organization_id=NULL ❌ 当前用户不是 owner

组织成员关系：
- organization_id=1 的成员：user_id=1, user_id=2, user_id=3
```

### 问题代码

**1. `backend/app/api/chat.py:100-105`**
```python
result = await db.execute(
    select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
)
project = result.scalar_one_or_none()
if not project:
    raise HTTPException(status_code=404, detail="Project not found")
```

**问题**：只检查 `Project.user_id == current_user.id`，没有考虑组织成员关系。

**2. `backend/app/api/assets.py:61-70`**
```python
result = await db.execute(
    select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
)
project = result.scalar_one_or_none()

if not project:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Project not found",
    )
```

**问题**：同样的问题，只检查 owner，不考虑组织成员。

### 正确的权限检查逻辑

`backend/app/api/projects.py:46-60` 有正确的实现：
```python
async def get_project_for_user(db: AsyncSession, project_id: int, user_id: int) -> Project:
    """获取项目并验证用户有权限访问（通过组织成员关系）"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.organization_id:
        await check_org_member(db, project.organization_id, user_id)
    else:
        # Fallback: old projects without org
        if project.user_id != user_id:
            raise HTTPException(status_code=403, detail="No access to this project")

    return project
```

**逻辑**：
1. 先查找项目（不限制 user_id）
2. 如果项目有 `organization_id`，检查用户是否是该组织成员
3. 如果项目没有 `organization_id`（旧项目），检查用户是否是 owner

## 修复方案

### 修改 1: `backend/app/api/chat.py`

**位置**: 第 97-105 行

**当前代码**:
```python
# 获取项目
project = None
if project_id:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
```

**修复后**:
```python
# 获取项目
project = None
if project_id:
    # 导入权限检查函数
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, project_id, current_user.id)
```

### 修改 2: `backend/app/api/assets.py`

**位置**: 第 60-70 行

**当前代码**:
```python
# Verify project exists and belongs to user
result = await db.execute(
    select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
)
project = result.scalar_one_or_none()

if not project:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Project not found",
    )
```

**修复后**:
```python
# Verify project exists and user has access
from app.api.projects import get_project_for_user
project = await get_project_for_user(db, project_id, current_user.id)
```

### 修改 3: 检查其他文件

需要检查所有使用 `Project.user_id == current_user.id` 的地方，确保都使用正确的权限检查。

```bash
grep -rn "Project.user_id == current_user.id" backend/app/api/
```

## 验证步骤

1. 重建后端容器：
   ```bash
   docker-compose build backend
   docker-compose up -d backend
   ```

2. 测试项目访问：
   - 登录用户 1（asxzsa588@gmail.com）
   - 切换到项目 6（测试多资产扫描）
   - 应该能正常查看项目信息和资产列表
   - 发送聊天消息，应该不再报错

3. 检查后端日志：
   ```bash
   docker logs certiproof-backend --tail 50 | grep -E "(GET /api/v1/projects|POST /api/v1/chat)"
   ```
   应该看到 200 OK 而不是 404 Not Found

## 预期结果

- 所有组织成员都能访问组织内的项目
- 不再出现 "Project not found" 错误
- 聊天功能在所有项目中正常工作
