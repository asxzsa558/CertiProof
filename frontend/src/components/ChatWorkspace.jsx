import { useState, useRef, useEffect } from 'react'
import { Input, Button, Avatar, Spin, Empty, Typography, Progress, Tag, Table, message, Modal, Checkbox, Dropdown, Menu, Popconfirm, Drawer, Steps, Form, Collapse } from 'antd'
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
  RocketOutlined,
  DatabaseOutlined,
  KeyOutlined,
  ClusterOutlined,
  CloudServerOutlined,
  GlobalOutlined,
  BugOutlined,
  WindowsOutlined,
  LockOutlined,
  FolderOpenOutlined,
  FileTextOutlined,
  DownOutlined,
  WifiOutlined,
  SearchOutlined,
  RadarChartOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import VeriSureLogo from './VeriSureLogo'
import AssetCredentialModal from './AssetCredentialModal'
import ToolResultCard from './ToolResultCard'
import './ChatWorkspace.css'
import './ScanAnimation.css'

const { TextArea } = Input
const { Text } = Typography

// 工具目录：快捷按钮、斜杠菜单、多资产执行和显示名都从这里派生。
// 组合工具和原子工具平铺展示；组合只是一种预设，不是父级。
const TOOL_CATALOG = [
  { command: '/scan', capability: 'scan_ports', name: '端口扫描', description: '高危/定制端口扫描', usage: '/scan [目标] [端口范围]', icon: <ThunderboltOutlined />, color: '#10b981', primary: true, requiresTarget: true },
  { command: '/scan-full', capability: 'scan_ports', name: '全端口扫描', description: '全端口扫描', usage: '/scan-full [目标]', icon: <ThunderboltOutlined />, color: '#dc2626', more: true, requiresTarget: true, parameters: { port_range: '1-65535' } },
  { command: '/masscan', capability: 'masscan_scan', name: '高速端口扫描', description: '高速端口扫描', usage: '/masscan [目标]', icon: <CloudServerOutlined />, color: '#059669', more: true, requiresTarget: true },
  { command: '/fping', capability: 'fping_scan', name: '批量存活检测', description: '批量存活检测', usage: '/fping [网段]', icon: <WifiOutlined />, color: '#14b8a6', more: true, requiresTarget: true },
  { command: '/ssl', capability: 'scan_ssl', name: 'SSL/TLS 检测', description: 'SSL/TLS 检测', usage: '/ssl [目标]', icon: <LockOutlined />, color: '#0ea5e9', more: true, requiresTarget: true },
  { command: '/vuln', capability: 'scan_vulnerabilities', name: '漏洞扫描', description: '漏洞扫描', usage: '/vuln [目标]', icon: <BugOutlined />, color: '#ef4444', primary: true, requiresTarget: true },
  { command: '/baseline', capability: 'baseline_check', name: '安全基线核查', description: '安全基线核查（自动识别操作系统）', usage: '/baseline [目标]', icon: <SafetyCertificateOutlined />, color: '#3b82f6', primary: true, requiresTarget: true, requiresSsh: true },
  { command: '/web', capability: 'nikto_scan', name: 'Web 安全扫描', description: 'Nikto Web 安全扫描', usage: '/web [URL]', icon: <MonitorOutlined />, color: '#8b5cf6', primary: true, requiresTarget: true },
  { command: '/nikto', capability: 'nikto_scan', name: 'Nikto Web 扫描', description: 'Nikto Web 扫描', usage: '/nikto [URL]', icon: <MonitorOutlined />, color: '#8b5cf6', requiresTarget: true },
  { command: '/sqlmap', capability: 'sqlmap_scan', name: 'SQL 注入检测', description: 'SQL 注入检测', usage: '/sqlmap [URL]', icon: <SearchOutlined />, color: '#8b5cf6', requiresTarget: true },
  { command: '/dirbust', capability: 'web_discovery_scan', name: 'Web 目录发现', description: '组合：Gobuster + FFUF', usage: '/dirbust [URL]', icon: <FolderOpenOutlined />, color: '#f59e0b', more: true, requiresTarget: true },
  { command: '/gobuster', capability: 'gobuster_scan', name: 'Gobuster 目录扫描', description: 'Gobuster 目录扫描', usage: '/gobuster [URL]', icon: <FolderOpenOutlined />, color: '#f59e0b', requiresTarget: true },
  { command: '/ffuf', capability: 'ffuf_scan', name: 'FFUF 模糊测试', description: 'FFUF Web 模糊测试', usage: '/ffuf [URL]', icon: <FolderOpenOutlined />, color: '#f59e0b', requiresTarget: true },
  { command: '/db', capability: 'database_security_scan', name: '数据库安全检测', description: '组合：Redis/MySQL/MongoDB/Memcached/Oracle', usage: '/db [目标]', icon: <DatabaseOutlined />, color: '#06b6d4', primary: true, requiresTarget: true },
  { command: '/redis', capability: 'redis_check', name: 'Redis 检测', description: 'Redis 未授权检测', usage: '/redis [目标]', icon: <DatabaseOutlined />, color: '#06b6d4', requiresTarget: true },
  { command: '/mysql', capability: 'mysql_check', name: 'MySQL 检测', description: 'MySQL 空口令检测', usage: '/mysql [目标]', icon: <DatabaseOutlined />, color: '#06b6d4', requiresTarget: true },
  { command: '/mongodb', capability: 'mongodb_check', name: 'MongoDB 检测', description: 'MongoDB 未授权检测', usage: '/mongodb [目标]', icon: <DatabaseOutlined />, color: '#06b6d4', requiresTarget: true },
  { command: '/memcached', capability: 'memcached_check', name: 'Memcached 检测', description: 'Memcached 未授权检测', usage: '/memcached [目标]', icon: <DatabaseOutlined />, color: '#06b6d4', requiresTarget: true },
  { command: '/oracle', capability: 'oracle_check', name: 'Oracle 检测', description: 'Oracle TNS 检测', usage: '/oracle [目标]', icon: <DatabaseOutlined />, color: '#06b6d4', requiresTarget: true },
  { command: '/snmp', capability: 'network_device_scan', name: '网络设备检测', description: '组合：SNMP 信息 + 团体字检测', usage: '/snmp [目标]', icon: <ClusterOutlined />, color: '#d946ef', more: true, requiresTarget: true },
  { command: '/snmpwalk', capability: 'snmp_walk', name: 'SNMP Walk', description: 'SNMP 信息读取', usage: '/snmpwalk [目标]', icon: <ClusterOutlined />, color: '#d946ef', requiresTarget: true },
  { command: '/snmpget', capability: 'snmp_get', name: 'SNMP OID 检测', description: 'SNMP OID 读取', usage: '/snmpget [目标]', icon: <ClusterOutlined />, color: '#d946ef', requiresTarget: true },
  { command: '/snmp-brute', capability: 'snmp_bruteforce', name: 'SNMP 团体字检测', description: 'SNMP 团体字检测', usage: '/snmp-brute [目标]', icon: <ClusterOutlined />, color: '#d946ef', requiresTarget: true },
  { command: '/password', capability: 'scan_weak_passwords', name: '弱口令检测', description: '弱口令检测', usage: '/password [目标]', icon: <KeyOutlined />, color: '#f97316', primary: true, requiresTarget: true },
  { command: '/windows', capability: 'windows_security_scan', name: 'Windows/AD/SMB 检测', description: '组合：用户/SID/SMB 共享枚举', usage: '/windows [目标]', icon: <WindowsOutlined />, color: '#0f766e', more: true, requiresTarget: true },
  { command: '/enum4linux', capability: 'enum4linux_scan', name: 'Windows 用户/组枚举', description: 'enum4linux 用户/组枚举', usage: '/enum4linux [目标]', icon: <WindowsOutlined />, color: '#0f766e', requiresTarget: true },
  { command: '/smb', capability: 'smb_enum', name: 'SMB 共享枚举', description: 'SMB 共享枚举', usage: '/smb [目标]', icon: <WindowsOutlined />, color: '#0f766e', requiresTarget: true },
  { command: '/cme', capability: 'crackmapexec_scan', name: 'Windows SID 枚举', description: 'Windows SID/SMB 枚举', usage: '/cme [目标]', icon: <WindowsOutlined />, color: '#0f766e', requiresTarget: true },
  { command: '/ping', capability: 'ping_host', name: 'Ping 检测', description: 'Ping 检测', usage: '/ping [目标]', icon: <ApiOutlined />, color: '#64748b', more: true, requiresTarget: true },
  { command: '/all', capability: 'full_compliance_scan', name: '全量合规扫描', description: '组合：端口+SSL+漏洞+弱口令', usage: '/all [目标]', icon: <SafetyCertificateOutlined />, color: '#6366f1', more: true, requiresTarget: true },
  { command: '/tech', capability: 'tech_assessment', name: '等保技术测评', description: '组合：等保技术检查', usage: '/tech [目标]', icon: <ThunderboltOutlined />, color: '#ef4444', more: true, requiresTarget: true, requiresSsh: true },
  { command: '/ssh', capability: 'ssh_config_check', name: 'SSH 配置检查', description: 'SSH 配置检查', usage: '/ssh [目标]', icon: <SafetyCertificateOutlined />, color: '#3b82f6', requiresTarget: true, requiresSsh: true },
]

