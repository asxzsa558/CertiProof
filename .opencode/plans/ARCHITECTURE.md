# VeriSure 技术架构文档

> 本文档描述 VeriSure 的当前技术架构、核心模块设计、数据流和调用链。
> 产品路线图和执行计划请参见 [ROADMAP.md](./ROADMAP.md)

---

## 一、系统架构总览

### 1.1 核心设计理念

**对话式 AI 驱动**：用户用自然语言描述需求，LLM 自主理解意图、规划执行路径、调度能力、生成结果描述。

| 维度 | 传统方式 | VeriSure 方式 |
|------|----------|-----------------|
| 意图识别 | 硬编码意图分类器 | LLM 自主理解语义 |
| 能力调度 | if-else 分支 | LLM 生成执行计划 |
| 上下文理解 | 无状态或简单 session | 多层记忆系统 |
| 能力扩展 | 改代码 + 改路由 | 注册即可用 |
| 结果展示 | 模板渲染 | LLM 生成自然语言描述 |

### 1.2 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户层 (Frontend)                        │
│  React + Ant Design + Zustand                                    │
│  ChatPage + ChatWorkspace + AgentStatusCard                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API 网关层 (FastAPI)                        │
│  Auth API | Chat API | Scan API | Project API | Model API        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    编排层 (Orchestrator)                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Orchestrator: 接收用户输入 → AI 决策 → 任务调度 → 结果汇总  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  AI Engine   │  │   Context    │  │  Execution   │          │
│  │ (LLM 决策)   │  │   Manager    │  │   Engine     │          │
│  │              │  │ (上下文管理)  │  │ (工具执行)    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MCP 工具层 (Tool Servers)                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  MCP Gateway: 路由分发 + 健康检查 + 异步任务管理            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │Security Tools│  │  OCR Server  │  │  (可扩展)     │          │
│  │ nmap/testssl │  │  截图分析     │  │              │          │
│  │ nuclei/hydra │  │              │  │              │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      数据层 (Storage)                            │
│  PostgreSQL | Redis | 文件存储 | 日志                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、核心模块详解

### 2.1 Orchestrator（调度中枢）

**文件**: `backend/app/orchestrator/orchestrator.py`

**核心职责**：
1. 接收用户输入
2. 构建上下文 → AI 决策 → 生成分流
3. 纯对话 → 直接返回（无 task_id）
4. 有执行计划 → 异步执行 → 返回 task_id
5. 异步任务完成后，AI 生成结果描述

**关键方法**：
```python
async def handle_user_input(user_input, project_id, user_id, db) -> dict:
    # 1. 构建上下文
    context = await context_manager.build_context()
    
    # 2. AI 决策
    plan_result = await ai_engine.decide(user_input, context, db)
    
    # 3. 分流判断
    if all_non_async(plan):
        return {"message": response}  # 无 task_id
    
    # 4. 异步执行
    task_id = uuid4()
    asyncio.create_task(_execute_plan_async(task_id, plan, ...))
    return {"message": response, "task_id": task_id}
```

**任务控制**：
- `pause_task()`: 暂停任务，广播状态变化
- `resume_task()`: 恢复任务
- `stop_task()`: 停止任务，取消 asyncio Task

### 2.2 AI Engine（AI 决策引擎）

**文件**: `backend/app/services/ai_engine.py`

**设计原则**：不预定义意图类型，LLM 自主理解语义。

**决策流程**：
```
用户输入 → 构建 System Prompt → LLM 返回 JSON → 解析 plan + response
```

**Prompt 结构**：
```
你是 VeriSure 等保合规智能助手。

## 能力列表
{capabilities}  # 动态注入所有能力描述

## 上下文
- 项目: {current_project}
- 资产: {project_assets}
- 归档上下文: {archive_context}  # 如果有归档

## 规则
1. 回顾性词语 → 用 view_* 查缓存
2. 缺少必填参数 → 用 chat 询问
3. 扫描目标 → 优先使用项目资产
4. 纯对话 → 用 chat 直接回复

## 输出格式
返回 JSON：{"plan": [...], "response": "..."}
```

