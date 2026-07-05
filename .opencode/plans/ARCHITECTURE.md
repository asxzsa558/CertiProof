# VeriSure 技术架构文档

> 本文档描述 VeriSure 当前实现架构、核心模块职责、数据流、安全边界和已知限制。
> 产品路线图和执行计划请参见 [ROADMAP.md](./ROADMAP.md)。

---

## 一、系统架构总览

### 1.1 核心设计理念

VeriSure 是一个面向等保测评和安全验证的对话式 SaaS 系统。当前实现采用“对话入口 + AI 计划 + 任务编排 + MCP 工具执行 + 结构化结果展示”的架构。

| 维度 | 当前实现 |
|------|----------|
| 意图识别 | LLM 生成 plan，快捷按钮和 `/` 命令走同一工具目录 |
| 能力调度 | Capability Registry 注册能力，Execution Engine 执行能力 |
| 上下文理解 | Conversation / Action / Cache / Project Memory / User Memory / Archive / Assessment State |
| 工具执行 | MCP Gateway 路由到安全、Web、数据库、网络、Windows、SSH 等工具服务 |
| 结果展示 | 后端归一化结果，前端按单资产/多资产聚合展示 |
| 权限控制 | JWT + Organization RBAC + 项目级权限检查 |
| 安全边界 | AI plan 参数 schema 校验、敏感参数脱敏、生产配置启动校验 |

### 1.2 当前架构图

```text
Frontend (React + Ant Design)
  Dashboard / Login / Project Chat Workspace / Result Cards
          |
          v
FastAPI API Layer
  Auth | Projects | Assets | Chat | Tasks | Dashboard | Assessments | RBAC
          |
          v
Orchestrator Layer
  Orchestrator
    - 创建/恢复 ScanTask
    - 进度广播和轮询恢复
    - 单资产/多资产执行分流
    - 结果提取、记忆写入、AI 结果描述
  AI Engine
    - LLM 决策
    - plan JSON 解析
    - capability 和参数 schema 校验
  Context Manager
    - 对话、操作、缓存、项目/用户记忆、归档、测评状态
  Execution Engine
    - 工具参数标准化
    - 串行/并发执行
    - 错误归一化
    - 组合工具矩阵
          |
          v
MCP Gateway / Tool Servers
  security-tools: nmap/testssl/nuclei/hydra/ping
  fast-scanner: masscan
  web-tools: nikto/sqlmap/gobuster/ffuf
  db-tools: Redis/MySQL/MongoDB/Memcached/Oracle
  network-tools: SNMP walk/get/bruteforce
  windows-tools: enum4linux/smb/crackmapexec
  ssh-checker: baseline/password/ssh/audit/service/file/mac checks
          |
          v
Storage
  SQL database | file uploads | in-process task state | persisted scan_tasks
```

---

## 二、核心模块

### 2.1 Orchestrator

**文件**: `backend/app/orchestrator/orchestrator.py`

职责：
- 接收 Chat API 传入的用户输入和项目上下文。
- 调用 `ContextManager.build_context()` 构造上下文。
- 调用 `AIEngine.decide()` 得到执行 plan。
- 将 `项目资产` 占位符扩展成具体资产。
- 对扫描类 plan 创建 `ScanTask` 持久化记录。
- 通过 `ExecutionEngine` 串行或并发执行工具。
- 维护进程内任务状态：running / paused / stopped / completed。
- 将完成结果写入 `completed_tasks` 和 `scan_tasks.result_summary`。
- 广播 WebSocket 进度，并支持前端轮询恢复。
- 生成 AI 结果描述；安全工具结果优先使用结构化摘要，避免只有一句“完成”。

当前注意点：
- `active_tasks`、暂停/恢复控制仍是进程内能力；重启后只能恢复 ScanTask 的最终结果或基础状态，不能恢复正在运行的 asyncio task。
- 多实例部署时需要引入独立 worker 和队列，否则任务控制会不一致。

### 2.2 AI Engine

**文件**: `backend/app/services/ai_engine.py`

职责：
- 构造稳定 system prompt + 动态上下文 prompt。
- 注入 Capability Registry 能力列表。
- 注入项目资产、归档摘要、测评状态、当前阶段工具建议。
- 调用 LLM，要求返回 JSON plan。
- 解析直接 JSON、markdown JSON block、普通 code block 中的 JSON。
- 检测提示词泄露倾向并降级为安全回复。
- 按 Capability Registry 做 plan 校验：
  - 未注册 capability 丢弃。
  - 未知参数丢弃。
  - 基础类型不匹配时尝试安全转换。
  - 缺必填参数时降级为 chat 提示补参。
