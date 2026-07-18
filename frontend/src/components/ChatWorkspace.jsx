import { useState, useRef, useEffect } from 'react'
import { Input, Button, Avatar, Spin, Empty, Typography, Tag, message, Modal, Checkbox, Dropdown, Popconfirm, Form, Tooltip } from 'antd'
import {
  SendOutlined,
  UserOutlined,
  CheckCircleOutlined,
  HistoryOutlined,
  SwapOutlined,
  DeleteOutlined,
  FolderOutlined,
  FileTextOutlined,
  PaperClipOutlined,
  ThunderboltOutlined,
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
  SLASH_COMMANDS,
  normalizeScanPortRange,
  buildToolActionText,
  CAPABILITY_NAMES,
} from './chatCommandConfig'
import './ChatWorkspace.css'
import './ScanAnimation.css'

const { TextArea } = Input
const { Text } = Typography

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

function ChatWorkspace({ projectId, projectName, modelId, externalCommand, onOpenResults }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [activeRequests, setActiveRequests] = useState(0)
  const loading = activeRequests > 0
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
  const [archiveDetail, setArchiveDetail] = useState(null)
  const [threads, setThreads] = useState([])
  const [currentThreadId, setCurrentThreadId] = useState(null)
  const [showArchivePanel, setShowArchivePanel] = useState(false)
  const [showThreadPanel, setShowThreadPanel] = useState(false)
  const messagesContainerRef = useRef(null)
  const wsRefsRef = useRef(new Map())
  const pollRefsRef = useRef(new Map())
  const completedTaskIdsRef = useRef(new Set())
  const inputRef = useRef(null)
  const stickToBottomRef = useRef(true)

  const rememberInput = (text) => {
    const value = (text || '').trim()
    if (!value) return
    stickToBottomRef.current = true
    setInputHistory(prev => (prev[prev.length - 1] === value ? prev : [...prev.slice(-49), value]))
    setHistoryIndex(null)
  }

  const buildMultiAssetActionText = (capability, count, allSelected) => {
    const name = CAPABILITY_NAMES[capability] || capability
    return `${allSelected ? '对项目所有资产' : '对选定资产'} (${count} 个) 执行${name}`
  }

  const scrollToBottom = () => {
    const el = messagesContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }

  const updateStickToBottom = () => {
    const el = messagesContainerRef.current
    if (!el) return
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96
  }

  const handleMessageWheel = (event) => {
    if (event.deltaY < 0) {
      stickToBottomRef.current = false
    } else {
      updateStickToBottom()
    }
  }

  useEffect(() => {
    if (stickToBottomRef.current) scrollToBottom()
  }, [messages])

  // Load history on mount (key prop ensures remount on project change)
  useEffect(() => {
    const loadHistory = async () => {
      if (!projectId) {
        setMessages([
          {
            role: 'assistant',
            content: '你好！我是 CertiProof 智能合规验证助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
          },
        ])
        return
      }
      
      try {
        const threadResponse = await api.get('/chat/threads', { params: { project_id: projectId } })
        const availableThreads = threadResponse.data.threads || []
        setThreads(availableThreads)
        const savedThreadId = Number(window.localStorage.getItem(`certiproof:thread:${projectId}`))
        const activeThreadId = availableThreads.some((thread) => thread.id === savedThreadId) ? savedThreadId : null
        setCurrentThreadId(activeThreadId)
        const response = await api.get('/chat/history', {
          params: { project_id: projectId, thread_id: activeThreadId || undefined },
        })
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
            dataReset: Boolean(h.context_snapshot?.assessment_data_reset),
          }))
        } else {
          nextMessages = [
            {
              role: 'assistant',
              content: '你好！我是 CertiProof 智能合规验证助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
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
            content: '你好！我是 CertiProof 智能合规验证助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
          },
        ])
      }
    }
    
    loadHistory()
  }, [projectId])

  useEffect(() => {
    return () => {
      wsRefsRef.current.forEach(ws => ws.close())
      wsRefsRef.current.clear()
      pollRefsRef.current.forEach(timeoutId => clearTimeout(timeoutId))
      pollRefsRef.current.clear()
    }
  }, [])

  useEffect(() => {
    const handleAssessmentReset = event => {
      if (Number(event.detail?.projectId) !== Number(projectId) || event.detail?.mode !== 'reset') return
      wsRefsRef.current.forEach(ws => ws.close())
      wsRefsRef.current.clear()
      pollRefsRef.current.forEach(timeoutId => clearTimeout(timeoutId))
      pollRefsRef.current.clear()
      setMessages(previous => [
        ...previous.map(item => item.isResult || item.taskId
          ? {
              ...item,
              isResult: false,
              scanResults: {},
              isMultiAsset: false,
              taskStatus: item.taskId ? 'stopped' : item.taskStatus,
              dataReset: true,
            }
          : item),
        {
          role: 'assistant',
          content: '本项目测评已完全重置，先前检测结果已从系统中清除。项目和资产仍然保留。',
        },
      ])
    }
    window.addEventListener('certiproof:assessment-reset', handleAssessmentReset)
    return () => window.removeEventListener('certiproof:assessment-reset', handleAssessmentReset)
  }, [projectId])

  useEffect(() => {
    if (!externalCommand?.text) return
    handleSend(externalCommand.text)
  }, [externalCommand?.id])

  const handleSend = async (text = null) => {
    const messageText = text || input.trim()
    if (!messageText) return
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
    setActiveRequests(prev => prev + 1)

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
      setActiveRequests(prev => Math.max(0, prev - 1))
    }
  }

  const handlePing = (target) => handleSendToAI(`ping ${target}`, `/ping ${target}`)

  const handleSendToAI = async (messageText, displayText = messageText) => {
    // 防重复
    const now = Date.now()
    if (messageText === lastRequest.message && 
        (now - lastRequest.timestamp) < 5000) {
      return
    }
    
    setLastRequest({ message: messageText, timestamp: now })

    const userMessage = { role: 'user', content: displayText }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setActiveRequests(prev => prev + 1)

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
      setActiveRequests(prev => Math.max(0, prev - 1))
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
      setActiveRequests(prev => prev + 1)
      
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
      setActiveRequests(prev => Math.max(0, prev - 1))
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
      setActiveRequests(prev => prev + 1)
      
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
      setActiveRequests(prev => Math.max(0, prev - 1))
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
      setActiveRequests(prev => prev + 1)
      
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
      setActiveRequests(prev => Math.max(0, prev - 1))
    }
  }

  const connectWebSocket = (taskId) => {
    const existingWs = wsRefsRef.current.get(taskId)
    if (existingWs) existingWs.close()

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsHost = window.location.host
    const wsUrl = `${protocol}//${wsHost}/api/v1/ws/agents/${taskId}`

    let wsConnected = false

    try {
      const ws = new WebSocket(wsUrl)
      wsRefsRef.current.set(taskId, ws)
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
            wsRefsRef.current.delete(taskId)
            clearPollingFallback(taskId)

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
            wsRefsRef.current.delete(taskId)
            clearPollingFallback(taskId)

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
        if (wsRefsRef.current.get(taskId) === ws) {
          wsRefsRef.current.delete(taskId)
        }
      }

      setTimeout(() => {
        if (!wsConnected && wsRefsRef.current.get(taskId) === ws) {
          ws.close()
          wsRefsRef.current.delete(taskId)
          startPollingFallback(taskId)
        }
      }, 3000)
    } catch (e) {
      startPollingFallback(taskId)
    }
  }

  const clearPollingFallback = (taskId) => {
    const timeoutId = pollRefsRef.current.get(taskId)
    if (timeoutId) {
      clearTimeout(timeoutId)
      pollRefsRef.current.delete(taskId)
    }
  }

  const startPollingFallback = (taskId) => {
    clearPollingFallback(taskId)
    const pollRef = {
      get current() {
        return pollRefsRef.current.get(taskId)
      },
      set current(timeoutId) {
        if (timeoutId) pollRefsRef.current.set(taskId, timeoutId)
        else pollRefsRef.current.delete(taskId)
      },
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

  const openSlashPalette = () => {
    setInput('/')
    setCommandFilter('')
    setSelectedCommandIndex(0)
    setShowCommandPalette(true)
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  const handleClearHistory = async () => {
    try {
      if (projectId) {
        await api.post(`/chat/clear/${projectId}`, null, { params: { thread_id: currentThreadId || undefined } })
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

  const handleAssessmentAction = () => {
    if (!projectId) {
      message.warning('请先选择项目')
      return
    }
    window.dispatchEvent(new CustomEvent('certiproof:open-assessment', { detail: { projectId } }))
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
      rememberInput(cmd.command)
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
      const response = await api.post('/chat/archives', {
        title: null,
        project_id: projectId,
        thread_id: currentThreadId,
      })
      const archiveId = response.data.archive_id
      
      message.loading({ content: '正在生成归档摘要...', key: 'archive', duration: 0 })
      setMessages([])
      const maxAttempts = 30
      let attempts = 0
      const params = projectId ? { project_id: projectId } : {}
      
      const pollInterval = setInterval(async () => {
        attempts++
        try {
          const archiveRes = await api.get(`/chat/archives/${archiveId}`, { params })
          if (archiveRes.data.status === 'completed') {
            clearInterval(pollInterval)
            message.success({ content: '归档完成', key: 'archive' })
            await loadArchives()
          } else if (archiveRes.data.status === 'failed') {
            clearInterval(pollInterval)
            message.error({ content: archiveRes.data.error_message || '归档摘要失败，可在归档列表重试', key: 'archive' })
            await loadArchives()
          } else if (attempts >= maxAttempts) {
            clearInterval(pollInterval)
            message.info({ content: '归档仍在后台处理，可在归档列表查看进度', key: 'archive' })
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
      const params = projectId ? { project_id: projectId } : {}
      await api.delete(`/chat/archives/${archiveId}`, { params: { ...params, permanent: true } })
      message.success('归档已删除')
      await loadArchives()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handleViewArchive = async (archiveId) => {
    try {
      const params = projectId ? { project_id: projectId } : {}
      const response = await api.get(`/chat/archives/${archiveId}`, { params })
      setArchiveDetail(response.data)
    } catch (error) {
      message.error('加载归档原文失败')
    }
  }

  const handleRetryArchive = async (archiveId) => {
    try {
      const params = projectId ? { project_id: projectId } : {}
      await api.post(`/chat/archives/${archiveId}/retry`, null, { params })
      message.success('归档摘要已重新加入队列')
      await loadArchives()
    } catch (error) {
      message.error(error.response?.data?.detail || '归档重试失败')
    }
  }

  const handleContinueFromArchive = async (archive) => {
    try {
      const params = projectId ? { project_id: projectId } : {}
      const response = await api.post(`/chat/archives/${archive.id}/continue`, null, { params })
      setCurrentThreadId(response.data.thread_id)
      window.localStorage.setItem(`certiproof:thread:${projectId}`, String(response.data.thread_id))
      setMessages([])
      
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
      const response = await api.post('/chat/threads', {
        title: null,
        parent_thread_id: currentThreadId,
        project_id: projectId,
      })
      setCurrentThreadId(response.data.thread_id)
      window.localStorage.setItem(`certiproof:thread:${projectId}`, String(response.data.thread_id))
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
      const params = projectId ? { project_id: projectId } : {}
      const response = await api.get('/chat/threads', { params })
      setThreads(response.data.threads || [])
    } catch (error) {
      console.error('Failed to load threads:', error)
    }
  }

  const handleSwitchThread = async (threadId) => {
    try {
      const params = projectId ? { project_id: projectId } : {}
      const response = await api.post(`/chat/threads/${threadId}/continue`, null, { params })
      setCurrentThreadId(threadId)
      window.localStorage.setItem(`certiproof:thread:${projectId}`, String(threadId))
      
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
      const params = projectId ? { project_id: projectId } : {}
      await api.delete(`/chat/threads/${threadId}`, { params })
      if (currentThreadId === threadId) {
        setCurrentThreadId(null)
        window.localStorage.removeItem(`certiproof:thread:${projectId}`)
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
  const compactResultBefore = Math.max(0, resultOrderByMessageIndex.size - 1)
  const isLongAssistantMessage = (item) => item.role === 'assistant'
    && !item.isResult
    && ((item.content || '').length > 240 || (item.content || '').split('\n').length > 4)
  const messageSummary = (content = '') => {
    const firstLine = content.split('\n').find(line => line.trim()) || content
    return firstLine.length > 72 ? `${firstLine.slice(0, 72)}...` : firstLine
  }

  return (
    <div className="chat-workspace">
      <div className="workspace-brand-watermark" aria-hidden="true">
        <VeriSureLogo size={92} />
        <span>CertiProof</span>
      </div>
      <div className="cockpit-chat-toolbar">
        <div className="cockpit-chat-tabs">
          <button type="button" className="active">对话</button>
          <button type="button" onClick={onOpenResults}>执行日志</button>
        </div>
        <div className="cockpit-chat-actions">
          <Popconfirm title="清空当前对话？" description="扫描任务和检测结果不会删除。" onConfirm={handleClearHistory} okText="清空" cancelText="取消">
            <Button type="text" icon={<DeleteOutlined />}>清空对话</Button>
          </Popconfirm>
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
            placement="bottomRight"
          >
            <Button type="text" icon={<HistoryOutlined />} aria-label="对话归档与线程" />
          </Dropdown>
        </div>
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
                  <div className="archive-summary">{archive.summary || (archive.status === 'failed' ? archive.error_message : '正在生成摘要...')}</div>
                  
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
                    <Tag color={archive.status === 'completed' ? 'green' : archive.status === 'failed' ? 'red' : 'processing'}>{archive.status === 'completed' ? '摘要完成' : archive.status === 'failed' ? '摘要失败' : '后台处理中'}</Tag>
                    <span className="archive-date">{new Date(archive.archived_at).toLocaleString()}</span>
                  </div>
                </div>
                <div className="archive-actions">
                  <Button size="small" onClick={() => handleViewArchive(archive.id)}>查看原文</Button>
                  <Button
                    type="primary"
                    size="small"
                    icon={<SwapOutlined />}
                    disabled={archive.status !== 'completed'}
                    onClick={() => handleContinueFromArchive(archive)}
                  >
                    接续
                  </Button>
                  {archive.status === 'failed' && !archive.legacy_summary_only ? <Button size="small" onClick={() => handleRetryArchive(archive.id)}>重试</Button> : null}
                  <Popconfirm title="永久删除归档？" description="归档摘要和原始对话将不可恢复。" onConfirm={() => handleDeleteArchive(archive.id)} okText="永久删除" cancelText="取消" okButtonProps={{ danger: true }}>
                    <Button type="text" danger size="small" icon={<DeleteOutlined />} />
                  </Popconfirm>
                </div>
              </div>
            ))}
          </div>
        )}
      </Modal>

      <Modal title={archiveDetail?.title || '归档原文'} open={Boolean(archiveDetail)} onCancel={() => setArchiveDetail(null)} footer={null} width={760}>
        {archiveDetail ? <div className="archive-transcript">
          <div className="archive-summary">{archiveDetail.summary || archiveDetail.error_message || '暂无可用摘要'}</div>
          {(archiveDetail.messages || []).map((item) => <div key={item.id} className={`archive-transcript-item ${item.role}`}>
            <strong>{item.role === 'user' ? '用户' : '助手'}</strong>
            <span>{item.content}</span>
          </div>)}
          {!archiveDetail.messages?.length ? <Empty description={archiveDetail.legacy_summary_only ? '旧版归档未保留原始对话' : '暂无原始对话'} /> : null}
        </div> : null}
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
      <div className="workspace-messages" ref={messagesContainerRef} onScroll={updateStickToBottom} onWheel={handleMessageWheel}>
        {messages.map((msg, index) => (
          <div key={index} className={`workspace-message ${msg.role}`}>
            <div className="message-avatar">
              {msg.role === 'user' ? (
                <Avatar size={32} style={{ background: 'rgba(255,255,255,0.1)' }} icon={<UserOutlined />} />
              ) : (
                <VeriSureLogo size={32} className="chat-avatar-logo" />
              )}
            </div>
            <div className="message-body">
              {/* 诊断结果 */}
              {msg.isDiagnostic ? (
                <DiagnosticResultCard data={msg.diagnosticData} />
              ) : msg.isResult ? (
                <ResultMessageRenderer msg={msg} compact={resultOrderByMessageIndex.get(index) < compactResultBefore} />
              ) : msg.taskId ? (
                <>
                  <TaskStatusCard
                    msg={msg}
                    onPause={handlePauseTask}
                    onStop={handleStopTask}
                    onResume={handleResumeTask}
                  />
                  {msg.dataReset && (
                    <div className="message-data-reset">相关测评数据已被完全重置，原结果不再可用</div>
                  )}
                </>
              ) : (
                <>
                  {isLongAssistantMessage(msg) ? (
                    <details className={`message-bubble ${msg.role} message-transcript ${msg.isError ? 'error' : ''}`}>
                      <summary>
                        <span>执行摘要</span>
                        <strong>{messageSummary(msg.content)}</strong>
                      </summary>
                      <pre>{msg.content}</pre>
                    </details>
                  ) : (
                    <div className={`message-bubble ${msg.role} ${msg.isError ? 'error' : ''}`}>
                      {msg.content}
                    </div>
                  )}
                  {msg.dataReset && (
                    <div className="message-data-reset">相关测评数据已被完全重置，原结果不再可用</div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="workspace-message assistant">
            <div className="message-avatar">
              <VeriSureLogo size={32} className="chat-avatar-logo" />
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
              <VeriSureLogo size={32} className="chat-avatar-logo" />
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
              <Avatar size={32} style={{ background: 'rgba(16, 185, 129, .18)', color: '#34d399' }} icon={<CheckCircleOutlined />} />
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
        
      </div>

      {/* Input */}
      <div className="workspace-input-area">
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
        <div className="input-row cockpit-input-row">
          <div className="cockpit-composer-tools">
            <Tooltip title="上传测评材料">
              <Button type="text" icon={<PaperClipOutlined />} onClick={handleAssessmentAction} aria-label="上传测评材料" />
            </Tooltip>
            <Tooltip title="输入快捷命令">
              <Button type="text" onClick={openSlashPalette} aria-label="输入快捷命令">/</Button>
            </Tooltip>
            <Tooltip title="打开快捷指令">
              <Button
                type="text"
                className="composer-shortcut-button"
                icon={<ThunderboltOutlined />}
                onClick={openSlashPalette}
                aria-label="打开快捷指令"
              >
                快捷指令
              </Button>
            </Tooltip>
          </div>
          <TextArea
            ref={inputRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyPress}
            placeholder={projectName ? `向 Agent 询问"${projectName}"的合规状态... 输入 / 查看快捷命令` : '向 Agent 询问合规相关问题... 输入 / 查看快捷命令'}
            autoSize={{ minRows: 1, maxRows: 4 }}
            className="workspace-input"
          />
          <span className="cockpit-input-hint">Enter 发送 · Shift + Enter 换行</span>
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={() => handleSend()}
            disabled={!input.trim()}
            className="workspace-send-btn"
            aria-label="发送"
          />
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