**超时控制**：
- AI 决策：60 秒超时
- 结果描述：45 秒超时

### 2.3 Context Manager（上下文管理器）

**文件**: `backend/app/services/context_manager.py`

**5 层记忆系统**（参考 Claude Code）：

| 层级 | 名称 | 说明 | 限制 |
|------|------|------|------|
| Layer 1 | 对话历史 | 最近 20 条对话 | 50000 tokens |
| Layer 2 | 操作历史 | 最近 50 条操作 | 按项目隔离 |
| Layer 3 | 结果缓存 | 最多 100 条缓存 | 1 小时过期 |
| Layer 4 | 项目记忆 | 每个项目最多 20 条 | 长期记忆 |
| Layer 5 | 用户记忆 | 每个用户最多 20 条 | 偏好记忆 |

**上下文压缩**：
- 当对话历史超过 50000 tokens 时触发
- LLM 生成摘要，存入 ProjectMemory
- 超时：30 秒

**归档功能**：
- 归档当前对话，生成结构化交接摘要
- 异步生成摘要，避免阻塞主流程
- 新线程可接续归档上下文

### 2.4 Capability Registry（能力注册表）

**文件**: `backend/app/services/capability_registry.py`

**设计原则**：新增能力只需注册，不需要修改任何代码。

**当前注册的能力（29 个）**：

| 类别 | 能力 | 说明 |
|------|------|------|
| **扫描类** (5) | scan_ports | 端口扫描（nmap） |
| | scan_ssl | SSL/TLS 检测（testssl） |
| | scan_vulnerabilities | 漏洞扫描（nuclei） |
| | scan_weak_passwords | 弱口令检测（hydra） |
| | full_compliance_scan | 全量合规扫描 |
| **查询类** (6) | view_scan_results | 查看扫描结果 |
| | view_open_ports | 查看开放端口 |
| | view_vulnerabilities | 查看漏洞 |
| | view_findings | 查看合规发现 |
| | view_compliance_score | 查看合规评分 |
| | view_scan_history | 查看扫描历史 |
| **项目类** (4) | create/list/update/delete_project | 项目管理 |
| **资产类** (3) | add/list/verify_asset | 资产管理 |
| **整改类** (3) | create/list/update_remediation | 整改管理 |
| **报告类** (2) | generate_pdf/json_report | 报告生成 |
| **监控类** (3) | create/list/trigger_scheduled_scan | 定时扫描 |
| **系统类** (2) | help/chat | 帮助和对话 |

**扩展方式**：
1. 注册能力：`self.register(Capability(...))`
2. 实现执行逻辑：`ExecutionEngine._execute_capability()` 添加分支
3. 完成：LLM 自动发现新能力

### 2.5 Execution Engine（执行引擎）

**文件**: `backend/app/services/execution_engine.py`

**执行流程**：
```
plan = [{"capability": "scan_ports", "parameters": {"target": "127.0.0.1"}}]
    │
    ▼
for step in plan:
    1. 标准化目标地址（localhost → host.docker.internal）
    2. 检查暂停/停止状态
    3. 回调 progress_callback（状态: running）
    4. 调用 _execute_capability()
    5. 记录操作历史
    6. 缓存结果
    7. 回调 progress_callback（状态: completed/failed）
```

**并发执行**（多资产场景）：
- `execute_plan_concurrent()`: 支持并发执行，最大并发数 5
- 重试机制：最多 3 次，指数退避（1s, 2s, 4s）
- 暂停/停止支持：每个 step 前检查状态

**结果判断逻辑**：
```python
if len(open_ports) > 0:
    display_status = "success"  # 有开放端口 → 主机可达
else:
    display_status = "warning"  # 无开放端口 → 可能不可达
```

### 2.6 MCP Gateway（MCP 网关）

**文件**: `mcp-servers/gateway/server.py`

**核心功能**：
1. 路由分发：根据 tool_name 路由到对应的 MCP Server
2. 健康检查：检查各 MCP Server 状态
3. 异步任务管理：支持长时任务异步执行

