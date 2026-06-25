# 多租户 + 新 Dashboard + 导航框架 完整实施计划

## Context

当前系统存在以下核心问题：
1. **无多租户**：项目按 user_id 隔离，无组织概念，无法团队协作
2. **Dashboard 数据错误**：显示全局聚合数据，不按用户/组织过滤
3. **导航断裂**：登录 → ChatPage（跳过 Dashboard），Dashboard 无返回按钮，用户菜单无效
4. **项目与测评类型无关联**：一个项目可能有多个测评（等保+密评+关基+数据安全法），但当前无法表达
5. **注册流程缺失**：注册时不创建组织

用户确认的设计决策：
- 登录 → Dashboard（主入口）→ 点项目卡片 → ChatPage（工作区）
- 用户可属于多个组织（组织切换器）
- 注册时创建组织
- Dashboard 以项目卡片为中心
- 测评类型：等保（实现）、密评/关基/数据安全法（占位）

---

## Phase 1: 后端数据模型

### 1.1 新增 Organization + OrganizationMember 模型
**文件**: `backend/app/models/organization.py`（新建）

```
Organization (organizations)
├── id: Integer PK
├── name: String(200)           # 组织名称
├── code: String(50) UNIQUE     # 组织代码
├── description: Text
├── is_active: Boolean default True
├── created_at, updated_at: DateTime

OrganizationMember (organization_members)
├── id: Integer PK
├── organization_id: FK → organizations.id
├── user_id: FK → users.id
├── role: Enum(OrgRole)         # admin / manager / member / viewer
├── joined_at: DateTime
└── UNIQUE(organization_id, user_id)
```

### 1.2 新增 AssessmentType + ProjectAssessment 模型
**文件**: `backend/app/models/assessment_type.py`（新建）

```
AssessmentType (assessment_types)
├── id: Integer PK
├── code: String(50) UNIQUE     # dengbao / miping / guanji / data_security
├── name: String(100)           # 等保 / 密评 / 关基 / 数据安全法合规
├── description: Text
├── icon: String(50)
├── is_active: Boolean
├── sort_order: Integer

ProjectAssessment (project_assessments)
├── id: Integer PK
├── project_id: FK → projects.id
├── assessment_type_id: FK → assessment_types.id
├── status: String(20)          # not_started / in_progress / completed
├── level: String(20)           # 二级/三级（等保用）
├── score: Float                # 0-100
├── progress: Float             # 0-100
├── started_at, completed_at, created_at: DateTime
```

### 1.3 修改 Project 模型
**文件**: `backend/app/models/project.py`（修改）

新增字段：
- `organization_id: Integer FK → organizations.id`（nullable 过渡期兼容）
- `system_name: String(500)`（被测系统名称）
- `owner_id: Integer FK → users.id`（项目负责人）

新增关系：`organization`, `owner`, `assessments`（→ ProjectAssessment）

### 1.4 数据库迁移 + 种子数据
**文件**: `backend/app/core/database.py`（修改 `init_db()`）

1. `create_all` 自动创建新表
2. ALTER TABLE `projects` 添加 `organization_id`, `system_name`, `owner_id`
3. 数据迁移：创建 "Default" 组织 → 现有用户加入 → 现有项目关联
4. 种子数据：插入 4 个 AssessmentType（等保/密评/关基/数据安全法）

### 1.5 注册新模型
**文件**: `backend/app/models/__init__.py`（修改）

---

## Phase 2: 后端 API

