import {
  ThunderboltOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
  MonitorOutlined,
  PlusOutlined,
  ApiOutlined,
  DatabaseOutlined,
  KeyOutlined,
  ClusterOutlined,
  CloudServerOutlined,
  BugOutlined,
  FileTextOutlined,
  WindowsOutlined,
  LockOutlined,
  FolderOpenOutlined,
  RocketOutlined,
  WifiOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { TOOL_CATALOG as TOOL_CONFIG, CAPABILITY_NAMES } from './toolCatalog'

const ICON_BY_KEY = {
  thunderbolt: <ThunderboltOutlined />,
  'cloud-server': <CloudServerOutlined />,
  wifi: <WifiOutlined />,
  lock: <LockOutlined />,
  bug: <BugOutlined />,
  'safety-certificate': <SafetyCertificateOutlined />,
  monitor: <MonitorOutlined />,
  search: <SearchOutlined />,
  'folder-open': <FolderOpenOutlined />,
  database: <DatabaseOutlined />,
  cluster: <ClusterOutlined />,
  key: <KeyOutlined />,
  windows: <WindowsOutlined />,
  api: <ApiOutlined />,
}

const TOOL_CATALOG = TOOL_CONFIG.map(tool => ({
  ...tool,
  icon: ICON_BY_KEY[tool.iconKey] || <ApiOutlined />,
}))

// 工具目录：快捷按钮、斜杠菜单、多资产执行和显示名都从这里派生。
// 组合工具和原子工具平铺展示；组合只是一种预设，不是父级。
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


export {
  TOOL_CATALOG,
  SYSTEM_COMMANDS,
  TOOL_BY_COMMAND,
  COMMAND_TO_CAPABILITY,
  PRIMARY_SUGGESTIONS,
  MORE_SUGGESTIONS,
  SUGGESTIONS,
  SLASH_COMMANDS,
  normalizeScanPortRange,
  buildScanText,
  buildToolActionText,
  CAPABILITY_NAMES,
}