- AI plan 日志会脱敏，不记录完整原始 LLM 内容。

设计取舍：
- 仍以 LLM 自主理解为主，但 `/` 命令和快捷按钮在 prompt 中有强规则。
- 参数 schema 校验是轻量实现，没有引入 jsonschema 依赖。

### 2.3 Context Manager

**文件**: `backend/app/services/context_manager.py`

当前上下文来源：
- `conversation_history`: 最近对话历史。
- `recent_messages`: 供 LLM 使用的最近 N 轮对话。
- `action_history`: 操作历史。
- `result_cache`: 结果缓存，默认最多 100 条，过期清理。
- `project_memory`: 项目长期记忆。
- `user_memory`: 用户偏好记忆。
- `project_archives_summary`: 项目归档摘要。
- `assessment_state`: 当前项目等保测评流程状态。
- `project_assets`: 当前项目资产。

当前限制：
- `MAX_CONVERSATION_TOKENS=200000`，`HARD_TOKEN_LIMIT=500000`，比早期设计更大。上下文能力更强，但 LLM 成本和隐私面也更大。
- ContextManager 本身假设调用方已做项目授权；API 入口必须先通过 `get_project_for_user()` 或 RBAC 检查。
- ActionHistory 参数已脱敏，避免 SSH 密码/API token 等进入历史。

### 2.4 Capability Registry

**文件**: `backend/app/services/capability_registry.py`

职责：
- 注册所有可被 AI 调用的能力。
- 为 prompt 提供精简能力说明。
- 为 AI plan 校验提供参数 schema。

当前能力覆盖：
- 端口扫描：`scan_ports`、`masscan_scan`、`fping_scan`
- TLS/漏洞/弱口令：`scan_ssl`、`scan_vulnerabilities`、`scan_weak_passwords`
- Web：`nikto_scan`、`sqlmap_scan`、`gobuster_scan`、`ffuf_scan`、`web_discovery_scan`
- 数据库：`redis_check`、`mysql_check`、`mongodb_check`、`memcached_check`、`oracle_check`、`database_security_scan`
- 网络设备：`snmp_walk`、`snmp_get`、`snmp_bruteforce`、`network_device_scan`
- Windows/AD/SMB：`enum4linux_scan`、`crackmapexec_scan`、`smb_enum`、`windows_security_scan`
- 白盒/基线：`baseline_check`、`linux_baseline`、`ssh_config_check`、`password_policy_check`、`audit_config_check`、`service_port_check`、`file_permission_check`、`mac_check`
- 组合：`full_compliance_scan`、`tech_assessment`
- 查询、项目、资产、整改、报告、监控、系统能力。

扩展方式：
1. 在 `CapabilityRegistry` 注册能力和参数 schema。
2. 在 `ExecutionEngine._execute_capability()` 添加执行分支。
3. 如需外部工具，添加 MCP server 工具并更新 Gateway 路由。
4. 同步 `scripts/tool_matrix_check.py` 覆盖前后端工具矩阵。

### 2.5 Execution Engine

**文件**: `backend/app/services/execution_engine.py`

职责：
- 标准化 capability alias，例如 `nmap_scan -> scan_ports`。
- 标准化 SSH 参数和 URL 参数。
- 执行单步能力或多资产并发能力。
- 多资产执行时，每个资产使用独立 DB session，避免共享 session 并发冲突。
- 对 MCP Gateway 错误做结构化归一化：timeout、filtered、auth failed、missing parameter、tool dependency missing 等。
- 组合工具返回子任务矩阵，允许单个子工具失败/跳过，整体仍可返回完整结果。
- 日志、ActionHistory、ScanTask parameters 和 cache key 对敏感字段脱敏。

并发策略：
- 早期文档写最大并发 5；当前 Orchestrator 会按资产数量动态调整，大致为 5/8/10/12。
- 并发越大越容易触发目标限速或误判，生产建议做组织级/项目级并发配置。

### 2.6 MCP Gateway 和 Tool Servers

**Gateway 文件**: `mcp-servers/gateway/server.py`

职责：
- 接收统一 `/call` 或异步调用。
- 将工具名路由到对应 tool server。
- 提供 `/health`、`/tools`、依赖诊断基础能力。

