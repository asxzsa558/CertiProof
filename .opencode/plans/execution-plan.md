# CertiProof 架构清理与功能完善执行计划

## 一、当前状态总结

### 已完成的核心架构
- ✅ Orchestrator 调度中枢（orchestrator.py + agent.py + skill_loader.py）
- ✅ MCP Gateway 统一入口（gateway/server.py）
- ✅ MCP Tool Servers（nmap-server, testssl-server, hydra-server）
- ✅ 前端新架构（ChatPage + ChatWorkspace + ToolCard + AgentStatusCard）
- ✅ 多模型配置系统（ModelProvider + ModelConfig）
- ✅ Docker Compose 编排

### 发现的问题
1. **遗留代码未清理**：旧的 agent/ 目录、real_scan_service.py、mock_scan.py 等仍在代码库中
2. **MCP Server 端口不一致**：nuclei-server 和 ocr-server 的端口配置与 docker-compose 不匹配
3. **MCP Server 接口不统一**：nuclei-server 和 ocr-server 没有实现标准的 `/execute` 接口
4. **AgentStatusCard 未集成**：组件已创建但未在 ChatWorkspace 中使用
5. **前端遗留页面**：Dashboard、Projects、ProjectDetail 等旧页面仍在使用旧的 ChatInterface

---

## 二、执行计划

### 阶段 1：清理遗留代码（预计 30 分钟）

#### 1.1 删除后端遗留文件
```bash
# 删除旧的 agent 目录
rm -rf backend/app/agent/

# 删除旧的扫描服务
rm backend/app/services/real_scan_service.py

# 删除旧的扫描 API
rm backend/app/api/real_scan.py
rm backend/app/api/mock_scan.py
```

#### 1.2 更新后端 API 注册
**文件**: `backend/app/api/__init__.py`
- 移除 `mock_scan_router` 和 `real_scan_router` 的导入和注册

#### 1.3 更新后端服务导出
**文件**: `backend/app/services/__init__.py`
- 移除 `scan_service` 的导出（或更新为使用 orchestrator）

#### 1.4 删除前端遗留文件
```bash
# 删除旧的聊天组件
rm frontend/src/components/ChatInterface.jsx
rm frontend/src/components/ChatInterface.css

# 删除旧的页面
rm frontend/src/pages/Dashboard.jsx
rm frontend/src/pages/Dashboard.css
rm frontend/src/pages/Projects.jsx
rm frontend/src/pages/Projects.css
rm frontend/src/pages/ProjectDetail.jsx
rm frontend/src/pages/ProjectDetail.css
rm frontend/src/pages/Remediation.jsx
rm frontend/src/pages/Remediation.css
rm frontend/src/pages/ScanResults.jsx
rm frontend/src/pages/ScanResults.css
rm frontend/src/pages/Monitoring.jsx
rm frontend/src/pages/Monitoring.css
```

#### 1.5 更新前端路由
**文件**: `frontend/src/App.jsx`
- 移除已删除页面的路由
- 保留：Login, Register, ChatPage, ModelSettings

---

### 阶段 2：修复 MCP Server（预计 1 小时）

#### 2.1 修复 nuclei-server

**文件**: `mcp-servers/nuclei-server/server.py`

**修改内容**:
1. 添加标准 `/execute` 端点
2. 修改端口从 8002 改为 8003
3. 统一响应格式为 `{tool, version, status, data, metadata}`

**文件**: `mcp-servers/nuclei-server/Dockerfile`

**修改内容**:
1. 修改 EXPOSE 从 8002 改为 8003
2. 修改 CMD 中的端口从 8002 改为 8003

#### 2.2 修复 ocr-server

**文件**: `mcp-servers/ocr-server/server.py`

**修改内容**:
1. 添加标准 `/execute` 端点
2. 修改端口从 8003 改为 8005
3. 统一响应格式为 `{tool, version, status, data, metadata}`

**文件**: `mcp-servers/ocr-server/Dockerfile`

**修改内容**:
1. 修改 EXPOSE 从 8003 改为 8005
2. 修改 CMD 中的端口从 8003 改为 8005

#### 2.3 更新环境变量示例

**文件**: `backend/.env.example`

