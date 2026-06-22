# CertiProof AI 驱动架构整体方案

## 一、设计哲学

CertiProof 的核心交互方式是**对话式 AI 驱动**：用户用自然语言描述需求，LLM 自主理解意图、规划执行路径、调度能力、生成结果描述。

**与传统系统的根本区别**：

| 维度 | 传统方式 | CertiProof 方式 |
|------|----------|-----------------|
| 意图识别 | 硬编码意图分类器，匹配关键词 | LLM 自主理解语义，无需预定义意图 |
| 能力调度 | if-else 分支，写死调用链 | LLM 生成执行计划，动态编排 |
| 上下文理解 | 无状态或简单 session | 多层记忆系统，支持引用解析 |
| 能力扩展 | 改代码 + 改路由 + 改前端 | 注册即可用，LLM 自动发现 |
| 结果展示 | 模板渲染 | LLM 根据上下文生成自然语言描述 |

**参考的业界最佳实践**：
- **Claude Code**：多层记忆系统（对话历史 + 操作历史 + 结果缓存 + 项目记忆 + 用户记忆）
- **Codex**：上下文压缩机制，长对话自动摘要
- **Claude Code / Codex**：Agent 自主规划 + 执行 + 反思的闭环

---

## 二、系统架构总览

```
用户自然语言输入
    |
    v
+-----------------------------------------------------------+
|  Orchestrator（调度中枢）                                    |
|                                                            |
|  1. 构建上下文 (ContextManager.build_context)               |
|     |                                                      |
|     v                                                      |
|  2. AI 决策 (AIEngine.decide)                               |
|     |  - 理解用户意图                                       |
|     |  - 生成执行计划 plan[]                                 |
|     |  - 生成即时回复 response                              |
|     v                                                      |
|  3. 分流判断                                               |
|     |  - 纯对话(chat/help) → 直接返回，无 task_id           |
|     |  - 有执行计划 → 异步执行，返回 task_id                |
|     v                                                      |
|  4. 异步执行 (ExecutionEngine.execute_plan)                 |
|     |  - 逐步执行能力，实时回调进度                          |
|     |  - 记录操作历史，缓存结果                              |
|     v                                                      |
|  5. AI 结果描述 (_generate_result_description)              |
|     |  - LLM 根据执行结果 + 对话历史生成自然语言描述         |
|     v                                                      |
|  6. 前端轮询 /chat/result/{task_id} 获取结果               |
+-----------------------------------------------------------+
```

---

## 三、AI 决策引擎（AIEngine）

**核心文件**: `backend/app/services/ai_engine.py`

### 3.1 设计原则

**不预定义意图类型**。LLM 拿到完整的上下文（对话历史 + 操作历史 + 缓存结果 + 项目信息 + 全部能力描述），自己判断用户想干什么，应该调用哪些能力。

### 3.2 决策流程

```
用户输入: "扫描本机 8000-8010 端口并查看结果"
    |
    v
构建 System Prompt:
  - 角色定义
  - 全部能力列表（28 个能力，8 个类别）
  - 最近 20 条对话历史
  - 最近 20 条操作历史
  - 缓存的结果摘要
  - 当前项目信息
    |
    v
LLM 返回 JSON:
{
    "plan": [
        {"capability": "scan_ports", "parameters": {"target": "localhost", "port_range": "8000-8010"}},
        {"capability": "view_scan_results", "parameters": {"query": "所有结果"}}
    ],
    "response": "好的，我先扫描本机 8000-8010 端口，然后展示结果"
}
    |
    v
_parse_plan() 解析 + _validate_plan() 验证能力是否存在
    |
    v
返回 plan + response
```

### 3.3 Prompt 工程要点

1. **能力描述注入**：`capability_registry.format_for_prompt()` 动态生成所有能力的描述，包含参数说明
2. **Few-shot 示例**：在 prompt 中提供典型场景的输入/输出示例
3. **规则约束**：
   - 纯对话场景使用 `chat` 能力，不生成 task_id
   - 复合任务可以生成多步骤 plan
   - 引用解析（"刚才的结果"、"那些端口"）依赖对话历史
4. **JSON 解析容错**：
   - 清理 `<think>` 标签
   - 支持 markdown 代码块提取
   - 正则提取 JSON 对象
   - 解析失败降级为 chat 能力