**路由表**：
```python
TOOL_ROUTES = {
    "nmap_scan": "http://security-tools:8010",
    "testssl_scan": "http://security-tools:8010",
    "nuclei_scan": "http://security-tools:8010",
    "hydra_bruteforce": "http://security-tools:8010",
    "ping_host": "http://security-tools:8010",
    "ocr_analyze": "http://ocr-server:8005",
}
```

### 2.7 MCP Tool Servers

#### Security Tools（统一安全工具服务）

**文件**: `mcp-servers/security-tools/server.py`

**包含工具**：
- `nmap_scan`: 端口扫描（--min-rate 10000，全端口 ~26 秒）
- `testssl_scan`: SSL/TLS 检测
- `nuclei_scan`: 漏洞扫描
- `hydra_bruteforce`: 弱口令检测（⚠️ 当前未真正实现）
- `ping_host`: Ping 检测

#### OCR Server（截图分析服务）

**文件**: `mcp-servers/ocr-server/server.py`

**包含工具**：
- `ocr_analyze`: 截图 OCR 分析
- `screenshot_analyze`: 截图分析（别名）

---

## 三、数据流与调用链

### 3.1 完整请求流程

```
1. 用户输入: "扫描 127.0.0.1 端口"
   │
   ▼
2. ChatWorkspace → POST /api/v1/chat/
   │
   ▼
3. chat.py → orchestrator.handle_user_input()
   │
   ▼
4. ContextManager.build_context()
   │  查询 5 层记忆 → 构建完整上下文
   │
   ▼
5. AIEngine.decide(user_input, context)
   │  构建 prompt → 调用 LLM → 解析 JSON
   │  返回: plan=[{scan_ports, target=127.0.0.1}]
   │        response="好的，我来扫描端口"
   │
   ▼
6. 分流判断: scan_ports 不是纯对话 → 创建 task_id
   │
   ▼
7. asyncio.create_task(_execute_plan_async)
   │  立即返回: {message: "好的...", task_id: "xxx"}
   │
   ▼
8. 前端收到响应:
   │  显示 AI 回复气泡
   │  显示进度卡片
   │  开始轮询 GET /chat/result/{task_id}
   │
   ▼
9. 异步任务执行:
   │  新数据库会话 (AsyncSessionLocal)
   │  ExecutionEngine.execute_plan()
   │    → 标准化目标: 127.0.0.1 → host.docker.internal
   │    → 回调: "正在执行: 端口扫描..."
   │    → MCPGatewayClient → security-tools 容器
   │    → nmap -sS -T5 --min-rate 10000 -p 1-65535 host.docker.internal
   │    → 回调: "已完成: 端口扫描"
   │    → 记录操作历史 + 缓存结果
   │
   ▼
10. AI 生成结果描述:
    │  提取执行结果（13 个开放端口）
    │  构建 prompt → LLM 生成自然语言描述
    │  "本机共开放 13 个端口，具体包括..."
    │
    ▼
11. 记录到 completed_tasks + 清理 task_progress
    │
    ▼
12. 前端轮询到 status=completed:
    │  标记消息 taskCompleted=true → 进度卡片消失
    │  添加结果消息（AI 描述 + 统计卡片 + 端口表格）
    │
    ▼
13. 用户看到完整结果
```

### 3.2 容器间通信

```
frontend (3000)
    │  HTTP/WebSocket
    ▼
backend (8000)
    │  HTTP
    ▼
mcp-gateway (9000)
    │  HTTP
    ▼
security-tools (8010)
    │  执行 nmap/testssl/nuclei/hydra
    ▼
目标主机 (host.docker.internal)
```

---

## 四、数据库设计

### 4.1 核心数据模型

| 模型 | 表名 | 说明 |
|------|------|------|
| User | users | 用户信息 |
| Project | projects | 项目信息 |
| Asset | assets | 资产信息 |
| ScanTask | scan_tasks | 扫描任务 |
| Finding | findings | 合规发现 |
| Evidence | evidences | 证据 |
| RemediationTicket | remediation_tickets | 整改工单 |
| ConversationHistory | conversation_history | 对话历史 |
| ActionHistory | action_history | 操作历史 |
| ResultCache | result_cache | 结果缓存 |
| ProjectMemory | project_memory | 项目记忆 |
| UserMemory | user_memory | 用户记忆 |
| ConversationArchive | conversation_archives | 对话归档 |
| ConversationThread | conversation_threads | 对话线程 |