**修改内容**:
```bash
# 移除
MCP_SERVER_HOST=localhost
MCP_SERVER_PORT=8001

# 添加
MCP_GATEWAY_URL=http://localhost:9000
```

---

### 阶段 3：修复后端遗留代码（预计 1 小时）

#### 3.1 修复 orchestrator/agent.py 的 bug

**文件**: `backend/app/orchestrator/agent.py`

**问题**: 第 229 行 `self.resolve_params(value, context)` 中 `context` 未定义

**修复**: 改为 `self.resolve_params(value, self.context)`

#### 3.2 更新 scan_service.py

**文件**: `backend/app/services/scan_service.py`

**修改内容**:
- 移除 `from app.agent.dispatcher import agent_dispatcher`
- 改为使用 `from app.orchestrator import orchestrator`
- 更新 `execute_scan_task` 方法，调用 orchestrator 而不是 agent_dispatcher

#### 3.3 更新 scans.py API

**文件**: `backend/app/api/scans.py`

**修改内容**:
- 确保使用更新后的 scan_service
- 或者考虑是否还需要这个 API（因为现在有 chat API）

#### 3.4 更新 monitoring.py

**文件**: `backend/app/api/monitoring.py`

**修改内容**:
- 移除 `from app.services.real_scan_service import scan_host, check_ssl, generate_compliance_findings`
- 改为通过 MCP Gateway 调用扫描工具
- 或者使用 orchestrator 触发扫描

---

### 阶段 4：集成 Orchestrator 前端 UI（预计 1 小时）

**核心需求**：orchestrator 会返回多个 Agent 的执行信息，前端需要实时展示这些 Agent 的执行状态。

#### 4.1 更新 ChatWorkspace.jsx

**文件**: `frontend/src/components/ChatWorkspace.jsx`

**修改内容**:

1. **导入 AgentStatusCard**
```jsx
import AgentStatusCard from './AgentStatusCard'
```

2. **在 handleSend 中保存 task_ids 和 agents 信息**
```jsx
const assistantMessage = {
  role: 'assistant',
  content: response.data.response,
  tool_cards: response.data.tool_cards || [],
  actions: response.data.actions || [],
  context: response.data.context,
  model_used: response.data.model_used,
  task_ids: response.data.task_ids || [],  // 新增：保存 task_ids
  agents: response.data.agents || [],       // 新增：保存 agents 信息
}
```

3. **在消息渲染中显示 AgentStatusCard**
```jsx
{msg.task_ids && msg.task_ids.length > 0 && (
  <AgentStatusCard 
    taskIds={msg.task_ids}
    onComplete={(results) => {
      // 当所有 Agent 完成时，可以添加一条汇总消息
      const summaryMessage = {
        role: 'assistant',
        content: `✅ 所有检测任务已完成！共收集 ${results.reduce((sum, r) => sum + (r.evidence_count || 0), 0)} 条证据。`,
      }
      setMessages(prev => [...prev, summaryMessage])
    }}
  />
)}
```

4. **在消息气泡下方显示 Agent 列表（简要信息）**
```jsx
{msg.agents && msg.agents.length > 0 && (
  <div className="message-agents">
    <div className="agents-header">
      <RobotOutlined /> 已派发 {msg.agents.length} 个 Agent
    </div>
    <div className="agents-list">
      {msg.agents.map((agent, i) => (
        <Tag key={i} color="blue">
          {agent.name}
        </Tag>
      ))}
    </div>
  </div>
)}
```

#### 4.2 更新 ChatWorkspace.css

**文件**: `frontend/src/components/ChatWorkspace.css`

**添加样式**:
```css
.message-agents {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(99, 102, 241, 0.1);
  border-radius: 8px;
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.agents-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  margin-bottom: 6px;
}

.agents-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.agents-list .ant-tag {
  margin: 0;
  font-size: 11px;
}
```

#### 4.3 后端 API 返回格式确认

**文件**: `backend/app/api/chat.py`

