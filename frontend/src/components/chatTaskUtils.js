const hasAssetResults = (scanResults = {}) => (
  scanResults.asset_results && Object.keys(scanResults.asset_results).length > 0
)

const createTaskResultMessage = ({ resultDescription, scanResults = {}, isMultiAsset }) => ({
  role: 'assistant',
  content: resultDescription || '任务执行完成',
  isResult: true,
  scanResults,
  isMultiAsset: Boolean(isMultiAsset || hasAssetResults(scanResults)),
})

const updateTaskMessage = (messages, taskId, patch) => (
  messages.map(msg => (msg.taskId === taskId ? { ...msg, ...patch } : msg))
)

const pollTaskResultUntilDone = async ({
  api,
  taskId,
  setMessages,
  completedTaskIdsRef,
  pollRef,
  maxAttempts = 900,
  interval = 2000,
}) => {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const response = await api.get(`/chat/result/${taskId}`)
      const data = response.data

      if (data.current_step || data.step_progress) {
        setMessages(prev => updateTaskMessage(prev, taskId, {
          currentStep: data.current_step,
          stepProgress: data.step_progress,
        }))
      }

      if (data.status === 'completed' || data.status === 'failed') {
        if (completedTaskIdsRef.current.has(taskId)) return
        completedTaskIdsRef.current.add(taskId)
        setMessages(prev => updateTaskMessage(prev, taskId, {
          taskCompleted: true,
          taskStatus: data.status,
        }))
        setMessages(prev => [...prev, createTaskResultMessage({
          resultDescription: data.result_description,
          scanResults: data.scan_results || {},
        })])
        return
      }

      await new Promise(resolve => {
        pollRef.current = setTimeout(resolve, interval)
      })
    } catch (error) {
      console.error('Poll error:', error)
      await new Promise(resolve => {
        pollRef.current = setTimeout(resolve, interval)
      })
    }
  }

  setMessages(prev => updateTaskMessage(prev, taskId, {
    taskCompleted: false,
    taskStatus: 'running',
    currentStep: '任务仍在后台执行，可稍后刷新或查看历史结果。',
  }))
  setMessages(prev => [...prev, {
    role: 'assistant',
    content: '任务仍在后台执行，漏洞扫描、弱口令、SSL 等长任务可能需要更久。你可以继续发送其他指令，稍后刷新或查看结果库。',
  }])
}

export {
  createTaskResultMessage,
  hasAssetResults,
  pollTaskResultUntilDone,
  updateTaskMessage,
}