### 2.1 组织 API
**文件**: `backend/app/api/organizations.py`（新建）

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/organizations/` | 创建组织 |
| GET | `/organizations/` | 当前用户的组织列表 |
| GET | `/organizations/{id}` | 组织详情 |
| PUT | `/organizations/{id}` | 更新组织（admin） |
| DELETE | `/organizations/{id}` | 删除组织（admin） |
| GET | `/organizations/{id}/members` | 成员列表 |
| POST | `/organizations/{id}/members` | 添加成员（admin） |
| PUT | `/organizations/{id}/members/{mid}` | 修改角色（admin） |
| DELETE | `/organizations/{id}/members/{mid}` | 移除成员（admin） |

### 2.2 修改 Auth API
**文件**: `backend/app/api/auth.py`（修改）

- **Register**: 请求体增加 `organization_name`，注册时创建 Organization + 首个 admin 成员
- **Login**: 响应增加 `organizations: [{id, name, code, role}]`
- **新增** `GET /auth/organizations` → 当前用户的组织列表

### 2.3 修改 Project API
**文件**: `backend/app/api/projects.py`（修改）

- **List**: 按 `organization_id` 过滤（query param）
- **Create**: 增加 `organization_id`, `system_name`, `assessment_type_ids: List[int]`
  - 创建 Project + 批量创建 ProjectAssessment
- **Get/Update/Delete**: 按 `organization_id` + 用户成员关系鉴权
- **Response**: 增加 `assessment_types`, `system_name`, `owner`

### 2.4 重写 Dashboard API
**文件**: `backend/app/api/dashboard.py`（重写）

`GET /dashboard/overview?org_id={org_id}` 返回：
```json
{
  "summary": { "total": 5, "in_progress": 3, "completed": 1, "not_started": 1, "avg_score": 78.5 },
  "projects": [
    {
      "id": 1, "name": "电商系统", "system_name": "电商交易平台",
      "assessment_types": [
        {"code": "dengbao", "name": "等保", "level": "三级", "status": "in_progress", "score": 78, "progress": 65},
        {"code": "miping", "name": "密评", "status": "not_started", "score": null, "progress": 0}
      ],
      "asset_count": 12, "overall_score": 78, "overall_status": "in_progress", "updated_at": "..."
    }
  ],
  "generated_at": "..."
}
```

### 2.5 新增 Schemas
- `backend/app/schemas/organization.py`（新建）
- `backend/app/schemas/assessment_type.py`（新建）
- `backend/app/schemas/dashboard.py`（新建）
- `backend/app/schemas/project.py`（修改）
- `backend/app/schemas/user.py`（修改 TokenResponse）

---

## Phase 3: 前端认证与导航

### 3.1 Auth Store
**文件**: `frontend/src/store/authStore.js`（修改）

新增：`organizations: []`, `currentOrgId: null`, `setOrganizations()`, `setCurrentOrg()`

### 3.2 注册页
**文件**: `frontend/src/pages/Register.jsx`（修改）

Step 0 增加「组织名称」必填字段。提交时发送 `organization_name`。

### 3.3 登录流程
**文件**: `frontend/src/pages/Login.jsx`（修改）

登录成功 → `setAuth(token, refreshToken, user, organizations)` → `navigate('/dashboard')`

### 3.4 路由重构
**文件**: `frontend/src/App.jsx`（修改）

```
/login           → Login
/register        → Register
/dashboard       → Dashboard（主入口）
/projects/:id    → ChatPage（工作区）
/projects/:id/results          → ResultsPage
/projects/:id/results/:scanId  → ResultDetailPage
/settings/models → ModelSettings
/settings/org    → OrganizationSettings（新增）
*                → Navigate to /dashboard
```

### 3.5 Dashboard 导航
**文件**: `frontend/src/pages/Dashboard.jsx`（修改）

Header：Logo + 组织切换器（下拉） + 用户菜单（组织设置/模型配置/登出）

### 3.6 ChatPage 导航
**文件**: `frontend/src/pages/ChatPage.jsx`（修改）

- 「态势总览」按钮 → 「← 返回 Dashboard」 → `navigate('/dashboard')`
- Header 面包屑：`Dashboard / 项目名称`
- 用户菜单：组织设置 → `/settings/org`，设置 → `/settings/models`

---

## Phase 4: Dashboard 重新设计（CIA 情报风格）

### 4.0 视觉设计方向
**核心风格**：美军情报系统 / CIA 指挥中心 / 电影级数据可视化

**视觉元素**：
- **背景**：深色底（#0a0a0b）+ VeriSure Logo 放大作为水印背景（低透明度 3-5%），叠加网格线（类似坐标纸）
- **色彩**：主色 `#00ff88`（军绿荧光）+ `#00b4d8`（情报蓝）+ `#ff6b35`（警报橙）+ `#d4af37`（金色点缀）
- **字体**：数据用等宽字体（`JetBrains Mono` / `SF Mono`），标题用无衬线
- **卡片**：玻璃态（`backdrop-filter: blur(20px)`）+ 细边框（`1px solid rgba(0,255,136,0.15)`）+ 微光扫描线动画
- **动效**：脉冲指示灯（状态点）、缓慢扫描线（卡片顶部）、数字翻转（计数器）
- **装饰**：角落 L 型标记线、坐标标注、分类标记（CLASSIFIED / TOP SECRET 风格文字）