确认 `/chat/` 端点返回的数据格式包含：
```python
return {
    "response": "已派出 3 个 Agent 执行任务",
    "task_ids": ["uuid1", "uuid2", "uuid3"],
    "agents": [
        {"id": "uuid1", "name": "边界访问控制", "clause": "8.1.3.1"},
        {"id": "uuid2", "name": "通信传输加密", "clause": "8.1.2.2"},
        {"id": "uuid3", "name": "弱口令检测", "clause": "8.1.4.1"},
    ],
    "context": {"asset": "47.96.10.100"},
}
```

#### 4.4 前端展示效果

**用户输入**: "对 47.96.10.100 做等保三级测评"

**前端展示**:
```
┌─────────────────────────────────────────────────────────┐
│ 🤖 CertiProof Agent                                     │
│                                                         │
│ 用户: 对 47.96.10.100 做等保三级测评                     │
│                                                         │
│ 助手: 已派出 4 个 Agent 执行任务                         │
│                                                         │
│ 🤖 已派发 4 个 Agent                                    │
│ [边界访问控制] [通信传输加密] [弱口令检测] [漏洞扫描]     │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 当前执行状态                          [执行中]       │ │
│ │                                                     │ │
│ │ ✓ 边界访问控制                    [已完成]          │ │
│ │   收集了 3 条证据                                   │ │
│ │                                                     │ │
│ │ ⟳ 通信传输加密                    [运行中 60%]     │ │
│ │   ████████████░░░░░░░░                              │ │
│ │                                                     │ │
│ │ ⟳ 弱口令检测                      [运行中 30%]     │ │
│ │   ██████░░░░░░░░░░░░░░                              │ │
│ │                                                     │ │
│ │ ⟳ 漏洞扫描                        [运行中 20%]     │ │
│ │   ████░░░░░░░░░░░░░░░░                              │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**当所有 Agent 完成后**:
```
┌─────────────────────────────────────────────────────────┐
│ 🤖 CertiProof Agent                                     │
│                                                         │
│ 用户: 对 47.96.10.100 做等保三级测评                     │
│                                                         │
│ 助手: 已派出 4 个 Agent 执行任务                         │
│                                                         │
│ 🤖 已派发 4 个 Agent                                    │
│ [边界访问控制] [通信传输加密] [弱口令检测] [漏洞扫描]     │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 当前执行状态                          [已完成]       │ │
│ │                                                     │ │
│ │ ✓ 边界访问控制                    [已完成]          │ │
│ │   收集了 3 条证据                                   │ │
│ │                                                     │ │
│ │ ✓ 通信传输加密                    [已完成]          │ │
│ │   收集了 2 条证据                                   │ │
│ │                                                     │ │
│ │ ✓ 弱口令检测                      [已完成]          │ │
│ │   收集了 1 条证据                                   │ │
│ │                                                     │ │
│ │ ✓ 漏洞扫描                        [已完成]          │ │
│ │   收集了 5 条证据                                   │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ 助手: ✅ 所有检测任务已完成！共收集 11 条证据。          │
│                                                         │
│ [ToolCard: 合规分数 45 分]                              │
│ [ToolCard: 严重问题 2 个]                               │
│ [ToolCard: 高危问题 3 个]                               │
└─────────────────────────────────────────────────────────┘
```

#### 4.5 后端 API 返回格式确认

**文件**: `backend/app/api/chat.py`

确认 `/chat/` 端点返回的数据格式：
```python
return ChatResponse(
    response="已派出 4 个 Agent 执行任务",
    task_ids=["uuid1", "uuid2", "uuid3", "uuid4"],
    agents=[
        {"id": "uuid1", "name": "边界访问控制", "clause": "8.1.3.1"},
        {"id": "uuid2", "name": "通信传输加密", "clause": "8.1.2.2"},
        {"id": "uuid3", "name": "弱口令检测", "clause": "8.1.4.1"},
        {"id": "uuid4", "name": "漏洞扫描", "clause": "8.1.3.3"},
    ],
    context={"asset": "47.96.10.100"},
)
```

#### 4.6 前端轮询机制优化

**当前问题**: AgentStatusCard 每 2 秒轮询一次 `/chat/status`，可能不够高效。

**优化方案**:
1. **保持轮询**：简单可靠，适合 MVP 阶段
2. **未来优化**：可以考虑 WebSocket 或 Server-Sent Events (SSE)

**轮询逻辑**:
```jsx
// AgentStatusCard.jsx
useEffect(() => {
  if (!taskIds || taskIds.length === 0) return

  fetchStatus()  // 初始加载

  const interval = setInterval(() => {
    if (polling) {
      fetchStatus()
    }
  }, 2000)  // 每 2 秒轮询

  return () => clearInterval(interval)
}, [taskIds, polling])
```

#### 4.7 错误处理

**场景 1**: Agent 执行失败
```jsx
{agent.status === 'failed' && agent.error && (
  <Text type="danger" className="error-message">
    {agent.error}
  </Text>
)}
```

**场景 2**: 轮询失败
```jsx
const fetchStatus = async () => {
  try {
    const response = await api.get('/chat/status')
    // ... 处理响应
  } catch (error) {
    console.error('Failed to fetch agent status:', error)
    // 可以选择显示错误提示或重试
  } finally {
    setLoading(false)
  }
}
```

**场景 3**: 所有 Agent 完成
```jsx
const allCompleted = filteredAgents.every(a => a.status === 'completed')
if (allCompleted && filteredAgents.length > 0) {
  setPolling(false)  // 停止轮询
  if (onComplete) {
    onComplete(filteredAgents)  // 触发完成回调
  }
}
```

#### 4.8 实施步骤

1. **更新 ChatWorkspace.jsx**
   - 导入 AgentStatusCard
   - 在 handleSend 中保存 task_ids 和 agents
   - 在消息渲染中显示 AgentStatusCard
   - 在消息气泡下方显示 Agent 列表

2. **更新 ChatWorkspace.css**
   - 添加 message-agents 样式
   - 添加 agents-header 样式
   - 添加 agents-list 样式

3. **测试验证**
   - 测试 Agent 执行状态显示
   - 测试轮询机制
   - 测试完成回调
   - 测试错误处理

---

### 阶段 5：更新 App.jsx 路由（预计 10 分钟）

**文件**: `frontend/src/App.jsx`

**修改内容**:
```jsx
// 移除已删除页面的导入
// import Dashboard from './pages/Dashboard'  // 删除
// import Projects from './pages/Projects'  // 删除
// import ProjectDetail from './pages/ProjectDetail'  // 删除
// import Remediation from './pages/Remediation'  // 删除
// import ScanResults from './pages/ScanResults'  // 删除
// import Monitoring from './pages/Monitoring'  // 删除

