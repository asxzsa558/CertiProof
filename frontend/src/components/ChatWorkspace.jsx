import { useState, useRef, useEffect } from 'react'
import { Input, Button, Avatar, Spin, Empty, Typography, Progress, Tag, Table, message, Modal, Checkbox, Dropdown, Menu, Popconfirm } from 'antd'
import {
  SendOutlined,
  UserOutlined,
  RobotOutlined,
  ThunderboltOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
  MonitorOutlined,
  PlusOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  ApiOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  ExclamationCircleFilled,
  InfoCircleFilled,
  PauseCircleOutlined,
  StopOutlined,
  PlayCircleOutlined,
  HistoryOutlined,
  SwapOutlined,
  DeleteOutlined,
  FolderOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import './ChatWorkspace.css'
import './ScanAnimation.css'

const { TextArea } = Input
const { Text } = Typography

const SUGGESTIONS = [
  { icon: <PlusOutlined />, title: '创建项目', text: '创建项目 ', color: '#6366f1' },
  { icon: <ThunderboltOutlined />, title: '端口扫描', text: '/scan', color: '#10b981' },
  { icon: <FileSearchOutlined />, title: '查看结果', text: '查看扫描结果', color: '#ef4444' },
  { icon: <SafetyCertificateOutlined />, title: '合规评分', text: '查看合规分数', color: '#f59e0b' },
  { icon: <ApiOutlined />, title: '连通测试', text: '/diagnose', color: '#8b5cf6' },
]

const SLASH_COMMANDS = [
  { command: '/scan', description: '端口扫描', usage: '/scan [目标]', defaultText: '/scan ' },
  { command: '/ssl', description: 'SSL/TLS 检测', usage: '/ssl [目标]', defaultText: '/ssl ' },
  { command: '/vuln', description: '漏洞扫描', usage: '/vuln [目标]', defaultText: '/vuln ' },
  { command: '/ping', description: 'Ping 检测', usage: '/ping [目标]', defaultText: '/ping ' },
  { command: '/asset', description: '添加资产', usage: '/asset [IP/域名]', defaultText: '/asset ' },
  { command: '/assets', description: '列出项目资产', usage: '/assets', direct: true },
  { command: '/project', description: '列出项目', usage: '/project', defaultText: '列出所有项目' },
  { command: '/diagnose', description: 'MCP 连通性测试', usage: '/diagnose', direct: true },
  { command: '/clear', description: '清理对话历史', usage: '/clear', direct: true },
  { command: '/help', description: '显示帮助', usage: '/help', direct: true },
]

function ChatWorkspace({ projectId, projectName, modelId }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [currentProjectId, setCurrentProjectId] = useState(projectId || null)
  const [currentModelId, setCurrentModelId] = useState(modelId || null)
  const [lastRequest, setLastRequest] = useState({ message: '', timestamp: 0 })
  const [showCommandPalette, setShowCommandPalette] = useState(false)
  const [commandFilter, setCommandFilter] = useState('')
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0)
  const [assetSelectorVisible, setAssetSelectorVisible] = useState(false)
  const [assetSelectorAssets, setAssetSelectorAssets] = useState([])
  const [assetSelectorSelected, setAssetSelectorSelected] = useState([])
  const [assetSelectorCommand, setAssetSelectorCommand] = useState('')
  const [compressionStatus, setCompressionStatus] = useState(null) // null | 'started' | 'completed'
  const [compressionInfo, setCompressionInfo] = useState(null) // { tokens_freed, message_count }
  const [archives, setArchives] = useState([])
  const [threads, setThreads] = useState([])
  const [currentThreadId, setCurrentThreadId] = useState(null)
  const [showArchivePanel, setShowArchivePanel] = useState(false)
  const [showThreadPanel, setShowThreadPanel] = useState(false)
  const messagesEndRef = useRef(null)
  const wsRef = useRef(null)
  const pollRef = useRef(null)
  const inputRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Load history on mount (key prop ensures remount on project change)
  useEffect(() => {
    const loadHistory = async () => {
      if (!projectId) {
        setMessages([
          {
            role: 'assistant',
            content: '你好！我是 CertiProof 等保合规智能助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
          },
        ])
        return
      }
      
      try {
        const response = await api.get('/chat/history', { params: { project_id: projectId } })
        const history = response.data
        
        if (history && history.length > 0) {
          setMessages(history.map(h => ({
            role: h.role,
            content: h.content,
            id: h.id,
          })))
        } else {
          setMessages([
            {
              role: 'assistant',
              content: '你好！我是 CertiProof 等保合规智能助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
            },
          ])
        }
      } catch (error) {
        console.error('Failed to load chat history:', error)
        setMessages([
          {
            role: 'assistant',
            content: '你好！我是 CertiProof 等保合规智能助手。我可以帮你扫描端口、检测SSL、发现漏洞、管理项目等。直接告诉我你想做什么。',
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

    // 检测扫描命令（/scan、/ssl、/vuln）
    const scanCommands = ['/scan', '/ssl', '/vuln']
    const matchedCommand = scanCommands.find(cmd => messageText === cmd || messageText.startsWith(cmd + ' '))
    if (matchedCommand) {
      const target = messageText.slice(matchedCommand.length).trim()
      if (target) {
        // 有指定目标，直接发送
        const commandTexts = {
          '/scan': `扫描 ${target} 端口`,
          '/ssl': `检测 ${target} SSL/TLS 配置`,
          '/vuln': `扫描 ${target} 漏洞`,
        }
        const translatedText = commandTexts[matchedCommand] || messageText
        await handleSendToAI(translatedText)
      } else {
        // 无目标，弹出资产选择对话框
        await openAssetSelector(matchedCommand)
      }
      return
    }

    await handleSendToAI(messageText)
  }

  const handleDiagnose = async () => {
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
    setMessages(prev => [...prev, { role: 'user', content: `/ping ${target}` }])
    setInput('')
    setLoading(true)

    try {
      const response = await api.post('/chat/', {
        message: `ping ${target}`,
        project_id: currentProjectId,
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
        project_id: currentProjectId,
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
      }
      setMessages((prev) => [...prev, assistantMessage])

      // 如果有 task_id，先尝试 WebSocket，失败则降级为轮询
      if (taskId) {
        connectWebSocket(taskId)
      }

      if (response.data.context?.project_id) {
        setCurrentProjectId(response.data.context.project_id)
      }
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

  const openAssetSelector = async (command) => {
    if (!currentProjectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目',
        isError: true,
      }])
      return
    }
    
    try {
      const response = await api.get(`/projects/${currentProjectId}/assets/`)
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
    const selectedAssets = assetSelectorAssets.filter(a => assetSelectorSelected.includes(a.id))
    
    if (selectedAssets.length === 0) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '未选择任何资产',
      }])
      return
    }
    
    await handleMultiAssetScan(assetSelectorCommand, selectedAssets)
  }

  const handleMultiAssetScan = async (command, selectedAssets) => {
    if (!currentProjectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目',
        isError: true,
      }])
      return
    }
    
    const assets = selectedAssets || []
    if (assets.length === 0) return
    
    const capabilityMap = {
      '/scan': 'scan_ports',
      '/ssl': 'scan_ssl',
      '/vuln': 'scan_vulnerabilities',
    }
    
    const capability = capabilityMap[command]
    const capabilityNames = {
      'scan_ports': '端口扫描',
      'scan_ssl': 'SSL/TLS 检测',
      'scan_vulnerabilities': '漏洞扫描',
    }
    
    const targetDesc = assets.length === assetSelectorAssets.length
      ? `扫描项目所有资产 (${assets.length} 个)`
      : `扫描选定资产 (${assets.length} 个)`
    
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
          assets: assets.map(a => ({ id: a.id, value: a.value, type: a.asset_type })),
        }),
        project_id: currentProjectId,
      })
      
      const taskId = scanResponse.data.task_id
      const aiResponse = scanResponse.data.response
      
      const assistantMessage = {
        role: 'assistant',
        content: aiResponse || `开始${capabilityNames[capability]}，共 ${assets.length} 个资产`,
        taskId: taskId,
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
            ws.close()
            wsRef.current = null

            setMessages(prev => prev.map(m =>
              m.taskId === taskId ? { ...m, taskCompleted: true, taskStatus: 'completed' } : m
            ))

            // 检查是否包含多资产结果
            const hasAssetResults = msg.data?.scan_results?.asset_results && 
                                  Object.keys(msg.data.scan_results.asset_results).length > 0

            const resultMessage = {
              role: 'assistant',
              content: msg.data?.result_description || '任务执行完成',
              isResult: true,
              scanResults: msg.data?.scan_results || {},
              isMultiAsset: msg.data?.is_multi_asset || hasAssetResults,
            }
            setMessages(prev => [...prev, resultMessage])
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
    pollTaskResult(taskId)
  }

  const pollTaskResult = async (taskId) => {
    const maxAttempts = 120
    const interval = 2000

    for (let i = 0; i < maxAttempts; i++) {
      try {
        const response = await api.get(`/chat/result/${taskId}`)
        const data = response.data

        if (data.current_step || data.step_progress) {
          setMessages(prev => prev.map(msg =>
            msg.taskId === taskId ? {
              ...msg,
              currentStep: data.current_step,
              stepProgress: data.step_progress,
            } : msg
          ))
        }

        if (data.status === 'completed' || data.status === 'failed') {
          setMessages(prev => prev.map(msg =>
            msg.taskId === taskId ? {
              ...msg,
              taskCompleted: true,
              taskStatus: data.status,
            } : msg
          ))
          
          // 检查是否包含多资产结果
          const hasAssetResults = data.scan_results?.asset_results && 
                                Object.keys(data.scan_results.asset_results).length > 0
          
          const resultMessage = {
            role: 'assistant',
            content: data.result_description || '任务执行完成',
            isResult: true,
            scanResults: data.scan_results || {},
            isMultiAsset: hasAssetResults,
          }
          setMessages((prev) => [...prev, resultMessage])
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

    setMessages(prev => prev.map(msg =>
      msg.taskId === taskId ? { ...msg, taskCompleted: true, taskStatus: 'timeout' } : msg
    ))
    setMessages((prev) => [...prev, {
      role: 'assistant',
      content: '任务执行超时，请稍后再试。',
      isError: true,
    }])
  }

  const filteredCommands = SLASH_COMMANDS.filter(cmd => 
    cmd.command.includes(commandFilter.toLowerCase()) || 
    cmd.description.includes(commandFilter.toLowerCase())
  )

  const handleInputChange = (e) => {
    const value = e.target.value
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
      if (currentProjectId) {
        await api.post(`/chat/clear/${currentProjectId}`)
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
    if (!currentProjectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目。',
      }])
      return
    }
    try {
      const response = await api.get(`/projects/${currentProjectId}/assets/`)
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

  const handleShowHelp = () => {
    const helpText = `可用命令：

/scan [目标] - 端口扫描（默认本机）
/ssl [目标] - SSL/TLS 检测
/vuln [目标] - 漏洞扫描
/asset [值] - 添加资产
/assets - 列出当前项目资产
/project - 列出所有项目
/clear - 清理对话历史
/help - 显示此帮助`
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
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // 渲染结果消息
  // 端口表格列定义（共用）
  const portColumns = [
    {
      title: '端口',
      dataIndex: 'port',
      key: 'port',
      width: 80,
      sorter: (a, b) => a.port - b.port,
    },
    {
      title: '协议',
      dataIndex: 'protocol',
      key: 'protocol',
      width: 80,
    },
    {
      title: '服务',
      dataIndex: 'service',
      key: 'service',
      render: (service) => service || '-',
    },
    {
      title: '状态',
      dataIndex: 'state',
      key: 'state',
      width: 100,
      render: (state) => {
        const colorMap = {
          open: 'green',
          closed: 'default',
          filtered: 'orange',
        }
        return <Tag color={colorMap[state] || 'default'}>{state}</Tag>
      },
    },
  ]

  const renderResultMessage = (msg) => {
    const scanResults = msg.scanResults || {}
    const openPorts = scanResults.open_ports || []
    const vulnerabilities = scanResults.vulnerabilities || []
    const sslIssues = scanResults.ssl_issues || []

    return (
      <div className="scan-animation-fade-in">
        <div className="message-bubble assistant" style={{ whiteSpace: 'pre-wrap' }}>
          {msg.content}
        </div>
        
        {/* 统计摘要 */}
        {(openPorts.length > 0 || vulnerabilities.length > 0 || sslIssues.length > 0) && (
          <div className="result-summary">
            {openPorts.length > 0 && (
              <div className="summary-item">
                <div className="summary-icon" style={{ background: 'rgba(59, 130, 246, 0.2)' }}>
                  <MonitorOutlined style={{ color: '#3b82f6' }} />
                </div>
                <div className="summary-content">
                  <div className="summary-title">开放端口</div>
                  <div className="summary-value">{openPorts.length} 个</div>
                </div>
              </div>
            )}
            {vulnerabilities.length > 0 && (
              <div className="summary-item">
                <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.2)' }}>
                  <CloseCircleFilled style={{ color: '#ef4444' }} />
                </div>
                <div className="summary-content">
                  <div className="summary-title">漏洞</div>
                  <div className="summary-value">{vulnerabilities.length} 个</div>
                </div>
              </div>
            )}
            {sslIssues.length > 0 && (
              <div className="summary-item">
                <div className="summary-icon" style={{ background: 'rgba(245, 158, 11, 0.2)' }}>
                  <SafetyCertificateOutlined style={{ color: '#f59e0b' }} />
                </div>
                <div className="summary-content">
                  <div className="summary-title">SSL 问题</div>
                  <div className="summary-value">{sslIssues.length} 个</div>
                </div>
              </div>
            )}
          </div>
        )}
        
        {/* 端口详情表格 */}
        {openPorts.length > 0 && (
          <div className="result-details-table">
            <div className="table-header">
              <span>端口详情</span>
            </div>
            <Table
              dataSource={openPorts.map((port, idx) => ({ ...port, key: idx }))}
              columns={portColumns}
              pagination={openPorts.length > 10 ? { defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] } : false}
              size="small"
              className="port-table"
            />
          </div>
        )}
        
        {/* 漏洞详情 */}
        {vulnerabilities.length > 0 && (
          <div className="result-details-section">
            <div className="section-title">漏洞列表</div>
            {vulnerabilities.map((vuln, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color="red">{vuln.severity || '未知'}</Tag>
                <span>{vuln.name || vuln.id}</span>
              </div>
            ))}
          </div>
        )}
        
        {/* SSL 问题 */}
        {sslIssues.length > 0 && (
          <div className="result-details-section">
            <div className="section-title">SSL/TLS 问题</div>
            {sslIssues.map((issue, idx) => (
              <div key={idx} className="ssl-issue-item">
                <Tag color="orange">警告</Tag>
                <span>{issue}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // 渲染任务状态
  const renderTaskStatus = (msg) => {
    if (!msg.taskId) return null

    if (msg.taskCompleted) return null

    if (msg.isMultiAsset && msg.assetProgress) {
      return renderMultiAssetProgress(msg)
    }

    const stepProgress = msg.stepProgress
    const currentStep = msg.currentStep
    const isPaused = msg.taskStatus === 'paused'

    return (
      <div className="scan-animation-fade-in" style={{ marginTop: 4 }}>
        <div className={`task-progress-card ${isPaused ? 'paused' : ''}`}>
          {isPaused && (
            <div className="task-status-badge badge-paused">
              <PauseCircleOutlined />
              <span>已暂停</span>
            </div>
          )}
          {/* 进度条 */}
          {stepProgress && stepProgress.total_steps > 0 && (
            <div className="progress-bar-container">
              <Progress
                percent={Math.round(((stepProgress.step_index + 1) / stepProgress.total_steps) * 100)}
                strokeColor={isPaused ? '#faad14' : { from: '#6366f1', to: '#8b5cf6' }}
                showInfo={false}
                size="small"
              />
              <span className="progress-text">
                {stepProgress.step_index + 1} / {stepProgress.total_steps}
              </span>
            </div>
          )}
          
          {/* 当前步骤 */}
          <div className="current-step">
            {isPaused ? (
              <PauseCircleOutlined style={{ color: '#faad14' }} />
            ) : (
              <LoadingOutlined style={{ color: '#6366f1' }} spin />
            )}
            <span className="step-text">{isPaused ? '任务已暂停' : (currentStep || '任务执行中...')}</span>
          </div>
          
          {/* 步骤列表 */}
          {stepProgress && stepProgress.steps && stepProgress.steps.length > 0 && (
            <div className="steps-list">
              {stepProgress.steps.map((step, idx) => (
                <div key={idx} className={`step-item step-${step.status}`}>
                  {step.status === 'completed' ? (
                    <CheckCircleFilled style={{ color: '#10b981' }} />
                  ) : step.status === 'failed' ? (
                    <CloseCircleFilled style={{ color: '#ef4444' }} />
                  ) : (
                    <LoadingOutlined style={{ color: '#6366f1' }} spin />
                  )}
                  <span>{step.display_name}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
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
      const params = currentProjectId ? { project_id: currentProjectId } : {}
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

  const renderMultiAssetProgress = (msg) => {
    const assetProgress = msg.assetProgress || {}
    const totalAssets = msg.totalAssets || Object.keys(assetProgress).length
    const taskStatus = msg.taskStatus || 'running'
    const isPaused = taskStatus === 'paused'
    const isStopped = taskStatus === 'stopped'
    
    const completedCount = Object.values(assetProgress).filter(a => 
      a.status === 'completed' || a.status === 'failed' || a.status === 'success' || a.status === 'cancelled'
    ).length
    
    const progress = totalAssets > 0 ? Math.round((completedCount / totalAssets) * 100) : 0

    const cardClassName = `task-progress-card multi-asset-card ${isPaused ? 'paused' : ''} ${isStopped ? 'stopped' : ''}`

    return (
      <div className="scan-animation-fade-in" style={{ marginTop: 4 }}>
        <div className={cardClassName}>
          {/* 状态徽章 */}
          {(isPaused || isStopped) && (
            <div className={`task-status-badge ${isPaused ? 'badge-paused' : 'badge-stopped'}`}>
              {isPaused ? <PauseCircleOutlined /> : <StopOutlined />}
              <span>{isPaused ? '已暂停' : '已停止'}</span>
            </div>
          )}
          
          {/* 总进度 */}
          <div className="progress-bar-container">
            <Progress
              percent={progress}
              strokeColor={isStopped ? '#ef4444' : isPaused ? '#faad14' : { from: '#6366f1', to: '#8b5cf6' }}
              showInfo={false}
              size="small"
            />
            <span className="progress-text">
              {completedCount} / {totalAssets}
            </span>
          </div>
          
          {/* 控制按钮 */}
          <div className="task-controls">
            {isPaused ? (
              <>
                <Button
                  size="small"
                  icon={<PlayCircleOutlined />}
                  onClick={() => handleResumeTask(msg.taskId)}
                  className="task-control-btn"
                  style={{ background: 'rgba(16, 185, 129, 0.1)', borderColor: '#10b981', color: '#10b981' }}
                >
                  恢复
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<StopOutlined />}
                  onClick={() => handleStopTask(msg.taskId)}
                  className="task-control-btn"
                >
                  停止
                </Button>
              </>
            ) : isStopped ? (
              <span className="task-stopped-text">任务已终止</span>
            ) : (
              <>
                <Button
                  size="small"
                  icon={<PauseCircleOutlined />}
                  onClick={() => handlePauseTask(msg.taskId)}
                  className="task-control-btn"
                >
                  暂停
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<StopOutlined />}
                  onClick={() => handleStopTask(msg.taskId)}
                  className="task-control-btn"
                >
                  停止
                </Button>
              </>
            )}
          </div>
          
          {/* 资产列表 */}
          <div className="asset-progress-list">
            {Object.entries(assetProgress).map(([index, asset]) => {
              const isRunning = asset.status === 'running' || asset.status === 'pending'
              const showPaused = isPaused && isRunning
              
              return (
                <div key={index} className={`asset-progress-item ${showPaused ? 'paused' : asset.status}`}>
                  {asset.status === 'completed' || asset.status === 'success' ? (
                    <CheckCircleFilled style={{ color: '#10b981' }} />
                  ) : asset.status === 'failed' ? (
                    <CloseCircleFilled style={{ color: '#ef4444' }} />
                  ) : asset.status === 'cancelled' ? (
                    <StopOutlined style={{ color: '#faad14' }} />
                  ) : showPaused ? (
                    <PauseCircleOutlined style={{ color: '#faad14' }} />
                  ) : (
                    <LoadingOutlined style={{ color: '#6366f1' }} spin />
                  )}
                  <span className="asset-name">{asset.name}</span>
                  {asset.status === 'running' && !isPaused && (
                    <span className="asset-status">扫描中...</span>
                  )}
                  {asset.status === 'cancelled' && (
                    <span className="asset-status">已取消</span>
                  )}
                  {showPaused && (
                    <span className="asset-status">已暂停</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    )
  }

  const renderMultiAssetResult = (msg) => {
    const scanResults = msg.scanResults || {}
    const assetResults = scanResults.asset_results || {}
    
    const totalAssets = Object.keys(assetResults).length
    const successCount = Object.values(assetResults).filter(r => r.display_status === 'success').length
    const warningCount = Object.values(assetResults).filter(r => r.display_status === 'warning').length
    const failedCount = Object.values(assetResults).filter(r => r.display_status === 'failed').length

    return (
      <div className="scan-animation-fade-in">
        {/* 统计摘要 */}
        <div className="result-summary multi-asset-summary">
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(99, 102, 241, 0.2)' }}>
              <MonitorOutlined style={{ color: '#6366f1' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">总资产数</div>
              <div className="summary-value">{totalAssets}</div>
            </div>
          </div>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(16, 185, 129, 0.2)' }}>
              <CheckCircleFilled style={{ color: '#10b981' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">成功</div>
              <div className="summary-value">{successCount}</div>
            </div>
          </div>
          {warningCount > 0 && (
            <div className="summary-item">
              <div className="summary-icon" style={{ background: 'rgba(245, 158, 11, 0.2)' }}>
                <ExclamationCircleFilled style={{ color: '#f59e0b' }} />
              </div>
              <div className="summary-content">
                <div className="summary-title">警告</div>
                <div className="summary-value">{warningCount}</div>
              </div>
            </div>
          )}
          {failedCount > 0 && (
            <div className="summary-item">
              <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.2)' }}>
                <CloseCircleFilled style={{ color: '#ef4444' }} />
              </div>
              <div className="summary-content">
                <div className="summary-title">失败</div>
                <div className="summary-value">{failedCount}</div>
              </div>
            </div>
          )}
        </div>
        
        {/* 资产详情卡片 */}
        <div className="asset-results-cards">
          {Object.entries(assetResults).map(([target, assetData], index) => {
            const displayStatus = assetData.display_status || (assetData.status === 'success' ? 'success' : 'failed')
            
            // 提取端口数据
            const openPorts = assetData.result?.open_ports || []
            
            // 提取错误信息
            const errorMsg = assetData.error
            
            // 根据状态设置图标和颜色
            const statusConfig = {
              success: {
                icon: <CheckCircleFilled style={{ color: '#10b981' }} />,
                tagColor: 'success',
                tagText: '成功',
                cardClass: 'success'
              },
              warning: {
                icon: <ExclamationCircleFilled style={{ color: '#f59e0b' }} />,
                tagColor: 'warning',
                tagText: '警告',
                cardClass: 'warning'
              },
              failed: {
                icon: <CloseCircleFilled style={{ color: '#ef4444' }} />,
                tagColor: 'error',
                tagText: '失败',
                cardClass: 'failed'
              }
            }
            
            const config = statusConfig[displayStatus]
            
            return (
              <div key={index} className={`asset-result-card ${config.cardClass}`}>
                {/* 卡片头部 */}
                <div className="asset-result-header">
                  <div className="asset-result-title">
                    {config.icon}
                    <span className="asset-target">{target}</span>
                  </div>
                  <Tag color={config.tagColor}>
                    {config.tagText}
                  </Tag>
                </div>
                
                {/* 成功状态：显示端口详情 */}
                {displayStatus === 'success' && (
                  <div className="asset-result-content">
                    <div className="asset-result-stats">
                      <span className="stat-label">开放端口:</span>
                      <span className="stat-value">{openPorts.length} 个</span>
                    </div>
                    
                    {openPorts.length > 0 && (
                      <div className="port-table-container">
                        <Table
                          dataSource={openPorts.map((port, idx) => ({ ...port, key: idx }))}
                          columns={portColumns}
                          pagination={openPorts.length > 5 ? { defaultPageSize: 5, showSizeChanger: true, pageSizeOptions: ['5', '10', '20'] } : false}
                          size="small"
                          className="port-table-compact"
                        />
                      </div>
                    )}
                  </div>
                )}
                
                {/* 警告状态：无开放端口 */}
                {displayStatus === 'warning' && (
                  <div className="asset-result-content">
                    <div className="asset-result-stats">
                      <span className="stat-label">开放端口:</span>
                      <span className="stat-value">0 个</span>
                    </div>
                    
                    <div className="info-box warning">
                      <InfoCircleFilled style={{ color: '#f59e0b', marginRight: 8 }} />
                      <div className="info-content">
                        <div className="info-title">未发现开放端口</div>
                        <div className="info-desc">可能原因：主机不可达、防火墙过滤、或服务未启动</div>
                      </div>
                    </div>
                  </div>
                )}
                
                {/* 失败状态：显示错误信息 */}
                {displayStatus === 'failed' && (
                  <div className="asset-result-content">
                    <div className="info-box error">
                      <CloseCircleFilled style={{ color: '#ef4444', marginRight: 8 }} />
                      <div className="info-content">
                        <div className="info-title">扫描失败</div>
                        <div className="info-desc">{errorMsg || '扫描过程中发生错误'}</div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const renderDiagnosticResult = (data) => {
    const services = data.services || {}
    const overallStatus = data.status
    
    const serviceConfig = {
      gateway: { 
        label: 'MCP Gateway', 
        icon: <ApiOutlined />, 
        gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' 
      },
      security_tools: { 
        label: 'Security Tools', 
        icon: <SafetyCertificateOutlined />, 
        gradient: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' 
      },
      ocr_server: { 
        label: 'OCR Server', 
        icon: <FileSearchOutlined />, 
        gradient: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' 
      },
    }

    const healthyCount = Object.values(services).filter(s => s.status === 'healthy').length
    const totalCount = Object.keys(services).length

    return (
      <div className="scan-animation-fade-in">
        <div className="diagnostic-card">
          {/* Header */}
          <div className="diagnostic-header">
            <div className="diagnostic-title">
              <ApiOutlined />
              <span>MCP 连通性测试</span>
            </div>
            <div className={`diagnostic-overall ${overallStatus === 'healthy' ? 'healthy' : 'unhealthy'}`}>
              {overallStatus === 'healthy' ? (
                <><CheckCircleFilled /> 全部正常</>
              ) : (
                <><CloseCircleFilled /> 部分异常</>
              )}
            </div>
          </div>

          {/* Service Cards */}
          <div className="diagnostic-services">
            {Object.entries(services).map(([key, info]) => {
              const config = serviceConfig[key] || { label: key, icon: <MonitorOutlined />, gradient: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }
              const isHealthy = info.status === 'healthy'
              const tools = info.details?.tools || info.details?.details?.tools || []
              
              return (
                <div key={key} className={`diagnostic-service-card ${isHealthy ? 'healthy' : 'unhealthy'}`}>
                  <div className="service-card-header" style={{ background: config.gradient }}>
                    <div className="service-icon">{config.icon}</div>
                    <div className="service-info">
                      <div className="service-name">{config.label}</div>
                      <div className="service-status">
                        {isHealthy ? (
                          <><CheckCircleFilled /> 正常</>
                        ) : (
                          <><CloseCircleFilled /> 异常</>
                        )}
                      </div>
                    </div>
                  </div>
                  
                  {tools.length > 0 && (
                    <div className="service-tools">
                      <div className="tools-label">可用工具</div>
                      <div className="tools-list">
                        {tools.map((tool, i) => (
                          <Tag key={i} color={isHealthy ? 'success' : 'default'} className="tool-tag">
                            {tool.replace(/_scan|_analyze|_bruteforce/, '')}
                          </Tag>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {info.error && (
                    <div className="service-error">
                      <CloseCircleFilled /> {info.error}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Summary */}
          <div className="diagnostic-summary">
            <div className="summary-stat">
              <span className="stat-value">{healthyCount}</span>
              <span className="stat-label">正常</span>
            </div>
            <div className="summary-divider">/</div>
            <div className="summary-stat">
              <span className="stat-value">{totalCount}</span>
              <span className="stat-label">服务</span>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-workspace">
      {/* Header */}
      <div className="workspace-header">
        <div className="workspace-title">
          <div className="workspace-logo">
            <RobotOutlined />
          </div>
          <div>
            <div className="workspace-name">CertiProof Agent</div>
            <div className="workspace-subtitle">
              {projectName ? `项目：${projectName}` : '等保合规智能对话'}
            </div>
          </div>
        </div>
        <div className="workspace-status">
          <div className="status-indicator">
            <div className="status-dot"></div>
            <span>在线</span>
          </div>
          <div className="header-actions">
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
            >
              <Button type="text" icon={<HistoryOutlined />} className="header-action-btn" />
            </Dropdown>
          </div>
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
                renderDiagnosticResult(msg.diagnosticData)
              ) : msg.isResult ? (
                msg.isMultiAsset ? renderMultiAssetResult(msg) : renderResultMessage(msg)
              ) : (
                <>
                  <div className={`message-bubble ${msg.role} ${msg.isError ? 'error' : ''}`}>
                    {msg.content}
                  </div>
                  {/* 任务状态指示器 */}
                  {msg.taskId && renderTaskStatus(msg)}
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
                onClick={() => handleSend(s.text)}
                style={{ '--accent': s.color }}
              >
                <span className="suggestion-icon">{s.icon}</span>
                <span className="suggestion-text">{s.title}</span>
              </button>
            ))}
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
    </div>
  )
}

export default ChatWorkspace