---

## 四、多层记忆系统（ContextManager）

**核心文件**: `backend/app/services/context_manager.py`
**数据模型**: `backend/app/models/context.py`

参考 Claude Code 的多层记忆系统设计，实现 5 层记忆：

### 4.1 记忆层次

```
+-----------------------------------------------------------+
| Layer 1: 对话历史 (ConversationHistory)                     |
| - 最近 20 条用户/助手对话                                    |
| - 包含 role, content, tokens_used, created_at              |
| - 超过 MAX_CONVERSATION_TOKENS(50000) 时触发压缩            |
+-----------------------------------------------------------+
| Layer 2: 操作历史 (ActionHistory)                           |
| - 最近 50 条操作记录                                        |
| - 包含 action_type, parameters, result, status             |
| - 按项目隔离                                                |
+-----------------------------------------------------------+
| Layer 3: 结果缓存 (ResultCache)                             |
| - 最多 100 条缓存                                           |
| - 包含 cache_key, result_data, expires_at                  |
| - 自动过期清理（默认 1 小时）                                |
| - 支持按 cache_key 精确查询                                  |
+-----------------------------------------------------------+
| Layer 4: 项目记忆 (ProjectMemory)                           |
| - 每个项目最多 20 条                                        |
| - 包含 memory_type, content, metadata                      |
| - 存储项目级别的长期记忆（如项目特征、历史发现）              |
+-----------------------------------------------------------+
| Layer 5: 用户记忆 (UserMemory)                              |
| - 每个用户最多 20 条                                        |
| - 包含 memory_type, content, extra_data                    |
| - 存储用户级别的长期记忆（如偏好、常用目标）                  |
+-----------------------------------------------------------+
```

### 4.2 上下文构建

```python
context = await context_manager.build_context()
# 返回:
# {
#     "conversation_history": [...],   # 最近 20 条对话
#     "action_history": [...],         # 最近 20 条操作
#     "result_cache": {...},           # 缓存的结果
#     "project_memory": [...],         # 项目记忆
#     "user_memory": [...],            # 用户记忆
#     "current_project": {...},        # 当前项目信息
# }
```

### 4.3 上下文压缩

当对话历史 token 数超过 `MAX_CONVERSATION_TOKENS` 时，触发压缩：
- 保留最近 N 条对话
- 旧对话由 LLM 生成摘要
- 摘要存入 ProjectMemory

### 4.4 数据库隔离

异步任务使用独立的数据库会话（`AsyncSessionLocal()`），避免与请求级 session 冲突：

```python
async with AsyncSessionLocal() as async_db:
    async_context_manager = ContextManager(async_db, user_id, project_id)
    # 异步任务中所有数据库操作使用 async_db
```

---

## 五、能力注册系统（CapabilityRegistry）

**核心文件**: `backend/app/services/capability_registry.py`

### 5.1 设计原则

**新增能力只需注册，不需要修改任何代码**。

### 5.2 能力定义

```python
@dataclass
class Capability:
    name: str              # 能力名称（唯一标识）
    description: str       # 能力描述（LLM 用来理解能力用途）
    parameters: Dict       # JSON Schema 格式的参数定义
    execute: Callable      # 异步执行函数（可选）
    category: str          # 能力分类
```

### 5.3 当前注册的 28 个能力

| 类别 | 能力 | 说明 |
|------|------|------|
| **扫描类** (5) | scan_ports | 端口扫描（默认全端口 1-65535） |
| | scan_ssl | SSL/TLS 配置分析 |
| | scan_vulnerabilities | 漏洞扫描（nuclei） |
| | scan_weak_passwords | 弱口令检测（hydra） |
| | full_compliance_scan | 全量合规扫描 |
| **查询类** (6) | view_scan_results | 查看扫描结果 |
| | view_open_ports | 查看开放端口（无缓存时自动触发扫描） |
| | view_vulnerabilities | 查看漏洞 |
| | view_findings | 查看合规发现 |
| | view_compliance_score | 查看合规评分 |
| | view_scan_history | 查看扫描历史 |
| **项目类** (4) | create_project / list_projects / update_project / delete_project | 项目管理 |
| **资产类** (3) | add_asset / list_assets / verify_asset | 资产管理 |
| **整改类** (3) | create_remediation_ticket / list_remediation_tickets / update_ticket_status | 整改管理 |
| **报告类** (2) | generate_pdf_report / generate_json_report | 报告生成 |
| **监控类** (3) | create_scheduled_scan / list_scheduled_scans / trigger_scheduled_scan | 定时扫描 |
| **系统类** (2) | help / chat | 帮助和对话 |