// 移除对应的路由
// <Route path="/dashboard" element={<Dashboard />} />  // 删除
// <Route path="/projects" element={<Projects />} />  // 删除
// <Route path="/projects/:projectId" element={<ProjectDetail />} />  // 删除
// <Route path="/projects/:projectId/remediation" element={<Remediation />} />  // 删除
// <Route path="/projects/:projectId/scans/:scanId" element={<ScanResults />} />  // 删除
// <Route path="/projects/:projectId/monitoring" element={<Monitoring />} />  // 删除
```

---

### 阶段 6：测试验证（预计 30 分钟）

#### 6.1 后端测试
```bash
cd backend
source venv/bin/activate

# 启动后端
uvicorn app.main:app --reload --port 8000

# 测试 API
curl http://localhost:8000/health
curl http://localhost:8000/docs
```

#### 6.2 MCP Server 测试
```bash
# 测试 Gateway
curl http://localhost:9000/health

# 测试 nmap-server
curl http://localhost:8001/health

# 测试 testssl-server
curl http://localhost:8002/health

# 测试 nuclei-server
curl http://localhost:8003/health

# 测试 hydra-server
curl http://localhost:8004/health

# 测试 ocr-server
curl http://localhost:8005/health
```

#### 6.3 前端测试
```bash
cd frontend
npm run dev

