import { useState, useEffect, useRef, useCallback } from 'react'
import { Progress, Tag, Tooltip, Drawer, Button, Steps, Empty, Spin, Modal, Upload, Input, message, Form, Radio, Checkbox, Alert } from 'antd'
import {
  CheckCircleFilled,
  ClockCircleFilled,
  CloseCircleFilled,
  MinusCircleFilled,
  PlayCircleFilled,
  RocketOutlined,
  SafetyCertificateOutlined,
  FileProtectOutlined,
  BugOutlined,
  TeamOutlined,
  FileTextOutlined,
  RadarChartOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  UploadOutlined,
  InboxOutlined,
  CloseCircleOutlined as CloseOutlined,
  StopOutlined,
  ReloadOutlined,
  WarningOutlined,
  InfoCircleOutlined,
  DownOutlined,
  RightOutlined,
  LockOutlined,
  KeyOutlined,
  DatabaseOutlined,
  ClusterOutlined,
  WindowsOutlined,
  GlobalOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import './AssessmentProgress.css'

const { Step } = Steps

const TASK_TYPE_ICONS = {
  asset_discovery: <RadarChartOutlined />,
  config_check: <SettingOutlined />,
  vuln_scan: <BugOutlined />,
  pentest: <FileTextOutlined />,  // 已废弃：渗透测试改为文档审查
  doc_review: <FileTextOutlined />,
  interview: <TeamOutlined />,
  ssl_check: <LockOutlined />,
  password_scan: <KeyOutlined />,
  db_check: <DatabaseOutlined />,
  network_check: <ClusterOutlined />,
  windows_check: <WindowsOutlined />,
  web_scan: <GlobalOutlined />,
}

const PHASE_ICONS = {
  1: <SafetyCertificateOutlined />,
  2: <FileProtectOutlined />,
  3: <RadarChartOutlined />,
  4: <BugOutlined />,
  5: <SettingOutlined />,
  6: <CheckCircleFilled />,
  7: <FileTextOutlined />,
}

const STATUS_CONFIG = {
  not_started: { color: '#64748b', text: '未开始', icon: <ClockCircleFilled /> },
  in_progress: { color: '#6366f1', text: '进行中', icon: <PlayCircleFilled /> },
  paused: { color: '#f59e0b', text: '已暂停', icon: <ClockCircleFilled /> },
  completed: { color: '#10b981', text: '已完成', icon: <CheckCircleFilled /> },
  failed: { color: '#ef4444', text: '失败', icon: <CloseCircleFilled /> },
}

const PHASE_STATUS_CONFIG = {
  pending: { color: '#64748b', text: '待开始', className: 'pending' },
  active: { color: '#6366f1', text: '进行中', className: 'active' },
  completed: { color: '#10b981', text: '已完成', className: 'completed' },
  skipped: { color: '#94a3b8', text: '已跳过', className: 'skipped' },
  failed: { color: '#ef4444', text: '失败', className: 'failed' },
}

const TASK_STATUS_CONFIG = {
  todo: { color: '#64748b', text: '待办', className: 'todo' },
  in_progress: { color: '#6366f1', text: '进行中', className: 'in-progress' },
  completed: { color: '#10b981', text: '已完成', className: 'completed' },
  failed: { color: '#ef4444', text: '失败', className: 'failed' },
  cancelled: { color: '#94a3b8', text: '已取消', className: 'cancelled' },
}

function AssessmentProgress({ projectId, projectName }) {
  const [assessment, setAssessment] = useState(null)
  const [phases, setPhases] = useState([])
  const [loading, setLoading] = useState(false)
  const [drawerVisible, setDrawerVisible] = useState(false)
  const [selectedPhase, setSelectedPhase] = useState(null)
  const [tasks, setTasks] = useState([])
  const [tasksLoading, setTasksLoading] = useState(false)

  // 轮询相关
  const pollingRef = useRef(null)
  const [expandedErrors, setExpandedErrors] = useState({})

  // 文档上传弹窗
  const [uploadModalVisible, setUploadModalVisible] = useState(false)
  const [uploadTask, setUploadTask] = useState(null)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [projectLevel, setProjectLevel] = useState(null)

  // 跳过任务弹窗
  const [skipModalVisible, setSkipModalVisible] = useState(false)
  const [skipTask, setSkipTask] = useState(null)
  const [skipReason, setSkipReason] = useState('')
  const [skipping, setSkipping] = useState(false)

  // 任务执行参数弹窗
  const [executeModalVisible, setExecuteModalVisible] = useState(false)
  const [executeTask, setExecuteTask] = useState(null)
  const [executeMode, setExecuteMode] = useState('single') // 'single' | 'all'
  const [executeParams, setExecuteParams] = useState({ target: '', username: 'root', password: '', key_file: '' })
  const [projectAssets, setProjectAssets] = useState([])
  const [selectedAssets, setSelectedAssets] = useState([])
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [unifiedCredential, setUnifiedCredential] = useState(true)
  const [assetCredentials, setAssetCredentials] = useState({})

  // 完成视图
  const [completionSummary, setCompletionSummary] = useState(null)
  const [showCompletionView, setShowCompletionView] = useState(false)
  const initialStatusRef = useRef(null)
  const [expandedPhases, setExpandedPhases] = useState({})

  useEffect(() => {
    if (projectId) {
      fetchAssessment()
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
      }
    }
  }, [projectId])

  // 记录首次加载时的测评状态
  useEffect(() => {
    if (assessment?.id && initialStatusRef.current === null) {
      initialStatusRef.current = assessment.status
    }
  }, [assessment?.id, assessment?.status])

  // 只在本次会话中测评变为 completed 时才弹窗
  useEffect(() => {
    if (
      assessment?.status === 'completed' &&
      assessment?.id &&
      initialStatusRef.current !== null &&
      initialStatusRef.current !== 'completed'
    ) {
      fetchCompletionSummary(assessment.id)
      setShowCompletionView(true)
    }
  }, [assessment?.status])

  const fetchCompletionSummary = async (assessmentId) => {
    try {
      const response = await api.get(`/assessments/${assessmentId}/summary`)
      setCompletionSummary(response.data)
    } catch (error) {
      console.error('Failed to fetch completion summary:', error)
    }
  }

  const togglePhaseExpand = (phaseId) => {
    setExpandedPhases(prev => ({ ...prev, [phaseId]: !prev[phaseId] }))
  }

  const handleRestartAssessment = async () => {
    if (!assessment?.id) return
    
    Modal.confirm({
      title: '确认重新测评',
      content: '重新测评将重置所有阶段和任务，已有的测评结果将被清除。确定要继续吗？',
      okText: '确认',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await api.post(`/assessments/${assessment.id}/restart`)
          message.success('测评已重新开始')
          setShowCompletionView(false)
          fetchAssessment()
        } catch (error) {
          console.error('Failed to restart assessment:', error)
          message.error(`重新开始失败: ${error.response?.data?.detail || error.message}`)
        }
      },
    })
  }

  const handleRestartPhase = async (phaseId) => {
    Modal.confirm({
      title: '确认重新开始阶段',
      content: '重新开始将重置该阶段下所有任务，已有的结果将被清除。确定要继续吗？',
      okText: '确认',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await api.post(`/assessments/phases/${phaseId}/restart`)
          message.success('阶段已重新开始')
          fetchAssessment()
          if (selectedPhase?.id === phaseId) {
            const response = await api.get(`/assessments/phases/${phaseId}/tasks`)
            setTasks(response.data)
          }
        } catch (error) {
          console.error('Failed to restart phase:', error)
          message.error(`重新开始失败: ${error.response?.data?.detail || error.message}`)
        }
      },
    })
  }

  const handleDownloadReport = async (format) => {
    if (!assessment?.id) return
    try {
      const response = await api.get(`/assessments/${assessment.id}/report`, {
        params: { format },
        responseType: format === 'pdf' ? 'blob' : 'json',
      })
      
      if (format === 'pdf') {
        // 检查是否为错误响应
        const contentType = response.headers['content-type'] || ''
        if (!contentType.includes('application/pdf')) {
          // 尝试读取错误信息
          const text = await response.data.text()
          throw new Error(text || '报告生成失败')
        }
        
        const blob = new Blob([response.data], { type: 'application/pdf' })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `测评报告_${assessment.id}.pdf`)
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)
        message.success('PDF 报告下载成功')
      } else {
        // 检查响应是否有错误字段
        if (response.data.detail) {
          throw new Error(response.data.detail)
        }
        
        const blob = new Blob([JSON.stringify(response.data, null, 2)], { 
          type: 'application/json' 
        })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `测评报告_${assessment.id}.json`)
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)
        message.success('JSON 报告导出成功')
      }
    } catch (error) {
      console.error('Failed to download report:', error)
      message.error(`报告下载失败: ${error.message}`)
    }
  }

  // 轮询任务状态
  const startPolling = useCallback(() => {
    if (pollingRef.current) return
    
    pollingRef.current = setInterval(async () => {
      if (!selectedPhase) return
      
      try {
        // 同时刷新任务列表和测评进度（确保 phase progress 和 total progress 实时更新）
        const [tasksRes] = await Promise.all([
          api.get(`/assessments/phases/${selectedPhase.id}/tasks`),
          fetchAssessment(),
        ])
        const newTasks = tasksRes.data
        setTasks(newTasks)
        
        // 检查是否还有进行中的任务
        const hasInProgress = newTasks.some(t => t.status === 'in_progress')
        if (!hasInProgress && pollingRef.current) {
          clearInterval(pollingRef.current)
          pollingRef.current = null
        }
      } catch (error) {
        console.error('Polling error:', error)
      }
    }, 2000)
  }, [selectedPhase])

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  const fetchAssessment = async () => {
    setLoading(true)
    try {
      const response = await api.get(`/assessments/projects/${projectId}`)
      if (response.data && response.data.length > 0) {
        const latestAssessment = response.data[0]
        setAssessment(latestAssessment)
        
        const phasesResponse = await api.get(`/assessments/${latestAssessment.id}/phases`)
        setPhases(phasesResponse.data)
      } else {
        setAssessment(null)
        setPhases([])
      }
    } catch (error) {
      console.error('Failed to fetch assessment:', error)
      setAssessment(null)
      setPhases([])
    } finally {
      setLoading(false)
    }
  }

  const handlePhaseClick = async (phase) => {
    setSelectedPhase(phase)
    setDrawerVisible(true)
    setTasksLoading(true)
    
    try {
      const response = await api.get(`/assessments/phases/${phase.id}/tasks`)
      setTasks(response.data)
      
      // 如果有进行中的任务，启动轮询
      const hasInProgress = response.data.some(t => t.status === 'in_progress')
      if (hasInProgress) {
        startPolling()
      }
    } catch (error) {
      console.error('Failed to fetch tasks:', error)
      setTasks([])
    } finally {
      setTasksLoading(false)
    }
  }

  const handleStartAssessment = async () => {
    if (!assessment) return
    
    try {
      await api.post(`/assessments/${assessment.id}/start`)
      fetchAssessment()
    } catch (error) {
      console.error('Failed to start assessment:', error)
    }
  }

  const handleCompletePhase = async (phaseId) => {
    try {
      await api.post(`/assessments/phases/${phaseId}/complete`, {})
      fetchAssessment()
      if (selectedPhase && selectedPhase.id === phaseId) {
        const response = await api.get(`/assessments/phases/${phaseId}`)
        setSelectedPhase(response.data)
      }
    } catch (error) {
      console.error('Failed to complete phase:', error)
    }
  }

  const handleStartTask = async (taskId) => {
    try {
      await api.post(`/assessments/tasks/${taskId}/start`)
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
      
      // 启动轮询
      startPolling()
    } catch (error) {
      console.error('Failed to start task:', error)
      message.error(`启动任务失败: ${error.response?.data?.detail || error.message}`)
    }
  }

  // 打开任务执行参数弹窗
  const handleOpenExecute = async (task) => {
    setExecuteTask(task)
    setExecuteMode('single')
    setExecuteParams({ target: '', username: 'root', password: '', key_file: '' })
    setSelectedAssets([])
    setExecuteModalVisible(true)
    setUnifiedCredential(true)
    setAssetCredentials({})
    
    // 获取项目资产
    setAssetsLoading(true)
    try {
      const response = await api.get(`/projects/${projectId}/assets/`)
      setProjectAssets(response.data || [])
    } catch (error) {
      console.error('Failed to fetch assets:', error)
      setProjectAssets([])
    } finally {
      setAssetsLoading(false)
    }
  }

  // 提交任务执行
  const handleSubmitExecute = async () => {
    if (!executeTask) return
    
    let targets = []
    let credentials = {}
    
    if (executeMode === 'single') {
      if (!executeParams.target) {
        message.warning('请输入目标地址')
        return
      }
      targets = [executeParams.target]
      if (executeParams.username || executeParams.password || executeParams.key_file) {
        credentials[executeParams.target] = {
          username: executeParams.username,
          password: executeParams.password,
          key_file: executeParams.key_file,
        }
      }
    } else {
      if (selectedAssets.length === 0) {
        message.warning('请至少选择一个资产')
        return
      }
      targets = selectedAssets.map(id => {
        const asset = projectAssets.find(a => a.id === id)
        return asset?.value
      }).filter(Boolean)
      
      if (unifiedCredential) {
        // 统一凭据
        if (executeParams.username || executeParams.password || executeParams.key_file) {
          targets.forEach(t => {
            credentials[t] = {
              username: executeParams.username,
              password: executeParams.password,
              key_file: executeParams.key_file,
            }
          })
        }
      } else {
        // 独立凭据
        credentials = { ...assetCredentials }
      }
    }

    setExecuting(true)
    try {
      const payload = { targets: targets }
      if (Object.keys(credentials).length > 0) {
        payload.credentials = credentials
      }
      await api.post(`/assessments/tasks/${executeTask.id}/execute`, payload)
      message.success('任务已启动')
      setExecuteModalVisible(false)
      
      // 刷新任务列表并启动轮询
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
      startPolling()
    } catch (error) {
      console.error('Failed to execute task:', error)
      message.error(`执行任务失败: ${error.response?.data?.detail || error.message}`)
    } finally {
      setExecuting(false)
    }
  }

  const handleCompleteTask = async (taskId) => {
    try {
      await api.post(`/assessments/tasks/${taskId}/complete`, { result: {} })
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
      fetchAssessment()
    } catch (error) {
      console.error('Failed to complete task:', error)
    }
  }

  const handleStopTask = async (taskId) => {
    try {
      await api.post(`/assessments/tasks/${taskId}/stop`, { reason: '' })
      message.success('任务已停止')
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
    } catch (error) {
      console.error('Failed to stop task:', error)
      message.error(`停止任务失败: ${error.response?.data?.detail || error.message}`)
    }
  }

  const handleResetTask = async (taskId) => {
    try {
      await api.post(`/assessments/tasks/${taskId}/reset`)
      message.success('任务已重置')
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
    } catch (error) {
      console.error('Failed to reset task:', error)
      message.error(`重置任务失败: ${error.response?.data?.detail || error.message}`)
    }
  }

  const handleOpenUpload = async (task) => {
    setUploadTask(task)
    setUploadFile(null)
    setUploadModalVisible(true)

    try {
      const response = await api.get(`/assessments/tasks/${task.id}/project-level`)
      setProjectLevel(response.data)
    } catch (error) {
      console.error('Failed to get project level:', error)
      setProjectLevel(null)
    }
  }

  const handleSubmitUpload = async () => {
    if (!uploadFile) {
      message.warning('请先选择文件')
      return
    }
    if (!uploadTask) return

    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', uploadFile)

      const response = await api.post(
        `/assessments/tasks/${uploadTask.id}/upload`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )

      if (response.data.status === 'failed') {
        Modal.error({
          title: '定级验证失败',
          content: (
            <div>
              <p>{response.data.message || '文档验证失败'}</p>
              {response.data.validation && (
                <div style={{ marginTop: 12, padding: 12, background: 'rgba(255,77,79,0.1)', borderRadius: 4 }}>
                  <p>项目等级：<strong>{response.data.validation.project_level || '未知'}</strong></p>
                  <p>文档识别定级：<strong>{response.data.validation.document_level || '未能识别'}</strong></p>
                </div>
              )}
            </div>
          ),
        })
      } else {
        message.success(response.data.message || '文档上传成功')
        const tasksResponse = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
        setTasks(tasksResponse.data)
        fetchAssessment()
        setUploadModalVisible(false)
        setUploadFile(null)
      }
    } catch (error) {
      console.error('Upload failed:', error)
      const errMsg = error.response?.data?.detail || error.message || '上传失败'
      message.error(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg))
    } finally {
      setUploading(false)
    }
  }

  const handleOpenSkip = (task) => {
    setSkipTask(task)
    setSkipReason('')
    setSkipModalVisible(true)
  }

  const handleSubmitSkip = async () => {
    if (!skipTask) return

    setSkipping(true)
    try {
      await api.post(`/assessments/tasks/${skipTask.id}/skip`, {
        reason: skipReason,
      })
      message.success('任务已跳过')
      const tasksResponse = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(tasksResponse.data)
      fetchAssessment()
      setSkipModalVisible(false)
    } catch (error) {
      console.error('Skip failed:', error)
      message.error(error.response?.data?.detail || '跳过失败')
    } finally {
      setSkipping(false)
    }
  }

  // 切换错误详情展开
  const toggleErrorExpand = (taskId) => {
    setExpandedErrors(prev => ({ ...prev, [taskId]: !prev[taskId] }))
  }

  // 获取失败原因
  const getFailureReason = (task) => {
    if (!task.result) return '任务执行失败'
    
    // 单目标失败
    if (task.result.error) return task.result.error
    
    // 多工具执行失败
    if (task.result.failed && task.result.failed.length > 0) {
      const firstFail = task.result.failed[0]
      if (firstFail.error) return firstFail.error
      if (firstFail.capability) return `${firstFail.capability} 执行失败`
    }
    
    // 多资产执行失败
    if (task.result.asset_results) {
      const failedAssets = Object.entries(task.result.asset_results)
        .filter(([_, r]) => r.status === 'failed')
      if (failedAssets.length > 0) {
        return `${failedAssets.length} 个资产执行失败`
      }
    }
    
    return '任务执行失败'
  }

  // 渲染失败详情
  const renderFailureDetails = (task) => {
    if (!task.result) return null
    
    const details = []
    
    // 多工具执行失败
    if (task.result.failed && task.result.failed.length > 0) {
      task.result.failed.forEach((f, i) => {
        details.push({
          target: f.target || task.result.target || '未知',
          capability: f.capability || '未知工具',
          error: f.error || '未知错误',
        })
      })
    }
    
    // 多资产执行失败
    if (task.result.asset_results) {
      Object.entries(task.result.asset_results).forEach(([target, r]) => {
        if (r.status === 'failed') {
          details.push({
            target: target,
            capability: '扫描',
            error: r.error || '执行失败',
          })
        }
      })
    }
    
    // 单错误
    if (task.result.error && details.length === 0) {
      details.push({
        target: task.result.target || '未知',
        capability: '执行',
        error: task.result.error,
      })
    }
    
    if (details.length === 0) return null
    
    return (
      <div className="task-error-details">
        {details.map((d, i) => (
          <div key={i} className="error-detail-item">
            <div className="error-detail-header">
              <WarningOutlined style={{ color: '#ef4444', marginRight: 6 }} />
              <span className="error-target">{d.target}</span>
              <span className="error-capability">[{d.capability}]</span>
            </div>
            <div className="error-detail-message">{d.error}</div>
          </div>
        ))}
      </div>
    )
  }

  if (loading) {
    return (
      <div className="assessment-progress-container loading">
        <Spin size="small" />
      </div>
    )
  }

  if (!assessment) {
    return null
  }

  const statusConfig = STATUS_CONFIG[assessment.status] || STATUS_CONFIG.not_started

  return (
    <>
      <div className="assessment-progress-container">
        {/* Header */}
        <div className="assessment-header">
          <div className="assessment-title">
            <RocketOutlined className="assessment-icon" />
            <span>测评进度</span>
          </div>
          <Tag 
            color={statusConfig.color} 
            icon={statusConfig.icon}
            className="assessment-status-tag"
          >
            {statusConfig.text}
          </Tag>
        </div>

        {/* Progress Ring */}
        <div className="assessment-progress-ring">
          <Progress
            type="circle"
            percent={Math.round(assessment.progress)}
            size={80}
            strokeColor={{
              '0%': '#6366f1',
              '100%': '#8b5cf6',
            }}
            format={(percent) => (
              <div className="progress-content">
                <span className="progress-percent">{percent}%</span>
              </div>
            )}
          />
          <div className="progress-stats">
            <div className="stat-item">
              <span className="stat-value">{assessment.completed_phases}</span>
              <span className="stat-label">/ {assessment.total_phases} 阶段</span>
            </div>
          </div>
        </div>

        {/* Phase List */}
        <div className="assessment-phases">
          {phases.map((phase, index) => {
            const phaseStatus = PHASE_STATUS_CONFIG[phase.status] || PHASE_STATUS_CONFIG.pending
            const isActive = phase.status === 'active'
            const isCompleted = phase.status === 'completed'
            const isPending = phase.status === 'pending'
            const isSkipped = phase.status === 'skipped'

            return (
              <div
                key={phase.id}
                className={`phase-item ${phaseStatus.className} ${isActive ? 'active' : ''}`}
                onClick={() => handlePhaseClick(phase)}
              >
                <div className="phase-connector">
                  {index > 0 && <div className="connector-line" />}
                  <div className={`phase-dot ${phaseStatus.className}`}>
                    {isCompleted ? (
                      <CheckCircleFilled />
                    ) : isActive ? (
                      <div className="pulse-dot" />
                    ) : isSkipped ? (
                      <MinusCircleFilled style={{ color: '#94a3b8' }} />
                    ) : (
                      <div className="empty-dot" />
                    )}
                  </div>
                </div>
                <div className="phase-content">
                  <div className="phase-header">
                    <span className="phase-name">{phase.name}</span>
                    {isActive && (
                      <Tag color="#6366f1" className="phase-progress-tag">
                        {Math.round(phase.progress)}%
                      </Tag>
                    )}
                    {isCompleted && (
                      <>
                        <Tag color="#10b981" icon={<CheckCircleFilled />} className="phase-done-tag">
                          完成
                        </Tag>
                        <Button
                          type="link"
                          size="small"
                          icon={<ReloadOutlined />}
                          onClick={(e) => {
                            e.stopPropagation()
                            handleRestartPhase(phase.id)
                          }}
                          style={{ padding: '0 4px', fontSize: 11 }}
                        >
                          重新开始
                        </Button>
                      </>
                    )}
                    {isSkipped && (
                      <Tag color="#94a3b8" className="phase-skipped-tag">
                        已跳过
                      </Tag>
                    )}
                  </div>
                  {isActive && (
                    <div className="phase-progress-bar">
                      <Progress
                        percent={Math.round(phase.progress)}
                        showInfo={false}
                        strokeColor="#6366f1"
                        size="small"
                      />
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* Start Button */}
        {assessment.status === 'not_started' && (
          <Button
            type="primary"
            block
            icon={<PlayCircleFilled />}
            onClick={handleStartAssessment}
            className="start-assessment-btn"
          >
            开始测评
          </Button>
        )}

        {/* View Completion Button */}
        {assessment.status === 'completed' && (
          <Button
            type="primary"
            block
            icon={<CheckCircleFilled />}
            onClick={async () => {
              if (!completionSummary && assessment?.id) {
                await fetchCompletionSummary(assessment.id)
              }
              setShowCompletionView(true)
            }}
            className="start-assessment-btn"
            style={{ background: 'linear-gradient(135deg, #10b981, #059669)', borderColor: '#10b981' }}
          >
            查看测评结果
          </Button>
        )}
      </div>

      {/* Completion View Modal */}
      <Modal
        title={null}
        open={showCompletionView && completionSummary}
        onCancel={() => setShowCompletionView(false)}
        footer={null}
        width={720}
        className="completion-modal"
      >
        {completionSummary && (
          <div className="completion-view">
            {/* Header */}
            <div className="completion-header">
              <div className="completion-icon">
                <CheckCircleFilled />
              </div>
              <h2>测评完成</h2>
              <p className="completion-project-name">{completionSummary.project?.name}</p>
            </div>

            {/* Score Card */}
            <div className="completion-score-card">
              <div className="score-circle">
                <Progress
                  type="circle"
                  percent={completionSummary.project?.score || 0}
                  size={120}
                  strokeColor={{
                    '0%': completionSummary.project?.score >= 75 ? '#10b981' : '#f59e0b',
                    '100%': completionSummary.project?.score >= 75 ? '#059669' : '#d97706',
                  }}
                  format={(percent) => (
                    <div className="score-content">
                      <span className="score-number">{percent}</span>
                      <span className="score-unit">分</span>
                    </div>
                  )}
                />
              </div>
              <div className="score-info">
                <div className="score-grade">
                  <Tag color={
                    completionSummary.project?.grade === '优秀' ? '#10b981' :
                    completionSummary.project?.grade === '良好' ? '#6366f1' :
                    completionSummary.project?.grade === '一般' ? '#f59e0b' : '#ef4444'
                  }>
                    {completionSummary.project?.grade}
                  </Tag>
                </div>
                <div className="score-level">
                  <SafetyCertificateOutlined style={{ marginRight: 6 }} />
                  {completionSummary.project?.level || '等保'}
                </div>
              </div>
            </div>

            {/* Stats Grid */}
            <div className="completion-stats">
              <div className="stat-card">
                <div className="stat-value">{completionSummary.stats?.total_tasks || 0}</div>
                <div className="stat-label">总任务数</div>
              </div>
              <div className="stat-card success">
                <div className="stat-value">{completionSummary.stats?.completed_tasks || 0}</div>
                <div className="stat-label">已完成</div>
              </div>
              <div className="stat-card failed">
                <div className="stat-value">{completionSummary.stats?.failed_tasks || 0}</div>
                <div className="stat-label">失败</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{completionSummary.stats?.completion_rate || 0}%</div>
                <div className="stat-label">完成率</div>
              </div>
            </div>

            {/* Phase Timeline */}
            <div className="completion-phases">
              <h3>阶段完成情况</h3>
              <div className="phase-timeline">
                {completionSummary.phases?.map((phase, index) => {
                  const isExpanded = expandedPhases[phase.id]
                  
                  return (
                    <div key={phase.id} className="phase-timeline-item">
                      <div 
                        className="phase-timeline-header"
                        onClick={() => togglePhaseExpand(phase.id)}
                        style={{ cursor: 'pointer', display: 'flex', alignItems: 'flex-start', gap: 12, flex: 1 }}
                      >
                        <div className="phase-timeline-dot">
                          <CheckCircleFilled style={{ color: '#10b981' }} />
                        </div>
                        <div className="phase-timeline-content" style={{ flex: 1 }}>
                          <div className="phase-timeline-name">
                            {isExpanded ? <DownOutlined style={{ marginRight: 6, fontSize: 10 }} /> : <RightOutlined style={{ marginRight: 6, fontSize: 10 }} />}
                            {phase.name}
                          </div>
                          <div className="phase-timeline-meta">
                            {phase.completed_tasks}/{phase.total_tasks} 任务 · 分数 {phase.score}
                            {phase.completed_at && (
                              <span> · {new Date(phase.completed_at).toLocaleDateString('zh-CN')}</span>
                            )}
                          </div>
                        </div>
                      </div>
                      
                      {/* 展开的任务列表 */}
                      {isExpanded && phase.tasks && (
                        <div className="phase-timeline-tasks">
                          {phase.tasks.map((task, idx) => (
                            <div key={idx} className="task-item-mini">
                              <span className="task-name-mini">{task.name}</span>
                              <Tag 
                                color={
                                  task.status === 'completed' ? 'green' : 
                                  task.status === 'failed' ? 'red' : 
                                  task.status === 'cancelled' ? 'default' : 'blue'
                                } 
                                size="small"
                              >
                                {
                                  task.status === 'completed' ? '通过' : 
                                  task.status === 'failed' ? '失败' : 
                                  task.status === 'cancelled' ? '已跳过' : 
                                  task.status === 'todo' ? '待办' :
                                  task.status === 'in_progress' ? '进行中' : task.status
                                }
                              </Tag>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Time Info */}
            <div className="completion-time">
              {completionSummary.started_at && (
                <span>开始时间：{new Date(completionSummary.started_at).toLocaleDateString('zh-CN')}</span>
              )}
              {completionSummary.completed_at && (
                <span>完成时间：{new Date(completionSummary.completed_at).toLocaleDateString('zh-CN')}</span>
              )}
            </div>

            {/* Action Buttons */}
            <div className="completion-actions">
              <Button
                icon={<FileTextOutlined />}
                onClick={() => handleDownloadReport('pdf')}
                type="primary"
                size="large"
              >
                下载 PDF 报告
              </Button>
              <Button
                icon={<FileTextOutlined />}
                onClick={() => handleDownloadReport('json')}
                size="large"
              >
                导出 JSON
              </Button>
              <Button
                icon={<ReloadOutlined />}
                onClick={handleRestartAssessment}
                size="large"
                danger
              >
                重新测评
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Phase Detail Drawer */}
      <Drawer
        title={
          <div className="drawer-title">
            <span>{selectedPhase?.name}</span>
            <Tag color={PHASE_STATUS_CONFIG[selectedPhase?.status]?.color}>
              {PHASE_STATUS_CONFIG[selectedPhase?.status]?.text}
            </Tag>
          </div>
        }
        placement="right"
        width={420}
        onClose={() => {
          setDrawerVisible(false)
          stopPolling()
        }}
        open={drawerVisible}
        className="phase-detail-drawer"
      >
        {selectedPhase && (
          <div className="phase-detail-content">
            {/* Phase Info */}
            <div className="phase-info-card">
              <div className="info-row">
                <span className="info-label">阶段描述</span>
                <span className="info-value">{selectedPhase.description || '-'}</span>
              </div>
              <div className="info-row">
                <span className="info-label">任务进度</span>
                <span className="info-value">
                  {selectedPhase.completed_tasks} / {selectedPhase.total_tasks}
                </span>
              </div>
              <div className="info-row">
                <span className="info-label">完成时间</span>
                <span className="info-value">
                  {selectedPhase.completed_at 
                    ? new Date(selectedPhase.completed_at).toLocaleString('zh-CN')
                    : '-'
                  }
                </span>
              </div>
            </div>

            {/* Tasks List */}
            <div className="tasks-section">
              <h4>任务列表</h4>
              {tasksLoading ? (
                <div className="tasks-loading">
                  <Spin />
                </div>
              ) : tasks.length === 0 ? (
                <Empty description="暂无任务" />
              ) : (
                <div className="tasks-list">
                  {tasks.map(task => {
                    const taskStatus = TASK_STATUS_CONFIG[task.status] || TASK_STATUS_CONFIG.todo
                    const taskIcon = TASK_TYPE_ICONS[task.task_type] || <FileTextOutlined />
                    const isFailed = task.status === 'failed'
                    const isInProgress = task.status === 'in_progress'
                    const isExpanded = expandedErrors[task.id]
                    
                    return (
                      <div key={task.id} className={`task-item ${taskStatus.className}`}>
                        <div className="task-icon">
                          {isInProgress ? (
                            <Spin size="small" />
                          ) : isFailed ? (
                            <CloseCircleFilled style={{ color: '#ef4444' }} />
                          ) : task.status === 'completed' ? (
                            <CheckCircleFilled style={{ color: '#10b981' }} />
                          ) : (
                            taskIcon
                          )}
                        </div>
                        <div className="task-content">
                          <div className="task-name">{task.name}</div>
                          <div className="task-meta">
                            <Tag color={taskStatus.color} size="small">
                              {taskStatus.text}
                            </Tag>
                            {isFailed && (
                              <span 
                                className="error-toggle"
                                onClick={() => toggleErrorExpand(task.id)}
                              >
                                {isExpanded ? '收起详情' : '查看原因'}
                              </span>
                            )}
                          </div>
                          {isFailed && (
                            <div className="task-error-summary">
                              <WarningOutlined style={{ marginRight: 4 }} />
                              {getFailureReason(task)}
                            </div>
                          )}
                          {isFailed && isExpanded && renderFailureDetails(task)}
                        </div>
                        <div className="task-actions">
                          {task.status === 'todo' && (
                            <>
                              {task.task_type === 'doc_review' && (
                                <Button
                                  type="link"
                                  size="small"
                                  icon={<UploadOutlined />}
                                  onClick={() => handleOpenUpload(task)}
                                >
                                  上传文档
                                </Button>
                              )}
                              {['config_check', 'vuln_scan', 'asset_discovery', 'ssl_check', 'password_scan', 'db_check', 'network_check', 'windows_check', 'web_scan'].includes(task.task_type) && (
                                <Button
                                  type="link"
                                  size="small"
                                  icon={<PlayCircleFilled />}
                                  onClick={() => handleOpenExecute(task)}
                                >
                                  执行
                                </Button>
                              )}
                              {!['config_check', 'vuln_scan', 'asset_discovery', 'ssl_check', 'password_scan', 'db_check', 'network_check', 'windows_check', 'web_scan', 'doc_review'].includes(task.task_type) && (
                                <Button
                                  type="link"
                                  size="small"
                                  icon={<PlayCircleFilled />}
                                  onClick={() => handleStartTask(task.id)}
                                >
                                  开始
                                </Button>
                              )}
                              <Button
                                type="link"
                                size="small"
                                danger
                                onClick={() => handleOpenSkip(task)}
                              >
                                跳过
                              </Button>
                            </>
                          )}
                          {isInProgress && (
                            <>
                              {task.task_type === 'doc_review' && (
                                <Button
                                  type="link"
                                  size="small"
                                  icon={<UploadOutlined />}
                                  onClick={() => handleOpenUpload(task)}
                                >
                                  上传文档
                                </Button>
                              )}
                              <Button
                                type="link"
                                size="small"
                                icon={<CheckCircleFilled />}
                                onClick={() => handleCompleteTask(task.id)}
                              >
                                完成
                              </Button>
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
                          {task.status === 'cancelled' && (
                            <>
                              <Tag color="#94a3b8" size="small">已跳过</Tag>
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
                          {isFailed && (
                            <Button
                              type="link"
                              size="small"
                              icon={<ReloadOutlined />}
                              onClick={() => handleResetTask(task.id)}
                            >
                              重新开始
                            </Button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Complete Phase Button */}
            {selectedPhase.status === 'active' && (
              <Button
                type="primary"
                block
                icon={<CheckCircleFilled />}
                onClick={() => handleCompletePhase(selectedPhase.id)}
                className="complete-phase-btn"
              >
                完成阶段
              </Button>
            )}
          </div>
        )}
      </Drawer>

      {/* 上传文档弹窗 */}
      <Modal
        title={
          <span>
            <UploadOutlined style={{ marginRight: 8 }} />
            上传任务文档 - {uploadTask?.name}
          </span>
        }
        open={uploadModalVisible}
        onCancel={() => !uploading && setUploadModalVisible(false)}
        onOk={handleSubmitUpload}
        confirmLoading={uploading}
        okText="上传"
        cancelText="取消"
        width={600}
        destroyOnClose
      >
        {projectLevel && projectLevel.requires_level_check && (
          <div
            style={{
              padding: 12,
              marginBottom: 16,
              background: 'rgba(99, 102, 241, 0.1)',
              border: '1px solid rgba(99, 102, 241, 0.3)',
              borderRadius: 6,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              <SafetyCertificateOutlined style={{ marginRight: 6 }} />
              项目等级：<span style={{ color: '#6366f1' }}>{projectLevel.project_level}</span>
            </div>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.6)' }}>
              上传定级报告后，系统将严格验证文档中的定级信息是否与项目等级一致。
              <br />
              如果不一致，任务将被标记为失败，需要重新上传正确的报告。
            </div>
          </div>
        )}

        <Upload.Dragger
          beforeUpload={(file) => {
            setUploadFile(file)
            return false
          }}
          fileList={uploadFile ? [{ uid: '-1', name: uploadFile.name, status: 'done' }] : []}
          onRemove={() => {
            setUploadFile(null)
          }}
          accept=".pdf,.doc,.docx,.txt,.md"
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p className="ant-upload-hint">
            支持 PDF、Word、TXT、MD 格式。单个文件不超过 20MB。
          </p>
        </Upload.Dragger>

        {uploadFile && (
          <div
            style={{
              marginTop: 12,
              padding: 12,
              background: 'rgba(16, 185, 129, 0.1)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              borderRadius: 4,
              fontSize: 13,
            }}
          >
            已选择：<strong>{uploadFile.name}</strong> ({(uploadFile.size / 1024).toFixed(1)} KB)
          </div>
        )}
      </Modal>

      {/* 跳过任务弹窗 */}
      <Modal
        title={
          <span>
            <CloseOutlined style={{ marginRight: 8, color: '#f59e0b' }} />
            跳过任务 - {skipTask?.name}
          </span>
        }
        open={skipModalVisible}
        onCancel={() => !skipping && setSkipModalVisible(false)}
        onOk={handleSubmitSkip}
        confirmLoading={skipping}
        okText="确认跳过"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        width={500}
        destroyOnClose
      >
        <div style={{ marginBottom: 16, color: 'rgba(255,255,255,0.7)' }}>
          确认要跳过这个任务吗？任务将被标记为已取消。
        </div>
        <div style={{ marginBottom: 8 }}>
          <label>跳过原因（选填）：</label>
          <Input.TextArea
            rows={3}
            value={skipReason}
            onChange={(e) => setSkipReason(e.target.value)}
            placeholder="例如：此任务不适用于本项目 / 已通过其他方式完成"
            disabled={skipping}
            maxLength={500}
            showCount
          />
        </div>
      </Modal>

      {/* 任务执行参数弹窗 */}
      <Modal
        title={
          <span>
            <PlayCircleFilled style={{ marginRight: 8, color: '#6366f1' }} />
            执行任务 - {executeTask?.name}
          </span>
        }
        open={executeModalVisible}
        onCancel={() => !executing && setExecuteModalVisible(false)}
        onOk={handleSubmitExecute}
        confirmLoading={executing}
        okText="开始执行"
        cancelText="取消"
        width={600}
        destroyOnClose
      >
        <div style={{ marginBottom: 16, color: 'rgba(255,255,255,0.7)' }}>
          选择检查模式，系统将根据任务类型自动调用相应的安全工具。
        </div>
        
        <Form layout="vertical">
          <Form.Item label="检查模式">
            <Radio.Group 
              value={executeMode} 
              onChange={(e) => setExecuteMode(e.target.value)}
              disabled={executing}
            >
              <Radio.Button value="single">单项资产</Radio.Button>
              <Radio.Button value="all">全部资产</Radio.Button>
            </Radio.Group>
          </Form.Item>

          {executeMode === 'single' ? (
            <Form.Item label="目标地址" required>
              <Input
                value={executeParams.target}
                onChange={(e) => setExecuteParams({ ...executeParams, target: e.target.value })}
                placeholder="例如：192.168.1.1 或 example.com"
                disabled={executing}
              />
            </Form.Item>
          ) : (
            <Form.Item label="选择资产" required>
              {assetsLoading ? (
                <Spin size="small" />
              ) : projectAssets.length === 0 ? (
                <Alert 
                  message="暂无资产" 
                  description="请先在项目设置中添加资产" 
                  type="info" 
                  showIcon 
                />
              ) : (
                <div style={{ 
                  maxHeight: 200, 
                  overflow: 'auto',
                  border: '1px solid rgba(255,255,255,0.15)',
                  borderRadius: 6,
                  padding: '8px 12px',
                }}>
                  <Checkbox
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedAssets(projectAssets.map(a => a.id))
                      } else {
                        setSelectedAssets([])
                      }
                    }}
                    checked={selectedAssets.length === projectAssets.length && projectAssets.length > 0}
                    indeterminate={selectedAssets.length > 0 && selectedAssets.length < projectAssets.length}
                    style={{ marginBottom: 8, paddingBottom: 8, borderBottom: '1px solid rgba(255,255,255,0.1)' }}
                  >
                    全选 ({selectedAssets.length}/{projectAssets.length})
                  </Checkbox>
                  <Checkbox.Group
                    value={selectedAssets}
                    onChange={setSelectedAssets}
                    style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
                  >
                    {projectAssets.map(asset => (
                      <Checkbox key={asset.id} value={asset.id}>
                        <span style={{ color: 'rgba(255,255,255,0.85)' }}>{asset.value}</span>
                        <Tag size="small" style={{ marginLeft: 8, fontSize: 11 }}>
                          {asset.asset_type === 'ip' ? 'IP' : asset.asset_type === 'domain' ? '域名' : '云资源'}
                        </Tag>
                        {asset.name && (
                          <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: 12, marginLeft: 4 }}>
                            {asset.name}
                          </span>
                        )}
                      </Checkbox>
                    ))}
                  </Checkbox.Group>
                </div>
              )}
            </Form.Item>
          )}

          {['config_check'].includes(executeTask?.task_type) && (
            <>
              {executeMode === 'all' && (
                <Form.Item label="凭据模式">
                  <Radio.Group
                    value={unifiedCredential}
                    onChange={(e) => setUnifiedCredential(e.target.value)}
                    disabled={executing}
                  >
                    <Radio.Button value={true}>统一凭据</Radio.Button>
                    <Radio.Button value={false}>独立凭据</Radio.Button>
                  </Radio.Group>
                </Form.Item>
              )}

              {(executeMode === 'single' || unifiedCredential) ? (
                <>
                  <Form.Item label="SSH 用户名">
                    <Input
                      value={executeParams.username}
                      onChange={(e) => setExecuteParams({ ...executeParams, username: e.target.value })}
                      placeholder="默认：root"
                      disabled={executing}
                    />
                  </Form.Item>
                  <Form.Item label="SSH 密码（与密钥文件二选一）">
                    <Input.Password
                      value={executeParams.password}
                      onChange={(e) => setExecuteParams({ ...executeParams, password: e.target.value })}
                      placeholder="输入 SSH 密码"
                      disabled={executing}
                    />
                  </Form.Item>
                  <Form.Item label="SSH 密钥文件路径（与密码二选一）">
                    <Input
                      value={executeParams.key_file}
                      onChange={(e) => setExecuteParams({ ...executeParams, key_file: e.target.value })}
                      placeholder="例如：/path/to/private_key"
                      disabled={executing}
                    />
                  </Form.Item>
                </>
              ) : (
                <div style={{
                  maxHeight: 250,
                  overflow: 'auto',
                  border: '1px solid rgba(255,255,255,0.15)',
                  borderRadius: 6,
                  padding: '8px 12px',
                }}>
                  {projectAssets
                    .filter(a => selectedAssets.includes(a.id) && a.asset_type === 'ip')
                    .map(asset => {
                      const cred = assetCredentials[asset.value] || {}
                      const updateCred = (field, value) => {
                        setAssetCredentials(prev => ({
                          ...prev,
                          [asset.value]: { ...cred, [field]: value },
                        }))
                      }
                      return (
                        <div key={asset.id} style={{
                          marginBottom: 12,
                          padding: '8px 10px',
                          background: 'rgba(255,255,255,0.04)',
                          borderRadius: 6,
                          border: '1px solid rgba(255,255,255,0.08)',
                        }}>
                          <div style={{ fontWeight: 500, marginBottom: 6, fontSize: 13, color: 'rgba(255,255,255,0.85)' }}>
                            {asset.value}
                            {asset.name && <span style={{ color: 'rgba(255,255,255,0.5)', fontWeight: 400, marginLeft: 6 }}>{asset.name}</span>}
                          </div>
                          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                            <Input
                              size="small"
                              placeholder="用户名"
                              value={cred.username || ''}
                              onChange={(e) => updateCred('username', e.target.value)}
                              style={{ width: 120 }}
                              disabled={executing}
                            />
                            <Input.Password
                              size="small"
                              placeholder="密码"
                              value={cred.password || ''}
                              onChange={(e) => updateCred('password', e.target.value)}
                              style={{ width: 140 }}
                              disabled={executing}
                            />
                            <Input
                              size="small"
                              placeholder="密钥路径"
                              value={cred.key_file || ''}
                              onChange={(e) => updateCred('key_file', e.target.value)}
                              style={{ flex: 1, minWidth: 140 }}
                              disabled={executing}
                            />
                          </div>
                        </div>
                      )
                    })}
                  {projectAssets.filter(a => selectedAssets.includes(a.id) && a.asset_type === 'ip').length === 0 && (
                    <div style={{ color: 'rgba(255,255,255,0.4)', textAlign: 'center', padding: 12 }}>
                      选中的资产中没有 IP 类型，无需凭据
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </Form>
      </Modal>
    </>
  )
}

export default AssessmentProgress
