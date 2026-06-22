import { useState, useRef, useEffect } from 'react'
import { Input, Button, Avatar, Spin, Empty, Typography, Progress, Tag, Table } from 'antd'
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
]

const SLASH_COMMANDS = [
  { command: '/scan', description: '端口扫描', usage: '/scan [目标]', defaultText: '/scan ' },
  { command: '/ssl', description: 'SSL/TLS 检测', usage: '/ssl [目标]', defaultText: '/ssl ' },
  { command: '/vuln', description: '漏洞扫描', usage: '/vuln [目标]', defaultText: '/vuln ' },
  { command: '/asset', description: '添加资产', usage: '/asset [IP/域名]', defaultText: '/asset ' },
  { command: '/assets', description: '列出项目资产', usage: '/assets', direct: true },
  { command: '/project', description: '列出项目', usage: '/project', defaultText: '列出所有项目' },
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
        // 无目标，使用项目资产
        await handleMultiAssetScan(matchedCommand)
      }
      return
    }

    await handleSendToAI(messageText)
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

  const handleMultiAssetScan = async (command) => {
    if (!currentProjectId) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '请先选择项目',
        isError: true,
      }])
      return
    }
    
    // 获取资产列表
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
      
      // 映射命令到能力
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
      
      // 添加用户消息
      const userMessage = {
        role: 'user',
        content: `扫描项目所有资产 (${assets.length} 个)`,
        isMultiAsset: true,
        totalAssets: assets.length,
      }
      setMessages(prev => [...prev, userMessage])
      setInput('')
      setLoading(true)
      
      // 发送多资产扫描请求
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
      
      // 添加 AI 回复消息
      const assistantMessage = {
        role: 'assistant',
        content: aiResponse || `开始${capabilityNames[capability]}，共 ${assets.length} 个资产`,
        taskId: taskId,
        isMultiAsset: true,
        totalAssets: assets.length,
        assetProgress: {},
      }
      setMessages(prev => [...prev, assistantMessage])
      
      // 连接 WebSocket 接收进度
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
            
            // 处理多资产进度
            if (data.type === 'multi_asset_progress') {
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

            const resultMessage = {
              role: 'assistant',
              content: msg.data?.result_description || '任务执行完成',
              isResult: true,
              scanResults: msg.data?.scan_results || {},
              isMultiAsset: msg.data?.is_multi_asset || false,
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
          
          const resultMessage = {
            role: 'assistant',
            content: data.result_description || '任务执行完成',
            isResult: true,
            scanResults: data.scan_results || {},
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
  const renderResultMessage = (msg) => {
    const scanResults = msg.scanResults || {}
    const openPorts = scanResults.open_ports || []
    const vulnerabilities = scanResults.vulnerabilities || []
    const sslIssues = scanResults.ssl_issues || []

    // 端口表格列定义
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
              pagination={openPorts.length > 10 ? { pageSize: 10, showSizeChanger: true } : false}
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

    // 如果任务已完成，不显示转圈指示器
    if (msg.taskCompleted) return null

    // 多资产进度
    if (msg.isMultiAsset && msg.assetProgress) {
      return renderMultiAssetProgress(msg)
    }

    const stepProgress = msg.stepProgress
    const currentStep = msg.currentStep

    return (
      <div className="scan-animation-fade-in" style={{ marginTop: 4 }}>
        <div className="task-progress-card">
          {/* 进度条 */}
          {stepProgress && stepProgress.total_steps > 0 && (
            <div className="progress-bar-container">
              <Progress
                percent={Math.round(((stepProgress.step_index + 1) / stepProgress.total_steps) * 100)}
                strokeColor={{ from: '#6366f1', to: '#8b5cf6' }}
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
            <LoadingOutlined style={{ color: '#6366f1' }} spin />
            <span className="step-text">{currentStep || '任务执行中...'}</span>
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

  const renderMultiAssetProgress = (msg) => {
    const assetProgress = msg.assetProgress || {}
    const totalAssets = msg.totalAssets || Object.keys(assetProgress).length
    const completedCount = Object.values(assetProgress).filter(a => 
      a.status === 'completed' || a.status === 'failed' || a.status === 'success'
    ).length
    
    const progress = totalAssets > 0 ? Math.round((completedCount / totalAssets) * 100) : 0

    return (
      <div className="scan-animation-fade-in" style={{ marginTop: 4 }}>
        <div className="task-progress-card multi-asset-card">
          {/* 总进度 */}
          <div className="progress-bar-container">
            <Progress
              percent={progress}
              strokeColor={{ from: '#6366f1', to: '#8b5cf6' }}
              showInfo={false}
              size="small"
            />
            <span className="progress-text">
              {completedCount} / {totalAssets}
            </span>
          </div>
          
          {/* 资产列表 */}
          <div className="asset-progress-list">
            {Object.entries(assetProgress).map(([index, asset]) => (
              <div key={index} className={`asset-progress-item ${asset.status}`}>
                {asset.status === 'completed' || asset.status === 'success' ? (
                  <CheckCircleFilled style={{ color: '#10b981' }} />
                ) : asset.status === 'failed' ? (
                  <CloseCircleFilled style={{ color: '#ef4444' }} />
                ) : (
                  <LoadingOutlined style={{ color: '#6366f1' }} spin />
                )}
                <span className="asset-name">{asset.name}</span>
                {asset.status === 'running' && (
                  <span className="asset-status">扫描中...</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  const renderMultiAssetResult = (msg) => {
    const scanResults = msg.scanResults || {}
    const assetResults = scanResults.asset_results || {}
    
    const totalAssets = Object.keys(assetResults).length
    const successCount = Object.values(assetResults).filter(r => 
      r.status === 'success' || r.every(item => item.status === 'success')
    ).length
    const failedCount = totalAssets - successCount

    return (
      <div className="scan-animation-fade-in">
        <div className="message-bubble assistant" style={{ whiteSpace: 'pre-wrap' }}>
          {msg.content}
        </div>
        
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
        
        {/* 资产详情 */}
        <div className="asset-results-details">
          {Object.entries(assetResults).map(([target, results], index) => {
            const isSuccess = Array.isArray(results) 
              ? results.every(r => r.status === 'success')
              : results.status === 'success'
            
            return (
              <div key={index} className={`asset-result-item ${isSuccess ? 'success' : 'failed'}`}>
                <div className="asset-result-header">
                  {isSuccess ? (
                    <CheckCircleFilled style={{ color: '#10b981' }} />
                  ) : (
                    <CloseCircleFilled style={{ color: '#ef4444' }} />
                  )}
                  <span className="asset-target">{target}</span>
                  <Tag color={isSuccess ? 'success' : 'error'}>
                    {isSuccess ? '成功' : '失败'}
                  </Tag>
                </div>
                
                {isSuccess && Array.isArray(results) && results[0]?.result && (
                  <div className="asset-result-data">
                    {results[0].result.open_ports && (
                      <div className="result-stat">
                        开放端口: {results[0].result.open_ports.length}
                      </div>
                    )}
                    {results[0].result.vulnerabilities && (
                      <div className="result-stat">
                        漏洞: {results[0].result.vulnerabilities.length}
                      </div>
                    )}
                  </div>
                )}
                
                {!isSuccess && (
                  <div className="asset-result-error">
                    {Array.isArray(results) ? results[0]?.error : results.error}
                  </div>
                )}
              </div>
            )
          })}
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
        </div>
      </div>

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
              {/* 结果消息 */}
              {msg.isResult ? (
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
    </div>
  )
}

export default ChatWorkspace