# 访问 http://localhost:3000
# 测试登录/注册
# 测试聊天功能
# 测试 AgentStatusCard 显示
```

---

## 三、执行顺序与时间估算

| 阶段 | 任务 | 预计时间 | 依赖 |
|------|------|----------|------|
| 1 | 清理遗留代码 | 30 分钟 | 无 |
| 2 | 修复 MCP Server | 1 小时 | 无 |
| 3 | 修复后端遗留代码 | 1 小时 | 阶段 1 |
| 4 | 集成 AgentStatusCard | 30 分钟 | 无 |
| 5 | 更新 App.jsx 路由 | 10 分钟 | 阶段 1 |
| 6 | 测试验证 | 30 分钟 | 阶段 1-5 |
| **总计** | | **4 小时** | |

---

## 四、风险与注意事项

### 4.1 风险
1. **scan_service.py 依赖复杂**：可能需要大量重构，考虑是否直接删除这个服务
2. **monitoring.py 依赖 real_scan_service**：需要改为使用 MCP Gateway
3. **前端路由删除**：确保没有其他地方引用这些路由

### 4.2 注意事项
1. **备份**：在删除文件前，确保已提交到 Git
2. **测试**：每完成一个阶段都要测试，避免累积问题
3. **文档**：更新 README.md，说明新的架构和使用方法

---

## 五、后续优化（可选）

### 5.1 功能增强
1. **LLM 意图识别**：在 orchestrator.py 中实现基于 LLM 的意图识别
2. **智能判定引擎**：在 agent.py 中实现更复杂的合规判定逻辑
3. **WebSocket 实时推送**：替代 AgentStatusCard 的轮询机制
4. **资产所有权验证**：实现真正的验证逻辑（DNS TXT、文件验证等）
5. **变更检测**：在 monitoring.py 中实现变更检测逻辑

### 5.2 架构优化
1. **Gateway Schema 验证**：在 gateway/server.py 中启用输出 Schema 验证
2. **错误处理**：统一错误处理和错误码
3. **日志系统**：添加统一的日志系统
4. **性能监控**：添加性能监控和指标收集

---

## 六、执行检查清单

### 阶段 1：清理遗留代码
- [ ] 删除 backend/app/agent/ 目录
- [ ] 删除 backend/app/services/real_scan_service.py
- [ ] 删除 backend/app/api/real_scan.py
- [ ] 删除 backend/app/api/mock_scan.py
- [ ] 更新 backend/app/api/__init__.py
- [ ] 更新 backend/app/services/__init__.py
- [ ] 删除前端遗留文件（7 个 JSX + 7 个 CSS）
- [ ] 更新 frontend/src/App.jsx 路由

### 阶段 2：修复 MCP Server
- [ ] 修复 nuclei-server/server.py（添加 /execute，改端口）
- [ ] 修复 nuclei-server/Dockerfile（改端口）
- [ ] 修复 ocr-server/server.py（添加 /execute，改端口）
- [ ] 修复 ocr-server/Dockerfile（改端口）
- [ ] 更新 backend/.env.example

### 阶段 3：修复后端遗留代码
- [ ] 修复 orchestrator/agent.py 第 229 行 bug
- [ ] 更新 scan_service.py（使用 orchestrator）
- [ ] 更新 scans.py API
- [ ] 更新 monitoring.py（使用 MCP Gateway）

### 阶段 4：集成 AgentStatusCard
- [ ] 在 ChatWorkspace.jsx 中导入 AgentStatusCard
- [ ] 在消息渲染中添加 AgentStatusCard
- [ ] 处理 onComplete 回调

### 阶段 5：测试验证
- [ ] 测试后端 API
- [ ] 测试所有 MCP Server
- [ ] 测试前端功能
- [ ] 测试 AgentStatusCard 显示

### 阶段 6：提交代码
- [ ] git add -A
- [ ] git commit -m "refactor: clean up legacy code and fix MCP servers"
- [ ] git push

---

## 七、确认事项

在开始执行前，请确认以下事项：

1. **是否删除所有遗留的前端页面？**
   - Dashboard, Projects, ProjectDetail, Remediation, ScanResults, Monitoring
   - 这些页面的功能已经被 ChatPage 替代

2. **scan_service.py 如何处理？**
   - 选项 A：重构为使用 orchestrator
   - 选项 B：直接删除，只保留 chat API 和 scans API

3. **monitoring.py 如何更新？**
   - 选项 A：改为使用 MCP Gateway 直接调用工具
   - 选项 B：改为使用 orchestrator 触发扫描

4. **是否现在就开始执行？**
   - 预计总时间：4 小时
   - 可以分阶段执行，每阶段完成后测试

---

**请确认以上计划，并回答上述 4 个问题，然后我将开始执行。**