### 5.4 扩展方式

新增能力只需 3 步：

1. **注册能力**：在 `_register_all_capabilities()` 中添加 `self.register(Capability(...))`
2. **实现执行逻辑**：在 `ExecutionEngine._execute_capability()` 中添加分支
3. **完成**：LLM 自动发现新能力，自动在决策中使用

---

## 六、执行引擎（ExecutionEngine）

**核心文件**: `backend/app/services/execution_engine.py`

### 6.1 执行流程

```
plan = [
    {"capability": "scan_ports", "parameters": {"target": "localhost"}},
    {"capability": "view_scan_results", "parameters": {"query": "所有结果"}}
]
    |
    v
for step in plan:
    1. 标准化目标地址（localhost → host.docker.internal）
    2. 回调 progress_callback（状态: running）
    3. 调用 _execute_capability()
    4. 记录操作历史（context_manager.add_action）
    5. 缓存结果（context_manager.cache_result）
    6. 回调 progress_callback（状态: completed/failed）
    |
    v
返回:
{
    "results": [...],
    "success_count": 2,
    "failed_count": 0,
}
```

### 6.2 进度回调机制

```python
def progress_callback(task_id, step_index, total_steps, capability_name, status):
    # status: "running" | "completed" | "failed"
    # 实时更新 orchestrator.task_progress[task_id]
```

进度信息通过 `/chat/result/{task_id}` 接口返回给前端：

```json
{
    "status": "running",
    "current_step": "正在执行: 端口扫描...",
    "step_progress": {
        "step_index": 0,
        "total_steps": 2,
        "steps": [
            {"capability": "scan_ports", "display_name": "端口扫描", "status": "running"}
        ]
    }
}
```

### 6.3 目标地址标准化

容器内无法直接访问宿主机 `localhost`，需要转换：

```python
if target in ["localhost", "127.0.0.1", "本机", "本地"]:
    target = "host.docker.internal"
```

### 6.4 缓存键生成

为避免长文本导致数据库字段溢出（`VARCHAR(255)`），使用哈希策略：

```python
# 参数值超过 100 字符 → MD5 哈希前 32 位
# 最终 cache_key 超过 250 字符 → 整体 MD5 哈希
```

---

## 七、调度中枢（Orchestrator）

**核心文件**: `backend/app/orchestrator/orchestrator.py`

### 7.1 核心职责

Orchestrator 是"包工头"，**永远不阻塞**：

1. 接收用户输入
2. 构建上下文 → AI 决策 → 生成分流
3. 纯对话 → 直接返回（无 task_id）
4. 有执行计划 → 异步执行 → 返回 task_id
5. 异步任务完成后，AI 生成结果描述

### 7.2 分流逻辑

```python
plan = ai_engine.decide(user_input, context)

# 纯对话能力不需要异步执行
non_async = ["chat", "help"]
if all step["capability"] in non_async:
    return {"message": response}  # 无 task_id，前端不轮询

# 有实际执行能力 → 异步执行
task_id = uuid4()
asyncio.create_task(_execute_plan_async(task_id, plan, ...))
return {"message": response, "task_id": task_id}  # 前端轮询结果
```

### 7.3 异步任务隔离

每个异步任务使用独立的数据库会话，避免与请求级 session 冲突：

```python
async def _execute_plan_async(self, task_id, plan, ...):
    async with AsyncSessionLocal() as async_db:
        async_context_manager = ContextManager(async_db, user_id, project_id)
        execution_result = await self.execution_engine.execute_plan(...)
        result_description = await self._generate_result_description(...)
        await async_db.commit()
```

### 7.4 进度跟踪