当前 Tool Servers：
- `security-tools`: nmap、testssl、nuclei、hydra、ping。
- `fast-scanner`: masscan。
- `web-tools`: nikto、sqlmap、gobuster、ffuf。
- `db-tools`: Redis、MySQL、MongoDB、Memcached、Oracle。
- `network-tools`: SNMP walk/get/bruteforce。
- `windows-tools`: enum4linux、smbclient、crackmapexec/SMB SID。
- `ssh-checker`: 自动识别 OS 的基线/SSH/审计/服务/文件权限/MAC 检查。

### 2.7 前端结果渲染

核心文件：
- `frontend/src/components/ChatWorkspace.jsx`: 聊天工作区、命令入口、任务轮询、资产/凭据交互。
- `frontend/src/components/toolCatalog.js`: 快捷按钮、斜杠菜单、结果展示共用工具目录。
- `frontend/src/components/ResultMessageRenderer.jsx`: 结果分发入口。
- `frontend/src/components/SingleResultMessage.jsx`: 单资产结果展示。
- `frontend/src/components/MultiAssetResultMessage.jsx`: 多资产审计矩阵。
- `frontend/src/components/AssetResultSections.jsx`: 单个资产摘要和详情。
- `frontend/src/components/ToolResultCard.jsx`: 统一结果卡片、复制结果。

原则：
- 快捷按钮、`/` 命令、聊天指令共用同一工具目录，避免入口漂移。
- 多资产结果聚合为一个结果卡，按资产/IP 展示状态、风险、工具、摘要和折叠详情。
- filtered/no-response 不能当作开放端口；错误详情要区分 timeout、connection refused、filtered、auth failed 等。

---

## 三、请求和任务数据流

### 3.1 Chat 请求流程

```text
用户输入或快捷按钮
  -> POST /api/v1/chat/
  -> 项目/RBAC 权限校验
  -> 多资产 JSON 快捷路径 或 Orchestrator.handle_user_input()
  -> ContextManager.build_context()
  -> AIEngine.decide()
  -> AI plan schema 校验
  -> Orchestrator.start_async_plan()
  -> 创建 ScanTask + 进程内 task metadata
  -> 前端立即显示运行态
  -> ExecutionEngine 执行工具
  -> WebSocket 广播 + 轮询 /chat/result/{task_id}
  -> 提取 scan_results + AI/结构化结果描述
  -> 持久化 ScanTask.result_summary
  -> 前端恢复/展示结果卡
```

### 3.2 多资产扫描流程

```text
前端选择多个资产
  -> 构造 type=multi_asset_scan JSON
  -> Chat API 去重资产并注入资产级 SSH 凭据
  -> 每个资产生成一个 plan step
  -> Orchestrator 判断为多资产扫描
  -> ExecutionEngine.execute_plan_concurrent()
  -> 每个资产独立执行、独立 DB session
  -> 汇总 asset_results
  -> MultiAssetResultMessage 聚合展示
```

### 3.3 任务恢复

- 运行中进度优先来自 Orchestrator 进程内 `task_progress`。
- 完成/失败结果优先来自 `completed_tasks`。
- 刷新或进程状态丢失时，从 `scan_tasks.orchestrator_task_id` 恢复基础状态和最终结果。
- 重启后不能恢复正在执行的 asyncio task，这是当前生产化限制。

---

## 四、权限与安全边界

### 4.1 认证与 RBAC

- 认证：JWT access token + refresh token。
- 组织权限：`backend/app/core/rbac.py`。
- 项目访问：`get_project_for_user()` 根据组织成员权限或项目所有者校验。
- 典型权限：`project:read`、`scan:execute`、`scan:read`、`scan:cancel`、`assessment:manage`、`role:manage`。

### 4.2 敏感信息处理

- 公共脱敏工具：`backend/app/core/redaction.py`。
- 脱敏字段包含 password、token、api_key、key_file、secret、credential 等。
- 当前脱敏位置：
  - ExecutionEngine 日志。
  - AI plan 日志。
  - ActionHistory parameters。
  - ScanTask parameters。
  - ResultCache cache key。
- 注意：扫描发现的弱口令结果属于审计证据，当前不会自动脱敏；报告导出或共享时应按场景决定是否隐藏。

### 4.3 AI 安全边界

