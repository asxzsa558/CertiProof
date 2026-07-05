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
  maxAttempts = 120,
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
    taskCompleted: true,
    taskStatus: 'timeout',
  }))
  setMessages(prev => [...prev, {
    role: 'assistant',
    content: '任务执行超时，请稍后再试。',
    isError: true,
  }])
}

export {
  createTaskResultMessage,
  hasAssetResults,
  pollTaskResultUntilDone,
  updateTaskMessage,
}