const SYSTEM_COMMANDS = [
  { command: '/asset', description: '添加资产', usage: '/asset [IP/域名]', defaultText: '/asset ' },
  { command: '/assets', description: '列出项目资产', usage: '/assets', direct: true },
  { command: '/project', description: '列出项目', usage: '/project', defaultText: '列出所有项目' },
  { command: '/assessment', description: '创建/查看等保测评', usage: '/assessment', direct: true },
  { command: '/diagnose', description: 'MCP 连通性测试', usage: '/diagnose', direct: true },
  { command: '/clear', description: '清理对话历史', usage: '/clear', direct: true },
  { command: '/help', description: '显示帮助', usage: '/help', direct: true },
]

const TOOL_BY_COMMAND = Object.fromEntries(TOOL_CATALOG.map(tool => [tool.command, tool]))
const COMMAND_TO_CAPABILITY = Object.fromEntries(TOOL_CATALOG.map(tool => [tool.command, tool.capability]))
const CAPABILITY_NAMES = TOOL_CATALOG.reduce((acc, tool) => {
  acc[tool.capability] = tool.name
  return acc
}, {
  linux_baseline: '安全基线核查',
  ping_asset: 'Ping 检测',
  testssl_scan: 'SSL/TLS 检测',
  nuclei_scan: '漏洞扫描',
  hydra_bruteforce: '弱口令检测',
})

const PRIMARY_SUGGESTIONS = TOOL_CATALOG
  .filter(tool => tool.primary)
  .map(tool => ({ icon: tool.icon, title: tool.name, text: `${tool.command} `, color: tool.color }))

const MORE_SUGGESTIONS = [
  ...TOOL_CATALOG
    .filter(tool => tool.more)
    .map(tool => ({ icon: tool.icon, title: tool.name, text: `${tool.command} `, color: tool.color })),
  { icon: <ApiOutlined />, title: '连通测试', text: '/diagnose', color: '#64748b' },
  { icon: <FileTextOutlined />, title: '查看结果', text: '查看扫描结果', color: '#ec4899', isText: true },
]

const SUGGESTIONS = [
  { icon: <PlusOutlined />, title: '创建项目', text: '创建项目 ', color: '#6366f1' },
  ...PRIMARY_SUGGESTIONS,
  { icon: <RocketOutlined />, title: '等保测评', text: '', color: '#f59e0b', action: 'assessment' },
]

const SLASH_COMMANDS = [
  ...TOOL_CATALOG.map(tool => ({
    command: tool.command,
    description: tool.description,
    usage: tool.usage,
    defaultText: `${tool.command} `,
  })),
  ...SYSTEM_COMMANDS,
]

const FULL_PORT_ALIASES = new Set(['all', 'full', '1-65535', '全端口', '全部端口', '全部'])
const HIGH_RISK_PORT_ALIASES = new Set(['high', 'high-risk', 'risk', '高危', '高危端口'])

const normalizeScanPortRange = (value) => {
  if (!value) return null
  const text = value.trim()
  const lower = text.toLowerCase()
  if (FULL_PORT_ALIASES.has(lower)) return '1-65535'
  if (HIGH_RISK_PORT_ALIASES.has(lower)) return 'high-risk'
  if (/^\d+(-\d+)?(,\d+(-\d+)?)*$/.test(text)) return text
  if (/^top-\d+$/i.test(text)) return lower
  return null
}

const buildScanText = (target, portRange) => {
  if (portRange === '1-65535') return `对 ${target} 进行全端口扫描，端口范围 1-65535`
  if (portRange && portRange !== 'high-risk') return `对 ${target} 进行定制端口扫描，端口范围 ${portRange}`
  return `对 ${target} 进行高危端口扫描`
}

const buildToolActionText = (command, target, options = {}) => {
  if (command === '/scan') return buildScanText(options.scanTarget || target, options.portRange || 'high-risk')
  if (command === '/scan-full') return buildScanText(options.scanTarget || target, '1-65535')
  const tool = TOOL_BY_COMMAND[command]
  if (!tool) return `${command} ${target}`.trim()
  if (command === '/fping') return `对 ${target} 进行批量存活检测`
  return `对 ${target} 进行${tool.name}`
}

