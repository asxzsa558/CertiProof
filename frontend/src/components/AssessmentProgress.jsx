import { Fragment, useState, useEffect, useRef, useCallback } from 'react'
import { Progress, Tag, Tooltip, Drawer, Button, Steps, Empty, Spin, Modal, Upload, Input, message, Form, Radio, Checkbox, Alert } from 'antd'
import {
  CheckCircleFilled,
  ClockCircleFilled,
  CloseCircleFilled,
  PlayCircleFilled,
  RocketOutlined,
  SafetyCertificateOutlined,
  FileProtectOutlined,
  BugOutlined,
  TeamOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
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
  ToolOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import VerificationWorkspace from './VerificationWorkspace'
import './AssessmentProgress.css'

const { Step } = Steps

const TASK_TYPE_ICONS = {
  asset_discovery: <RadarChartOutlined />,
  high_risk_port_scan: <RadarChartOutlined />,
  basic_vulnerability_scan: <BugOutlined />,
  basic_baseline_check: <SettingOutlined />,
  basic_weak_password_scan: <KeyOutlined />,
  basic_ssl_tls_scan: <LockOutlined />,
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
  full_compliance_scan: <SafetyCertificateOutlined />,
  full_asset_assessment: <SafetyCertificateOutlined />,
  web_vulnerability_assessment: <GlobalOutlined />,
  directory_discovery_assessment: <GlobalOutlined />,
  web_fuzz_assessment: <GlobalOutlined />,
  sql_injection_assessment: <DatabaseOutlined />,
  database_security_assessment: <DatabaseOutlined />,
  network_device_assessment: <ClusterOutlined />,
  windows_ad_smb_assessment: <WindowsOutlined />,
  ssh_baseline_assessment: <SettingOutlined />,
  remediation: <ToolOutlined />,
  retest: <CheckCircleFilled />,
  html_report: <FileTextOutlined />,
}

const EXECUTABLE_TASK_TYPES = [
  'asset_discovery',
  'high_risk_port_scan',
  'basic_vulnerability_scan',
  'basic_baseline_check',
  'basic_weak_password_scan',
  'basic_ssl_tls_scan',
  'config_check',
  'vuln_scan',
  'ssl_check',
  'password_scan',
  'db_check',
  'network_check',
  'windows_check',
  'web_scan',
  'full_compliance_scan',
  'full_asset_assessment',
  'web_vulnerability_assessment',
  'directory_discovery_assessment',
  'web_fuzz_assessment',
  'sql_injection_assessment',
  'database_security_assessment',
  'network_device_assessment',
  'windows_ad_smb_assessment',
  'ssh_baseline_assessment',
]

const GAP_TECH_BATCH_TYPE = 'gap_technical_batch'
const SSH_CREDENTIAL_TASK_TYPES = ['config_check', 'basic_baseline_check', 'ssh_baseline_assessment', GAP_TECH_BATCH_TYPE]
const BASIC_TECHNICAL_TASK_TYPES = new Set([
  'high_risk_port_scan',
  'basic_vulnerability_scan',
  'basic_baseline_check',
  'basic_weak_password_scan',
  'basic_ssl_tls_scan',
])

const DOCUMENT_PIPELINE_STAGES = [
  ['native_extraction', '内容提取'],
  ['fusion', '视觉补充与融合'],
  ['retrieval', '标准检索'],
  ['judging', '模型判证'],
  ['generating_results', '规则汇总'],
  ['completed', '生成结果'],
]

const BATCH_DOCUMENT_STAGES = [
  ['native_extraction', '内容提取'],
  ['classification', '混合归类'],
  ['analyzing', '子项排队'],
  ['completed', '提交分析'],
]

function DocumentPipelineProgress({ progress = {}, batch = false }) {
  const stages = batch ? BATCH_DOCUMENT_STAGES : DOCUMENT_PIPELINE_STAGES
  const currentStage = progress.stage || stages[0][0]
  const currentIndex = Math.max(0, stages.findIndex(([key]) => key === currentStage))
  const completed = currentStage === 'completed'
  const failed = currentStage === 'failed'

  return (
    <div className="document-pipeline-progress">
      <div className="document-pipeline-stages">
        {stages.map(([key, label], index) => (
          <span
            key={key}
            className={completed || index < currentIndex ? 'done' : index === currentIndex ? (failed ? 'failed' : 'active') : ''}
          >
            <i />{label}
          </span>
        ))}
      </div>
      <div className="document-pipeline-message">
        <span>{progress.message || '等待文档分析'}</span>
        <em>{progress.percent || 0}%</em>
      </div>
    </div>
  )
}

const PHASE_ICONS = {
  1: <SafetyCertificateOutlined />,
  2: <FileProtectOutlined />,
  3: <RadarChartOutlined />,
  4: <BugOutlined />,
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
  failed: { color: '#ef4444', text: '失败', className: 'failed' },
}

const TASK_STATUS_CONFIG = {
  todo: { color: '#64748b', text: '待办', className: 'todo' },
  in_progress: { color: '#6366f1', text: '进行中', className: 'in-progress' },
  completed: { color: '#10b981', text: '已完成', className: 'completed' },
  failed: { color: '#ef4444', text: '失败', className: 'failed' },
  cancelled: { color: '#94a3b8', text: '已取消', className: 'cancelled' },
}

const COMPLETION_STATE_CONFIG = {
  all_fixed: { title: '本轮测评已完成', label: '全部问题已修复', color: 'success', tone: 'success' },
  coverage_limited: { title: '本轮测评已完成', label: '存在无法验证项', color: 'error', tone: 'warning' },
  needs_remediation: { title: '本轮测评已完成', label: '仍有待整改问题', color: 'error', tone: 'warning' },
}

const VERIFICATION_RUN_STATUS = {
  completed: '已完成', partial: '部分完成', failed: '失败', cancelled: '已停止',
  queued: '排队中', running: '执行中', paused: '已暂停',
}
const keepIfUnchanged = (previous, next) => JSON.stringify(previous) === JSON.stringify(next) ? previous : next

function AssessmentProgress({ projectId, projectName, variant = 'default', openIssues }) {
  const [assessment, setAssessment] = useState(null)
  const [phases, setPhases] = useState([])
  const [loading, setLoading] = useState(false)
  const [drawerVisible, setDrawerVisible] = useState(false)
  const [selectedPhase, setSelectedPhase] = useState(null)
  const [tasks, setTasks] = useState([])
  const [tasksLoading, setTasksLoading] = useState(false)

  // 轮询相关
  const pollingRef = useRef(null)
  const pollingPhaseIdRef = useRef(null)
  const openingAssessmentRef = useRef(false)
  const [expandedErrors, setExpandedErrors] = useState({})

  // 文档上传弹窗
  const [uploadModalVisible, setUploadModalVisible] = useState(false)
  const [uploadTask, setUploadTask] = useState(null)
  const [uploadFiles, setUploadFiles] = useState([])
  const [taskDocuments, setTaskDocuments] = useState([])
  const [uploadAnalysisMode, setUploadAnalysisMode] = useState('default')
  const [uploading, setUploading] = useState(false)
  const [projectLevel, setProjectLevel] = useState(null)
  const [batchUploadMode, setBatchUploadMode] = useState(false)
  const [batchDocumentRun, setBatchDocumentRun] = useState(null)
  const batchPollingRef = useRef(null)

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
      if (batchPollingRef.current) {
        clearInterval(batchPollingRef.current)
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

  const handleRestartAssessment = async (mode = 'reset') => {
    if (!assessment?.id) return
    const reset = mode === 'reset'
    
    Modal.confirm({
      title: reset ? '确认完全重置测评' : '继续整改或补充材料',
      content: reset
        ? '此操作不可恢复。系统将停止当前任务，并永久删除本项目的测评进度、文档与解析数据、技术检测结果、问题证据、整改复测记录、变更快照和历史报告。项目、资产、成员权限、标准库及审计日志不会删除。'
        : '测评将恢复为可编辑状态，可上传改进后的文档或重新执行技术检测；已有结果、证据和处置记录都会保留。',
      okText: reset ? '完全重置' : '恢复可编辑',
      cancelText: '取消',
      okButtonProps: reset ? { danger: true } : undefined,
      onOk: async () => {
        try {
          const response = await api.post(`/assessments/${assessment.id}/restart`, { mode })
          const cleanup = response.data?.cleanup || {}
          const deletedRecords = Number(cleanup.scan_tasks || 0)
            + Number(cleanup.findings || 0)
            + Number(cleanup.evidences || 0)
            + Number(cleanup.document_files || 0)
            + Number(cleanup.document_runs || 0)
            + Number(cleanup.reports || 0)
            + Number(cleanup.change_snapshots || 0)
          const releasedSize = cleanup.released_file_bytes >= 1024 * 1024
            ? `${(cleanup.released_file_bytes / 1024 / 1024).toFixed(1)} MB`
            : `${(Number(cleanup.released_file_bytes || 0) / 1024).toFixed(1)} KB`
          message.success(reset
            ? `测评已完全重置，清理 ${deletedRecords} 条测评数据、${cleanup.deleted_file_count || 0} 个文件，释放 ${releasedSize}`
            : '测评已恢复为可编辑状态')
          window.dispatchEvent(new CustomEvent('certiproof:assessment-reset', {
            detail: { projectId, assessmentId: assessment.id, mode },
          }))
          setShowCompletionView(false)
          fetchAssessment()
        } catch (error) {
          console.error('Failed to restart assessment:', error)
          message.error(`${reset ? '完全重置' : '继续测评'}失败: ${error.response?.data?.detail || error.message}`)
        }
      },
    })
  }

  const handleRestartPhase = async (phaseId, mode = 'reset') => {
    const reset = mode === 'reset'
    Modal.confirm({
      title: reset ? '确认重置当前阶段' : '继续阶段',
      content: reset
        ? '将清空该阶段下所有任务进度和任务结果，其他阶段不受影响。'
        : '将重新打开该阶段以便补充材料，已有任务结果和证据都会保留。',
      okText: reset ? '重置阶段' : '继续',
      cancelText: '取消',
      okButtonProps: reset ? { danger: true } : undefined,
      onOk: async () => {
        try {
          await api.post(`/assessments/phases/${phaseId}/restart`, { mode })
          message.success(reset ? '阶段进度已重置' : '阶段已重新打开')
          fetchAssessment()
          if (selectedPhase?.id === phaseId) {
            const response = await api.get(`/assessments/phases/${phaseId}/tasks`)
            setTasks(response.data)
          }
        } catch (error) {
          console.error('Failed to restart phase:', error)
          message.error(`${reset ? '重置阶段' : '继续阶段'}失败: ${error.response?.data?.detail || error.message}`)
        }
      },
    })
  }

  const handleDownloadReport = async (format) => {
    if (!assessment?.id) return
    try {
      const response = await api.get(`/assessments/${assessment.id}/report`, {
        params: { format },
        responseType: format === 'json' ? 'json' : 'blob',
      })
      
      if (format === 'html') {
        const blob = new Blob([response.data], { type: 'text/html;charset=utf-8' })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `测评报告_${assessment.id}.html`)
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)
        message.success('HTML 报告下载成功')
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
  const startPolling = useCallback((phaseId) => {
    const activePhaseId = phaseId || selectedPhase?.id
    if (!activePhaseId) return
    if (pollingRef.current && pollingPhaseIdRef.current === activePhaseId) return
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
    pollingPhaseIdRef.current = activePhaseId

    const pollTasks = async () => {
      try {
        // 同时刷新任务列表和测评进度（确保 phase progress 和 total progress 实时更新）
        const [tasksRes] = await Promise.all([
          api.get(`/assessments/phases/${activePhaseId}/tasks`),
          fetchAssessment({ silent: true }),
        ])
        const newTasks = tasksRes.data
        setTasks(previous => keepIfUnchanged(previous, newTasks))
        
        // 检查是否还有进行中的任务
        const hasInProgress = newTasks.some(t => t.status === 'in_progress')
        if (!hasInProgress && pollingRef.current) {
          clearInterval(pollingRef.current)
          pollingRef.current = null
          pollingPhaseIdRef.current = null
        }
      } catch (error) {
        console.error('Polling error:', error)
      }
    }

    pollTasks()
    pollingRef.current = setInterval(pollTasks, 2000)
  }, [selectedPhase])

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
      pollingPhaseIdRef.current = null
    }
  }, [])

  const fetchAssessment = useCallback(async (options = {}) => {
    const silent = options.silent === true
    if (!silent) setLoading(true)
    try {
      const response = await api.get(`/assessments/projects/${projectId}`)
      if (response.data && response.data.length > 0) {
        const latestAssessment = response.data[0]
        setAssessment(previous => keepIfUnchanged(previous, latestAssessment))
        
        const phasesResponse = await api.get(`/assessments/${latestAssessment.id}/phases`)
        setPhases(previous => keepIfUnchanged(previous, phasesResponse.data))
        return { assessment: latestAssessment, phases: phasesResponse.data }
      } else {
        setAssessment(null)
        setPhases([])
        return null
      }
    } catch (error) {
      console.error('Failed to fetch assessment:', error)
      setAssessment(null)
      setPhases([])
      return null
    } finally {
      if (!silent) setLoading(false)
    }
  }, [projectId])

  const shouldRefreshAssessment = assessment?.status === 'in_progress'
    || phases.some(phase => phase.status === 'active')

  useEffect(() => {
    if (!projectId || !shouldRefreshAssessment) return undefined
    const timer = window.setInterval(() => fetchAssessment({ silent: true }), 5000)
    return () => window.clearInterval(timer)
  }, [projectId, shouldRefreshAssessment, fetchAssessment])

  const startBatchPolling = (runId, phaseId, notify = false) => {
    if (!runId || !phaseId) return
    if (batchPollingRef.current) clearInterval(batchPollingRef.current)
    const poll = async () => {
      try {
        const response = await api.get(`/assessments/document-runs/${runId}`)
        const run = response.data
        setBatchDocumentRun(run)
        if (['completed', 'failed', 'cancelled'].includes(run.status)) {
          clearInterval(batchPollingRef.current)
          batchPollingRef.current = null
          const tasksResponse = await api.get(`/assessments/phases/${phaseId}/tasks`)
          setTasks(tasksResponse.data)
          fetchAssessment({ silent: true })
          if (tasksResponse.data.some(task => task.status === 'in_progress')) startPolling(phaseId)
          if (notify) {
            if (run.status === 'completed') {
              const count = run.result?.classified?.length || 0
              const unresolved = run.result?.unclassified?.length || 0
              message.success(`已归类 ${count} 个文档${unresolved ? `，${unresolved} 个需调整文件名或内容` : ''}`)
            } else if (run.status === 'cancelled') {
              message.info('批量文档归类已停止')
            } else {
              message.error(run.error || '批量文档归类失败')
            }
          }
        }
      } catch (error) {
        console.error('Batch document polling failed:', error)
      }
    }
    poll()
    batchPollingRef.current = setInterval(poll, 2000)
  }

  const handlePhaseClick = async (phase) => {
    setSelectedPhase(phase)
    setDrawerVisible(true)
    setTasksLoading(true)
    
    try {
      const [response, latestBatchResponse] = await Promise.all([
        api.get(`/assessments/phases/${phase.id}/tasks`),
        ['gap_analysis', 'remediation_verification'].includes(phase.phase_id)
          ? api.get(`/assessments/phases/${phase.id}/documents/batch/latest`)
          : Promise.resolve({ data: null }),
      ])
      setTasks(response.data)
      setBatchDocumentRun(latestBatchResponse.data)
      if (latestBatchResponse.data && ['queued', 'pending', 'running'].includes(latestBatchResponse.data.status)) {
        startBatchPolling(latestBatchResponse.data.id, phase.id)
      }
      
      // 如果有进行中的任务，启动轮询
      const hasInProgress = response.data.some(t => t.status === 'in_progress')
      if (hasInProgress) {
        startPolling(phase.id)
      }
    } catch (error) {
      console.error('Failed to fetch tasks:', error)
      setTasks([])
    } finally {
      setTasksLoading(false)
    }
  }

  const handleOpenAssessment = async () => {
    if (openingAssessmentRef.current) return
    openingAssessmentRef.current = true
    let current = await fetchAssessment()
    try {
      if (!current) {
        const projectResponse = await api.get(`/projects/${projectId}`)
        const project = projectResponse.data
        const targetLevel = project.compliance_level === '二级' ? 2 : 3
        const templatesResponse = await api.get('/assessments/templates')
        const template = templatesResponse.data.find(item => item.compliance_level === targetLevel)
        if (!template) throw new Error('未找到匹配的测评模板')

        const created = await api.post(`/assessments/projects/${projectId}`, {
          template_id: template.id,
          name: `${projectName || project.name} - 等保${project.compliance_level}测评`,
        })
        const phasesResponse = await api.get(`/assessments/${created.data.id}/phases`)
        current = { assessment: created.data, phases: phasesResponse.data }
        setAssessment(current.assessment)
        setPhases(current.phases)
        message.success('测评流程已创建')
      }

      const phase = current.phases.find(item => item.status === 'active') || current.phases.find(item => item.status === 'pending') || current.phases[0]
      if (phase) await handlePhaseClick(phase)
    } catch (error) {
      console.error('Failed to open assessment:', error)
      message.error(error.response?.data?.detail || error.message || '打开测评失败')
    } finally {
      openingAssessmentRef.current = false
    }
  }

  useEffect(() => {
    const openAssessment = (event) => {
      if (event.detail?.projectId === projectId) handleOpenAssessment()
    }
    window.addEventListener('certiproof:open-assessment', openAssessment)
    return () => window.removeEventListener('certiproof:open-assessment', openAssessment)
  }, [projectId])

  useEffect(() => {
    const refreshAfterDocumentClear = async (event) => {
      if (event.detail?.projectId !== projectId) return
      await fetchAssessment({ silent: true })
      if (selectedPhase?.id) {
        const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
        setTasks(response.data)
        setBatchDocumentRun(null)
      }
    }
    window.addEventListener('certiproof:document-data-cleared', refreshAfterDocumentClear)
    return () => window.removeEventListener('certiproof:document-data-cleared', refreshAfterDocumentClear)
  }, [projectId, selectedPhase?.id])

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
      const current = await fetchAssessment({ silent: true })
      const reportPhase = current?.phases?.find(phase => phase.phase_id === 'report')
      message.success('已进入生成报告阶段，未解决问题会如实写入报告')
      if (reportPhase) await handlePhaseClick(reportPhase)
    } catch (error) {
      console.error('Failed to complete phase:', error)
      message.error(error.response?.data?.detail || '暂时无法进入生成报告阶段')
    }
  }

  const handleStartTask = async (taskId) => {
    try {
      await api.post(`/assessments/tasks/${taskId}/start`)
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
      
      // 启动轮询
      startPolling(selectedPhase.id)
    } catch (error) {
      console.error('Failed to start task:', error)
      message.error(`启动任务失败: ${error.response?.data?.detail || error.message}`)
    }
  }

  const loadProjectAssets = async (selectAll = false) => {
    setAssetsLoading(true)
    try {
      const response = await api.get(`/projects/${projectId}/assets/`)
      const assets = response.data || []
      setProjectAssets(assets)
      if (selectAll) setSelectedAssets(assets.map(asset => asset.id))
    } catch (error) {
      console.error('Failed to fetch assets:', error)
      setProjectAssets([])
    } finally {
      setAssetsLoading(false)
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
    
    await loadProjectAssets()
  }

  const handleOpenTechnicalBatch = async () => {
    setExecuteTask({
      task_type: GAP_TECH_BATCH_TYPE,
      name: selectedPhase?.phase_id === 'field_assessment' ? '自动现场技术检测' : '自动基础技术检测',
    })
    setExecuteMode('all')
    setExecuteParams({ target: '', username: 'root', password: '', key_file: '' })
    setSelectedAssets([])
    setUnifiedCredential(true)
    setAssetCredentials({})
    setExecuteModalVisible(true)
    await loadProjectAssets(true)
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
      const isGapBatch = executeTask.task_type === GAP_TECH_BATCH_TYPE
      const executeResponse = isGapBatch
        ? await api.post(`/assessments/phases/${selectedPhase.id}/technical/execute`, {
            asset_ids: selectedAssets,
            ...(Object.keys(credentials).length > 0 ? { credentials } : {}),
          })
        : await api.post(`/assessments/tasks/${executeTask.id}/execute`, payload)
      if (executeResponse.data?.status === 'partial') {
        message.warning(executeResponse.data.message || '任务部分完成，存在无法检测项')
      } else {
        message.success(executeResponse.data?.message || (isGapBatch ? '基础技术检测已提交' : '任务执行完成'))
      }
      setExecuteModalVisible(false)
      
      // 刷新任务列表并启动轮询
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
      startPolling(selectedPhase.id)
    } catch (error) {
      console.error('Failed to execute task:', error)
      message.error(`执行任务失败: ${error.response?.data?.detail || error.message}`)
    } finally {
      setExecuting(false)
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

  const handleStopBatchDocumentRun = async () => {
    if (!batchDocumentRun?.id) return
    try {
      await api.post(`/assessments/document-runs/${batchDocumentRun.id}/stop`, { reason: '' })
      message.success('文档合规检查已停止')
      const response = await api.get(`/assessments/document-runs/${batchDocumentRun.id}`)
      setBatchDocumentRun(response.data)
    } catch (error) {
      message.error(`停止文档检查失败: ${error.response?.data?.detail || error.message}`)
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
    setBatchUploadMode(false)
    setUploadTask(task)
    setUploadFiles([])
    setTaskDocuments([])
    setUploadAnalysisMode('default')
    setUploadModalVisible(true)

    try {
      const [levelResponse, documentsResponse] = await Promise.all([
        api.get(`/assessments/tasks/${task.id}/project-level`),
        api.get(`/assessments/tasks/${task.id}/documents`),
      ])
      setProjectLevel(levelResponse.data)
      setTaskDocuments(documentsResponse.data || [])
    } catch (error) {
      console.error('Failed to load document task:', error)
      setProjectLevel(null)
    }
  }

  const handleOpenBatchUpload = () => {
    setBatchUploadMode(true)
    setUploadTask(null)
    setUploadFiles([])
    setTaskDocuments([])
    setProjectLevel(null)
    setUploadAnalysisMode('default')
    setUploadModalVisible(true)
  }

  const handleSubmitUpload = async () => {
    if (uploadFiles.length === 0) {
      message.warning('请先选择文件')
      return
    }
    if (!batchUploadMode && !uploadTask) return

    setUploading(true)
    try {
      const formData = new FormData()
      uploadFiles.forEach(file => formData.append('files', file, file.webkitRelativePath || file.name))
      formData.append('analysis_mode', uploadAnalysisMode)

      const response = await api.post(
        batchUploadMode
          ? `/assessments/phases/${selectedPhase.id}/documents/batch`
          : `/assessments/tasks/${uploadTask.id}/documents`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )

      message.success(batchUploadMode
        ? (isVerificationPhase ? '整改材料已上传，正在自动归类并重新检查' : '文档集已上传，正在自动归类')
        : `已上传 ${uploadFiles.length} 个文件，正在后台分析`)
      if (batchUploadMode) {
        setBatchDocumentRun({ id: response.data.run_id, status: 'pending', progress: { percent: 0, message: '等待批量文档归类' } })
        startBatchPolling(response.data.run_id, selectedPhase.id, true)
      }
      const tasksResponse = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(tasksResponse.data)
      fetchAssessment()
      setUploadModalVisible(false)
      setUploadFiles([])
      if (!batchUploadMode) startPolling(selectedPhase.id)
    } catch (error) {
      console.error('Upload failed:', error)
      const errMsg = error.response?.data?.detail || error.message || '上传失败'
      message.error(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg))
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteDocument = async (documentId) => {
    if (!uploadTask) return
    try {
      await api.delete(`/assessments/tasks/${uploadTask.id}/documents/${documentId}`)
      const response = await api.get(`/assessments/tasks/${uploadTask.id}/documents`)
      setTaskDocuments(response.data || [])
      message.success('文档已移除，检查结果将自动更新')
      startPolling(selectedPhase?.id || uploadTask.phase_id)
    } catch (error) {
      message.error(error.response?.data?.detail || '删除文档失败')
    }
  }

  const handleReanalyzeDocuments = async (task) => {
    let analysisMode = 'default'
    Modal.confirm({
      title: '重新分析文档',
      content: (
        <Radio.Group
          defaultValue="default"
          onChange={(event) => { analysisMode = event.target.value }}
          className="document-mode-options"
        >
          <Radio value="default">使用系统默认</Radio>
          <Radio value="standard">标准模式</Radio>
          <Radio value="deep">深度模式</Radio>
        </Radio.Group>
      ),
      okText: '重新分析',
      cancelText: '取消',
      onOk: async () => {
        try {
          await api.post(`/assessments/tasks/${task.id}/documents/analyze`, null, {
            params: { analysis_mode: analysisMode },
          })
          message.success('已重新提交文档分析')
          const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
          setTasks(response.data)
          startPolling(selectedPhase.id)
        } catch (error) {
          message.error(error.response?.data?.detail || '重新分析失败')
        }
      },
    })
  }

  // 切换错误详情展开
  const toggleErrorExpand = (taskId) => {
    setExpandedErrors(prev => ({ ...prev, [taskId]: !prev[taskId] }))
  }

  // 获取失败原因
  const getFailureReason = (task) => {
    if (!task.result) return '任务执行失败'
    const issues = getTaskIssues(task)
    const firstWarning = issues.find(item => item.level === 'warning')
    if (firstWarning && !issues.some(item => item.level === 'failed')) return firstWarning.error
    
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

  const getTaskIssues = (task) => {
    const result = task.result || {}
    const issues = []

    ;(result.failed || []).forEach((item) => {
      issues.push({
        level: 'failed',
        target: item.target || result.target || '未知',
        capability: item.capability || '未知工具',
        error: item.error || '执行失败',
      })
    })

    ;(result.warnings || []).forEach((item) => {
      issues.push({
        level: 'warning',
        target: item.target || result.target || '未知',
        capability: item.capability || '未知工具',
        error: item.error || item.warning || '检测未完整完成',
      })
    })

    if (result.asset_results) {
      Object.entries(result.asset_results).forEach(([target, r]) => {
        ;(r.failed || []).forEach((item) => {
          issues.push({
            level: 'failed',
            target,
            capability: item.capability || '扫描',
            error: item.error || '执行失败',
          })
        })
        ;(r.warnings || []).forEach((item) => {
          issues.push({
            level: 'warning',
            target,
            capability: item.capability || '扫描',
            error: item.error || item.warning || '检测未完整完成',
          })
        })
        if (r.status === 'failed') {
          issues.push({
            level: 'failed',
            target,
            capability: '扫描',
            error: r.error || '执行失败',
          })
        } else if (r.status === 'partial') {
          issues.push({
            level: 'warning',
            target,
            capability: r.task_type || '扫描',
            error: '该资产存在无法检测或未完整完成的子项',
          })
        }
      })
    }

    if (result.error && issues.length === 0) {
      issues.push({
        level: 'failed',
        target: result.target || '未知',
        capability: '执行',
        error: result.error,
      })
    }

    return issues
  }

  // 渲染失败详情
  const renderFailureDetails = (task) => {
    const details = getTaskIssues(task)
    
    if (details.length === 0) return null
    
    return (
      <div className="task-error-details">
        {details.map((d, i) => (
          <div key={i} className={`error-detail-item ${d.level}`}>
            <div className="error-detail-header">
              <WarningOutlined style={{ color: d.level === 'warning' ? '#f59e0b' : '#ef4444', marginRight: 6 }} />
              <span className="error-target">{d.target}</span>
              <span className="error-capability">[{d.capability}]</span>
            </div>
            <div className="error-detail-message">{d.error}</div>
          </div>
        ))}
      </div>
    )
  }

  const handleOpenEvidence = async (item) => {
    const documentId = item.document_file_id || item.evidence_id
    if (!documentId) return
    try {
      const response = await api.get(`/assessments/documents/${documentId}/download`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(response.data)
      window.open(`${url}${item.page ? `#page=${item.page}` : ''}`, '_blank', 'noopener,noreferrer')
      window.setTimeout(() => window.URL.revokeObjectURL(url), 60000)
    } catch (error) {
      message.error(error.response?.data?.detail || '证据文件打开失败')
    }
  }

  const renderDocumentAnalysis = (task) => {
    const analysis = task.result?.analysis
    if (!analysis) return null

    const statusMap = {
      pass: { color: 'success', text: '通过' },
      partial: { color: 'warning', text: '部分通过' },
      fail: { color: 'error', text: '不通过' },
      unable: { color: 'default', text: '无法判断' },
    }
    const status = statusMap[analysis.status] || statusMap.unable
    const gaps = analysis.gaps || []
    const comparison = analysis.retest_comparison
    const controls = analysis.controls || []
    const retrieval = analysis.retrieval || {}
    const engineLabel = analysis.evidence_engine === 'hybrid'
      ? 'LLM 判证 + 规则汇总'
      : analysis.evidence_engine === 'rule'
        ? '规则汇总'
        : '判证不可用'

    return (
      <div className="document-analysis">
        <div className="document-analysis-summary">
          <Tag color={status.color}>{status.text}</Tag>
          <strong>{analysis.document_name || '文档检查'}</strong>
          <span>覆盖率 {Math.round((analysis.coverage || 0) * 100)}%</span>
          <span>置信度 {analysis.status === 'unable' ? '不可用' : `${Math.round((analysis.confidence || 0) * 100)}%`}</span>
          <span>{analysis.analysis_mode === 'deep' ? '深度模式' : '标准模式'}</span>
        </div>
        <div className="document-engine-summary">
          <Tag color={retrieval.semantic_available ? 'cyan' : 'warning'}>
            {retrieval.engine || '精确检索 + 标准图谱'}
          </Tag>
          <Tag color={analysis.evidence_engine === 'unavailable' ? 'error' : 'geekblue'}>{engineLabel}</Tag>
          {retrieval.embedding_model && <span>向量模型：{retrieval.embedding_model}</span>}
        </div>
        {(analysis.message || retrieval.semantic_error) && (
          <Alert
            type={analysis.status === 'unable' ? 'error' : 'warning'}
            showIcon
            message={analysis.message || '语义检索不可用，已降级为精确检索和图谱扩展'}
            description={retrieval.semantic_error || undefined}
          />
        )}
        {(analysis.files || []).length > 0 && (
          <div className="document-file-summary">
            {analysis.files.map(file => (
              <div key={file.document_file_id} className={file.status === 'failed' ? 'failed' : ''}>
                <FileTextOutlined />
                <span>{file.file_name}</span>
                <em>
                  {file.status === 'failed'
                    ? `提取失败：${file.error || '未知错误'}`
                    : `${file.page_count || 0} 页 · 原生 ${file.native_blocks || 0} · OCR ${file.ocr_blocks || 0} · 视觉 ${Math.max((file.vision_blocks || 0) - (file.ocr_blocks || 0), 0)} · 向量${file.embedding_status === 'ready' ? '就绪' : '不可用'}`}
                </em>
                {(file.warnings || []).length > 0 && (
                  <small>
                    {file.visual_degraded && !file.visual_incomplete ? '视觉交叉验证部分降级，已使用原生或轻量 OCR 结果继续判定：' : ''}
                    {file.warnings.join('；')}
                  </small>
                )}
              </div>
            ))}
          </div>
        )}
        {comparison && (
          <div className={`document-analysis-comparison ${comparison.comparison_reliable === false ? 'unreliable' : ''}`}>
            <strong>
              复测：{comparison.comparison_reliable === false
                ? '无法可靠比较'
                : comparison.status === 'improved' ? '已改善' : comparison.status === 'regressed' ? '有退化' : '无变化'}
            </strong>
            <span>{comparison.delta > 0 ? '+' : ''}{Math.round((comparison.delta || 0) * 100)}%</span>
            {comparison.comparison_reliable !== false && (
              <em>已修复 {comparison.fixed_gap_ids?.length || 0} · 未解决 {comparison.remaining_gap_ids?.length || 0} · 新增 {comparison.new_gap_ids?.length || 0}</em>
            )}
            {comparison.comparison_reliable === false && <em>初检或本次分析未完成，不自动关闭原问题</em>}
          </div>
        )}
        {gaps.length > 0 && (
          <div className="document-analysis-gaps">
            {gaps.slice(0, 3).map((gap, index) => (
              <div key={index}>缺失：{gap}</div>
            ))}
            {gaps.length > 3 && <div>还有 {gaps.length - 3} 项缺失</div>}
          </div>
        )}
        {controls.length > 0 && (
          <details className="document-analysis-details">
            <summary>
              检查详情：通过 {analysis.passed_points || 0} · 部分 {analysis.partial_points || 0} · 不通过 {analysis.failed_points || 0} · 无法判断 {analysis.unable_points || 0}
            </summary>
            <div className="document-control-list">
              {controls.map((control) => {
                const controlStatus = statusMap[control.status] || statusMap.unable
                return (
                  <div key={control.id} className="document-control">
                    <div className="document-control-title">
                      <Tag color={controlStatus.color}>{controlStatus.text}</Tag>
                      <strong>{control.title}</strong>
                    </div>
                    {(control.points || []).map((point) => {
                      const pointStatus = statusMap[point.status] || statusMap.unable
                      const evidence = point.evidence || []
                      return (
                        <div key={`${control.id}-${point.id}`} className="document-control-point">
                          <div className="document-control-point-title">
                            <Tag color={pointStatus.color}>{pointStatus.text}</Tag>
                            <span>{point.text}</span>
                          </div>
                          {['fail', 'partial'].includes(point.status) && (
                            <div className="document-control-missing">
                              {point.contradiction ? '发现冲突：' : point.status === 'partial' ? '证据不足：' : '缺失：'}
                              {point.llm_reason || point.missing_judgement}
                            </div>
                          )}
                          {evidence.slice(0, 2).map((item, index) => (
                            <div key={index} className="document-control-evidence">
                              <button
                                type="button"
                                className="evidence-location"
                                onClick={() => handleOpenEvidence(item)}
                                title="打开原始证据文件"
                              >
                                {item.file_name || '文档'}
                                {item.page ? ` · 第 ${item.page} 页` : ''}
                                {item.section ? ` · ${item.section}` : ''}
                                {item.type ? ` · ${item.type}` : ''}
                              </button>
                              <span>证据：{item.text}</span>
                              <small>
                                {item.retrieval_sources?.length ? `${item.retrieval_sources.join(' + ')} · ` : ''}
                                置信度 {Math.round((item.confidence || 0) * 100)}%
                              </small>
                            </div>
                          ))}
                          {(point.basis || []).length > 0 && (
                            <div className="document-control-basis">
                              依据：{point.basis.join('、')}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )
              })}
            </div>
          </details>
        )}
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
    return (
      <div className="assessment-progress-container empty">
        <div className="assessment-header">
          <div className="assessment-title"><RocketOutlined className="assessment-icon" /><span>测评进度</span></div>
        </div>
        <Button type="primary" block icon={<PlayCircleFilled />} onClick={handleOpenAssessment} className="start-assessment-btn">
          创建等保测评
        </Button>
      </div>
    )
  }

  const statusConfig = STATUS_CONFIG[assessment.status] || STATUS_CONFIG.not_started
  const isGapAnalysis = selectedPhase?.phase_id === 'gap_analysis'
  const isFieldAssessment = selectedPhase?.phase_id === 'field_assessment'
  const isVerificationPhase = selectedPhase?.phase_id === 'remediation_verification'
  const documentTasks = tasks.filter(task => task.task_type === 'doc_review')
  const technicalTasks = tasks.filter(task => (
    isGapAnalysis ? BASIC_TECHNICAL_TASK_TYPES.has(task.task_type) : isFieldAssessment && EXECUTABLE_TASK_TYPES.includes(task.task_type)
  ))
  const documentCompleted = documentTasks.filter(task => task.status === 'completed').length
  const technicalCompleted = technicalTasks.filter(task => task.status === 'completed').length
  const technicalQueued = technicalTasks.filter(task => task.status === 'in_progress' && task.result?.execution?.state === 'queued').length
  const technicalRunning = technicalTasks.filter(task => task.status === 'in_progress' && task.result?.execution?.state !== 'queued').length
  const technicalActive = technicalQueued + technicalRunning
  const batchDocumentRunning = ['queued', 'pending', 'running'].includes(batchDocumentRun?.status)
  const completionState = COMPLETION_STATE_CONFIG[completionSummary?.completion_state] || COMPLETION_STATE_CONFIG.needs_remediation
  const cockpitTracks = {
    gap_analysis: ['文档合规检查', '基础技术检测', '差距结果汇总'],
    field_assessment: ['全资产技术检测', '专项安全检测', '现场结果归集'],
    remediation_verification: ['文档整改复测', '技术问题复测', '问题处置确认'],
    report: ['报告数据固化', 'HTML 报告生成'],
    report_generation: ['报告数据固化', 'HTML 报告生成'],
  }
  const totalTasks = phases.reduce((sum, phase) => sum + Number(phase.total_tasks || 0), 0)
  const completedTasks = phases.reduce((sum, phase) => sum + Number(phase.completed_tasks || 0), 0)

  return (
    <>
      {variant === 'cockpit' ? (
        <div className="assessment-progress-container cockpit-assessment">
          <div className="cockpit-phase-list">
            {phases.map((phase, index) => {
              const isActive = phase.status === 'active'
              const isCompleted = phase.status === 'completed'
              const phaseStatus = phase.phase_id === 'remediation_verification' && isCompleted
                ? { color: '#10b981', text: '本轮已完成', className: 'completed' }
                : PHASE_STATUS_CONFIG[phase.status] || PHASE_STATUS_CONFIG.pending
              const isSelected = selectedPhase?.id === phase.id
              const isExpanded = isSelected || (!selectedPhase && (
                isActive || (assessment.status === 'completed' && index === phases.length - 1)
              ))
              const tracks = cockpitTracks[phase.phase_id] || [phase.description || '阶段任务']
              const phaseProgress = isCompleted ? 100 : Number(phase.progress || 0)

              return (
                <section
                  key={phase.id}
                  className={`cockpit-phase ${phase.status} ${isSelected ? 'selected' : ''} ${isExpanded ? 'expanded' : ''}`}
                  onClick={() => handlePhaseClick(phase)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      handlePhaseClick(phase)
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  aria-label={`${phase.name}，${phaseStatus.text}，点击查看与执行`}
                >
                  <div className="cockpit-phase-rail">
                    <i>{isCompleted ? <CheckCircleFilled /> : index + 1}</i>
                    {index < phases.length - 1 && <span />}
                  </div>
                  <div className="cockpit-phase-content">
                    <div className="cockpit-phase-title">
                      <div>
                        <strong>{phase.name}</strong>
                        <small className="cockpit-phase-meta">
                          <span>任务 {phase.completed_tasks || 0}/{phase.total_tasks || 0}</span>
                          {phase.phase_id === 'remediation_verification' && Number.isFinite(openIssues)
                            ? <span className="cockpit-pending-badge"><b>{openIssues}</b> 待处理</span>
                            : <span>{tracks.length} 个步骤</span>}
                        </small>
                      </div>
                      <em><b>{Math.round(phaseProgress)}%</b><span>{phaseStatus.text}</span></em>
                    </div>

                    {isExpanded && (
                      <div className="cockpit-phase-detail">
                        {tracks.map((label, trackIndex) => {
                          const trackProgress = Math.max(0, Math.min(100, phaseProgress * tracks.length - trackIndex * 100))
                          const trackDone = trackProgress >= 100
                          const trackActive = isActive && !trackDone && trackIndex === Math.floor((phaseProgress / 100) * tracks.length)
                          return (
                            <div className={trackDone ? 'done' : trackActive ? 'running' : 'pending'} key={label}>
                              <span>{trackDone ? <CheckCircleFilled /> : TASK_TYPE_ICONS[trackIndex === 0 ? 'doc_review' : trackIndex === 1 ? 'config_check' : 'retest']}</span>
                              <strong>{label}</strong>
                              <small>{trackDone ? '100% · 完成' : trackActive ? `${Math.round(trackProgress)}% · 执行中` : '0% · 等待'}</small>
                            </div>
                          )
                        })}
                        <div className="cockpit-phase-actions">
                          <Button
                            type="primary"
                            size="small"
                            icon={<PlayCircleFilled />}
                            onClick={(event) => {
                              event.stopPropagation()
                              handlePhaseClick(phase)
                            }}
                          >
                            查看与执行
                          </Button>
                          <Tooltip title="重置本阶段">
                            <Button
                              size="small"
                              icon={<ReloadOutlined />}
                              onClick={(event) => {
                                event.stopPropagation()
                                handleRestartPhase(phase.id, 'reset')
                              }}
                              aria-label={`重置${phase.name}`}
                            />
                          </Tooltip>
                        </div>
                      </div>
                    )}
                  </div>
                </section>
              )
            })}
          </div>

          <div className="cockpit-flow-summary">
            <div>
              <span>流程总览</span>
              <strong>完成度 {Math.round(assessment.progress)}%</strong>
            </div>
            <Progress percent={Math.round(assessment.progress)} showInfo={false} />
            <dl>
              <div><dt>总任务</dt><dd>{totalTasks}</dd></div>
              <div><dt>已完成</dt><dd>{completedTasks}</dd></div>
              <div><dt>待处理</dt><dd>{Math.max(totalTasks - completedTasks, 0)}</dd></div>
            </dl>
          </div>

          {assessment.status === 'not_started' && (
            <Button type="primary" block icon={<PlayCircleFilled />} onClick={handleStartAssessment}>
              开始测评
            </Button>
          )}
          {assessment.status === 'completed' && (
            <Button
              type="primary"
              block
              icon={<CheckCircleFilled />}
              onClick={async () => {
                if (!completionSummary && assessment?.id) await fetchCompletionSummary(assessment.id)
                setShowCompletionView(true)
              }}
            >
              查看测评结果
            </Button>
          )}
          <Button
            block
            danger
            icon={<ReloadOutlined />}
            onClick={() => handleRestartAssessment('reset')}
            className="cockpit-full-reset"
          >
            完全重置测评
          </Button>
        </div>
      ) : (
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
                      <Tag color="#10b981" icon={<CheckCircleFilled />} className="phase-done-tag">
                        {phase.phase_id === 'remediation_verification' ? '本轮结束' : '完成'}
                      </Tag>
                    )}
                    <Button
                      type="link"
                      size="small"
                      icon={<ReloadOutlined />}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleRestartPhase(phase.id, 'reset')
                      }}
                      style={{ padding: '0 4px', fontSize: 11 }}
                    >
                      重置
                    </Button>
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

        <Button
          block
          danger
          icon={<ReloadOutlined />}
          onClick={() => handleRestartAssessment('reset')}
          style={{ marginTop: 8 }}
        >
          完全重置测评
        </Button>
      </div>
      )}

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
            <div className={`completion-header ${completionState.tone}`}>
              <div className="completion-icon">
                {completionState.tone === 'success' ? <CheckCircleFilled /> : <WarningOutlined />}
              </div>
              <h2>{completionState.title}</h2>
              <p className="completion-project-name">{completionSummary.project?.name}</p>
              <Tag color={completionState.color}>{completionState.label}</Tag>
            </div>

            {/* Score Card */}
            <div className="completion-score-card">
              <div className="score-circle">
                <Progress
                  type="circle"
                  percent={completionSummary.project?.score ?? 0}
                  size={120}
                  strokeColor={{
                    '0%': completionSummary.project?.score >= 75 ? '#10b981' : '#f59e0b',
                    '100%': completionSummary.project?.score >= 75 ? '#059669' : '#d97706',
                  }}
                  format={(percent) => (
                    <div className="score-content">
                      <span className="score-number">{completionSummary.project?.score == null ? '-' : percent}</span>
                      <span className="score-unit">{completionSummary.project?.score == null ? '未判定' : '合规分'}</span>
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
                <div className="score-coverage">
                  可靠检测覆盖 {completionSummary.score_metrics?.coverage ?? 0}%
                  <span>只有可靠检测通过或真实复测修复的问题才计入合规结果。</span>
                </div>
              </div>
            </div>

            {/* Stats Grid */}
            <div className="completion-stats">
              <div className="stat-card">
                <div className="stat-value">{completionSummary.stats?.completion_rate || 0}%</div>
                <div className="stat-label">流程已处理</div>
              </div>
              <div className="stat-card success">
                <div className="stat-value">{completionSummary.phases?.find(item => item.disposition)?.disposition?.fixed || 0}</div>
                <div className="stat-label">已修复问题</div>
              </div>
              <div className="stat-card warning">
                <div className="stat-value">{completionSummary.phases?.find(item => item.disposition)?.disposition?.open || 0}</div>
                <div className="stat-label">待处理问题</div>
              </div>
              <div className="stat-card failed">
                <div className="stat-value">{completionSummary.phases?.find(item => item.disposition)?.disposition?.unable || 0}</div>
                <div className="stat-label">无法验证</div>
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
                      <button
                        type="button"
                        className="phase-timeline-header"
                        onClick={() => togglePhaseExpand(phase.id)}
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
                            {phase.completed_tasks}/{phase.total_tasks} {phase.metric_label || '任务'}{phase.metric_suffix || '已处理'}
                            {phase.execution_coverage != null && <> · 执行覆盖 {phase.execution_coverage}%</>}
                            {phase.skipped_tasks > 0 && <> · {phase.skipped_tasks} 项不适用 / 跳过</>}
                            {phase.completed_at && (
                              <span> · {new Date(phase.completed_at).toLocaleDateString('zh-CN')}</span>
                            )}
                          </div>
                        </div>
                      </button>
                      
                      {/* 展开的任务列表 */}
                      {isExpanded && phase.disposition && (
                        <div className="phase-remediation-detail">
                          <div className="phase-remediation-summary">
                            <span><b>{phase.disposition.fixed || 0}</b>已修复</span>
                            <span><b>{phase.disposition.unable || 0}</b>无法验证</span>
                            <span><b>{phase.disposition.open || 0}</b>待处理</span>
                          </div>
                          <div className="phase-verification-runs">
                            {(phase.verification_runs || []).length ? phase.verification_runs.map(run => (
                              <div className="phase-verification-run" key={run.id}>
                                <span>{run.source_type === 'document' ? '文档复测' : '技术复测'} #{run.id}</span>
                                <em>{VERIFICATION_RUN_STATUS[run.status] || run.status}</em>
                                <small>
                                  已修复 {run.summary?.fixed || 0} · 未解决 {run.summary?.still_present || 0} · 无法验证 {run.summary?.unable || 0}
                                </small>
                              </div>
                            )) : <div className="phase-empty-detail">尚未产生复测记录</div>}
                          </div>
                        </div>
                      )}
                      {isExpanded && !phase.disposition && phase.tasks && (
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
                                  task.status === 'completed' ? '已执行' :
                                  task.status === 'failed' ? '执行失败' :
                                  task.status === 'cancelled' ? '不适用 / 已跳过' :
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
                onClick={() => handleDownloadReport('html')}
                type="primary"
                size="large"
              >
                下载 HTML 报告
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
                onClick={() => handleRestartAssessment('continue')}
                size="large"
              >
                继续整改 / 重新检测
              </Button>
              <Button
                icon={<ReloadOutlined />}
                onClick={() => handleRestartAssessment('reset')}
                size="large"
                danger
              >
                完全重置测评
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
              {selectedPhase?.phase_id === 'remediation_verification' && selectedPhase?.status === 'completed'
                ? '本轮结束'
                : PHASE_STATUS_CONFIG[selectedPhase?.status]?.text}
            </Tag>
          </div>
        }
        placement="right"
        width={isGapAnalysis || isVerificationPhase ? 'min(920px, 96vw)' : 'min(720px, 94vw)'}
        onClose={() => {
          setDrawerVisible(false)
          stopPolling()
        }}
        open={drawerVisible}
        className="phase-detail-drawer"
        destroyOnHidden
      >
        {drawerVisible && selectedPhase && (
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

            {isGapAnalysis && (
              <div className="gap-analysis-tracks">
                <section className="gap-track document-track">
                  <div className="gap-track-header">
                    <span className="gap-track-icon"><FileProtectOutlined /></span>
                    <div>
                      <strong>文档合规检查</strong>
                      <p>上传文件、文件夹、ZIP、RAR 或 7z，系统通过文件名、正文标题和内容混合归类并逐项分析。</p>
                    </div>
                  </div>
                  <div className="gap-track-stats">
                    <span><b>{documentCompleted}</b> / {documentTasks.length} 已完成</span>
                    <span><b>{documentTasks.filter(task => task.status === 'in_progress').length}</b> 分析中</span>
                    <span><b>{batchDocumentRun?.result?.unclassified?.length || 0}</b> 未归类</span>
                  </div>
                  {batchDocumentRun && (
                    <div className={`batch-document-status ${batchDocumentRun.status}`}>
                      {batchDocumentRunning ? (
                        <>
                          <DocumentPipelineProgress progress={batchDocumentRun.progress} batch />
                          {batchDocumentRun.stale && <Alert type="warning" showIcon message="Worker 心跳已过期，任务将自动恢复" />}
                          <Button danger size="small" icon={<StopOutlined />} onClick={handleStopBatchDocumentRun}>
                            停止文档检查
                          </Button>
                        </>
                      ) : batchDocumentRun.status === 'cancelled' ? (
                        <span><StopOutlined /> 文档合规检查已停止，可重新上传后再次执行</span>
                      ) : batchDocumentRun.status === 'failed' ? (
                        <span><WarningOutlined /> {batchDocumentRun.error || '批量文档归类失败'}</span>
                      ) : (
                        <>
                          <span>最近归类：{batchDocumentRun.result?.classified?.length || 0} 个已匹配，{batchDocumentRun.result?.missing?.length || 0} 类仍缺材料</span>
                          {(batchDocumentRun.result?.classified?.length || 0) > 0 && (
                            <details>
                              <summary>查看归类结果与文件名提示</summary>
                              {batchDocumentRun.result.classified.map(item => (
                                <div key={item.document_file_id} className="classification-result-row">
                                  <span>{item.file_name} → {item.document_name}</span>
                                  <Tag color={item.extraction_status === 'unable' ? 'error' : item.naming_status === 'filename_warning' ? 'warning' : 'success'}>
                                    {item.extraction_status === 'unable' ? '内容提取失败' : item.naming_status === 'filename_warning' ? '命名不规范' : '名称匹配'}
                                  </Tag>
                                  <em>
                                    {item.extraction_status === 'unable'
                                      ? item.extraction_error
                                      : `${item.classifier === 'hybrid' ? '规则 + LLM' : item.classifier === 'rule_fallback' ? '规则降级' : '规则确认'} · ${Math.round((item.confidence || 0) * 100)}%`}
                                  </em>
                                </div>
                              ))}
                            </details>
                          )}
                          {(batchDocumentRun.result?.unclassified?.length || 0) > 0 && (
                            <details>
                              <summary>{batchDocumentRun.result.unclassified.length} 个文件未可靠归类</summary>
                              {batchDocumentRun.result.unclassified.map(item => (
                                <div key={item.document_file_id}>{item.file_name}：{item.reason}</div>
                              ))}
                            </details>
                          )}
                        </>
                      )}
                    </div>
                  )}
                  <Button
                    type="primary"
                    icon={<InboxOutlined />}
                    onClick={handleOpenBatchUpload}
                    disabled={batchDocumentRunning || documentTasks.some(task => task.status === 'in_progress')}
                  >
                    批量上传并自动分析
                  </Button>
                </section>

                <section className="gap-track technical-track">
                  <div className="gap-track-header">
                    <span className="gap-track-icon"><ThunderboltOutlined /></span>
                    <div>
                      <strong>基础技术检测</strong>
                      <p>一次选择资产和 SSH 凭证，并行执行端口、漏洞、基线、弱口令和 SSL/TLS 检测。</p>
                    </div>
                  </div>
                  <div className="gap-track-stats">
                    <span><b>{technicalCompleted}</b> / {technicalTasks.length} 已完成</span>
                    <span><b>{technicalRunning}</b> 执行中</span>
                    <span><b>{technicalQueued}</b> 排队中</span>
                    <span><b>{technicalTasks.filter(task => task.status === 'failed').length}</b> 失败</span>
                  </div>
                  {technicalActive > 0 && (
                    <div className="technical-batch-status">
                      <Spin size="small" />
                      <span>{technicalRunning} 项执行中，{technicalQueued} 项排队中；可继续文档检查或提交其他扫描</span>
                    </div>
                  )}
                  <Button
                    type="primary"
                    icon={<ThunderboltOutlined />}
                    onClick={handleOpenTechnicalBatch}
                    disabled={technicalTasks.length === 0 || technicalActive > 0}
                  >
                    自动检测全部资产
                  </Button>
                </section>
              </div>
            )}

            {isFieldAssessment && (
              <section className="gap-track technical-track field-auto-track">
                <div className="gap-track-header">
                  <span className="gap-track-icon"><RadarChartOutlined /></span>
                  <div>
                    <strong>自动现场技术检测</strong>
                    <p>一次选择资产和凭证，后台并发执行适用的 Web、数据库、网络设备、Windows/AD 和主机深度检测。</p>
                  </div>
                </div>
                <div className="gap-track-stats">
                  <span><b>{technicalCompleted}</b> / {technicalTasks.length} 已完成</span>
                  <span><b>{technicalRunning}</b> 执行中</span>
                  <span><b>{technicalQueued}</b> 排队中</span>
                  <span><b>{technicalTasks.filter(task => task.status === 'failed').length}</b> 无法完成</span>
                </div>
                {technicalActive > 0 && <div className="technical-batch-status"><Spin size="small" /><span>{technicalRunning} 项执行中，{technicalQueued} 项排队中；结果和失败原因会逐项回写</span></div>}
                <Button type="primary" icon={<ThunderboltOutlined />} onClick={handleOpenTechnicalBatch} disabled={!technicalTasks.length || technicalActive > 0}>
                  自动执行全部现场检测
                </Button>
              </section>
            )}

            {isVerificationPhase && (
              <>
                <section className="gap-track document-track verification-document-track">
                  <div className="gap-track-header">
                    <span className="gap-track-icon"><FileProtectOutlined /></span>
                    <div>
                      <strong>批量提交整改材料</strong>
                      <p>一次提交多个文件、文件夹、ZIP、RAR 或 7z。系统自动归类，同类材料替换旧版本并重新检查该类全部未解决问题。</p>
                    </div>
                  </div>
                  <div className="gap-track-stats">
                    <span><b>{batchDocumentRun?.result?.classified?.length || 0}</b> 已归类</span>
                    <span><b>{batchDocumentRun?.result?.verification_runs?.length || 0}</b> 已复测排队</span>
                    <span><b>{batchDocumentRun?.result?.unclassified?.length || 0}</b> 未归类</span>
                  </div>
                  {batchDocumentRun && (
                    <div className={`batch-document-status ${batchDocumentRun.status}`}>
                      {batchDocumentRunning ? (
                        <>
                          <DocumentPipelineProgress progress={batchDocumentRun.progress} batch />
                          {batchDocumentRun.stale && <Alert type="warning" showIcon message="Worker 心跳已过期，任务将自动恢复" />}
                          <Button danger size="small" icon={<StopOutlined />} onClick={handleStopBatchDocumentRun}>停止批量整改检查</Button>
                        </>
                      ) : batchDocumentRun.status === 'failed' ? (
                        <span><WarningOutlined /> {batchDocumentRun.error || '整改材料归类失败'}</span>
                      ) : batchDocumentRun.status === 'cancelled' ? (
                        <span><StopOutlined /> 本次批量整改检查已停止</span>
                      ) : (
                        <>
                          <span>{batchDocumentRun.progress?.message || '整改材料已处理'}</span>
                          {(batchDocumentRun.result?.unclassified?.length || 0) > 0 && (
                            <details>
                              <summary>{batchDocumentRun.result.unclassified.length} 个文件未可靠归类</summary>
                              {batchDocumentRun.result.unclassified.map(item => <div key={item.document_file_id}>{item.file_name}：{item.reason}</div>)}
                            </details>
                          )}
                          {(batchDocumentRun.result?.verification_skipped?.length || 0) > 0 && (
                            <details>
                              <summary>{batchDocumentRun.result.verification_skipped.length} 类未进入复测</summary>
                              {batchDocumentRun.result.verification_skipped.map(item => <div key={item.task_id}>{item.document_name}：{item.reason}</div>)}
                            </details>
                          )}
                        </>
                      )}
                    </div>
                  )}
                  <Button type="primary" icon={<InboxOutlined />} onClick={handleOpenBatchUpload} disabled={batchDocumentRunning}>
                    批量上传并自动重新检查
                  </Button>
                </section>
                <VerificationWorkspace
                  projectId={projectId}
                  onChanged={fetchAssessment}
                  refreshKey={`${batchDocumentRun?.id || ''}:${batchDocumentRun?.status || ''}`}
                  onContinue={selectedPhase.status === 'active' ? () => handleCompletePhase(selectedPhase.id) : null}
                />
              </>
            )}

            {/* Tasks List */}
            {!isVerificationPhase && (
            <div className="tasks-section">
              <h4>{isGapAnalysis ? '单项检查与结果' : '任务列表'}</h4>
              {tasksLoading ? (
                <div className="tasks-loading">
                  <Spin />
                </div>
              ) : tasks.length === 0 ? (
                <Empty description="暂无任务" />
              ) : (
                <div className="tasks-list">
                  {tasks.map((task, taskIndex) => {
                    const taskStatus = TASK_STATUS_CONFIG[task.status] || TASK_STATUS_CONFIG.todo
                    const taskIcon = TASK_TYPE_ICONS[task.task_type] || <FileTextOutlined />
                    const taskIssues = getTaskIssues(task)
                    const hasIssues = taskIssues.length > 0
                    const hasOnlyWarnings = hasIssues && taskIssues.every(item => item.level === 'warning')
                    const isFailed = task.status === 'failed'
                    const isInProgress = task.status === 'in_progress'
                    const isQueued = isInProgress && task.result?.execution?.state === 'queued'
                    const isExpanded = expandedErrors[task.id]
                    const firstDocumentIndex = tasks.findIndex(item => item.task_type === 'doc_review')
                    const firstTechnicalIndex = tasks.findIndex(item => BASIC_TECHNICAL_TASK_TYPES.has(item.task_type))
                    
                    return (
                      <Fragment key={task.id}>
                      {isGapAnalysis && taskIndex === firstDocumentIndex && (
                        <div className="task-track-divider"><FileProtectOutlined /> 文档检查子项</div>
                      )}
                      {isGapAnalysis && taskIndex === firstTechnicalIndex && (
                        <div className="task-track-divider technical"><ThunderboltOutlined /> 基础技术子项</div>
                      )}
                      <div className={`task-item ${taskStatus.className} ${hasOnlyWarnings ? 'partial' : ''}`}>
                        <div className="task-icon">
                          {isQueued ? (
                            <ClockCircleFilled style={{ color: '#38bdf8' }} />
                          ) : isInProgress ? (
                            <Spin size="small" />
                          ) : isFailed ? (
                            <CloseCircleFilled style={{ color: '#ef4444' }} />
                          ) : hasOnlyWarnings ? (
                            <WarningOutlined style={{ color: '#f59e0b' }} />
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
                              {isQueued ? '排队中' : taskStatus.text}
                            </Tag>
                            {hasOnlyWarnings && (
                              <Tag color="warning" size="small">存在无法检测项</Tag>
                            )}
                            {(isFailed || hasIssues) && (
                              <span 
                                className="error-toggle"
                                onClick={() => toggleErrorExpand(task.id)}
                              >
                                {isExpanded ? '收起详情' : '查看原因'}
                              </span>
                            )}
                          </div>
                          {(isFailed || hasIssues) && (
                            <div className={`task-error-summary ${hasOnlyWarnings ? 'warning' : ''}`}>
                              <WarningOutlined style={{ marginRight: 4 }} />
                              {hasOnlyWarnings ? getFailureReason(task) : getFailureReason(task)}
                            </div>
                          )}
                          {(isFailed || hasIssues) && isExpanded && renderFailureDetails(task)}
                          {task.task_type === 'doc_review' && task.status === 'in_progress' && task.result?.progress && (
                            <DocumentPipelineProgress progress={task.result.progress} />
                          )}
                          {task.task_type === 'doc_review' && task.status === 'completed' && renderDocumentAnalysis(task)}
                        </div>
                        <div className="task-actions">
                          {task.status === 'completed' && task.task_type === 'doc_review' && (
                            <Button
                              type="link"
                              size="small"
                              icon={<UploadOutlined />}
                              onClick={() => handleOpenUpload(task)}
                            >
                              管理文档
                            </Button>
                          )}
                          {task.status === 'completed' && EXECUTABLE_TASK_TYPES.includes(task.task_type) && (
                            <Button
                              type="link"
                              size="small"
                              icon={<PlayCircleFilled />}
                              onClick={() => handleOpenExecute(task)}
                            >
                              重新执行
                            </Button>
                          )}
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
                              {EXECUTABLE_TASK_TYPES.includes(task.task_type) && (
                                <Button
                                  type="link"
                                  size="small"
                                  icon={<PlayCircleFilled />}
                                  onClick={() => handleOpenExecute(task)}
                                >
                                  执行
                                </Button>
                              )}
                              {!EXECUTABLE_TASK_TYPES.includes(task.task_type) && task.task_type !== 'doc_review' && (
                                <Button
                                  type="link"
                                  size="small"
                                  icon={<PlayCircleFilled />}
                                  onClick={() => handleStartTask(task.id)}
                                >
                                  {task.task_type === 'html_report' ? '生成报告' : '开始'}
                                </Button>
                              )}
                            </>
                          )}
                          {isInProgress && (
                            <>
                              {task.task_type === 'doc_review' ? (
                                <>
                                  <Tag color="processing">分析中</Tag>
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
                              ) : (
                                <>
                                  <Tag color="processing">执行中</Tag>
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
                                继续处理
                              </Button>
                            </>
                          )}
                          {!isInProgress && !['todo', 'cancelled'].includes(task.status) && (
                            <>
                              {task.task_type === 'doc_review' && task.status === 'failed' && (
                                <>
                                  <Button type="link" size="small" onClick={() => handleOpenUpload(task)}>
                                    管理文档
                                  </Button>
                                  <Button
                                    type="link"
                                    size="small"
                                    icon={<ReloadOutlined />}
                                    onClick={() => handleReanalyzeDocuments(task)}
                                  >
                                    重新分析
                                  </Button>
                                </>
                              )}
                              <Button
                                type="link"
                                size="small"
                                icon={<ReloadOutlined />}
                                onClick={() => handleResetTask(task.id)}
                              >
                                重置
                              </Button>
                            </>
                          )}
                        </div>
                      </div>
                      </Fragment>
                    )
                  })}
                </div>
              )}
            </div>
            )}

            {selectedPhase.status === 'active' && isVerificationPhase && (
              <div className="phase-auto-note">
                每项问题获得重新检查结论后，本轮自动结束；也可按当前结果生成报告，未解决和无法验证项会如实保留。
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* 上传文档弹窗 */}
      <Modal
        title={
          <span>
            <UploadOutlined style={{ marginRight: 8 }} />
            {batchUploadMode
              ? (isVerificationPhase ? '批量提交整改材料' : '批量上传文档集')
              : `上传任务文档 - ${uploadTask?.name || ''}`}
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
        {batchUploadMode && (
          <Alert
            type="info"
            showIcon
            message={isVerificationPhase ? '系统会先归类，再自动重新检查' : '系统会先归类，再执行检查'}
            description={isVerificationPhase
              ? '可靠归类后，同类旧材料会停用并保留审计记录，新材料将重新检查该类全部未解决问题。无法可靠归类的文件不会误更新整改结论。'
              : '文件名允许包含版本号、日期和修订标记；名称不规范但正文标题明确时会归类并提示。名称与正文都无法确认的文件不会被强行判定。'}
            style={{ marginBottom: 16 }}
          />
        )}
        {!batchUploadMode && projectLevel && projectLevel.requires_level_check && (
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

        <Form layout="vertical" style={{ marginBottom: 16 }}>
          <Form.Item
            label="本次分析模式"
            help="标准模式按需补充 OCR；深度模式会对 PDF 全页做 OCR/视觉交叉验证。"
          >
            <Radio.Group
              value={uploadAnalysisMode}
              onChange={(event) => setUploadAnalysisMode(event.target.value)}
              disabled={uploading}
              className="document-mode-options"
            >
              <Radio value="default">使用系统默认</Radio>
              <Radio value="standard">标准模式</Radio>
              <Radio value="deep">深度模式</Radio>
            </Radio.Group>
          </Form.Item>
        </Form>

        {batchUploadMode && (
          <Upload
            directory
            multiple
            showUploadList={false}
            beforeUpload={(file) => {
              if (file.size > 100 * 1024 * 1024) {
                message.error('文件过大，单个文档最大支持 100MB')
                return Upload.LIST_IGNORE
              }
              setUploadFiles(current => current.some(item => item.uid === file.uid) ? current : [...current, file])
              return false
            }}
            disabled={uploading}
          >
            <Button icon={<FolderOpenOutlined />} disabled={uploading}>选择文件夹</Button>
          </Upload>
        )}

        <Upload.Dragger
          multiple
          beforeUpload={(file) => {
            if (file.size > 100 * 1024 * 1024) {
              message.error('文件过大，单个文档最大支持 100MB')
              return Upload.LIST_IGNORE
            }
            setUploadFiles(current => current.some(item => item.uid === file.uid) ? current : [...current, file])
            return false
          }}
          fileList={uploadFiles.map(file => ({ uid: file.uid, name: file.name, status: 'done' }))}
          onRemove={(file) => {
            setUploadFiles(current => current.filter(item => item.uid !== file.uid))
          }}
          accept={batchUploadMode ? '.zip,.rar,.7z,.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff' : '.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">{batchUploadMode ? '拖拽文档集、ZIP、RAR 或 7z 到此区域' : '点击或拖拽一个或多个文件到此区域'}</p>
          <p className="ant-upload-hint">
            支持 DOCX、PDF、TXT、MD 和常见图片。{batchUploadMode ? '压缩包最多 100 个文档、解压后 300MB。' : '单个文件不超过 100MB。'}
          </p>
        </Upload.Dragger>

        {taskDocuments.length > 0 && (
          <div className="existing-document-list">
            <strong>已纳入本项检查的文档</strong>
            {taskDocuments.map(document => (
              <div key={document.id}>
                <span><FileTextOutlined /> {document.file_name}</span>
                <div className="existing-document-meta">
                  <em>
                    {document.extraction
                      ? `${document.extraction.analysis_mode === 'deep' ? '深度' : '标准'} · ${document.extraction.page_count || 0} 页 · 原生 ${document.extraction.native_blocks || 0} · OCR ${document.extraction.ocr_blocks || 0} · 视觉 ${Math.max((document.extraction.vision_blocks || 0) - (document.extraction.ocr_blocks || 0), 0)} · 向量${document.extraction.embedding_status === 'ready' ? '就绪' : '不可用'}`
                      : '等待解析'}
                  </em>
                  {document.classification && (
                    <Tag color={document.classification.naming_status === 'filename_warning' ? 'warning' : 'cyan'}>
                      {document.classification.document_name || '未归类'}
                      {document.classification.naming_status === 'filename_warning' ? ' · 命名不规范' : ''}
                    </Tag>
                  )}
                </div>
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<CloseOutlined />}
                  onClick={() => handleDeleteDocument(document.id)}
                  aria-label={`删除 ${document.file_name}`}
                />
              </div>
            ))}
          </div>
        )}
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
        okText={executeTask?.task_type === GAP_TECH_BATCH_TYPE ? '提交五项检测' : '开始执行'}
        cancelText="取消"
        width={600}
        destroyOnClose
      >
        <div style={{ marginBottom: 16, color: 'rgba(255,255,255,0.7)' }}>
          {executeTask?.task_type === GAP_TECH_BATCH_TYPE
            ? '选择本次测评资产并配置 SSH 凭证。无凭证时端口、漏洞、弱口令和 SSL/TLS 仍会执行，基线检查会明确标记为无法检测。'
            : '选择检查模式，系统将根据任务类型自动调用相应的安全工具。'}
        </div>
        
        <Form layout="vertical">
          {executeTask?.task_type !== GAP_TECH_BATCH_TYPE && <Form.Item label="检查模式">
            <Radio.Group 
              value={executeMode} 
              onChange={(e) => setExecuteMode(e.target.value)}
              disabled={executing}
            >
              <Radio.Button value="single">单项资产</Radio.Button>
              <Radio.Button value="all">全部资产</Radio.Button>
            </Radio.Group>
          </Form.Item>}

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

          {SSH_CREDENTIAL_TASK_TYPES.includes(executeTask?.task_type) && (
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