**图表**：安装 `recharts` 库
- 雷达图：等保各支柱合规度（物理/网络/主机/应用/数据/管理）
- 环形图：项目状态分布（未开始/进行中/已完成）
- 折线图：合规分数趋势（30天）
- 柱状图：风险等级分布（严重/高/中/低）

### 4.1 Dashboard 页面重写
**文件**: `frontend/src/pages/Dashboard.jsx` + `Dashboard.css`（重写）

**布局**（从上到下）：

```
┌─────────────────────────────────────────────────────────────────────┐
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │ ← Logo 水印背景
│                                                                     │
│ [◆ VeriSure] [组织切换 ▾]              [搜索...]   [通知] [用户 ▾]  │ ← 顶部导航栏
│ ─────────────────────────────────────────────────────────────────── │
│                                                                     │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────────┐ │
│ │ PROJECTS│ │ ACTIVE  │ │ SCORE   │ │ ASSETS  │ │ 雷达图       │ │
│ │    4    │ │    2    │ │  78.5   │ │   12    │ │ 各支柱合规度 │ │
│ │  ▓▓▓▓▓  │ │  ▓▓▓▓▓  │ │  ▓▓▓▓▓  │ │  ▓▓▓▓▓  │ │   ◎          │ │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └──────────────┘ │
│                                                                     │
│ ┌─ PROJECT DOSSIERS ──────────────────────────────── [筛选▾] [+新建]┐
│ │                                                                   │
│ │ ┌───────────────────────────┐ ┌───────────────────────────┐      │
│ │ │ ◆ 电商系统                │ │ ◆ 金融系统                │      │
│ │ │   SYSTEM: 电商交易平台    │ │   SYSTEM: 金融核心系统    │      │
│ │ │   [等保三级] [密评]       │ │   [等保三级] [关基]       │      │
│ │ │   ─────────────────────   │ │   ─────────────────────   │      │
│ │ │   ASSETS: 12  SCORE: 78%  │ │   ASSETS: 8   SCORE: 92%  │      │
│ │ │   ████████░░  IN_PROGRESS │ │   █████████░  COMPLETED   │      │
│ │ │   LAST: 2026-06-25 14:30  │ │   LAST: 2026-06-20 09:15  │      │
│ │ └───────────────────────────┘ └───────────────────────────┘      │
│ │                                                                   │
│ │ ┌───────────────────────────┐ ┌───────────────────────────┐      │
│ │ │ ◆ 政务云                  │ │ ＋ 新建项目               │      │
│ │ │   [等保三级][密评][关基]  │ │   点击创建新的测评项目    │      │
│ │ │   ASSETS: 25  NOT_STARTED │ │                           │      │
│ │ └───────────────────────────┘ └───────────────────────────┘      │
│ └───────────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 项目卡片组件（Dossier 风格）
**文件**: `frontend/src/components/ProjectCard.jsx` + `.css`（新建）

每张卡片设计为「档案袋/Dossier」风格：
- 左上角：状态指示灯（绿色脉冲=进行中，灰色=未开始，金色=已完成）
- 项目名称（大字）+ 系统名称（副标题）
- 测评类型标签（彩色 Tag，每个类型有独特颜色）
- 分割线
- 资产数 + 合规分数 + 进度条（等宽字体）
- 最后更新时间
- 点击卡片 → `navigate('/projects/${id}')`
- hover 效果：边框发光 + 轻微上移

### 4.3 统计卡片（Intel Panel 风格）
每个统计卡片设计为「情报面板」：
- 顶部：分类标签（如 `PROJECTS`、`ACTIVE`、`SCORE`、`ASSETS`）全大写等宽字体
- 中间：大数字（带数字翻转动画）
- 底部：迷你趋势线（sparkline）或进度条
- 角落：L 型装饰线

### 4.4 新增依赖
- `recharts`：图表库（雷达图、环形图、折线图、柱状图）

---

## Phase 5: 项目创建

**文件**: `frontend/src/pages/Dashboard.jsx`（内嵌 Modal）

新建项目字段：项目名称、系统名称、描述、测评类型（多选）、等保级别（条件显示）

---

## Phase 6: 组织管理

**文件**: `frontend/src/pages/OrganizationSettings.jsx` + `.css`（新建）

功能：组织信息编辑、成员列表、添加/修改/移除成员

---

## 文件变更清单

### 新建（11个）
| 文件 | 描述 |
|------|------|
| `backend/app/models/organization.py` | Organization + OrganizationMember |
| `backend/app/models/assessment_type.py` | AssessmentType + ProjectAssessment |
| `backend/app/api/organizations.py` | 组织 API |
| `backend/app/schemas/organization.py` | 组织 schemas |
| `backend/app/schemas/assessment_type.py` | 测评类型 schemas |
| `backend/app/schemas/dashboard.py` | Dashboard schemas |
| `frontend/src/components/ProjectCard.jsx` | 项目卡片 |
| `frontend/src/components/ProjectCard.css` | 卡片样式 |
| `frontend/src/pages/OrganizationSettings.jsx` | 组织设置 |
| `frontend/src/pages/OrganizationSettings.css` | 设置样式 |

### 修改（14个）
| 文件 | 变更 |
|------|------|
| `backend/app/models/__init__.py` | 注册新模型 |
| `backend/app/models/project.py` | +organization_id, system_name, owner_id |
| `backend/app/core/database.py` | 迁移 + 种子数据 |
| `backend/app/api/auth.py` | 注册+组织，登录+组织列表 |
| `backend/app/api/projects.py` | 按组织过滤，测评类型关联 |
| `backend/app/api/dashboard.py` | 完全重写 |
| `backend/app/api/__init__.py` | 注册 organizations router |
| `backend/app/schemas/user.py` | TokenResponse +organizations |
| `backend/app/schemas/project.py` | +assessment_type_ids, system_name |
| `frontend/src/store/authStore.js` | +organizations, currentOrgId |
| `frontend/src/pages/Login.jsx` | → /dashboard |
| `frontend/src/pages/Register.jsx` | +组织名称字段 |
| `frontend/src/pages/Dashboard.jsx` | 完全重写 |
| `frontend/src/pages/Dashboard.css` | 重写 |
| `frontend/src/pages/ChatPage.jsx` | 导航改造 |
| `frontend/src/App.jsx` | 路由重构 |

---

## 实施顺序

1. Phase 1（后端模型 + 迁移）
2. Phase 2（后端 API）
3. Phase 3（前端认证 + 导航）
4. Phase 4（Dashboard 重写）
5. Phase 5（项目创建）
6. Phase 6（组织管理）

---

## 验证方案

### 后端
1. 注册新用户（带组织名）→ 检查 organizations + organization_members
2. 登录 → 返回 organizations 列表
3. 创建项目（选测评类型）→ 检查 project_assessments
4. Dashboard API → 按组织过滤 + 项目卡片数据
5. 组织成员管理 CRUD

### 前端
1. 注册 → 创建组织 → 跳转 Dashboard
2. 登录 → Dashboard → 看到项目卡片
3. 筛选/排序 → 验证过滤
4. 点卡片 → ChatPage → 返回 Dashboard
5. 新建项目 → 选测评类型 → 卡片显示正确
6. 组织设置 → 添加成员
7. 多组织切换 → 不同项目

### 数据迁移
1. 现有用户 → 自动加入 "Default" 组织
2. 现有项目 → 关联 "Default" + 创建等保 ProjectAssessment
