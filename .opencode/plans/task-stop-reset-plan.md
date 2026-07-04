# 任务停止和重新开始功能实现计划

## 需求
用户要求：测评进度的每个阶段都应该提供停止能力，可以停止阶段内的任务并重新开始。

## 当前状态
- 后端已有 `skip_task` 方法（将任务标记为 cancelled）
- 后端缺少 `stop_task` 方法（将 in_progress 任务标记为 failed）
- 后端缺少 `reset_task` 方法（将 failed/cancelled 任务重置为 todo）
- 前端缺少停止和重新开始按钮

## 实现计划

### 1. 后端：添加 stop_task 和 reset_task 方法

**文件**: `backend/app/services/flow_engine.py`

在 `skip_task` 方法后添加两个新方法：

```python
async def stop_task(self, task_id: int, reason: str = "") -> TaskInstance:
    """
    停止任务（将 in_progress 状态的任务标记为 failed）
    """
    task = await self.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    # 任务只能从 in_progress 状态停止
    if task.status != "in_progress":
        raise ValueError(f"Cannot stop task with status {task.status}")

    task.status = "failed"
    task.completed_at = datetime.utcnow()
    if reason:
        existing = task.result or {}
        existing["stop_reason"] = reason
        task.result = existing

    await self.db.commit()

    phase = await self.get_phase(task.phase_id)
    await self.emit_event(phase.assessment_id, "task_stopped", {"task_id": task_id, "reason": reason})

    logger.info(f"Task {task_id} stopped with reason: {reason}")
    return task

async def reset_task(self, task_id: int) -> TaskInstance:
    """
    重置任务（将 failed/cancelled 状态的任务重置为 todo）
    """
    task = await self.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    # 任务只能从 failed 或 cancelled 状态重置
    if task.status not in ("failed", "cancelled"):
        raise ValueError(f"Cannot reset task with status {task.status}")

    task.status = "todo"
    task.started_at = None
    task.completed_at = None
    task.result = None

    # 更新阶段进度
    phase = await self.get_phase(task.phase_id)
    phase.completed_tasks -= 1
    phase.progress = (phase.completed_tasks / phase.total_tasks * 100) if phase.total_tasks > 0 else 0

    await self.db.commit()

    await self.emit_event(phase.assessment_id, "task_reset", {"task_id": task_id})

    logger.info(f"Task {task_id} reset to todo")
    return task
```

### 2. 后端：添加 API 端点

**文件**: `backend/app/api/assessments.py`

在 `skip_task` 端点后添加两个新端点：

```python
@router.post("/tasks/{task_id}/stop")
async def stop_task(
    task_id: int,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停止任务"""
    engine = get_flow_engine(db)
    
    try:
        task = await engine.stop_task(task_id, reason)
        return {
            "message": "任务已停止",
            "task_id": task.id,
            "status": task.status
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tasks/{task_id}/reset")
async def reset_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重置任务（将 failed/cancelled 状态的任务重置为 todo）"""
    engine = get_flow_engine(db)
    
    try:
        task = await engine.reset_task(task_id)
        return {
            "message": "任务已重置",
            "task_id": task.id,
            "status": task.status
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### 3. 前端：添加停止和重新开始按钮

**文件**: `frontend/src/components/AssessmentProgress.jsx`

在任务列表中添加停止和重新开始按钮：

```jsx
<div className="task-actions">
  {task.status === 'todo' && (
    <>
      {/* 现有的上传文档、执行、开始、跳过按钮 */}
    </>
  )}
  {task.status === 'in_progress' && (
    <>
      <Button
        type="link"
        size="small"
        danger
        icon={<StopOutlined />}
        onClick={() => handleStopTask(task.id)}
      >
        停止
      </Button>
    </>
  )}
  {(task.status === 'failed' || task.status === 'cancelled') && (
    <>
      <Button
        type="link"
        size="small"
        icon={<ReloadOutlined />}
        onClick={() => handleResetTask(task.id)}
      >
        重新开始
      </Button>
    </>
  )}
</div>
```

添加处理函数：

```jsx
const handleStopTask = async (taskId) => {
  try {
    await api.post(`/assessments/tasks/${taskId}/stop`)
    message.success('任务已停止')
    // 刷新任务列表
    const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
    setTasks(response.data)
  } catch (error) {
    message.error(`停止任务失败: ${error.response?.data?.detail || error.message}`)
  }
}

const handleResetTask = async (taskId) => {
  try {
    await api.post(`/assessments/tasks/${taskId}/reset`)
    message.success('任务已重置')
    // 刷新任务列表
    const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
    setTasks(response.data)
  } catch (error) {
    message.error(`重置任务失败: ${error.response?.data?.detail || error.message}`)
  }
}
```

## 执行步骤

1. 修改 `backend/app/services/flow_engine.py`，添加 `stop_task` 和 `reset_task` 方法
2. 修改 `backend/app/api/assessments.py`，添加 `/stop` 和 `/reset` API 端点
3. 修改 `frontend/src/components/AssessmentProgress.jsx`，添加停止和重新开始按钮
4. 重新构建后端和前端服务
5. 测试功能

## 测试场景

1. 启动一个任务（如"安全区域边界检查"）
2. 点击"停止"按钮，任务状态变为"失败"
3. 点击"重新开始"按钮，任务状态变为"待办"
4. 再次点击"执行"按钮，任务重新开始执行