- Prompt 中要求不得泄露系统提示词。
- `_check_prompt_leak()` 对疑似泄露做降级回复。
- `_validate_plan()` 只允许注册能力进入执行层。
- `_validate_step()` 按 CapabilityRegistry schema 做参数白名单和基础类型校验。
- 原始 LLM 响应不再截断写入日志，只记录长度。

### 4.4 生产启动校验

`settings.validate_runtime_security()` 在 FastAPI lifespan 启动阶段执行：
- `APP_ENV=production/prod` 时，`DEBUG=True` 会拒绝启动。
- 默认 `SECRET_KEY` 会拒绝启动。
- `CORS_ORIGINS` 包含 `*` 会拒绝启动。

---

## 五、数据库模型

核心模型：

| 模型 | 表 | 用途 |
|------|----|------|
| User | users | 用户、角色、登录信息 |
| Organization / Member / Role | organizations 等 | 多租户与 RBAC |
| Project | projects | 测评项目 |
| Asset | assets | 项目资产 |
| ScanTask | scan_tasks | 扫描任务、进度、结果摘要 |
| Finding | findings | 风险/合规发现 |
| Evidence | evidences | 证据材料 |
| RemediationTicket | remediation_tickets | 整改工单 |
| Assessment / Phase / Task | assessments 等 | 等保测评流程 |
| ConversationHistory | conversation_history | 对话历史 |
| ActionHistory | action_history | 操作历史 |
| ResultCache | result_cache | 结果缓存 |
| ProjectMemory / UserMemory | project_memory / user_memory | 长期记忆 |
| ConversationArchive / Thread | conversation_archives / conversation_threads | 归档和线程 |

当前项目仍使用自动补表/轻量迁移逻辑，文档中早期 Alembic “003 head” 描述不再准确。生产化应恢复正式迁移管理。

---

## 六、验证脚本

| 脚本/命令 | 用途 |
|-----------|------|
| `python3 scripts/tool_matrix_check.py` | 校验前端工具目录、后端显示名、Orchestrator 扫描能力矩阵 |
| `python3 scripts/security_boundary_check.py` | 校验脱敏、AI plan guard、生产配置 guard 没被改丢 |
| `python3 -m compileall -q backend/app mcp-servers scripts` | Python 编译检查 |
| `npm run build` in `frontend/` | 前端生产构建 |

---

## 七、当前限制与后续方向

### 7.1 当前限制

| 限制 | 说明 |
|------|------|
| 任务控制仍部分进程内 | pause/resume/active asyncio task 不支持多实例/重启恢复 |
| ContextManager 依赖调用方授权 | 构建上下文前必须由 API 层完成项目/RBAC 校验 |
| AI 参数校验是轻量实现 | 只做白名单和基础类型；尚未做 IP/URL/端口范围和 SSRF 策略校验 |
| 工具执行受容器网络影响 | Docker 内扫描云主机时会遇到安全组、防火墙、出口 IP 限制 |
| ChatWorkspace 仍偏大 | 结果渲染已拆，但命令解析、任务轮询、诊断展示还在主组件 |
| 数据库迁移体系不完整 | 当前仍有运行时补表逻辑，生产应统一迁移工具 |

### 7.2 建议优先级

1. 将 Orchestrator 任务执行迁移为 DB-backed worker/queue。
2. 拆分 ChatWorkspace 的命令解析、任务轮询、诊断渲染。
3. 为 AI plan 增加 IP/URL/端口范围安全策略。
4. 增加组织/项目级扫描并发、目标范围和高危工具确认策略。
5. 完善 `.env.example`、生产 Docker profile、迁移管理和日志策略。

---

## 八、扩展指南

### 8.1 添加新能力

1. 在 `capability_registry.py` 注册 `Capability` 和参数 schema。
2. 在 `execution_engine.py` 实现执行分支。
3. 如果依赖外部工具，在对应 MCP server 暴露 `/execute` 工具。
4. 更新 MCP Gateway 路由。
5. 更新前端 `toolCatalog.js`。
6. 运行 `scripts/tool_matrix_check.py`。

### 8.2 添加新工具结果展示

1. 后端统一返回 `{status, target, capability, data, metadata, error}` 或可归一化结构。
2. Orchestrator `_extract_scan_results_from_execution()` 提取摘要字段。
3. 前端在 `AssetResultSections.jsx` 增加摘要和详情展示。
4. 确认复制文本不是 `[object Object]`。

---

**文档版本**: v2.0
**最后更新**: 2026-07-05
**维护者**: VeriSure Team
