# 修复快捷按钮和测评完成相关问题

## 问题概述

### 问题 A：快捷按钮状态值不一致（当前发现）

**现象：**
- 汇总显示"成功 1，失败 3"
- 但所有 4 个结果都显示 ✗（包括成功的 127.0.0.1）
- 127.0.0.1 显示"未知错误"
- AI 无法理解结果，返回"抱歉，我暂时无法理解你的需求"

**根因：**
Skill 返回 `status: "completed"` 表示成功，但 Orchestrator 多处检查 `status == "success"` 判断成功。

**涉及代码位置：**

| 文件 | 行号 | 问题 |
|------|------|------|
| `backend/app/orchestrator/skill.py` | 99 | 返回 `status: "completed"` |
| `backend/app/orchestrator/orchestrator.py` | 346 | 汇总用 `status == "completed"` ✓ |
| `backend/app/orchestrator/orchestrator.py` | 863 | `_summarize_execution_result` 用 `status != "success"` ✗ |
| `backend/app/orchestrator/orchestrator.py` | 941 | `_generate_fallback_description` 用 `status != "success"` ✗ |
| `backend/app/orchestrator/orchestrator.py` | 1116 | `_extract_scan_results_from_execution` 用 `status == "success"` ✗ |

**修复方案：**
统一支持 `"success"` 和 `"completed"` 两种成功状态：
```python
# 修改前
if status != "success":
if status == "success":

# 修改后
if status not in ["success", "completed"]:
if status in ["success", "completed"]:
```

**额外修复：**
- 添加 `redis_check` 的结果处理逻辑到 `_generate_fallback_description`

---

### 问题 B：PDF/JSON 报告无法打开

**现象：** 下载报告后无法打开

**根因：**
1. PDF Blob 没有指定 MIME type
2. 没有检查响应是否为错误

**修复：**
```javascript
// PDF 下载
const blob = new Blob([response.data], { type: 'application/pdf' })

// 检查响应类型
const contentType = response.headers['content-type']
if (!contentType.includes('application/pdf')) {
  message.error('报告生成失败')
  return
}
```

---

### 问题 C：阶段完成情况不支持展开

**现象：** 完成视图只显示阶段名称，无法查看详细信息

**修复：**

**后端** - `/assessments/{id}/summary` 每个 phase 增加：
```python
{
    "id": p.id,
    "name": p.name,
    "status": p.status,
    "order": p.order,
    "total_tasks": p.total_tasks,
    "completed_tasks": p.completed_tasks,
    "completed_at": ...,
    # 新增
    "tasks": [
        {
            "name": task.name,
            "type": task.task_type,
            "status": task.status,
            "result_summary": "简要结果描述"
        }
    ],
    "score": 80.0  # 阶段分数
}
```

**前端** - phase-timeline-item 添加：
- 点击展开/折叠
- 展开后显示任务列表和分数
- 箭头旋转动画

---

### 问题 D：测评完成后无法重新开始

**现象：** 没有重新开始按钮

**根因：** 状态机中 `completed` 是终态，没有转出路径

**修复：**

**1. 扩展状态机** - `flow_engine.py`：
```python
class StateMachine:
    ASSESSMENT_TRANSITIONS = {
        "not_started": ["in_progress"],
        "in_progress": ["paused", "completed", "failed"],
        "paused": ["in_progress"],
        "completed": ["not_started"],  # 新增：允许重置
        "failed": ["in_progress"],
    }
    
    PHASE_TRANSITIONS = {
        "pending": ["active", "skipped"],
        "active": ["completed", "failed"],
        "completed": ["pending"],  # 新增：允许重置
        "skipped": ["pending"],
        "failed": ["active"],
    }
    
    TASK_TRANSITIONS = {
        "todo": ["in_progress", "cancelled"],
        "in_progress": ["completed", "failed"],
        "completed": ["todo"],  # 新增：允许重置
        "failed": ["in_progress"],
        "cancelled": ["todo"],
    }
```

**2. 新增方法** - `FlowEngine`：
```python
async def restart_assessment(self, assessment_id: int):
    """重置整个测评"""
    # 1. 重置所有任务为 todo
    # 2. 重置所有阶段为 pending
    # 3. 重置测评为 not_started
    
async def restart_phase(self, phase_id: int):
    """重置单个阶段"""
    # 1. 重置阶段内所有任务为 todo
    # 2. 重置阶段为 pending
    # 3. 重新计算测评进度
```

**3. 新增 API**：
- `POST /assessments/{id}/restart`
- `POST /assessments/phases/{id}/restart`

**4. 前端按钮**：
- 完成视图添加"重新测评"按钮
- 阶段列表添加"重新开始"按钮

---

### 问题 E：每次刷新都弹出完成窗口

**现象：** 测评完成后每次刷新页面都自动弹出完成视图

**根因：** `useEffect` 监听 `assessment?.status`，只要 status 是 `'completed'` 就自动弹窗

**修复：** 用 `useRef` 追踪上一次状态，只在状态**变化时**弹窗：
```javascript
const prevStatusRef = useRef(null)

useEffect(() => {
  if (
    assessment?.status === 'completed' &&
    assessment?.id &&
    prevStatusRef.current !== 'completed'  // 只在状态变化时弹窗
  ) {
    fetchCompletionSummary(assessment.id)
    setShowCompletionView(true)
  }
  prevStatusRef.current = assessment?.status
}, [assessment?.status, assessment?.id])
```

---

## 实施顺序

1. **问题 A**：修复状态值不一致（最紧急，影响所有快捷按钮）
2. **问题 E**：修复完成窗口自动弹出（影响用户体验）
3. **问题 B**：修复报告下载（功能修复）
4. **问题 C**：添加阶段展开功能（功能增强）
5. **问题 D**：添加重新开始功能（功能增强）

---

## 测试计划

### 问题 A 测试
1. 使用快捷按钮执行数据库检测
2. 验证成功结果显示 ✓，失败结果显示 ✗
3. 验证汇总计数与显示一致
4. 验证 AI 能正确理解结果

### 问题 B 测试
1. 点击"下载 PDF 报告"，验证文件可打开
2. 点击"导出 JSON"，验证文件可打开
3. 模拟后端错误，验证前端正确提示

### 问题 C 测试
1. 完成测评后查看完成视图
2. 点击阶段名称展开详情
3. 验证显示任务列表和分数
4. 点击折叠，验证动画效果

### 问题 D 测试
1. 完成测评后点击"重新测评"
2. 验证所有阶段重置为待开始
3. 验证可以重新执行任务
4. 测试单个阶段重新开始

### 问题 E 测试
1. 完成测评后刷新页面
2. 验证不会自动弹出完成视图
3. 点击"查看测评结果"按钮
4. 验证手动打开完成视图正常