### 4.2 数据库迁移

使用 Alembic 管理数据库迁移：
- 迁移文件：`backend/migrations/versions/`
- 当前版本：003（head）

---

## 五、前端架构

### 5.1 技术栈

- React 18
- Ant Design 5
- Zustand（状态管理）
- Vite 5（构建工具）

### 5.2 核心组件

| 组件 | 文件 | 说明 |
|------|------|------|
| ChatPage | `pages/ChatPage.jsx` | 主页面，包含侧边栏和聊天区 |
| ChatWorkspace | `components/ChatWorkspace.jsx` | 聊天工作区，核心交互组件 |
| AgentStatusCard | `components/AgentStatusCard.jsx` | Agent 执行状态卡片 |
| ResultsPage | `pages/ResultsPage.jsx` | 扫描结果列表页 |

### 5.3 状态管理

```javascript
// Zustand store
const useStore = create((set) => ({
  user: null,
  token: null,
  currentProjectId: null,
  // ...
}))
```

---

## 六、性能优化

### 6.1 nmap 扫描优化

| 优化项 | 之前 | 之后 |
|--------|------|------|
| 扫描方式 | TCP connect (-sT) | SYN scan (-sS) |
| 速度等级 | 默认 | -T5（最激进） |
| 发包速率 | 默认 | --min-rate 10000 |
| 全端口扫描耗时 | ~38 分钟 | **~26 秒** |

### 6.2 LLM 超时控制

| 调用点 | 超时时间 | Fallback |
|--------|----------|----------|
| AI 决策 | 60s | 降级为 chat |
| 结果描述 | 45s | 硬编码描述 |
| 归档摘要 | 30s | 简单截取 |
| 对话压缩 | 30s | 简单截断 |

### 6.3 缓存策略

| 缓存类型 | 过期时间 | 用途 |
|----------|----------|------|
| 扫描结果 | 1 小时 | 避免重复扫描 |
| 对话历史 | 不过期 | 上下文连续性 |
| 操作历史 | 不过期 | 审计追溯 |

---

## 七、已知问题与限制

### 7.1 当前问题

| 问题 | 说明 | 影响 |
|------|------|------|
| hydra 未真正实现 | 硬编码返回空结果 | 弱口令检测无效 |
| 只有黑盒检测 | 没有白盒配置核查 | 等保覆盖率低 |
| 容器网络限制 | Docker 内无法准确判断主机可达性 | 误判主机状态 |
| 访谈管理缺失 | 没有访谈记录功能 | 无法满足等保三维验证 |

### 7.2 技术限制

| 限制 | 说明 |
|------|------|
| 容器部署 | 无法直接访问宿主机网络，需要 host.docker.internal |
| LLM 依赖 | 依赖外部 LLM 服务（MiniMax） |
| 并发限制 | 多资产扫描最大并发 5 |

---

## 八、扩展指南

### 8.1 添加新能力

1. 注册能力：`capability_registry.py` 添加 `Capability`
2. 实现执行：`execution_engine.py` 添加 `_execute_xxx` 方法
3. 添加 MCP 工具（如需要）：`security-tools/server.py`
4. 更新 Gateway 路由（如需要）：`gateway/server.py`

### 8.2 添加新 MCP Server

1. 创建 `mcp-servers/xxx-server/` 目录
2. 实现 `server.py`，暴露 `/execute` 端点
3. 编写 `Dockerfile`
4. 更新 `docker-compose.yml`
5. 更新 Gateway 路由

---

## 九、参考文档

- [产品路线图](./ROADMAP.md)
- [等保测评 skill 参考](https://github.com/openocta/openocta_skills)
- [GB/T 22239-2019 等保基本要求](https://www.tc260.org.cn/front/bzzqyj.html)

---

**文档版本**: v1.0  
**最后更新**: 2026-06-24  
**维护者**: VeriSure Team
