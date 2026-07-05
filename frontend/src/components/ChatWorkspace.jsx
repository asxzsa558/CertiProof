import { useState, useRef, useEffect } from 'react'
import { Input, Button, Avatar, Spin, Empty, Typography, Progress, Tag, message, Modal, Checkbox, Dropdown, Popconfirm, Drawer, Steps, Form } from 'antd'
import {
  SendOutlined,
  UserOutlined,
  RobotOutlined,
  CheckCircleOutlined,
  CheckCircleFilled,
  PlayCircleOutlined,
  HistoryOutlined,
  SwapOutlined,
  DeleteOutlined,
  FolderOutlined,
  RocketOutlined,
  FileTextOutlined,
  DownOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import VeriSureLogo from './VeriSureLogo'
import AssetCredentialModal from './AssetCredentialModal'
import ResultMessageRenderer from './ResultMessageRenderer'
import DiagnosticResultCard from './DiagnosticResultCard'
import TaskStatusCard from './TaskStatusCard'
import { createTaskResultMessage, pollTaskResultUntilDone } from './chatTaskUtils'
import {
  TOOL_CATALOG,
  SYSTEM_COMMANDS,
  TOOL_BY_COMMAND,
  COMMAND_TO_CAPABILITY,
  SUGGESTIONS,
  MORE_SUGGESTIONS,
  SLASH_COMMANDS,
  normalizeScanPortRange,
  buildToolActionText,
  CAPABILITY_NAMES,
} from './chatCommandConfig'
import './ChatWorkspace.css'
import './ScanAnimation.css'

const assetKey = (asset) => String(asset?.value || asset?.target || '').trim().toLowerCase()

const dedupeAssets = (assets = []) => {
  const seen = new Set()
  return assets.filter(asset => {
    const key = assetKey(asset)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function ChatWorkspace({ projectId, projectName, modelId }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [inputHistory, setInputHistory] = useState([])
  const [historyIndex, setHistoryIndex] = useState(null)

  const [currentModelId, setCurrentModelId] = useState(modelId || null)
  const [lastRequest, setLastRequest] = useState({ message: '', timestamp: 0 })
  const [showCommandPalette, setShowCommandPalette] = useState(false)
  const [commandFilter, setCommandFilter] = useState('')
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0)
  const [assetSelectorVisible, setAssetSelectorVisible] = useState(false)
  const [assetSelectorAssets, setAssetSelectorAssets] = useState([])
  const [assetSelectorSelected, setAssetSelectorSelected] = useState([])
  const [assetSelectorCommand, setAssetSelectorCommand] = useState('')
  const [assetSelectorParameters, setAssetSelectorParameters] = useState({})
  const [sshCredentialVisible, setSshCredentialVisible] = useState(false)
  const [sshCredentialTarget, setSshCredentialTarget] = useState('')
  const [sshCredentialCommand, setSshCredentialCommand] = useState('')
  const [sshUsername, setSshUsername] = useState('root')
  const [sshPassword, setSshPassword] = useState('')
  const [sshKeyFile, setSshKeyFile] = useState('')
  const [sshPort, setSshPort] = useState(22)
  
  // Per-Asset 凭据配置
  const [credentialModalVisible, setCredentialModalVisible] = useState(false)
  const [credentialAssets, setCredentialAssets] = useState([])
  const [credentialCommand, setCredentialCommand] = useState('')
  const [compressionStatus, setCompressionStatus] = useState(null) // null | 'started' | 'completed'
  const [compressionInfo, setCompressionInfo] = useState(null) // { tokens_freed, message_count }
  const [archives, setArchives] = useState([])
  const [threads, setThreads] = useState([])
  const [currentThreadId, setCurrentThreadId] = useState(null)
  const [showArchivePanel, setShowArchivePanel] = useState(false)
  const [showThreadPanel, setShowThreadPanel] = useState(false)
  const [assessment, setAssessment] = useState(null)
  const [assessmentPhases, setAssessmentPhases] = useState([])
  const [assessmentDrawerVisible, setAssessmentDrawerVisible] = useState(false)
  const [assessmentLoading, setAssessmentLoading] = useState(false)
  const messagesEndRef = useRef(null)
  const wsRef = useRef(null)
  const pollRef = useRef(null)
  const completedTaskIdsRef = useRef(new Set())
  const inputRef = useRef(null)

  const rememberInput = (text) => {
    const value = (text || '').trim()
    if (!value) return
    setInputHistory(prev => (prev[prev.length - 1] === value ? prev : [...prev.slice(-49), value]))
    setHistoryIndex(null)
  }

  const buildMultiAssetActionText = (capability, count, allSelected) => {
    const name = CAPABILITY_NAMES[capability] || capability
    return `${allSelected ? '对项目所有资产' : '对选定资产'} (${count} 个) 执行${name}`
  }

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Load history on mount (key prop ensures remount on project change)
  useEffect(() => {
    const loadHistory = async () => {
      console.log('[ChatWorkspace] loadHistory called, projectId:', projectId)
      if (!projectId) {
        console.log('[ChatWorkspace] No projectId, showing welcome message')
        setMessages([
          {
            role: 'assistant',
            content: '你好！我是 VeriSure 智能合规验证助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
          },
        ])
        return
      }
      
      try {
        console.log('[ChatWorkspace] Fetching history for project_id:', projectId)
        const response = await api.get('/chat/history', { params: { project_id: projectId } })
        console.log('[ChatWorkspace] History response:', response.data.length, 'messages')
        const history = response.data
        
        let nextMessages
        if (history && history.length > 0) {
          nextMessages = history.map(h => ({
            role: h.role,
            content: h.content,
            id: h.id,
            // 从 context_snapshot 恢复任务结果
            isResult: h.context_snapshot?.scan_results ? true : false,
            scanResults: h.context_snapshot?.scan_results || {},
            isMultiAsset: h.context_snapshot?.is_multi_asset || false,
          }))
        } else {
          nextMessages = [
            {
              role: 'assistant',
              content: '你好！我是 VeriSure 智能合规验证助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
            },
          ]
        }

        let runningTasks = []
        try {
          const statusResponse = await api.get('/chat/status')
          runningTasks = (statusResponse.data.running || []).filter(t => t.task_id)
        } catch (statusError) {
          console.error('Failed to load running tasks:', statusError)
        }
        if (runningTasks.length > 0) {
          runningTasks.forEach(task => completedTaskIdsRef.current.delete(task.task_id))
          nextMessages = [
            ...nextMessages,
            ...runningTasks.map(task => ({
              role: 'assistant',
              content: task.current_step || '任务恢复中...',
              taskId: task.task_id,
              taskStatus: 'running',
              currentStep: task.current_step || '任务执行中...',
              stepProgress: task.step_progress || { step_index: 0, total_steps: 1, steps: [] },
            })),
          ]
        }

        setMessages(nextMessages)
        runningTasks.forEach(task => connectWebSocket(task.task_id))
      } catch (error) {
        console.error('Failed to load chat history:', error)
        setMessages([
          {
            role: 'assistant',
            content: '你好！我是 VeriSure 智能合规验证助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
          },
        ])
      }
    }
    
    loadHistory()
  }, [projectId])

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (pollRef.current) {
        clearTimeout(pollRef.current)
      }
    }
  }, [])

  const handleSend = async (text = null) => {
    const messageText = text || input.trim()
    if (!messageText || loading) return
    rememberInput(messageText)

    // 检测诊断命令
    if (messageText === '/diagnose') {
      await handleDiagnose()
      return
    }

    // 检测 ping 命令
    if (messageText.startsWith('/ping')) {
      const target = messageText.slice(5).trim()
      if (target) {
        await handlePing(target)
      } else {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: '请指定 ping 目标，例如：/ping 192.168.1.1',
        }])
      }
      return
    }

    // 检测扫描命令
    const scanCommands = TOOL_CATALOG.map(tool => tool.command).sort((a, b) => b.length - a.length)
    const matchedCommand = scanCommands.find(cmd => messageText === cmd || messageText.startsWith(cmd + ' '))
    if (matchedCommand) {
      const matchedTool = TOOL_BY_COMMAND[matchedCommand]
      const target = messageText.slice(matchedCommand.length).trim()
      if (target) {
        // 有指定目标
        if (matchedTool?.requiresSsh) {
          // 需要 SSH 凭证的命令，弹出凭证输入框
          setSshCredentialTarget(target)
          setSshCredentialCommand(matchedCommand)
          setSshCredentialVisible(true)
        } else {
          // 不需要 SSH 凭证，直接发送
          const isScanCommand = matchedCommand === '/scan' || matchedCommand === '/scan-full'
          const scanParts = isScanCommand ? target.split(/\s+/) : []
          const scanTarget = scanParts[0]
          const scanPortRange = matchedCommand === '/scan-full'
            ? '1-65535'
            : normalizeScanPortRange(scanParts[1])

          if (matchedCommand === '/scan' && scanParts.length === 1) {
            const projectAssetPortRange = normalizeScanPortRange(scanParts[0])
            if (projectAssetPortRange) {
              await openAssetSelector(matchedCommand, { port_range: projectAssetPortRange })
              return
            }
          }

          const translatedText = buildToolActionText(matchedCommand, target, {
            scanTarget,
            portRange: scanPortRange || 'high-risk',
          })
          await handleSendToAI(translatedText)
        }
      } else {
        // 无目标，弹出资产选择对话框
        const selectorParameters = matchedCommand === '/scan'
          ? { port_range: 'high-risk' }
          : (matchedTool?.parameters || {})
        await openAssetSelector(matchedCommand, selectorParameters)
      }
      return
    }

    await handleSendToAI(messageText)
  }

  const handleDiagnose = async () => {
    rememberInput('/diagnose')
    setMessages(prev => [...prev, { role: 'user', content: '/diagnose' }])
    setInput('')
    setLoading(true)

    try {
      const response = await api.get('/diagnostics/mcp/health')
      const data = response.data
      
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '',
        isDiagnostic: true,
        diagnosticData: data,
      }])
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `诊断失败: ${error.response?.data?.detail || error.message}`,
        isError: true,
      }])
    } finally {
      setLoading(false)
    }
  }

  const handlePing = async (target) => {
    rememberInput(`/ping ${target}`)
    setMessages(prev => [...prev, { role: 'user', content: `/ping ${target}` }])
    setInput('')
    setLoading(true)

    try {
      const response = await api.post('/chat/', {
        message: `ping ${target}`,
        project_id: projectId,
      })
      
      const aiResponse = response.data.response
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: aiResponse,
      }])
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Ping 失败: ${error.response?.data?.detail || error.message}`,
        isError: true,
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleSendToAI = async (messageText) => {
    // 防重复
    const now = Date.now()
    if (messageText === lastRequest.message && 
        (now - lastRequest.timestamp) < 5000) {
      return
    }
    
    setLastRequest({ message: messageText, timestamp: now })

    const userMessage = { role: 'user', content: messageText }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      const response = await api.post('/chat/', {
        message: messageText,
        project_id: projectId,
        model_id: currentModelId,
        thread_id: currentThreadId,
      })

      const taskId = response.data.task_id
      const aiResponse = response.data.response

      // 添加 AI 回复消息
      const assistantMessage = {
        role: 'assistant',
        content: aiResponse,
        taskId: taskId,  // 保存 task_id
        taskStatus: taskId ? 'running' : undefined,
        currentStep: taskId ? '正在准备执行...' : undefined,
        stepProgress: taskId ? { step_index: 0, total_steps: 1, steps: [] } : undefined,
      }
      setMessages((prev) => [...prev, assistantMessage])

      // 如果有 task_id，先尝试 WebSocket，失败则降级为轮询
      if (taskId) {
        connectWebSocket(taskId)
      }

      // ponytail: server project_id override removed — prop is the sole source of truth
    } catch (error) {
      const errorMessage = {
        role: 'assistant',
        content: `抱歉，处理请求时出错：${error.response?.data?.detail || error.message || '未知错误'}`,
        isError: true,
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }

  const openAssetSelector = async (command, parameters = {}) => {
    if (!projectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目',
        isError: true,
      }])
      return
    }
    
    try {
      const response = await api.get(`/projects/${projectId}/assets/`)
      const assets = response.data
      
      if (assets.length === 0) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: '当前项目暂无资产，请先添加资产',
        }])
        return
      }
      
      setAssetSelectorAssets(assets)
      setAssetSelectorSelected(assets.map(a => a.id))
      setAssetSelectorCommand(command)
      setAssetSelectorParameters(parameters)
      setAssetSelectorVisible(true)
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `获取资产列表失败：${error.response?.data?.detail || error.message || '未知错误'}`,
        isError: true,
      }])
    }
  }

  const handleAssetSelectorConfirm = async () => {
    setAssetSelectorVisible(false)
    const selectedAssets = dedupeAssets(assetSelectorAssets.filter(a => assetSelectorSelected.includes(a.id)))
    
    if (selectedAssets.length === 0) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '未选择任何资产',
      }])
      return
    }
    
    // 检查是否需要 SSH 凭证
    if (TOOL_BY_COMMAND[assetSelectorCommand]?.requiresSsh) {
      // 打开 Per-Asset 凭据配置弹窗
      setCredentialAssets(selectedAssets)
      setCredentialCommand(assetSelectorCommand)
      setCredentialModalVisible(true)
    } else {
      await handleMultiAssetScan(assetSelectorCommand, selectedAssets, assetSelectorParameters)
    }
  }

  // Per-Asset 凭据配置确认
  const handleCredentialConfirm = async (assetsWithCredentials) => {
    setCredentialModalVisible(false)
    
    if (!projectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目',
        isError: true,
      }])
      return
    }
    
    const capability = COMMAND_TO_CAPABILITY[credentialCommand]
    const uniqueAssets = dedupeAssets(assetsWithCredentials)
    const sshCount = uniqueAssets.filter(a => a.ssh_credential).length
    const skipCount = uniqueAssets.filter(a => !a.ssh_credential).length
    
    const sshInfo = sshCount > 0
      ? `（${sshCount} 个资产提供 SSH 凭据${skipCount > 0 ? `，${skipCount} 个跳过基线检查` : ''}）`
      : '（未提供 SSH 凭据，将跳过安全基线检查）'
    
    const targetDesc = buildMultiAssetActionText(
      capability,
      uniqueAssets.length,
      uniqueAssets.length === dedupeAssets(assetSelectorAssets).length,
    )
    
    try {
      const userMessage = {
        role: 'user',
        content: `${targetDesc}。${sshInfo}`,
        isMultiAsset: true,
        totalAssets: uniqueAssets.length,
      }
      setMessages(prev => [...prev, userMessage])
      setInput('')
      setLoading(true)
      
      const scanResponse = await api.post('/chat/', {
        message: JSON.stringify({
          type: 'multi_asset_scan',
          capability: capability,
          assets: uniqueAssets,
        }),
        project_id: projectId,
      })
      
      const taskId = scanResponse.data.task_id
      const aiResponse = scanResponse.data.response
      
      const assistantMessage = {
        role: 'assistant',
        content: aiResponse || `开始${CAPABILITY_NAMES[capability] || capability}，共 ${uniqueAssets.length} 个资产`,
        taskId: taskId,
        taskStatus: taskId ? 'running' : undefined,
        isMultiAsset: true,
        totalAssets: uniqueAssets.length,
        assetProgress: {},
      }
      setMessages(prev => [...prev, assistantMessage])
      
      if (taskId) {
        connectWebSocket(taskId)
      }
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `扫描失败：${error.response?.data?.detail || error.message}`,
        isError: true,
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleMultiAssetScan = async (command, selectedAssets, parameters = {}) => {
    if (!projectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目',
        isError: true,
      }])
      return
    }
    
    const assets = dedupeAssets(selectedAssets || [])
    if (assets.length === 0) return
    
    const capability = COMMAND_TO_CAPABILITY[command]
    const targetDesc = buildMultiAssetActionText(capability, assets.length, assets.length === dedupeAssets(assetSelectorAssets).length)
    
    try {
      const userMessage = {
        role: 'user',
        content: targetDesc,
        isMultiAsset: true,
        totalAssets: assets.length,
      }
      setMessages(prev => [...prev, userMessage])
      setInput('')
      setLoading(true)
      
      const scanResponse = await api.post('/chat/', {
        message: JSON.stringify({
          type: 'multi_asset_scan',
          capability: capability,
          parameters: parameters,
          assets: assets.map(a => ({ id: a.id, value: a.value, type: a.asset_type })),
        }),
        project_id: projectId,
      })
      
      const taskId = scanResponse.data.task_id
      const aiResponse = scanResponse.data.response
      
      const assistantMessage = {
        role: 'assistant',
        content: aiResponse || `开始${CAPABILITY_NAMES[capability] || capability}，共 ${assets.length} 个资产`,
        taskId: taskId,
        taskStatus: taskId ? 'running' : undefined,
        isMultiAsset: true,
        totalAssets: assets.length,
        assetProgress: {},
      }
      setMessages(prev => [...prev, assistantMessage])
      
      if (taskId) {
        connectWebSocket(taskId)
      }
      
    } catch (error) {
      console.error('Multi-asset scan failed:', error)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `多资产扫描失败：${error.response?.data?.detail || error.message || '未知错误'}`,
        isError: true,
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleSshCredentialConfirm = async () => {
    setSshCredentialVisible(false)
    
    if (!sshUsername) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请输入 SSH 用户名',
        isError: true,
      }])
      return
    }
    
    if (!sshPassword && !sshKeyFile) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请输入 SSH 密码或密钥文件路径',
        isError: true,
      }])
      return
    }
    
    // 构建 SSH 凭证信息
    const sshCredentialInfo = `SSH用户名: ${sshUsername}, ${sshPassword ? '密码: ******' : `密钥文件: ${sshKeyFile}`}, 端口: ${sshPort}`
    
    // 根据目标类型构建消息
    let targetMessage = ''
    if (sshCredentialTarget === 'selected_assets') {
      // 从资产选择器选择的多资产
      const selectedAssets = dedupeAssets(assetSelectorAssets.filter(a => assetSelectorSelected.includes(a.id)))
      const assetValues = selectedAssets.map(a => a.value).join('、')
      targetMessage = `对 ${assetValues} 执行等保技术测评（10项检查）。${sshCredentialInfo}`
      await handleMultiAssetScanWithSsh(sshCredentialCommand, selectedAssets, sshCredentialInfo)
    } else {
      // 单个目标
      const commandTexts = {
        '/baseline': `对 ${sshCredentialTarget} 进行安全基线核查（自动识别操作系统）。${sshCredentialInfo}`,
        '/tech': `对 ${sshCredentialTarget} 进行等保技术测评（10项检查）。${sshCredentialInfo}`,
        '/ssh': `对 ${sshCredentialTarget} 进行SSH配置检查。${sshCredentialInfo}`,
      }
      targetMessage = commandTexts[sshCredentialCommand] || `对 ${sshCredentialTarget} 执行 ${sshCredentialCommand}`
      await handleSendToAI(targetMessage)
    }
    
    // 重置 SSH 凭证表单
    setSshUsername('root')
    setSshPassword('')
    setSshKeyFile('')
    setSshPort(22)
  }

  const handleMultiAssetScanWithSsh = async (command, selectedAssets, sshCredentialInfo) => {
    if (!projectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目',
        isError: true,
      }])
      return
    }
    
    const assets = dedupeAssets(selectedAssets || [])
    if (assets.length === 0) return
    
    const capability = COMMAND_TO_CAPABILITY[command]
    const targetDesc = buildMultiAssetActionText(capability, assets.length, assets.length === dedupeAssets(assetSelectorAssets).length)
    
    try {
      const userMessage = {
        role: 'user',
        content: `${targetDesc}。${sshCredentialInfo}`,
        isMultiAsset: true,
        totalAssets: assets.length,
      }
      setMessages(prev => [...prev, userMessage])
      setInput('')
      setLoading(true)
      
      const scanResponse = await api.post('/chat/', {
        message: JSON.stringify({
          type: 'multi_asset_scan',
          capability: capability,
          assets: assets.map(a => ({ id: a.id, value: a.value, type: a.asset_type })),
          ssh_credential: {
            username: sshUsername,
            password: sshPassword,
            key_file: sshKeyFile,
            port: sshPort,
          },
        }),
        project_id: projectId,
      })
      
      const taskId = scanResponse.data.task_id
      const aiResponse = scanResponse.data.response
      
      const assistantMessage = {
        role: 'assistant',
        content: aiResponse || `开始${CAPABILITY_NAMES[capability] || capability}，共 ${assets.length} 个资产`,
        taskId: taskId,
        taskStatus: taskId ? 'running' : undefined,
        isMultiAsset: true,
        totalAssets: assets.length,
        assetProgress: {},
      }
      setMessages(prev => [...prev, assistantMessage])
      
      if (taskId) {
        connectWebSocket(taskId)
      }
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `扫描失败：${error.response?.data?.detail || error.message}`,
        isError: true,
      }])
    } finally {
      setLoading(false)
    }
  }

  const connectWebSocket = (taskId) => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsHost = window.location.host
    const wsUrl = `${protocol}//${wsHost}/api/v1/ws/agents/${taskId}`

    let wsConnected = false

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      startPollingFallback(taskId)

      ws.onopen = () => {
        wsConnected = true
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)

          if (msg.type === 'status') {
            const data = msg.data
            
            // 处理任务暂停
            if (data.type === 'task_paused') {
              setMessages(prev => prev.map(m =>
                m.taskId === taskId ? { ...m, taskStatus: 'paused' } : m
              ))
            }
            // 处理任务恢复
            else if (data.type === 'task_resumed') {
              setMessages(prev => prev.map(m =>
                m.taskId === taskId ? { ...m, taskStatus: 'running' } : m
              ))
            }
            // 处理任务停止
            else if (data.type === 'task_stopped') {
              setMessages(prev => prev.map(m =>
                m.taskId === taskId ? { ...m, taskStatus: 'stopped', taskCompleted: true } : m
              ))
            }
            // 处理多资产进度
            else if (data.type === 'multi_asset_progress') {
              setMessages(prev => prev.map(m => {
                if (m.taskId === taskId) {
                  return {
                    ...m,
                    assetProgress: {
                      ...m.assetProgress,
                      [data.asset_index]: {
                        name: data.asset_name,
                        status: data.status,
                        capability: data.capability,
                      }
                    }
                  }
                }
                return m
              }))
            } else {
              // 原有单资产进度处理
              setMessages(prev => prev.map(m =>
                m.taskId === taskId ? {
                  ...m,
                  currentStep: data.display_name ? `正在执行: ${data.display_name}...` : data.current_step,
                  stepProgress: data.total_steps ? {
                    step_index: data.step_index || 0,
                    total_steps: data.total_steps,
                    steps: data.steps || [],
                  } : m.stepProgress,
                } : m
              ))
            }
          } else if (msg.type === 'completed') {
            const hasCompletedPayload = !!(
              msg.data?.result_description ||
              (msg.data?.scan_results && Object.keys(msg.data.scan_results).length > 0)
            )
            if (!hasCompletedPayload) {
              setMessages(prev => prev.map(m =>
                m.taskId === taskId ? { ...m, taskCompleted: true, taskStatus: 'completed' } : m
              ))
              startPollingFallback(taskId)
              return
            }
            if (completedTaskIdsRef.current.has(taskId)) return
            completedTaskIdsRef.current.add(taskId)
            ws.close()
            wsRef.current = null

            setMessages(prev => prev.map(m =>
              m.taskId === taskId ? { ...m, taskCompleted: true, taskStatus: 'completed' } : m
            ))

            setMessages(prev => [...prev, createTaskResultMessage({
              resultDescription: msg.data?.result_description,
              scanResults: msg.data?.scan_results || {},
              isMultiAsset: msg.data?.is_multi_asset,
            })])
          } else if (msg.type === 'failed') {
            ws.close()
            wsRef.current = null

            setMessages(prev => prev.map(m =>
              m.taskId === taskId ? { ...m, taskCompleted: true, taskStatus: 'failed' } : m
            ))

            setMessages(prev => [...prev, {
              role: 'assistant',
              content: `任务执行失败：${msg.data?.error || '未知错误'}`,
              isError: true,
            }])
          } else if (msg.type === 'compression_status') {
            // 处理上下文压缩状态
            const data = msg.data
            if (data.status === 'started') {
              setCompressionStatus('started')
              setCompressionInfo(null)
            } else if (data.status === 'completed') {
              setCompressionStatus('completed')
              setCompressionInfo({
                tokens_freed: data.tokens_freed,
                message_count: data.message_count,
              })
              // 3秒后清除压缩完成提示
              setTimeout(() => {
                setCompressionStatus(null)
                setCompressionInfo(null)
              }, 3000)
            }
          }
        } catch (e) {
          console.error('WebSocket message parse error:', e)
        }
      }

      ws.onerror = () => {
        if (!wsConnected) {
          startPollingFallback(taskId)
        }
      }

      ws.onclose = () => {
        if (wsRef.current === ws) {
          wsRef.current = null
        }
      }

      setTimeout(() => {
        if (!wsConnected && wsRef.current === ws) {
          ws.close()
          wsRef.current = null
          startPollingFallback(taskId)
        }
      }, 3000)
    } catch (e) {
      startPollingFallback(taskId)
    }
  }

  const startPollingFallback = (taskId) => {
    if (pollRef.current) {
      clearTimeout(pollRef.current)
      pollRef.current = null
    }
    pollTaskResultUntilDone({
      api,
      taskId,
      setMessages,
      completedTaskIdsRef,
      pollRef,
    })
  }

  const filteredCommands = SLASH_COMMANDS.filter(cmd => 
    cmd.command.includes(commandFilter.toLowerCase()) || 
    cmd.description.includes(commandFilter.toLowerCase())
  )

  const handleInputChange = (e) => {
    const value = e.target.value
    setHistoryIndex(null)
    setInput(value)
    
    if (value.startsWith('/')) {
      setShowCommandPalette(true)
      setCommandFilter(value.slice(1))
      setSelectedCommandIndex(0)
    } else {
      setShowCommandPalette(false)
    }
  }

  const handleClearHistory = async () => {
    try {
      if (projectId) {
        await api.post(`/chat/clear/${projectId}`)
      } else {
        await api.post('/chat/clear')
      }
      setMessages([{
        role: 'assistant',
        content: '对话历史已清空。',
      }])
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '清理失败，请重试。',
        isError: true,
      }])
    }
  }

  const handleListAssets = async () => {
    if (!projectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目。',
      }])
      return
    }
    try {
      const response = await api.get(`/projects/${projectId}/assets/`)
      const assets = response.data
      if (assets.length === 0) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: '当前项目暂无资产。',
        }])
      } else {
        const text = assets.map(a => 
          `[${a.asset_type}] ${a.value}${a.name ? ` (${a.name})` : ''}`
        ).join('\n')
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: `当前项目共 ${assets.length} 个资产：\n\n${text}`,
        }])
      }
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '获取资产列表失败。',
        isError: true,
      }])
    }
  }

  const fetchAssessment = async () => {
    if (!projectId) return null
    try {
      const response = await api.get(`/assessments/projects/${projectId}`)
      if (response.data && response.data.length > 0) {
        const latestAssessment = response.data[0]
        const phasesResponse = await api.get(`/assessments/${latestAssessment.id}/phases`)
        return { assessment: latestAssessment, phases: phasesResponse.data }
      }
      return null
    } catch (error) {
      console.error('Failed to fetch assessment:', error)
      return null
    }
  }

  const handleAssessmentAction = async () => {
    if (!projectId) {
      message.warning('请先选择项目')
      return
    }
    
    setAssessmentLoading(true)
    try {
      const result = await fetchAssessment()
      
      if (result) {
        setAssessment(result.assessment)
        setAssessmentPhases(result.phases)
        setAssessmentDrawerVisible(true)
      } else {
        const projectRes = await api.get(`/projects/${projectId}`)
        const project = projectRes.data
        const complianceLevel = project.compliance_level
        const targetLevel = complianceLevel === '二级' ? 2 : 3
        
        const templatesRes = await api.get('/assessments/templates')
        const templates = templatesRes.data
        const template = templates.find(t => t.compliance_level === targetLevel)
        
        if (!template) {
          message.error('未找到匹配的测评模板')
          return
        }
        
        const createRes = await api.post(`/assessments/projects/${projectId}`, {
          template_id: template.id,
          name: `${projectName || project.name} - 等保${complianceLevel}测评`,
        })
        
        const newAssessment = createRes.data
        const phasesRes = await api.get(`/assessments/${newAssessment.id}/phases`)
        
        setAssessment(newAssessment)
        setAssessmentPhases(phasesRes.data)
        setAssessmentDrawerVisible(true)
        message.success('测评流程已创建')
      }
    } catch (error) {
      console.error('Assessment action failed:', error)
      message.error('操作失败，请重试')
    } finally {
      setAssessmentLoading(false)
    }
  }

  const handleShowHelp = () => {
    const toolText = TOOL_CATALOG.map(tool => `${tool.usage} - ${tool.description}`).join('\n')
    const systemText = SYSTEM_COMMANDS.map(cmd => `${cmd.usage} - ${cmd.description}`).join('\n')
    const helpText = `可用命令：\n\n${toolText}\n\n系统命令：\n${systemText}`
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: helpText,
    }])
  }

  const executeCommand = (cmd) => {
    setShowCommandPalette(false)
    setInput('')
    
    if (cmd.direct) {
      if (cmd.command === '/clear') {
        handleClearHistory()
      } else if (cmd.command === '/assets') {
        handleListAssets()
      } else if (cmd.command === '/assessment') {
        handleAssessmentAction()
      } else if (cmd.command === '/diagnose') {
        handleDiagnose()
      } else if (cmd.command === '/help') {
        handleShowHelp()
      }
    } else {
      handleSend(cmd.defaultText)
    }
  }

  const handleKeyPress = (e) => {
    if (showCommandPalette) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedCommandIndex(prev => Math.min(prev + 1, filteredCommands.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedCommandIndex(prev => Math.max(prev - 1, 0))
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        if (filteredCommands[selectedCommandIndex]) {
          executeCommand(filteredCommands[selectedCommandIndex])
        }
      } else if (e.key === 'Escape') {
        e.preventDefault()
        setShowCommandPalette(false)
        setInput('')
      }
    } else if (e.key === 'ArrowUp') {
      if (inputHistory.length > 0) {
        e.preventDefault()
        const nextIndex = historyIndex === null ? inputHistory.length - 1 : Math.max(historyIndex - 1, 0)
        setHistoryIndex(nextIndex)
        setInput(inputHistory[nextIndex])
      }
    } else if (e.key === 'ArrowDown' && historyIndex !== null) {
      e.preventDefault()
      const nextIndex = historyIndex + 1
      if (nextIndex >= inputHistory.length) {
        setHistoryIndex(null)
        setInput('')
      } else {
        setHistoryIndex(nextIndex)
        setInput(inputHistory[nextIndex])
      }
    } else if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent?.isComposing) {
      e.preventDefault()
      e.stopPropagation()
      handleSend()
    }
  }

  const handlePauseTask = async (taskId) => {
    try {
      await api.post(`/tasks/${taskId}/pause`)
      setMessages(prev => prev.map(m =>
        m.taskId === taskId ? { ...m, taskStatus: 'paused' } : m
      ))
      message.success('任务已暂停')
    } catch (error) {
      message.error('暂停失败')
    }
  }

  const handleStopTask = async (taskId) => {
    try {
      await api.post(`/tasks/${taskId}/stop`)
      setMessages(prev => prev.map(m =>
        m.taskId === taskId ? { ...m, taskStatus: 'stopped' } : m
      ))
      message.success('任务已停止')
    } catch (error) {
      message.error('停止失败')
    }
  }

  const handleResumeTask = async (taskId) => {
    try {
      await api.post(`/tasks/${taskId}/resume`)
      setMessages(prev => prev.map(m =>
        m.taskId === taskId ? { ...m, taskStatus: 'running' } : m
      ))
      message.success('任务已恢复')
    } catch (error) {
      message.error('恢复失败')
    }
  }

  // ==================== 归档管理 ====================

  const handleCreateArchive = async () => {
    try {
      // 1. 创建归档（立即返回）
      const response = await api.post('/chat/archives', { title: null })
      const archiveId = response.data.archive_id
      
      // 2. 显示"正在生成摘要..."
      message.loading({ content: '正在生成归档摘要...', key: 'archive', duration: 0 })
      
      // 3. 清空当前对话
      setMessages([{
        role: 'assistant',
        content: '对话已归档，正在生成摘要...',
      }])
      
      // 4. 轮询直到摘要生成完成
      const maxAttempts = 15  // 最多等待 30 秒
      let attempts = 0
      
      const pollInterval = setInterval(async () => {
        attempts++
        try {
          const archiveRes = await api.get(`/chat/archives/${archiveId}`)
          if (archiveRes.data.summary) {
            clearInterval(pollInterval)
            message.success({ content: '归档完成', key: 'archive' })
            setMessages([{
              role: 'assistant',
              content: `对话已归档完成！\n\n**摘要**: ${archiveRes.data.summary}`,
            }])
            await loadArchives()
          } else if (attempts >= maxAttempts) {
            clearInterval(pollInterval)
            message.warning({ content: '摘要生成超时，归档已保存', key: 'archive' })
            await loadArchives()
          }
        } catch (e) {
          console.error('Poll archive error:', e)
        }
      }, 2000)
      
    } catch (error) {
      message.error(error.response?.data?.detail || '归档失败')
    }
  }

  const loadArchives = async () => {
    try {
      const params = projectId ? { project_id: projectId } : {}
      const response = await api.get('/chat/archives', { params })
      setArchives(response.data.archives || [])
    } catch (error) {
      console.error('Failed to load archives:', error)
    }
  }

  const handleDeleteArchive = async (archiveId) => {
    try {
      await api.delete(`/chat/archives/${archiveId}`)
      message.success('归档已删除')
      await loadArchives()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handleContinueFromArchive = async (archive) => {
    try {
      // 创建新线程，标题包含归档信息
      const threadTitle = `接续: ${archive.title}`
      const response = await api.post('/chat/threads', { 
        title: threadTitle, 
        parent_thread_id: currentThreadId 
      })
      setCurrentThreadId(response.data.thread_id)
      
      // 构建接续消息
      let continueMsg = `📋 已接续归档「${archive.title}」\n\n`
      continueMsg += `**工作状态**: ${archive.summary}\n\n`
      
      if (archive.completed_tasks && archive.completed_tasks.length > 0) {
        continueMsg += `**已完成**:\n`
        archive.completed_tasks.forEach(t => {
          continueMsg += `- ${t.task}: ${t.result}\n`
        })
        continueMsg += '\n'
      }
      
      if (archive.current_task) {
        continueMsg += `**进行中**: ${archive.current_task.task} - ${archive.current_task.progress}\n\n`
      }
      
      if (archive.interrupt_point) {
        continueMsg += `**中断点**: ${archive.interrupt_point}\n\n`
      }
      
      continueMsg += '告诉我"继续"即可接续之前的工作。'
      
      setMessages([{
        role: 'assistant',
        content: continueMsg,
      }])
      
      setShowArchivePanel(false)
      await loadThreads()
      message.success('已创建新线程并接续归档')
    } catch (error) {
      message.error('接续归档失败')
    }
  }

  // ==================== 线程管理 ====================

  const handleCreateThread = async () => {
    try {
      const response = await api.post('/chat/threads', { title: null, parent_thread_id: currentThreadId })
      setCurrentThreadId(response.data.thread_id)
      message.success('新线程已创建')
      // 清空当前对话
      setMessages([{
        role: 'assistant',
        content: '新线程已创建，开始新的对话吧！',
      }])
      await loadThreads()
    } catch (error) {
      message.error('创建线程失败')
    }
  }

  const loadThreads = async () => {
    try {
      const response = await api.get('/chat/threads')
      setThreads(response.data.threads || [])
    } catch (error) {
      console.error('Failed to load threads:', error)
    }
  }

  const handleSwitchThread = async (threadId) => {
    try {
      const response = await api.post(`/chat/threads/${threadId}/continue`)
      setCurrentThreadId(threadId)
      
      // 加载线程的对话历史
      const conversationHistory = response.data.conversation_history || []
      if (conversationHistory.length > 0) {
        // 显示历史对话
        setMessages(conversationHistory.map(h => ({
          role: h.role,
          content: h.content,
        })))
      } else {
        // 没有历史对话，显示提示信息
        const archiveSummary = response.data.archive_summary
        setMessages([{
          role: 'assistant',
          content: archiveSummary 
            ? `已接续线程上下文：\n\n${archiveSummary}`
            : '已切换到新线程，开始新的对话吧！',
        }])
      }
      
      setShowThreadPanel(false)
      message.success('线程已切换')
    } catch (error) {
      message.error('切换线程失败')
    }
  }

  const handleDeleteThread = async (threadId) => {
    try {
      await api.delete(`/chat/threads/${threadId}`)
      if (currentThreadId === threadId) {
        setCurrentThreadId(null)
      }
      message.success('线程已删除')
      await loadThreads()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const resultOrderByMessageIndex = new Map()
  messages.forEach((messageItem, messageIndex) => {
    if (messageItem.isResult) resultOrderByMessageIndex.set(messageIndex, resultOrderByMessageIndex.size)
  })
  const compactResultBefore = Math.max(0, resultOrderByMessageIndex.size - 5)

  return (
    <div className="chat-workspace">
      {/* 浮动操作按钮 - 归档/线程管理 */}
      <div className="floating-actions">
        <Dropdown
          menu={{
            items: [
              { key: 'archive', icon: <FolderOutlined />, label: '归档当前对话' },
              { key: 'view-archives', icon: <HistoryOutlined />, label: '查看归档' },
              { type: 'divider' },
              { key: 'new-thread', icon: <SwapOutlined />, label: '新建线程' },
              { key: 'view-threads', icon: <SwapOutlined />, label: '切换线程' },
            ],
            onClick: ({ key }) => {
              if (key === 'archive') handleCreateArchive()
              else if (key === 'view-archives') { loadArchives(); setShowArchivePanel(true) }
              else if (key === 'new-thread') handleCreateThread()
              else if (key === 'view-threads') { loadThreads(); setShowThreadPanel(true) }
            }
          }}
          trigger={['click']}
          placement="topRight"
        >
          <Button 
            type="text" 
            icon={<HistoryOutlined />} 
            className="floating-action-btn"
            title="对话管理"
          />
        </Dropdown>
      </div>

      {/* Archive Panel Modal */}
      <Modal
        title="对话归档"
        open={showArchivePanel}
        onCancel={() => setShowArchivePanel(false)}
        footer={null}
        className="archive-panel-modal"
        width={560}
      >
        {archives.length === 0 ? (
          <Empty description="暂无归档" />
        ) : (
          <div className="archive-list">
            {archives.map(archive => (
              <div key={archive.id} className="archive-item">
                <div className="archive-info">
                  <div className="archive-title">{archive.title}</div>
                  <div className="archive-summary">{archive.summary}</div>
                  
                  {/* 结构化交接信息 */}
                  {archive.completed_tasks && archive.completed_tasks.length > 0 && (
                    <div className="archive-section">
                      <span className="archive-section-label">已完成:</span>
                      {archive.completed_tasks.map((t, i) => (
                        <Tag key={i} color="green">{t.task}: {t.result}</Tag>
                      ))}
                    </div>
                  )}
                  
                  {archive.current_task && (
                    <div className="archive-section">
                      <span className="archive-section-label">进行中:</span>
                      <Tag color="processing">{archive.current_task.task}</Tag>
                      <span className="archive-detail">{archive.current_task.progress}</span>
                    </div>
                  )}
                  
                  {archive.interrupt_point && (
                    <div className="archive-section">
                      <span className="archive-section-label">中断点:</span>
                      <span className="archive-detail">{archive.interrupt_point}</span>
                    </div>
                  )}
                  
                  {archive.key_findings && archive.key_findings.length > 0 && (
                    <div className="archive-section">
                      <span className="archive-section-label">关键发现:</span>
                      {archive.key_findings.map((f, i) => (
                        <Tag key={i} color="blue">{f}</Tag>
                      ))}
                    </div>
                  )}
                  
                  <div className="archive-meta">
                    <Tag>{archive.message_count} 条消息</Tag>
                    <span className="archive-date">{new Date(archive.archived_at).toLocaleString()}</span>
                  </div>
                </div>
                <div className="archive-actions">
                  <Button
                    type="primary"
                    size="small"
                    icon={<SwapOutlined />}
                    onClick={() => handleContinueFromArchive(archive)}
                  >
                    接续
                  </Button>
                  <Button
                    type="text"
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    onClick={() => handleDeleteArchive(archive.id)}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* Thread Panel Modal */}
      <Modal
        title="对话线程"
        open={showThreadPanel}
        onCancel={() => setShowThreadPanel(false)}
        footer={null}
        className="thread-panel-modal"
      >
        {threads.length === 0 ? (
          <Empty description="暂无线程">
            <Button type="primary" onClick={handleCreateThread}>创建新线程</Button>
          </Empty>
        ) : (
          <div className="thread-list">
            {threads.map(thread => (
              <div key={thread.id} className={`thread-item ${currentThreadId === thread.id ? 'active' : ''}`}>
                <div className="thread-info" onClick={() => handleSwitchThread(thread.id)}>
                  <div className="thread-title">
                    {thread.title}
                    {currentThreadId === thread.id && <Tag color="blue">当前</Tag>}
                  </div>
                  <div className="thread-meta">
                    <span className="thread-date">创建于 {new Date(thread.created_at).toLocaleString()}</span>
                  </div>
                </div>
                <Popconfirm
                  title="确定要删除这个线程吗？"
                  onConfirm={() => handleDeleteThread(thread.id)}
                  okText="确定"
                  cancelText="取消"
                >
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* Messages */}
      <div className="workspace-messages">
        {messages.map((msg, index) => (
          <div key={index} className={`workspace-message ${msg.role}`}>
            <div className="message-avatar">
              {msg.role === 'user' ? (
                <Avatar size={32} style={{ background: 'rgba(255,255,255,0.1)' }} icon={<UserOutlined />} />
              ) : (
                <Avatar
                  size={32}
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
                  icon={<RobotOutlined />}
                />
              )}
            </div>
            <div className="message-body">
              {/* 诊断结果 */}
              {msg.isDiagnostic ? (
                <DiagnosticResultCard data={msg.diagnosticData} />
              ) : msg.isResult ? (
                <ResultMessageRenderer msg={msg} compact={resultOrderByMessageIndex.get(index) < compactResultBefore} />
              ) : (
                <>
                  <div className={`message-bubble ${msg.role} ${msg.isError ? 'error' : ''}`}>
                    {msg.content}
                  </div>
                  {/* 任务状态指示器 */}
                  {msg.taskId && (
                    <TaskStatusCard
                      msg={msg}
                      onPause={handlePauseTask}
                      onStop={handleStopTask}
                      onResume={handleResumeTask}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="workspace-message assistant">
            <div className="message-avatar">
              <Avatar
                size={32}
                style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
                icon={<RobotOutlined />}
              />
            </div>
            <div className="message-body">
              <div className="message-bubble assistant loading">
                <Spin size="small" />
                <span style={{ marginLeft: 8, color: 'rgba(255,255,255,0.6)' }}>思考中...</span>
              </div>
            </div>
          </div>
        )}
        
        {/* Compression Status Indicator */}
        {compressionStatus === 'started' && (
          <div className="workspace-message assistant">
            <div className="message-avatar">
              <Avatar
                size={32}
                style={{ background: 'linear-gradient(135deg, #f59e0b, #ef4444)' }}
                icon={<RobotOutlined />}
              />
            </div>
            <div className="message-body">
              <div className="message-bubble assistant compression-indicator">
                <Spin size="small" />
                <span style={{ marginLeft: 8, color: 'rgba(255,255,255,0.8)' }}>正在压缩上下文...</span>
              </div>
            </div>
          </div>
        )}
        
        {compressionStatus === 'completed' && compressionInfo && (
          <div className="workspace-message assistant">
            <div className="message-avatar">
              <Avatar
                size={32}
                style={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}
                icon={<CheckCircleOutlined />}
              />
            </div>
            <div className="message-body">
              <div className="message-bubble assistant compression-completed">
                <span style={{ color: 'rgba(255,255,255,0.9)' }}>
                  ✓ 上下文已压缩（释放 {compressionInfo.tokens_freed} tokens，压缩 {compressionInfo.message_count} 条消息）
                </span>
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="workspace-input-area">
        {/* Suggestions - always visible */}
        <div className="workspace-suggestions">
          <div className="suggestions-row">
            {SUGGESTIONS.map((s, i) => (
              <button
                key={i}
                className="suggestion-btn"
                onClick={() => s.action === 'assessment' ? handleAssessmentAction() : handleSend(s.text)}
                style={{ '--accent': s.color }}
              >
                <span className="suggestion-icon">{s.icon}</span>
                <span className="suggestion-text">{s.title}</span>
              </button>
            ))}
            {/* 更多检测下拉 */}
            <Dropdown
              menu={{ items: MORE_SUGGESTIONS.map((s, i) => ({
                key: `more-${i}`,
                label: (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: s.color, fontSize: 14 }}>{s.icon}</span>
                    <span>{s.title}</span>
                  </span>
                ),
                onClick: () => s.isText ? handleSend(s.text) : handleSend(s.text),
              })) }}
              placement="bottomRight"
              trigger={['click']}
            >
              <button
                className="suggestion-btn more-btn"
                style={{ '--accent': '#94a3b8' }}
              >
                <span className="suggestion-icon"><DownOutlined /></span>
                <span className="suggestion-text">更多检测</span>
              </button>
            </Dropdown>
          </div>
        </div>
        
        {/* Command Palette */}
        {showCommandPalette && filteredCommands.length > 0 && (
          <div className="command-palette">
            {filteredCommands.map((cmd, index) => (
              <div
                key={cmd.command}
                className={`command-item ${index === selectedCommandIndex ? 'selected' : ''}`}
                onClick={() => executeCommand(cmd)}
                onMouseEnter={() => setSelectedCommandIndex(index)}
              >
                <span className="command-name">{cmd.command}</span>
                <span className="command-desc">{cmd.description}</span>
                <span className="command-usage">{cmd.usage}</span>
              </div>
            ))}
          </div>
        )}
        <div className="input-row">
          <TextArea
            ref={inputRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyPress}
            placeholder={projectName ? `向 Agent 询问"${projectName}"的合规状态... 输入 / 查看快捷命令` : '向 Agent 询问合规相关问题... 输入 / 查看快捷命令'}
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            className="workspace-input"
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={() => handleSend()}
            loading={loading}
            disabled={!input.trim()}
            className="workspace-send-btn"
          >
            发送
          </Button>
        </div>
      </div>

      {/* Asset Selector Modal */}
      <Modal
        title="选择扫描资产"
        open={assetSelectorVisible}
        onOk={handleAssetSelectorConfirm}
        onCancel={() => setAssetSelectorVisible(false)}
        okText="开始扫描"
        cancelText="取消"
        className="asset-selector-modal"
      >
        <div style={{ marginBottom: 12 }}>
          <Checkbox
            indeterminate={assetSelectorSelected.length > 0 && assetSelectorSelected.length < assetSelectorAssets.length}
            checked={assetSelectorSelected.length === assetSelectorAssets.length}
            onChange={(e) => {
              if (e.target.checked) {
                setAssetSelectorSelected(assetSelectorAssets.map(a => a.id))
              } else {
                setAssetSelectorSelected([])
              }
            }}
          >
            全选 ({assetSelectorSelected.length}/{assetSelectorAssets.length})
          </Checkbox>
        </div>
        <div className="asset-selector-list">
          {assetSelectorAssets.map(asset => (
            <div key={asset.id} className="asset-selector-item">
              <Checkbox
                checked={assetSelectorSelected.includes(asset.id)}
                onChange={(e) => {
                  if (e.target.checked) {
                    setAssetSelectorSelected(prev => [...prev, asset.id])
                  } else {
                    setAssetSelectorSelected(prev => prev.filter(id => id !== asset.id))
                  }
                }}
              >
                <span className="asset-selector-value">{asset.value}</span>
                <Tag color="blue" style={{ marginLeft: 8 }}>{asset.asset_type}</Tag>
              </Checkbox>
            </div>
          ))}
        </div>
      </Modal>

      {/* Assessment Progress Drawer */}
      <Drawer
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <RocketOutlined style={{ color: '#f59e0b' }} />
            <span>等保测评进度</span>
          </div>
        }
        placement="right"
        width={480}
        open={assessmentDrawerVisible}
        onClose={() => setAssessmentDrawerVisible(false)}
        className="assessment-drawer"
      >
        {assessment && (
          <div className="assessment-drawer-content">
            <div className="assessment-drawer-header">
              <div className="assessment-drawer-title">{assessment.name}</div>
              <Tag color={
                assessment.status === 'completed' ? '#10b981' :
                assessment.status === 'in_progress' ? '#6366f1' :
                assessment.status === 'paused' ? '#f59e0b' : '#64748b'
              }>
                {assessment.status === 'not_started' ? '未开始' :
                 assessment.status === 'in_progress' ? '进行中' :
                 assessment.status === 'paused' ? '已暂停' :
                 assessment.status === 'completed' ? '已完成' : '失败'}
              </Tag>
            </div>
            
            <div className="assessment-drawer-progress">
              <Progress
                type="circle"
                percent={Math.round(assessment.progress || 0)}
                size={100}
                strokeColor={{ '0%': '#D4AF37', '100%': '#C5A55A' }}
              />
              <div className="assessment-drawer-stats">
                <div className="stat-item">
                  <span className="stat-value">{assessment.completed_phases || 0}</span>
                  <span className="stat-label">/ {assessment.total_phases} 阶段</span>
                </div>
              </div>
            </div>

            <div className="assessment-drawer-phases">
              {assessmentPhases.map((phase, index) => (
                <div key={phase.id} className={`assessment-phase-item ${phase.status}`}>
                  <div className="phase-indicator">
                    {phase.status === 'completed' ? (
                      <CheckCircleFilled style={{ color: '#10b981' }} />
                    ) : phase.status === 'active' ? (
                      <div className="phase-active-dot" />
                    ) : (
                      <div className="phase-pending-dot" />
                    )}
                    {index < assessmentPhases.length - 1 && (
                      <div className={`phase-connector-line ${phase.status === 'completed' ? 'completed' : ''}`} />
                    )}
                  </div>
                  <div className="phase-info">
                    <div className="phase-name">{phase.name}</div>
                    <div className="phase-meta">
                      {phase.status === 'completed' && <Tag color="#10b981">完成</Tag>}
                      {phase.status === 'active' && <Tag color="#6366f1">{Math.round(phase.progress || 0)}%</Tag>}
                      {phase.status === 'pending' && <Tag>待开始</Tag>}
                      {phase.status === 'skipped' && <Tag>已跳过</Tag>}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {assessment.status === 'not_started' && (
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                block
                style={{ marginTop: 16, background: 'linear-gradient(135deg, #D4AF37, #C5A55A)', border: 'none' }}
                onClick={async () => {
                  try {
                    await api.post(`/assessments/${assessment.id}/start`)
                    const result = await fetchAssessment()
                    if (result) {
                      setAssessment(result.assessment)
                      setAssessmentPhases(result.phases)
                    }
                    message.success('测评已开始')
                  } catch (error) {
                    message.error('启动失败')
                  }
                }}
              >
                开始测评
              </Button>
            )}
          </div>
        )}
      </Drawer>

      {/* SSH 凭证输入 Modal（单目标场景保留） */}
      <Modal
        title="SSH 认证信息"
        open={sshCredentialVisible}
        onOk={handleSshCredentialConfirm}
        onCancel={() => setSshCredentialVisible(false)}
        okText="开始核查"
        cancelText="取消"
        width={500}
      >
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            目标：{sshCredentialTarget === 'selected_assets' ? '已选资产' : sshCredentialTarget}
          </Text>
        </div>
        <Form layout="vertical">
          <Form.Item label="SSH 用户名" required>
            <Input
              value={sshUsername}
              onChange={(e) => setSshUsername(e.target.value)}
              placeholder="root"
            />
          </Form.Item>
          <Form.Item label="SSH 密码">
            <Input.Password
              value={sshPassword}
              onChange={(e) => setSshPassword(e.target.value)}
              placeholder="输入 SSH 密码"
            />
          </Form.Item>
          <Form.Item label="或 SSH 密钥文件路径">
            <Input
              value={sshKeyFile}
              onChange={(e) => setSshKeyFile(e.target.value)}
              placeholder="/path/to/private_key"
            />
          </Form.Item>
          <Form.Item label="SSH 端口">
            <Input
              type="number"
              value={sshPort}
              onChange={(e) => setSshPort(parseInt(e.target.value) || 22)}
              placeholder="22"
            />
          </Form.Item>
        </Form>
        <div style={{ marginTop: 8 }}>
          <Text type="warning" style={{ fontSize: 12 }}>
            提示：密码和密钥文件二选一即可
          </Text>
        </div>
      </Modal>

      {/* Per-Asset 凭据配置 Modal（多资产场景） */}
      <AssetCredentialModal
        visible={credentialModalVisible}
        assets={credentialAssets}
        onConfirm={handleCredentialConfirm}
        onCancel={() => setCredentialModalVisible(false)}
        title={
          credentialCommand === '/tech'
            ? '配置 SSH 凭据（等保技术测评）'
            : '配置 SSH 凭据（安全基线核查）'
        }
        description="仅用于安全基线检查，其他 9 项检查无需 SSH 凭据"
      />
    </div>
  )
}

export default ChatWorkspace