const safeJson = (value) => {
  if (value === undefined || value === null) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

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
    if (pollRef.current) {
      clearTimeout(pollRef.current)
      pollRef.current = null
    }
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
          if (completedTaskIdsRef.current.has(taskId)) return
          completedTaskIdsRef.current.add(taskId)
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
    const helpText = `可用命令：

/scan [目标] - 高危端口扫描
/scan [目标] [30-3000] - 定制端口扫描
/scan-full [目标] - 全端口扫描
/masscan [目标] - 高速端口扫描
/ssl [目标] - SSL/TLS 检测
/vuln [目标] - 漏洞扫描
/baseline [目标] - 安全基线核查（自动识别操作系统）
/web [URL] - Web安全扫描
/dirbust [URL] - Web目录发现（目录爆破+模糊测试）
/db [目标] - 数据库安全检测（Redis/MySQL/MongoDB/Memcached/Oracle）
/snmp [目标] - 网络设备检测（SNMP信息+团体字检测）
/windows [目标] - Windows/AD/SMB 组合检测（用户/SID/SMB共享枚举）
/password [目标] - 弱口令检测
/all [目标] - 全量合规扫描
/tech [目标] - 等保技术测评
/ping [目标] - Ping 检测
/asset [值] - 添加资产
/assets - 列出当前项目资产
/project - 列出所有项目
/assessment - 创建/查看等保测评
/diagnose - MCP 连通性测试
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
      } else if (cmd.command === '/assessment') {
        handleAssessmentAction()
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
    const filteredPorts = scanResults.filtered_ports || []
    const vulnerabilities = scanResults.vulnerabilities || []
    const sslIssues = scanResults.ssl_issues || []
    const weakPasswords = scanResults.weak_passwords || []
    const weakPasswordStats = scanResults.weak_password_stats || {}
    const weakPasswordIncompleteTargets = Object.entries(weakPasswordStats)
      .filter(([, stats]) => stats.scan_completed === false)
    const webVulnerabilities = scanResults.web_vulnerabilities || []
    const webDiscoveries = scanResults.web_discoveries || []
    const databaseIssues = scanResults.database_issues || []
    const databaseResults = scanResults.database_results || {}
    const snmpResults = scanResults.snmp_results || {}
    const windowsResults = scanResults.windows_results || {}
    const compositeResults = scanResults.composite_results || []
    const baselineResults = scanResults.baseline_results || {}
    const discoveredAssets = scanResults.discovered_assets || {}

    // 从 asset_results 提取工具类型和状态
    const assetResults = scanResults.asset_results || {}
    const firstAsset = Object.values(assetResults)[0]
    const tool = firstAsset?.capability || 'scan_ports'
    const status = firstAsset?.status === 'failed' ? 'failed' :
                   firstAsset?.display_status || 'success'
    const error = firstAsset?.error
    const copyText = [
      msg.content,
      firstAsset ? `资产/IP: ${Object.keys(assetResults)[0] || firstAsset.result?.target || '-'}` : '',
      `检测工具: ${CAPABILITY_NAMES[tool] || tool}`,
      error ? `错误信息: ${error}` : '',
      scanResults ? `结构化结果:\n${safeJson(scanResults)}` : '',
    ].filter(Boolean).join('\n\n')

    // 构建摘要内容
    const summary = (
      <div className="result-summary">
        {openPorts.length > 0 && (
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(59, 130, 246, 0.2)' }}>
              <MonitorOutlined style={{ color: '#3b82f6' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">明确开放端口</div>
              <div className="summary-value">{openPorts.length} 个</div>
            </div>
          </div>
        )}
        {filteredPorts.length > 0 && (
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(245, 158, 11, 0.2)' }}>
              <ExclamationCircleFilled style={{ color: '#f59e0b' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">被过滤端口</div>
              <div className="summary-value">{filteredPorts.length} 个</div>
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
        {weakPasswords.length > 0 && (
          <div className="summary-item critical">
            <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.3)' }}>
              <KeyOutlined style={{ color: '#ef4444' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">弱口令</div>
              <div className="summary-value" style={{ color: '#ef4444' }}>{weakPasswords.length} 个</div>
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
        {webVulnerabilities.length > 0 && (
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(168, 85, 247, 0.2)' }}>
              <GlobalOutlined style={{ color: '#a855f7' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">Web 漏洞</div>
              <div className="summary-value">{webVulnerabilities.length} 个</div>
            </div>
          </div>
        )}
        {webDiscoveries.length > 0 && (
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(14, 165, 233, 0.2)' }}>
              <FolderOpenOutlined style={{ color: '#0ea5e9' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">Web 发现</div>
              <div className="summary-value">{webDiscoveries.length} 个</div>
            </div>
          </div>
        )}
        {databaseIssues.length > 0 && (
          <div className="summary-item critical">
            <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.2)' }}>
              <DatabaseOutlined style={{ color: '#ef4444' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">数据库风险</div>
              <div className="summary-value">{databaseIssues.length} 项</div>
            </div>
          </div>
        )}
        {Object.keys(snmpResults).length > 0 && (
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(217, 70, 239, 0.2)' }}>
              <ClusterOutlined style={{ color: '#d946ef' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">SNMP</div>
              <div className="summary-value">{Object.keys(snmpResults).length} 个目标</div>
            </div>
          </div>
        )}
        {Object.keys(windowsResults).length > 0 && (
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(100, 116, 139, 0.2)' }}>
              <CloudServerOutlined style={{ color: '#64748b' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">Windows/SMB</div>
              <div className="summary-value">{Object.keys(windowsResults).length} 个目标</div>
            </div>
          </div>
        )}
        {compositeResults.length > 0 && (
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(99, 102, 241, 0.2)' }}>
              <RadarChartOutlined style={{ color: '#6366f1' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">组合扫描</div>
              <div className="summary-value">{compositeResults.length} 组</div>
            </div>
          </div>
        )}
        {Object.keys(discoveredAssets).length > 0 && (
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(16, 185, 129, 0.2)' }}>
              <RadarChartOutlined style={{ color: '#10b981' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">已发现资产</div>
              <div className="summary-value">{Object.keys(discoveredAssets).length} 个</div>
            </div>
          </div>
        )}
      </div>
    )

    // 构建详情内容
    const details = (
      <>
        {/* 错误信息 */}
        {error && (
          <div className="result-details-section error-section">
            <div className="section-title danger">
              <ExclamationCircleFilled style={{ marginRight: 8 }} />
              错误信息
            </div>
            <div className="error-message">{error}</div>
          </div>
        )}

        {/* 弱口令详情 - 高亮显示 */}
        {weakPasswords.length > 0 && (
          <div className="result-details-section weak-password-section">
            <div className="section-title danger">
              ⚠ 发现 {weakPasswords.length} 个弱口令！
            </div>
            {Object.entries(weakPasswordStats).map(([target, stats]) => {
              const targetPasswords = weakPasswords.filter(p => p.target === target)
              return (
                <div key={target} className="weak-password-target">
                  <div className="target-header">
                    <span className="target-name">{target}</span>
                    <span className="target-stats">
                      测试 {stats.tested_users} 用户 × {stats.tested_passwords} 密码 = {stats.total_combinations} 组合
                      {targetPasswords.length > 0 && (
                        <Tag color="red" style={{ marginLeft: 8 }}>
                          ⚠ {targetPasswords.length} 个弱口令
                        </Tag>
                      )}
                    </span>
                  </div>
                  {targetPasswords.length > 0 && (
                    <div className="password-list">
                      {targetPasswords.map((fp, idx) => (
                        <div key={idx} className="password-item danger">
                          <Tag color="red">{fp.username || '?'}</Tag>
                          <span className="password-text">{fp.password || '?'}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {targetPasswords.length === 0 && (
                    <div className={`password-list ${stats.scan_completed === false ? 'warning' : 'success'}`}>
                      <Tag color={stats.scan_completed === false ? 'orange' : 'green'}>{stats.scan_completed === false ? '未完成' : '✓ 安全'}</Tag>
                      <span>{stats.scan_completed === false ? (stats.tool_error || '无法判定是否存在弱口令') : '未发现弱口令'}</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* 弱口令全部安全的提示 */}
        {weakPasswords.length === 0 && Object.keys(weakPasswordStats).length > 0 && (
          <div className={`result-details-section ${weakPasswordIncompleteTargets.length ? 'warning-section' : 'success-section'}`}>
            <div className={`section-title ${weakPasswordIncompleteTargets.length ? 'warning' : 'success'}`}>
              {weakPasswordIncompleteTargets.length ? '⚠ 弱口令检测未完成，无法判定' : '✓ 弱口令检测完成，未发现弱口令'}
            </div>
            {Object.entries(weakPasswordStats).map(([target, stats]) => (
              <div key={target} className="baseline-target-item">
                <span>{target}</span>
                <span className="text-muted">
                  {stats.scan_completed === false
                    ? (stats.tool_error || '目标服务不可达或检测未完成')
                    : `测试 ${stats.tested_users} 用户 × ${stats.tested_passwords} 密码 = ${stats.total_combinations} 组合`}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Web 漏洞详情 */}
        {webVulnerabilities.length > 0 && (
          <div className="result-details-section">
            <div className="section-title">Web 漏洞列表</div>
            {webVulnerabilities.map((vuln, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color="red">{vuln.severity || '未知'}</Tag>
                <span className="vuln-target">[{vuln.target}]</span>
                <span>{vuln.name || vuln.id || 'Web 漏洞'}</span>
                {vuln.tool && <Tag color="purple" style={{ marginLeft: 4 }}>{vuln.tool}</Tag>}
              </div>
            ))}
          </div>
        )}

        {webDiscoveries.length > 0 && (
          <div className="result-details-section">
            <div className="section-title">Web 路径/端点发现</div>
            {webDiscoveries.slice(0, 50).map((item, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color="blue">{item.status || item.status_code || '发现'}</Tag>
                <span className="vuln-target">[{item.target}]</span>
                <span>{item.url || item.path || item.input || '未知端点'}</span>
                {item.tool && <Tag color="purple" style={{ marginLeft: 4 }}>{item.tool}</Tag>}
              </div>
            ))}
            {webDiscoveries.length > 50 && <div className="text-muted">还有 {webDiscoveries.length - 50} 条未展开</div>}
          </div>
        )}

        {databaseIssues.length > 0 && (
          <div className="result-details-section">
            <div className="section-title danger">数据库风险项</div>
            {databaseIssues.map((issue, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color="red">{issue.tool}</Tag>
                <span className="vuln-target">[{issue.target}]</span>
                <span>
                  {issue.unauthorized ? '存在未授权访问' : issue.empty_password ? '存在空口令风险' : issue.version_info ? `暴露版本信息：${issue.version_info}` : '需关注'}
                </span>
              </div>
            ))}
          </div>
        )}

        {Object.keys(databaseResults).length > 0 && databaseIssues.length === 0 && (
          <div className="result-details-section success-section">
            <div className="section-title success">数据库检测完成，未发现明显风险</div>
            {Object.entries(databaseResults).map(([target, tools]) => (
              <div key={target} className="baseline-target-item">
                <span>{target}</span>
                <span className="text-muted">{Object.keys(tools).join(', ')}</span>
              </div>
            ))}
          </div>
        )}

        {Object.keys(snmpResults).length > 0 && (
          <div className="result-details-section">
            <div className="section-title">SNMP 检测结果</div>
            {Object.entries(snmpResults).map(([target, tools]) => (
              <div key={target} className="baseline-target-item">
                <span>{target}</span>
                <span className="text-muted">{Object.keys(tools).join(', ')}</span>
              </div>
            ))}
          </div>
        )}

        {Object.keys(windowsResults).length > 0 && (
          <div className="result-details-section">
            <div className="section-title">Windows/SMB 检测结果</div>
            {Object.entries(windowsResults).map(([target, tools]) => (
              <div key={target} className="baseline-target-item">
                <span>{target}</span>
                <span className="text-muted">{Object.keys(tools).join(', ')}</span>
              </div>
            ))}
          </div>
        )}

        {compositeResults.length > 0 && (
          <div className="result-details-section">
            <div className="section-title">组合扫描子任务</div>
            {(() => {
              const describeSubResult = (sub) => {
                const data = sub.data || {}
                if (data.scan_completed === false || data.success === false) {
                  return `未完成/无响应${data.tool_error ? `：${data.tool_error}` : ''}`
                }
                if (['redis_check', 'mongodb_check', 'memcached_check'].includes(sub.capability)) {
                  return data.unauthorized ? '存在未授权访问' : data.reachable === false ? `不可达/无响应，端口 ${data.port || '-'}` : `未发现未授权访问，端口 ${data.port || '-'}`
                }
                if (sub.capability === 'mysql_check') {
                  return data.empty_password ? '存在空口令' : data.reachable === false ? `不可达/无响应，端口 ${data.port || '-'}` : `未发现空口令，端口 ${data.port || '-'}`
                }
                if (sub.capability === 'oracle_check') {
                  const hasVersion = data.version_info && Object.keys(data.version_info).length > 0
                  return hasVersion ? `存在版本信息，端口 ${data.port || '-'}` : data.reachable === false ? `不可达/无响应，端口 ${data.port || '-'}` : `未发现版本信息泄露，端口 ${data.port || '-'}`
                }
                if (sub.capability === 'nikto_scan') return `Web 问题 ${data.total_findings ?? data.findings?.length ?? 0} 个`
                if (sub.capability === 'scan_ports') return `明确开放 ${data.open_ports?.length || 0} 个，被过滤/未确认 ${data.filtered_count || data.filtered_ports?.length || 0} 个`
                if (sub.capability === 'scan_ssl') return `SSL 问题 ${data.issues?.length || 0} 个`
                if (sub.capability === 'scan_vulnerabilities') return `漏洞 ${data.total_findings ?? data.findings?.length ?? 0} 个`
                if (sub.capability === 'scan_weak_passwords') return `弱口令 ${data.found?.length || 0} 个`
                if (sub.capability === 'snmp_walk') return `SNMP 返回 ${data.total_results || 0} 条`
                return sub.error || '已完成'
              }
              return compositeResults.map((group, groupIdx) => (
                <div key={groupIdx} className="weak-password-target">
                  <div className="target-header">
                    <span className="target-name">{group.target}</span>
                    <span className="target-stats">
                      成功 {group.summary?.success || 0}，失败 {group.summary?.failed || 0}，跳过 {group.summary?.skipped || 0}
                    </span>
                  </div>
                  {(group.sub_results || []).map((sub, idx) => (
                    <div key={idx} className="baseline-target-item">
                      <span>{sub.label || sub.capability}</span>
                      <Tag color={sub.status === 'success' ? 'green' : sub.status === 'skipped' ? 'gold' : 'red'}>{sub.status}</Tag>
                      <span className="text-muted">{describeSubResult(sub)}</span>
                    </div>
                  ))}
                </div>
              ))
            })()}
          </div>
        )}

        {/* 端口详情表格 */}
        {openPorts.length > 0 && (
          <div className="result-details-table">
            <div className="table-header">
              <span>明确开放端口详情</span>
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

        {filteredPorts.length > 0 && (
          <div className="result-details-table">
            <div className="table-header">
              <span>被过滤端口详情（未确认开放）</span>
            </div>
            <div className="info-box warning" style={{ marginBottom: 12 }}>
              <InfoCircleFilled style={{ color: '#f59e0b', marginRight: 8 }} />
              <span>这些端口状态是 filtered/no-response，不能作为 SSH 登录、弱口令或基线检查的开放依据。</span>
            </div>
            <Table
              dataSource={filteredPorts.map((port, idx) => ({ ...port, key: idx }))}
              columns={portColumns}
              pagination={filteredPorts.length > 10 ? { defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] } : false}
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
      </>
    )

    return (
      <div className="scan-animation-fade-in">
        <div className="message-bubble assistant" style={{ whiteSpace: 'pre-wrap' }}>
          {msg.content}
        </div>

        <ToolResultCard
          tool={tool}
          status={status}
          summary={summary}
          details={details}
          copyText={copyText}
        />
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
    const capabilitySet = Array.from(new Set(Object.values(assetResults).map(r => r.capability).filter(Boolean)))
    const mainCapability = capabilitySet.length === 1 ? capabilitySet[0] : 'full_compliance_scan'
    const mainTool = mainCapability
    const overallStatus = failedCount > 0 ? 'failed' : warningCount > 0 ? 'warning' : 'success'
    const statusTextMap = { success: '成功', warning: '警告', failed: '失败', skipped: '跳过' }

    const assetStatusConfig = {
      success: { color: 'success', text: '成功', icon: <CheckCircleFilled /> },
      warning: { color: 'warning', text: '警告', icon: <ExclamationCircleFilled /> },
      failed: { color: 'error', text: '失败', icon: <CloseCircleFilled /> },
    }

    const metricText = (assetData) => {
      const result = assetData.result || {}
      const capability = assetData.capability
      if (capability === 'scan_ports' || capability === 'masscan_scan') {
        return `明确开放 ${result.open_ports?.length || 0}，被过滤/未确认 ${result.filtered_count || result.filtered_ports?.length || 0}`
      }
      if (capability === 'scan_ssl') {
        return result.scan_completed === false || result.reachable === false
          ? 'SSL/TLS 未完成'
          : `SSL 问题 ${result.issues?.length || 0}，漏洞 ${result.vulnerabilities?.length || 0}`
      }
      if (capability === 'scan_vulnerabilities') return `漏洞 ${result.total_findings ?? result.findings?.length ?? 0}`
      if (capability === 'scan_weak_passwords') return `弱口令 ${result.found?.length || 0}`
      if (capability === 'database_security_scan') {
        const summary = result.summary || {}
        return `子项成功 ${summary.success || 0}/${summary.total || result.sub_results?.length || 0}`
      }
      if (result.sub_results) {
        const summary = result.summary || {}
        return `子项成功 ${summary.success || 0}，失败 ${summary.failed || 0}，跳过 ${summary.skipped || 0}`
      }
      if (capability === 'baseline_check' || capability === 'linux_baseline') {
        return result.skipped ? (result.connection_error ? '无法连接' : '已跳过') : `未通过 ${result.summary?.non_compliant || 0} 项`
      }
      if (capability === 'nikto_scan') return `Web 问题 ${result.total_findings ?? result.findings?.length ?? 0}`
      return assetData.error || '已完成'
    }

    const buildMultiAssetCopyText = () => {
      const lines = []
      if (msg.content) lines.push(msg.content)
      lines.push(`总资产数: ${totalAssets}`)
      lines.push(`成功: ${successCount}`)
      if (warningCount) lines.push(`警告/未完成: ${warningCount}`)
      if (failedCount) lines.push(`失败: ${failedCount}`)
      lines.push(`检测工具: ${capabilitySet.map(c => CAPABILITY_NAMES[c] || c).join('、') || '安全检测'}`)
      lines.push('')

      Object.entries(assetResults).forEach(([target, assetData], index) => {
        const displayStatus = assetData.display_status || (assetData.status === 'success' ? 'success' : 'failed')
        const capability = assetData.capability
        lines.push(`资产 ${index + 1}: ${target}`)
        lines.push(`状态: ${statusTextMap[displayStatus] || displayStatus}`)
        lines.push(`工具: ${CAPABILITY_NAMES[capability] || capability}`)
        lines.push(`摘要: ${metricText(assetData)}`)
        if (assetData.error) lines.push(`错误: ${assetData.error}`)
        if (assetData.error_detail) lines.push(`错误详情: ${safeJson(assetData.error_detail)}`)
        if (assetData.result) lines.push(`结果:\n${safeJson(assetData.result)}`)
        lines.push('')
      })

      return lines.join('\n').trim()
    }

    // Helper: Build summary for a single asset
    const buildAssetSummary = (assetData, capability) => {
      const result = assetData.result || {}
      const openPorts = assetData.result?.open_ports || []
      const filteredPorts = assetData.result?.filtered_ports || []
      const vulnerabilities = assetData.result?.vulnerabilities || []
      const findings = assetData.result?.findings || []
      const issues = assetData.result?.issues || []
      const weakPasswords = assetData.result?.weak_passwords || []
      const rawWeakPasswords = assetData.result?.found || []
      const weakPasswordIncomplete = capability === 'scan_weak_passwords' && (
        assetData.result?.scan_completed === false ||
        assetData.result?.reachable === false ||
        assetData.display_status === 'warning'
      )
      const weakPasswordStats = assetData.result?.weak_password_stats || {}
      const webVulnerabilities = assetData.result?.web_vulnerabilities || []
      const webDiscoveries = assetData.result?.web_discoveries || []
      const sslIssues = assetData.result?.ssl_issues || []
      const compositeResults = assetData.result?.composite_results || (assetData.result?.sub_results ? [{
        target: assetData.result?.target,
        summary: assetData.result?.summary,
        sub_results: assetData.result?.sub_results,
      }] : [])
      const discoveredAssets = assetData.result?.discovered_assets || {}
      
      const items = []
      if (openPorts.length > 0) items.push({ label: '明确开放端口', value: `${openPorts.length} 个`, color: '#3b82f6', icon: <MonitorOutlined /> })
      if (filteredPorts.length > 0) items.push({ label: '被过滤端口', value: `${filteredPorts.length} 个`, color: '#f59e0b', icon: <ExclamationCircleFilled /> })
      if (vulnerabilities.length > 0) items.push({ label: '漏洞', value: `${vulnerabilities.length} 个`, color: '#ef4444', icon: <CloseCircleFilled /> })
      if (findings.length > 0) items.push({ label: capability === 'nikto_scan' ? 'Web 问题' : '发现项', value: `${findings.length} 个`, color: '#ef4444', icon: <BugOutlined /> })
      if (weakPasswords.length > 0) items.push({ label: '弱口令', value: `${weakPasswords.length} 个`, color: '#ef4444', icon: <KeyOutlined /> })
      if (rawWeakPasswords.length > 0) items.push({ label: '弱口令', value: `${rawWeakPasswords.length} 个`, color: '#ef4444', icon: <KeyOutlined /> })
      if (sslIssues.length > 0) items.push({ label: 'SSL 问题', value: `${sslIssues.length} 个`, color: '#f59e0b', icon: <SafetyCertificateOutlined /> })
      if (issues.length > 0) items.push({ label: '问题', value: `${issues.length} 个`, color: '#f59e0b', icon: <SafetyCertificateOutlined /> })
      if (webVulnerabilities.length > 0) items.push({ label: 'Web 漏洞', value: `${webVulnerabilities.length} 个`, color: '#a855f7', icon: <GlobalOutlined /> })
      if (webDiscoveries.length > 0) items.push({ label: 'Web 发现', value: `${webDiscoveries.length} 个`, color: '#0ea5e9', icon: <FolderOpenOutlined /> })
      if (compositeResults.length > 0) {
        const summary = compositeResults[0]?.summary || {}
        items.push({ label: '子项结果', value: `${summary.success || 0}/${summary.total || compositeResults[0]?.sub_results?.length || 0}`, color: '#6366f1', icon: <RadarChartOutlined /> })
      }
      if (Object.keys(discoveredAssets).length > 0) items.push({ label: '已发现资产', value: `${Object.keys(discoveredAssets).length} 个`, color: '#10b981', icon: <RadarChartOutlined /> })
      if (capability === 'nikto_scan' && findings.length === 0) items.push({ label: 'Web 问题', value: '0 个', color: '#10b981', icon: <GlobalOutlined /> })
      if (capability === 'sqlmap_scan' && !result.vulnerable) items.push({ label: 'SQL 注入', value: '未发现', color: '#10b981', icon: <SearchOutlined /> })
      if (['redis_check', 'mongodb_check', 'memcached_check'].includes(capability)) {
        items.push({ label: '未授权访问', value: result.unauthorized ? '存在' : '未发现', color: result.unauthorized ? '#ef4444' : '#10b981', icon: <DatabaseOutlined /> })
      }
      if (capability === 'mysql_check') {
        items.push({ label: '空口令', value: result.empty_password ? '存在' : '未发现', color: result.empty_password ? '#ef4444' : '#10b981', icon: <DatabaseOutlined /> })
      }
      if (capability === 'oracle_check') {
        const hasVersion = result.version_info && Object.keys(result.version_info).length > 0
        items.push({ label: '版本信息泄露', value: hasVersion ? '存在' : '未发现', color: hasVersion ? '#f59e0b' : '#10b981', icon: <DatabaseOutlined /> })
      }
      if (capability === 'scan_weak_passwords' && rawWeakPasswords.length === 0) {
        items.push({
          label: '弱口令',
          value: weakPasswordIncomplete ? '无法判定' : '未发现',
          color: weakPasswordIncomplete ? '#f59e0b' : '#10b981',
          icon: <KeyOutlined />,
        })
      }
      if (capability === 'scan_vulnerabilities' && findings.length === 0) items.push({ label: '漏洞', value: '0 个', color: '#10b981', icon: <BugOutlined /> })
      if (capability === 'scan_ssl') {
        const sslDone = result.scan_completed !== false && result.reachable !== false
        items.push({ label: 'SSL 状态', value: sslDone ? '已完成' : '未完成', color: sslDone ? '#10b981' : '#f59e0b', icon: <SafetyCertificateOutlined /> })
        if (result.tls_version) items.push({ label: 'TLS 版本', value: result.tls_version, color: '#3b82f6', icon: <LockOutlined /> })
        if (result.certificate) items.push({ label: '证书', value: '已获取', color: '#10b981', icon: <SafetyCertificateOutlined /> })
      }
      if (capability === 'fping_scan') items.push({ label: '存活主机', value: `${result.alive_count || 0}/${result.total_scanned || 0}`, color: '#10b981', icon: <WifiOutlined /> })
      if (capability === 'snmp_walk') items.push({ label: 'SNMP 返回', value: `${result.total_results || 0} 条`, color: result.success ? '#10b981' : '#f59e0b', icon: <ClusterOutlined /> })
      if (['baseline_check', 'linux_baseline'].includes(capability)) {
        const summary = result.summary || {}
        items.push({ label: '操作系统', value: result.os_type || '未知', color: '#3b82f6', icon: <MonitorOutlined /> })
        if (result.skipped) {
          items.push({ label: '核查状态', value: result.connection_error ? '无法连接' : '已跳过', color: '#f59e0b', icon: <ExclamationCircleFilled /> })
        } else {
          items.push({ label: '未通过', value: `${summary.non_compliant || 0} 项`, color: summary.non_compliant ? '#ef4444' : '#10b981', icon: <SafetyCertificateOutlined /> })
        }
      }
      
      if (items.length === 0) {
        return (
          <div className="result-summary">
            <div className="summary-item">
              <div className="summary-icon" style={{ background: 'rgba(16, 185, 129, 0.2)' }}>
                <CheckCircleFilled style={{ color: '#10b981' }} />
              </div>
              <div className="summary-content">
                <div className="summary-title">执行状态</div>
                <div className="summary-value">完成</div>
              </div>
            </div>
          </div>
        )
      }
      
      return (
        <div className="result-summary">
          {items.map((item, idx) => (
            <div key={idx} className="summary-item">
              <div className="summary-icon" style={{ background: `rgba(${item.color.slice(1)}, 0.2)` }}>
                <span style={{ color: item.color }}>{item.icon}</span>
              </div>
              <div className="summary-content">
                <div className="summary-title">{item.label}</div>
                <div className="summary-value" style={{ color: item.color }}>{item.value}</div>
              </div>
            </div>
          ))}
        </div>
      )
    }

    // Helper: Build details for a single asset
    const buildAssetDetails = (assetData, capability) => {
      const result = assetData.result || {}
      const openPorts = assetData.result?.open_ports || []
      const filteredPorts = assetData.result?.filtered_ports || []
      const vulnerabilities = assetData.result?.vulnerabilities || []
      const findings = assetData.result?.findings || []
      const issues = assetData.result?.issues || []
      const weakPasswords = assetData.result?.weak_passwords || []
      const rawWeakPasswords = assetData.result?.found || []
      const weakPasswordStats = assetData.result?.weak_password_stats || {}
      const weakPasswordIncomplete = capability === 'scan_weak_passwords' && (
        assetData.result?.scan_completed === false ||
        assetData.result?.reachable === false ||
        assetData.display_status === 'warning'
      )
      const webVulnerabilities = assetData.result?.web_vulnerabilities || []
      const webDiscoveries = assetData.result?.web_discoveries || []
      const compositeResults = assetData.result?.composite_results || (assetData.result?.sub_results ? [{
        target: assetData.result?.target,
        summary: assetData.result?.summary,
        sub_results: assetData.result?.sub_results,
      }] : [])
      const errorMsg = assetData.error
      const errorDetail = assetData.error_detail || result.error_detail
      
      const sections = []
      
      // Error section
      if (errorMsg) {
        sections.push(
          <div key="error" className="result-details-section error-section">
            <div className="section-title danger">
              <ExclamationCircleFilled style={{ marginRight: 8 }} />
              错误信息
            </div>
            {errorDetail ? (
              <>
                <div className="baseline-target-item">
                  <span>错误类型</span>
                  <Tag color="red">{errorDetail.error_type || 'tool_execution_failed'}</Tag>
                </div>
                <div className="baseline-target-item">
                  <span>具体原因</span>
                  <span className="text-muted">{errorDetail.error_reason || errorMsg}</span>
                </div>
                <div className="baseline-target-item">
                  <span>处理建议</span>
                  <span className="text-muted">{errorDetail.remediation || '检查目标、网络和工具诊断后重试'}</span>
                </div>
                <div className="error-message">{errorDetail.raw_error || errorMsg}</div>
              </>
            ) : (
              <div className="error-message">{errorMsg}</div>
            )}
          </div>
        )
      }
      
      // Weak passwords
      if (weakPasswords.length > 0) {
        sections.push(
          <div key="weak-passwords" className="result-details-section weak-password-section">
            <div className="section-title danger">
              ⚠ 发现 {weakPasswords.length} 个弱口令！
            </div>
            {Object.entries(weakPasswordStats).map(([target, stats]) => {
              const targetPasswords = weakPasswords.filter(p => p.target === target)
              return (
                <div key={target} className="weak-password-target">
                  <div className="target-header">
                    <span className="target-name">{target}</span>
                    <span className="target-stats">
                      测试 {stats.tested_users} 用户 × {stats.tested_passwords} 密码 = {stats.total_combinations} 组合
                      {targetPasswords.length > 0 && (
                        <Tag color="red" style={{ marginLeft: 8 }}>
                          ⚠ {targetPasswords.length} 个弱口令
                        </Tag>
                      )}
                    </span>
                  </div>
                  {targetPasswords.length > 0 && (
                    <div className="password-list">
                      {targetPasswords.map((fp, idx) => (
                        <div key={idx} className="password-item danger">
                          <Tag color="red">{fp.username || '?'}</Tag>
                          <span className="password-text">{fp.password || '?'}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {targetPasswords.length === 0 && (
                    <div className={`password-list ${stats.scan_completed === false ? 'warning' : 'success'}`}>
                      <Tag color={stats.scan_completed === false ? 'orange' : 'green'}>{stats.scan_completed === false ? '未完成' : '✓ 安全'}</Tag>
                      <span>{stats.scan_completed === false ? (stats.tool_error || '无法判定是否存在弱口令') : '未发现弱口令'}</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )
      }

      if (capability === 'scan_weak_passwords') {
        const weakPasswordError = result.tool_error || assetData.error || '目标服务不可达或检测未完成'
        sections.push(
          <div key="raw-weak-passwords" className={`result-details-section ${rawWeakPasswords.length ? 'weak-password-section' : weakPasswordIncomplete ? 'warning-section' : 'success-section'}`}>
            <div className={`section-title ${rawWeakPasswords.length ? 'danger' : weakPasswordIncomplete ? 'warning' : 'success'}`}>
              弱口令检测：{rawWeakPasswords.length ? `发现 ${rawWeakPasswords.length} 个弱口令` : weakPasswordIncomplete ? '未完成，无法判定' : '未发现弱口令'}
            </div>
            {weakPasswordIncomplete && (
              <div className="baseline-target-item">
                <span>原因</span>
                <span className="text-muted">{weakPasswordError}</span>
              </div>
            )}
            <div className="baseline-target-item">
              <span>服务</span>
              <span className="text-muted">{result.service || 'ssh'}:{result.port || 22}</span>
            </div>
            <div className="baseline-target-item">
              <span>组合数</span>
              <span className="text-muted">{result.tested_users || 0} 用户 x {result.tested_passwords || 0} 密码 = {result.total_combinations || 0}</span>
            </div>
            {rawWeakPasswords.map((fp, idx) => (
              <div key={idx} className="password-item danger">
                <Tag color="red">{fp.username || '?'}</Tag>
                <span className="password-text">{fp.password || '?'}</span>
              </div>
            ))}
          </div>
        )
      }
      
      // Web vulnerabilities
      if (webVulnerabilities.length > 0) {
        sections.push(
          <div key="web-vulns" className="result-details-section">
            <div className="section-title">Web 漏洞列表</div>
            {webVulnerabilities.map((vuln, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color="red">{vuln.severity || '未知'}</Tag>
                <span className="vuln-target">[{vuln.target}]</span>
                <span>{vuln.name || vuln.id || 'Web 漏洞'}</span>
                {vuln.tool && <Tag color="purple" style={{ marginLeft: 4 }}>{vuln.tool}</Tag>}
              </div>
            ))}
          </div>
        )
      }

      if (capability === 'nikto_scan') {
        sections.push(
          <div key="nikto-summary" className={`result-details-section ${findings.length ? '' : 'success-section'}`}>
            <div className={`section-title ${findings.length ? '' : 'success'}`}>
              Nikto Web 扫描：{findings.length ? `发现 ${findings.length} 个问题` : '未发现 Web 问题'}
            </div>
            <div className="baseline-target-item">
              <span>扫描目标</span>
              <span className="text-muted">{result.target || '-'}</span>
            </div>
            {findings.map((finding, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color="orange">{finding.severity || finding.osvdb || '发现'}</Tag>
                <span>{finding.name || finding.description || finding.message || finding.id || 'Web 问题'}</span>
              </div>
            ))}
          </div>
        )
      }

      if (capability === 'sqlmap_scan') {
        const injectionPoints = result.injection_points || []
        sections.push(
          <div key="sqlmap-summary" className={`result-details-section ${result.vulnerable ? 'weak-password-section' : 'success-section'}`}>
            <div className={`section-title ${result.vulnerable ? 'danger' : 'success'}`}>
              SQL 注入检测：{result.vulnerable ? `发现 ${injectionPoints.length || 1} 个注入点` : '未发现注入点'}
            </div>
            <div className="baseline-target-item">
              <span>扫描 URL</span>
              <span className="text-muted">{result.url || result.target || '-'}</span>
            </div>
          </div>
        )
      }

      if (capability === 'scan_vulnerabilities') {
        const durationMs = result.metadata?.duration_ms
        const vulnDone = result.scan_completed !== false
        sections.push(
          <div key="nuclei-summary" className={`result-details-section ${!vulnDone || findings.length ? 'weak-password-section' : 'success-section'}`}>
            <div className={`section-title ${!vulnDone || findings.length ? 'danger' : 'success'}`}>
              漏洞扫描：{!vulnDone ? '未完成' : findings.length ? `发现 ${findings.length} 个漏洞/发现项` : '未发现漏洞'}
            </div>
            <div className="baseline-target-item">
              <span>扫描目标</span>
              <span className="text-muted">{result.target || '-'}</span>
            </div>
            <div className="baseline-target-item">
              <span>扫描引擎</span>
              <span className="text-muted">nuclei</span>
            </div>
            <div className="baseline-target-item">
              <span>模板/级别</span>
              <span className="text-muted">{result.templates || '默认模板'} / {result.severity_filter || '全部级别'}</span>
            </div>
            {durationMs !== undefined && (
              <div className="baseline-target-item">
                <span>耗时</span>
                <span className="text-muted">{Math.round(durationMs / 1000)} 秒</span>
              </div>
            )}
            {result.tool_error && (
              <div className="baseline-target-item">
                <span>工具提示</span>
                <span className="text-muted">{result.tool_error}</span>
              </div>
            )}
            {findings.map((finding, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color={finding.severity === 'critical' || finding.severity === 'high' ? 'red' : finding.severity === 'medium' ? 'orange' : 'blue'}>
                  {finding.severity || 'info'}
                </Tag>
                <span className="vuln-target">[{finding.host || finding.matched_at || result.target}]</span>
                <span>{finding.name || finding.template_id || '漏洞发现项'}</span>
                {finding.template_id && <Tag color="purple" style={{ marginLeft: 4 }}>{finding.template_id}</Tag>}
              </div>
            ))}
          </div>
        )
      }

      if (['redis_check', 'mysql_check', 'mongodb_check', 'memcached_check', 'oracle_check'].includes(capability)) {
        const dbLabels = {
          redis_check: 'Redis 未授权访问',
          mysql_check: 'MySQL 空口令',
          mongodb_check: 'MongoDB 未授权访问',
          memcached_check: 'Memcached 未授权访问',
          oracle_check: 'Oracle TNS 版本信息',
        }
        const risky = result.unauthorized || result.empty_password || (result.version_info && Object.keys(result.version_info).length > 0)
        sections.push(
          <div key="database-summary" className={`result-details-section ${risky ? 'weak-password-section' : 'success-section'}`}>
            <div className={`section-title ${risky ? 'danger' : 'success'}`}>
              {dbLabels[capability]}：{risky ? '发现需关注项' : '未发现明显风险'}
            </div>
            <div className="baseline-target-item">
              <span>目标端口</span>
              <span className="text-muted">{result.target || '-'}:{result.port || '-'}</span>
            </div>
            {'reachable' in result && (
              <div className="baseline-target-item">
                <span>连接状态</span>
                <Tag color={result.reachable === false ? 'gold' : 'green'}>{result.reachable === false ? '不可达/无响应' : '可连接'}</Tag>
              </div>
            )}
            {result.tool_error && (
              <div className="baseline-target-item">
                <span>工具提示</span>
                <span className="text-muted">{result.tool_error}</span>
              </div>
            )}
          </div>
        )
      }

      if (capability === 'scan_ssl') {
        const cert = result.certificate || {}
        const sslDone = result.scan_completed !== false && result.reachable !== false
        sections.push(
          <div key="ssl-summary" className={`result-details-section ${sslDone ? (issues.length || vulnerabilities.length ? 'warning-section' : 'success-section') : 'warning-section'}`}>
            <div className={`section-title ${sslDone && !issues.length && !vulnerabilities.length ? 'success' : 'warning'}`}>
              SSL/TLS 检测：{sslDone ? `问题 ${issues.length || 0} 个，漏洞 ${vulnerabilities.length || 0} 个` : '未完成'}
            </div>
            <div className="baseline-target-item">
              <span>检测目标</span>
              <span className="text-muted">{result.target || '-'}:{result.port || 443}</span>
            </div>
            <div className="baseline-target-item">
              <span>连接状态</span>
              <Tag color={sslDone ? 'green' : 'gold'}>{sslDone ? '已完成 TLS 检测' : '未获取 TLS 信息'}</Tag>
            </div>
            <div className="baseline-target-item">
              <span>TLS 版本</span>
              <span className="text-muted">{result.tls_version || '未获取'}</span>
            </div>
            <div className="baseline-target-item">
              <span>证书主体</span>
              <span className="text-muted">{cert.subject || '未获取'}</span>
            </div>
            <div className="baseline-target-item">
              <span>证书签发者</span>
              <span className="text-muted">{cert.issuer || '未获取'}</span>
            </div>
            {result.tool_error && (
              <div className="baseline-target-item">
                <span>工具提示</span>
                <span className="text-muted">{result.tool_error}</span>
              </div>
            )}
            {issues.map((issue, idx) => (
              <div key={idx} className="ssl-issue-item">
                <Tag color="orange">警告</Tag>
                <span>{issue}</span>
              </div>
            ))}
          </div>
        )
      }

      if (capability === 'fping_scan') {
        sections.push(
          <div key="fping-summary" className="result-details-section">
            <div className="section-title">批量存活检测</div>
            <div className="baseline-target-item">
              <span>扫描数量</span>
              <span className="text-muted">{result.total_scanned || 0}</span>
            </div>
            <div className="baseline-target-item">
              <span>存活主机</span>
              <span className="text-muted">{(result.alive_hosts || []).join(', ') || '无'}</span>
            </div>
          </div>
        )
      }

      if (capability === 'snmp_walk') {
        sections.push(
          <div key="snmp-summary" className="result-details-section">
            <div className="section-title">SNMP 检测结果</div>
            <div className="baseline-target-item">
              <span>返回结果</span>
              <span className="text-muted">{result.total_results || 0} 条</span>
            </div>
            {result.tool_error && (
              <div className="baseline-target-item">
                <span>工具提示</span>
                <span className="text-muted">{result.tool_error}</span>
              </div>
            )}
          </div>
        )
      }

      if (['baseline_check', 'linux_baseline'].includes(capability)) {
        const summary = result.summary || {}
        const baselineReason = result.error_detail?.error_reason || result.skip_reason || result.tool_error
        const baselineRemediation = result.error_detail?.remediation
        sections.push(
          <div key="baseline-summary" className={`result-details-section ${result.skipped ? 'warning-section' : 'success-section'}`}>
            <div className={`section-title ${result.skipped ? 'warning' : 'success'}`}>
              安全基线核查：{result.skipped ? (result.connection_error ? '无法连接目标' : '已跳过') : `未通过 ${summary.non_compliant || 0} 项`}
            </div>
            <div className="baseline-target-item">
              <span>目标</span>
              <span className="text-muted">{result.target || '-'}</span>
            </div>
            <div className="baseline-target-item">
              <span>操作系统</span>
              <span className="text-muted">{result.os_type || '未知'}</span>
            </div>
            {baselineReason && (
              <div className="baseline-target-item">
                <span>原因</span>
                <span className="text-muted">{baselineReason}</span>
              </div>
            )}
            {baselineRemediation && (
              <div className="baseline-target-item">
                <span>建议</span>
                <span className="text-muted">{baselineRemediation}</span>
              </div>
            )}
          </div>
        )
      }

      if (webDiscoveries.length > 0) {
        sections.push(
          <div key="web-discoveries" className="result-details-section">
            <div className="section-title">Web 路径/端点发现</div>
            {webDiscoveries.slice(0, 30).map((item, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color="blue">{item.status || item.status_code || '发现'}</Tag>
                <span>{item.url || item.path || item.input || '未知端点'}</span>
              </div>
            ))}
          </div>
        )
      }

      if (compositeResults.length > 0) {
        const describeSubResult = (sub) => {
          const data = sub.data || {}
          if (data.scan_completed === false || data.success === false) {
            return `未完成/无响应${data.tool_error ? `：${data.tool_error}` : ''}`
          }
          if (['redis_check', 'mongodb_check', 'memcached_check'].includes(sub.capability)) {
            return data.unauthorized ? '存在未授权访问' : data.reachable === false ? '不可达/无响应，未发现未授权访问' : '未发现未授权访问'
          }
          if (sub.capability === 'mysql_check') {
            return data.empty_password ? '存在空口令' : data.reachable === false ? '不可达/无响应，未发现空口令' : '未发现空口令'
          }
          if (sub.capability === 'oracle_check') {
            const hasVersion = data.version_info && Object.keys(data.version_info).length > 0
            return hasVersion ? '存在版本信息泄露' : data.reachable === false ? '不可达/无响应，未发现版本信息泄露' : '未发现版本信息泄露'
          }
          if (sub.capability === 'nikto_scan') return `Web 问题 ${data.total_findings ?? data.findings?.length ?? 0} 个`
          if (sub.capability === 'scan_ports') return `明确开放 ${data.open_ports?.length || 0} 个，被过滤/未确认 ${data.filtered_count || data.filtered_ports?.length || 0} 个`
          if (sub.capability === 'scan_ssl') return `SSL 问题 ${data.issues?.length || 0} 个`
          if (sub.capability === 'scan_vulnerabilities') return `漏洞 ${data.total_findings ?? data.findings?.length ?? 0} 个`
          if (sub.capability === 'scan_weak_passwords') return `弱口令 ${data.found?.length || 0} 个`
          if (sub.capability === 'snmp_walk') return `SNMP 返回 ${data.total_results || 0} 条`
          return sub.error || '已完成'
        }
        sections.push(
          <div key="composite-results" className="result-details-section">
            <div className="section-title">组合扫描子任务</div>
            {compositeResults.map((group, groupIdx) => (
              <div key={groupIdx} className="weak-password-target">
                <div className="target-header">
                  <span className="target-name">{group.target}</span>
                  <span className="target-stats">
                    成功 {group.summary?.success || 0}，失败 {group.summary?.failed || 0}，跳过 {group.summary?.skipped || 0}
                  </span>
                </div>
                {(group.sub_results || []).map((sub, idx) => (
                  <div key={idx} className="baseline-target-item">
                    <span>{sub.label || sub.capability}</span>
                    <Tag color={sub.status === 'success' ? 'green' : sub.status === 'skipped' ? 'gold' : 'red'}>{sub.status}</Tag>
                    <span className="text-muted">{describeSubResult(sub)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )
      }
      
      // Port table
      if (openPorts.length > 0) {
        sections.push(
          <div key="ports" className="result-details-table">
            <div className="table-header"><span>明确开放端口详情</span></div>
            <Table
              dataSource={openPorts.map((port, idx) => ({ ...port, key: idx }))}
              columns={portColumns}
              pagination={openPorts.length > 10 ? { defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] } : false}
              size="small"
              className="port-table-compact"
            />
          </div>
        )
      }

      if (filteredPorts.length > 0) {
        sections.push(
          <div key="filtered-ports" className="result-details-table">
            <div className="table-header"><span>被过滤端口详情（未确认开放）</span></div>
            <div className="info-box warning" style={{ marginBottom: 12 }}>
              <InfoCircleFilled style={{ color: '#f59e0b', marginRight: 8 }} />
              <span>filtered/no-response 表示被过滤或无响应，不能当作开放端口。</span>
            </div>
            <Table
              dataSource={filteredPorts.map((port, idx) => ({ ...port, key: idx }))}
              columns={portColumns}
              pagination={filteredPorts.length > 10 ? { defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] } : false}
              size="small"
              className="port-table-compact"
            />
          </div>
        )
      }
      
      // Vulnerabilities
      if (vulnerabilities.length > 0) {
        sections.push(
          <div key="vulns" className="result-details-section">
            <div className="section-title">漏洞列表</div>
            {vulnerabilities.map((vuln, idx) => (
              <div key={idx} className="vulnerability-item">
                <Tag color={vuln.severity === 'critical' ? 'red' : vuln.severity === 'high' ? 'red' : 'orange'}>{vuln.severity || '未知'}</Tag>
                <span>{vuln.name || vuln.id || '漏洞'}</span>
              </div>
            ))}
          </div>
        )
      }
      
      return <>{sections}</>
    }

    // Map capability to ToolResultCard tool name
    const capabilityToTool = {
      ...Object.fromEntries(TOOL_CATALOG.map(tool => [tool.capability, tool.capability])),
      ping_asset: 'ping_host',
      linux_baseline: 'baseline_check',
      testssl_scan: 'scan_ssl',
      nuclei_scan: 'scan_vulnerabilities',
      hydra_bruteforce: 'scan_weak_passwords',
    }

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
        
        <ToolResultCard
          tool={mainTool}
          status={overallStatus}
          summary={
            <div className="asset-unified-summary">
              <div className="baseline-target-item">
                <span>检测工具</span>
                <span className="text-muted">{capabilitySet.map(c => CAPABILITY_NAMES[c] || c).join('、') || '安全检测'}</span>
              </div>
              <div className="baseline-target-item">
                <span>资产范围</span>
                <span className="text-muted">{Object.keys(assetResults).join('、')}</span>
              </div>
            </div>
          }
          details={
            <Collapse
              className="asset-result-collapse"
              bordered={false}
              defaultActiveKey={totalAssets <= 2 ? Object.keys(assetResults) : []}
              items={Object.entries(assetResults).map(([target, assetData]) => {
                const displayStatus = assetData.display_status || (assetData.status === 'success' ? 'success' : 'failed')
                const capability = assetData.capability
                const currentStatus = assetStatusConfig[displayStatus] || assetStatusConfig.success
                return {
                  key: target,
                  label: (
                    <div className="asset-collapse-label">
                      <span className="asset-collapse-target">{target}</span>
                      <Tag color={currentStatus.color} icon={currentStatus.icon}>{currentStatus.text}</Tag>
                      <Tag color="blue">{CAPABILITY_NAMES[capability] || capability}</Tag>
                      <span className="asset-collapse-metric">{metricText(assetData)}</span>
                    </div>
                  ),
                  children: (
                    <div className="asset-collapse-body">
                      <div className="asset-result-identity">
                        <div className="baseline-target-item">
                          <span>资产/IP</span>
                          <span className="text-muted">{target}</span>
                        </div>
                        <div className="baseline-target-item">
                          <span>检测工具</span>
                          <span className="text-muted">{CAPABILITY_NAMES[capability] || capability}</span>
                        </div>
                      </div>
                      {buildAssetSummary(assetData, capability)}
                      {buildAssetDetails(assetData, capability)}
                    </div>
                  ),
                }
              })}
            />
          }
          copyText={buildMultiAssetCopyText()}
        />
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
