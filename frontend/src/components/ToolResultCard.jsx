import React, { useState } from 'react'
import { Tag, Button, message } from 'antd'
import {
  CopyOutlined,
  DownOutlined,
  UpOutlined,
  MonitorOutlined,
  CloseCircleFilled,
  KeyOutlined,
  SafetyCertificateOutlined,
  GlobalOutlined,
  CheckCircleFilled,
  ExclamationCircleFilled,
  ToolOutlined,
  ProjectOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  ClockCircleOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import './ToolResultCard.css'

// 工具图标映射
const TOOL_ICONS = {
  // 扫描工具
  scan_ports: <MonitorOutlined />,
  masscan_scan: <MonitorOutlined />,
  scan_ssl: <SafetyCertificateOutlined />,
  scan_vulnerabilities: <CloseCircleFilled />,
  scan_weak_passwords: <KeyOutlined />,
  full_compliance_scan: <CheckCircleFilled />,
  nikto_scan: <GlobalOutlined />,
  sqlmap_scan: <GlobalOutlined />,
  gobuster_scan: <GlobalOutlined />,
  ffuf_scan: <GlobalOutlined />,
  web_discovery_scan: <GlobalOutlined />,
  baseline_check: <ToolOutlined />,
  linux_baseline: <ToolOutlined />,
  database_security_scan: <DatabaseOutlined />,
  redis_check: <DatabaseOutlined />,
  oracle_check: <DatabaseOutlined />,
  mongodb_check: <DatabaseOutlined />,
  memcached_check: <DatabaseOutlined />,
  mysql_check: <DatabaseOutlined />,
  fping_scan: <MonitorOutlined />,
  snmp_walk: <ToolOutlined />,
  snmp_bruteforce: <ToolOutlined />,
  snmp_get: <ToolOutlined />,
  network_device_scan: <ToolOutlined />,
  enum4linux_scan: <MonitorOutlined />,
  crackmapexec_scan: <MonitorOutlined />,
  smb_enum: <MonitorOutlined />,
  windows_security_scan: <MonitorOutlined />,
  ping_host: <MonitorOutlined />,
  
  // 查询工具
  view_open_ports: <MonitorOutlined />,
  view_vulnerabilities: <CloseCircleFilled />,
  view_findings: <FileTextOutlined />,
  view_compliance_score: <CheckCircleFilled />,
  view_scan_history: <ClockCircleOutlined />,
  
  // 项目管理
  create_project: <ProjectOutlined />,
  list_projects: <ProjectOutlined />,
  update_project: <ProjectOutlined />,
  delete_project: <ProjectOutlined />,
  add_asset: <DatabaseOutlined />,
  list_assets: <DatabaseOutlined />,
  verify_asset: <DatabaseOutlined />,
  
  // 问题整改与复测
  
  // 报告生成
  generate_html_report: <FileTextOutlined />,
  generate_json_report: <FileTextOutlined />,
  
  // 定时扫描
  create_scheduled_scan: <ClockCircleOutlined />,
  list_scheduled_scans: <ClockCircleOutlined />,
  trigger_scheduled_scan: <ClockCircleOutlined />,
  
  // 其他
  help: <RobotOutlined />,
  chat: <RobotOutlined />,
}

// 工具名称映射
const TOOL_NAMES = {
  scan_ports: '端口扫描',
  masscan_scan: '高速扫描',
  scan_ssl: 'SSL/TLS 检测',
  scan_vulnerabilities: '漏洞扫描',
  scan_weak_passwords: '弱口令检测',
  full_compliance_scan: '全量合规扫描',
  nikto_scan: 'Web 漏洞扫描',
  sqlmap_scan: 'SQL 注入检测',
  gobuster_scan: '目录爆破',
  ffuf_scan: 'Web 模糊测试',
  web_discovery_scan: 'Web 目录发现',
  baseline_check: '安全基线核查',
  linux_baseline: '安全基线核查',
  database_security_scan: '数据库安全检测',
  redis_check: 'Redis 检测',
  oracle_check: 'Oracle 检测',
  mongodb_check: 'MongoDB 检测',
  memcached_check: 'Memcached 检测',
  mysql_check: 'MySQL 检测',
  fping_scan: '批量存活检测',
  snmp_walk: 'SNMP Walk',
  snmp_bruteforce: 'SNMP 团体字检测',
  snmp_get: 'SNMP OID 检测',
  network_device_scan: '网络设备检测',
  enum4linux_scan: 'Windows 用户/组枚举',
  crackmapexec_scan: 'Windows SID 枚举',
  smb_enum: 'SMB 共享枚举',
  windows_security_scan: 'Windows/AD/SMB 检测',
  ping_host: 'Ping 检测',
  view_open_ports: '查看开放端口',
  view_vulnerabilities: '查看漏洞',
  view_findings: '查看合规发现',
  view_compliance_score: '查看合规评分',
  view_scan_history: '查看扫描历史',
  create_project: '创建项目',
  list_projects: '列出项目',
  update_project: '更新项目',
  delete_project: '删除项目',
  add_asset: '添加资产',
  list_assets: '列出资产',
  verify_asset: '验证资产',
  generate_html_report: '生成 HTML 报告',
  generate_json_report: '生成 JSON 报告',
  create_scheduled_scan: '创建定时扫描',
  list_scheduled_scans: '列出定时扫描',
  trigger_scheduled_scan: '触发定时扫描',
  help: '显示帮助',
  chat: '对话',
}

const formatCopyPart = (value) => {
  if (value === null || value === undefined || value === false) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(formatCopyPart).filter(Boolean).join('\n')
  if (React.isValidElement(value)) return formatCopyPart(value.props?.children)
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return ''
    }
  }
  return ''
}