```python
self.task_progress: Dict[str, Dict] = {}
# {
#     "task_id": {
#         "current_step": "正在执行: 端口扫描...",
#         "step_index": 0,
#         "total_steps": 2,
#         "steps": [...]
#     }
# }
```

任务完成后自动清理进度记录。

### 7.5 AI 结果描述

执行完成后，用 LLM 根据执行结果 + 对话历史生成自然语言描述：

```python
prompt = f"""根据执行结果，用简洁的中文描述结果。
对话历史：{conversation_history}
执行结果：{results_summary}
请用简洁的中文描述，包含具体的数据（如端口列表、漏洞数量等）。"""
```

结果摘要包含**全部数据**（不截断），确保 AI 描述完整。

---

## 八、前端交互设计

**核心文件**: `frontend/src/components/ChatWorkspace.jsx`

### 8.1 消息流设计

```
用户发送消息
    |
    v
POST /chat/ → 获取 response + task_id
    |
    v
显示 AI 回复（气泡消息）
    |
    +-- task_id 存在 → 显示执行进度卡片 + 开始轮询
    |                      |
    |                      v
    |                  每 2 秒 GET /chat/result/{task_id}
    |                      |
    |                      +-- running → 更新进度卡片（当前步骤 + 进度条）
    |                      |
    |                      +-- completed → 移除进度卡片 + 添加结果消息
    |
    +-- task_id 不存在 → 仅显示 AI 回复（纯对话）
```

### 8.2 执行进度展示

```
┌─────────────────────────────────────────────┐
│  ████████████████░░░░░░░░░░  1/2            │
│                                             │
│  ⟳ 正在执行: 端口扫描...                     │
│                                             │
│  ─────────────────────────────────          │
│  ✓ 端口扫描                                 │
│  ⟳ 查看扫描结果                              │
└─────────────────────────────────────────────┘
```

任务完成后，进度卡片自动消失，替换为结果消息。

### 8.3 结果展示

结果消息包含三部分：

1. **AI 描述**：自然语言描述（如"本机共开放 16 个端口..."）
2. **统计摘要卡片**：开放端口数 / 漏洞数 / SSL 问题数
3. **详情表格**：Ant Design Table，支持排序和分页，全量展示

```
┌─────────────────────────────────────────────┐
│ 本机共开放 16 个端口，具体包括：...            │
├─────────────────────────────────────────────┤
│ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│ │ 🔵 开放   │ │ 🔴 漏洞   │ │ 🟡 SSL   │     │
│ │ 端口      │ │ 0 个     │ │ 问题     │     │
│ │ 16 个     │ │          │ │ 0 个     │     │
│ └──────────┘ └──────────┘ └──────────┘     │
├─────────────────────────────────────────────┤
│ 端口详情                                     │
│ ┌──────┬──────┬──────────┬───────┐         │
│ │ 端口  │ 协议  │ 服务      │ 状态  │         │
│ ├──────┼──────┼──────────┼───────┤         │
│ │ 53   │ tcp  │ domain   │ open  │         │
│ │ 3000 │ tcp  │ http     │ open  │         │
│ │ ...  │ ...  │ ...      │ ...   │         │
│ └──────┴──────┴──────────┴───────┘         │
│                          < 1 2 >           │
└─────────────────────────────────────────────┘
```

### 8.4 关键实现细节

| 问题 | 解决方案 |
|------|----------|
| 端口截断（"等 16 个"） | 移除 slice 限制，Table 全量展示 + 分页 |
| 转圈不停 | 消息对象属性 `taskCompleted: true` 标记完成，移除进度卡片 |
| 纯对话也有 task_id | 后端判断纯 chat/help 不返回 task_id |
| 结果消息重复 | 纯对话不轮询，只显示一条 AI 回复 |

---

## 九、端到端数据流

### 9.1 完整请求流程