const ToolResultCard = ({ tool, status, summary, details, copyText, defaultExpanded = false, children }) => {
  const [expanded, setExpanded] = useState(defaultExpanded)

  const toolIcon = TOOL_ICONS[tool] || <ToolOutlined />
  const toolName = TOOL_NAMES[tool] || tool

  // 状态配置
  const statusConfig = {
    success: { color: 'success', text: '成功', icon: <CheckCircleFilled /> },
    warning: { color: 'warning', text: '无法判定', icon: <ExclamationCircleFilled /> },
    failed: { color: 'error', text: '失败', icon: <CloseCircleFilled /> },
    skipped: { color: 'default', text: '已跳过', icon: <ExclamationCircleFilled /> },
  }

  const currentStatus = statusConfig[status] || statusConfig.success

  // 复制到剪贴板
  const handleCopy = () => {
    const body = copyText || [formatCopyPart(summary), formatCopyPart(details)].filter(Boolean).join('\n\n')
    const textToCopy = `${toolName} - ${currentStatus.text}${body ? `\n\n${body}` : ''}`
    navigator.clipboard.writeText(textToCopy).then(() => {
      message.success('已复制到剪贴板')
    }).catch(() => {
      message.error('复制失败')
    })
  }

  return (
    <div className="tool-result-card">
      {/* 卡片头部 */}
      <div
        className={`tool-card-header ${details ? 'expandable' : ''}`}
        role={details ? 'button' : undefined}
        tabIndex={details ? 0 : undefined}
        aria-expanded={details ? expanded : undefined}
        onClick={details ? () => setExpanded(value => !value) : undefined}
        onKeyDown={details ? (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            setExpanded(value => !value)
          }
        } : undefined}
      >
        <div className="tool-info">
          <span className="tool-icon">{toolIcon}</span>
          <span className="tool-name">{toolName}</span>
          <Tag color={currentStatus.color} icon={currentStatus.icon}>
            {currentStatus.text}
          </Tag>
        </div>
        <div className="tool-actions">
          <Button
            type="text"
            size="small"
            icon={<CopyOutlined />}
            onClick={(event) => {
              event.stopPropagation()
              handleCopy()
            }}
          >
            复制
          </Button>
          {details && (
            <Button
              type="text"
              size="small"
              icon={expanded ? <UpOutlined /> : <DownOutlined />}
              onClick={(event) => {
                event.stopPropagation()
                setExpanded(!expanded)
              }}
            >
              {expanded ? '收起' : '展开'}
            </Button>
          )}
        </div>
      </div>

      {/* 摘要统计 */}
      {summary && (
        <div className="tool-summary">
          {summary}
        </div>
      )}

      {/* 详情区域 */}
      {expanded && details && (
        <div className="tool-details">
          {details}
        </div>
      )}

      {/* 自定义内容 */}
      {children}
    </div>
  )
}

export default ToolResultCard