```
1. 用户输入: "本机开启了哪些端口"
   |
   v
2. ChatWorkspace → POST /api/v1/chat/
   |
   v
3. chat.py → orchestrator.handle_user_input()
   |
   v
4. ContextManager.build_context()
   |  查询 5 层记忆 → 构建完整上下文
   |
   v
5. AIEngine.decide(user_input, context)
   |  构建 prompt → 调用 LLM → 解析 JSON
   |  返回: plan=[{scan_ports, target=localhost}]
   |        response="好的，我来扫描本机全部端口"
   |
   v
6. 分流判断: scan_ports 不是纯对话 → 创建 task_id
   |
   v
7. asyncio.create_task(_execute_plan_async)
   |  立即返回: {message: "好的...", task_id: "xxx"}
   |
   v
8. 前端收到响应:
   |  显示 AI 回复气泡
   |  显示进度卡片
   |  开始轮询 GET /chat/result/{task_id}
   |
   v
9. 异步任务执行:
   |  新数据库会话 (AsyncSessionLocal)
   |  ExecutionEngine.execute_plan()
   |    → 标准化目标: localhost → host.docker.internal
   |    → 回调: "正在执行: 端口扫描..."
   |    → MCPGatewayClient → security-tools 容器
   |    → nmap -sS -T4 -p 1-65535 host.docker.internal
   |    → 回调: "已完成: 端口扫描"
   |    → 记录操作历史 + 缓存结果
   |
   v
10. AI 生成结果描述:
    |  提取执行结果（16 个开放端口）
    |  构建 prompt → LLM 生成自然语言描述
    |  "本机共开放 16 个端口，具体包括..."
    |
    v
11. 记录到 completed_tasks + 清理 task_progress
    |
    v
12. 前端轮询到 status=completed:
    |  标记消息 taskCompleted=true → 进度卡片消失
    |  添加结果消息（AI 描述 + 统计卡片 + 端口表格）
    |
    v
13. 用户看到完整结果
```

### 9.2 容器间通信

```
frontend (3000)
    |  HTTP/WebSocket
    v
backend (8000)
    |  HTTP
    v
mcp-gateway (9000)
    |  HTTP
    v
security-tools (8010)
    |  执行 nmap/testssl/nuclei/hydra
    v
目标主机 (host.docker.internal)
```

---

## 十、性能优化

### 10.1 nmap 扫描优化

| 优化项 | 之前 | 之后 |
|--------|------|------|
| 扫描方式 | TCP connect (-sT) | SYN scan (-sS, 需 root) |
| 速度等级 | 默认 | -T4（激进超时） |
| 全端口服务检测 | 开启 | 关闭（大幅提速） |
| 全端口扫描耗时 | 123 秒 | **49 秒** |

### 10.2 缓存策略

| 缓存类型 | 过期时间 | 用途 |
|----------|----------|------|
| 扫描结果 | 1 小时 | 避免重复扫描 |
| 对话历史 | 不过期 | 上下文连续性 |
| 操作历史 | 不过期 | 审计追溯 |

### 10.3 数据库会话管理

| 场景 | 会话类型 | 说明 |
|------|----------|------|
| API 请求 | 请求级 session（Depends(get_db)） | 请求结束自动关闭 |
| 异步任务 | 独立 session（AsyncSessionLocal()） | 避免与请求级冲突 |
| ContextManager | flush() 而非 commit() | 由调用方控制事务 |

---

## 十一、当前状态与待办

### 已完成

- [x] AI 决策引擎（LLM 驱动意图识别 + 执行计划生成）
- [x] 多层记忆系统（5 层记忆 + 上下文构建）
- [x] 能力注册系统（28 个能力，8 个类别）
- [x] 执行引擎（逐步执行 + 进度回调 + 结果缓存）
- [x] 调度中枢（异步执行 + 进度跟踪 + AI 结果描述）
- [x] 前端交互（进度展示 + 结果表格 + 转圈修复）
- [x] 全端口扫描（1-65535，49 秒完成）
- [x] 纯对话分流（chat/help 不触发异步执行）
- [x] 数据库会话隔离（异步任务独立 session）
- [x] 缓存键防溢出（长文本 MD5 哈希）

### 待完成

- [ ] 上下文压缩（对话历史超长时 LLM 摘要）
- [ ] 项目记忆 / 用户记忆的写入逻辑
- [ ] WebSocket 实时推送（替代轮询）
- [ ] Multi-Agent 并行执行（当前串行）
- [ ] 三引擎判定架构（规则引擎 + LLM + 混合）
- [ ] 等保知识库集成（条款自动匹配）
- [ ] 整改闭环（发现 → 工单 → 整改 → 复测）
- [ ] 报告生成（PDF / JSON）
