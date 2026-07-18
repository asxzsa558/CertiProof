export const TOOL_CATALOG = [
  { command: '/scan', capability: 'scan_ports', name: '端口扫描', description: '高危/定制端口扫描', usage: '/scan [目标] [端口范围]', iconKey: 'thunderbolt', color: '#10b981', primary: true, requiresTarget: true },
  { command: '/scan-full', capability: 'scan_ports', name: '全端口扫描', description: '全端口扫描', usage: '/scan-full [目标]', iconKey: 'thunderbolt', color: '#dc2626', more: true, requiresTarget: true, parameters: { port_range: '1-65535' } },
  { command: '/masscan', capability: 'masscan_scan', name: '高速端口扫描', description: '高速端口扫描', usage: '/masscan [目标]', iconKey: 'cloud-server', color: '#059669', more: true, requiresTarget: true },
  { command: '/fping', capability: 'fping_scan', name: '批量存活检测', description: '批量存活检测', usage: '/fping [网段]', iconKey: 'wifi', color: '#14b8a6', more: true, requiresTarget: true },
  { command: '/ssl', capability: 'scan_ssl', name: 'SSL/TLS 检测', description: 'SSL/TLS 检测', usage: '/ssl [目标]', iconKey: 'lock', color: '#0ea5e9', more: true, requiresTarget: true },
  { command: '/vuln', capability: 'scan_vulnerabilities', name: '漏洞扫描', description: '漏洞扫描', usage: '/vuln [目标]', iconKey: 'bug', color: '#ef4444', primary: true, requiresTarget: true },
  { command: '/baseline', capability: 'baseline_check', name: '安全基线核查', description: '安全基线核查（自动识别操作系统）', usage: '/baseline [目标]', iconKey: 'safety-certificate', color: '#3b82f6', primary: true, requiresTarget: true, requiresSsh: true },
  { command: '/web', capability: 'nikto_scan', name: 'Web 安全扫描', description: 'Nikto Web 安全扫描', usage: '/web [URL]', iconKey: 'monitor', color: '#8b5cf6', primary: true, requiresTarget: true },
  { command: '/nikto', capability: 'nikto_scan', name: 'Nikto Web 扫描', description: 'Nikto Web 扫描', usage: '/nikto [URL]', iconKey: 'monitor', color: '#8b5cf6', requiresTarget: true },
  { command: '/sqlmap', capability: 'sqlmap_scan', name: 'SQL 注入检测', description: 'SQL 注入检测', usage: '/sqlmap [URL]', iconKey: 'search', color: '#8b5cf6', requiresTarget: true },
  { command: '/dirbust', capability: 'web_discovery_scan', name: 'Web 目录发现', description: '组合：Gobuster + FFUF', usage: '/dirbust [URL]', iconKey: 'folder-open', color: '#f59e0b', more: true, requiresTarget: true },
  { command: '/gobuster', capability: 'gobuster_scan', name: 'Gobuster 目录扫描', description: 'Gobuster 目录扫描', usage: '/gobuster [URL]', iconKey: 'folder-open', color: '#f59e0b', requiresTarget: true },
  { command: '/ffuf', capability: 'ffuf_scan', name: 'FFUF 模糊测试', description: 'FFUF Web 模糊测试', usage: '/ffuf [URL]', iconKey: 'folder-open', color: '#f59e0b', requiresTarget: true },
  { command: '/db', capability: 'database_security_scan', name: '数据库安全检测', description: '组合：Redis/MySQL/MongoDB/Memcached/Oracle', usage: '/db [目标]', iconKey: 'database', color: '#06b6d4', primary: true, requiresTarget: true },
  { command: '/redis', capability: 'redis_check', name: 'Redis 检测', description: 'Redis 未授权检测', usage: '/redis [目标]', iconKey: 'database', color: '#06b6d4', requiresTarget: true },
  { command: '/mysql', capability: 'mysql_check', name: 'MySQL 检测', description: 'MySQL 空口令检测', usage: '/mysql [目标]', iconKey: 'database', color: '#06b6d4', requiresTarget: true },
  { command: '/mongodb', capability: 'mongodb_check', name: 'MongoDB 检测', description: 'MongoDB 未授权检测', usage: '/mongodb [目标]', iconKey: 'database', color: '#06b6d4', requiresTarget: true },
  { command: '/memcached', capability: 'memcached_check', name: 'Memcached 检测', description: 'Memcached 未授权检测', usage: '/memcached [目标]', iconKey: 'database', color: '#06b6d4', requiresTarget: true },
  { command: '/oracle', capability: 'oracle_check', name: 'Oracle 检测', description: 'Oracle TNS 检测', usage: '/oracle [目标]', iconKey: 'database', color: '#06b6d4', requiresTarget: true },
  { command: '/snmp', capability: 'network_device_scan', name: '网络设备检测', description: '组合：SNMP 信息 + 团体字检测', usage: '/snmp [目标]', iconKey: 'cluster', color: '#d946ef', more: true, requiresTarget: true },
  { command: '/snmpwalk', capability: 'snmp_walk', name: 'SNMP Walk', description: 'SNMP 信息读取', usage: '/snmpwalk [目标]', iconKey: 'cluster', color: '#d946ef', requiresTarget: true },
  { command: '/snmpget', capability: 'snmp_get', name: 'SNMP OID 检测', description: 'SNMP OID 读取', usage: '/snmpget [目标]', iconKey: 'cluster', color: '#d946ef', requiresTarget: true },
  { command: '/snmp-brute', capability: 'snmp_bruteforce', name: 'SNMP 团体字检测', description: 'SNMP 团体字检测', usage: '/snmp-brute [目标]', iconKey: 'cluster', color: '#d946ef', requiresTarget: true },
  { command: '/password', capability: 'scan_weak_passwords', name: '弱口令检测', description: '弱口令检测', usage: '/password [目标]', iconKey: 'key', color: '#f97316', primary: true, requiresTarget: true },
  { command: '/windows', capability: 'windows_security_scan', name: 'Windows/AD/SMB 检测', description: '组合：用户/SID/SMB 共享枚举', usage: '/windows [目标]', iconKey: 'windows', color: '#0f766e', more: true, requiresTarget: true },
  { command: '/enum4linux', capability: 'enum4linux_scan', name: 'Windows 用户/组枚举', description: 'enum4linux 用户/组枚举', usage: '/enum4linux [目标]', iconKey: 'windows', color: '#0f766e', requiresTarget: true },
  { command: '/smb', capability: 'smb_enum', name: 'SMB 共享枚举', description: 'SMB 共享枚举', usage: '/smb [目标]', iconKey: 'windows', color: '#0f766e', requiresTarget: true },
  { command: '/cme', capability: 'crackmapexec_scan', name: 'Windows SID 枚举', description: 'Windows SID/SMB 枚举', usage: '/cme [目标]', iconKey: 'windows', color: '#0f766e', requiresTarget: true },
  { command: '/ping', capability: 'ping_host', name: 'Ping 检测', description: 'Ping 检测', usage: '/ping [目标]', iconKey: 'api', color: '#64748b', more: true, requiresTarget: true },
  { command: '/all', capability: 'full_compliance_scan', name: '全量合规扫描', description: '组合：端口+SSL+漏洞+弱口令', usage: '/all [目标]', iconKey: 'safety-certificate', color: '#6366f1', more: true, requiresTarget: true },
  { command: '/tech', capability: 'tech_assessment', name: '等保技术测评', description: '组合：等保技术检查', usage: '/tech [目标]', iconKey: 'thunderbolt', color: '#ef4444', more: true, requiresTarget: true, requiresSsh: true },
  { command: '/ssh', capability: 'ssh_config_check', name: 'SSH 配置检查', description: 'SSH 配置检查', usage: '/ssh [目标]', iconKey: 'safety-certificate', color: '#3b82f6', requiresTarget: true, requiresSsh: true },
]

export const CAPABILITY_NAMES = TOOL_CATALOG.reduce((acc, tool) => {
  acc[tool.capability] = tool.name
  return acc
}, {
  linux_baseline: '安全基线核查',
  ping_asset: 'Ping 检测',
  testssl_scan: 'SSL/TLS 检测',
  nuclei_scan: '漏洞扫描',
  hydra_bruteforce: '弱口令检测',
})

const ASSESSMENT_TASK_NAMES = {
  asset_discovery: '资产发现',
  high_risk_port_scan: '高危端口扫描',
  basic_vulnerability_scan: '基础漏洞扫描',
  basic_baseline_check: '安全基线核查',
  basic_weak_password_scan: '弱口令检测',
  basic_ssl_tls_scan: 'SSL/TLS 检测',
  config_check: '安全基线核查',
  vuln_scan: '漏洞扫描',
  web_scan: 'Web 安全检测',
  ssl_check: 'SSL/TLS 检测',
  password_scan: '弱口令检测',
  db_check: '数据库安全检测',
  network_check: '网络设备检测',
  windows_check: 'Windows/AD/SMB 检测',
  full_compliance_scan: '全量合规扫描',
  full_asset_assessment: '全资产组合扫描',
}

export function scanTaskCapabilities(task = {}) {
  const parameters = task.parameters || {}
  const summary = task.result_summary || {}
  const values = [parameters.capability, parameters.tool_name, ...(parameters.capabilities || [])]
  for (const step of parameters.plan || []) values.push(step?.capability)
  for (const item of [...(summary.results || []), ...(summary.failed || []), ...(summary.warnings || [])]) values.push(item?.capability)
  return [...new Set(values.filter(Boolean))]
}

export function scanTaskName(task = {}) {
  const parameters = task.parameters || {}
  const capabilities = scanTaskCapabilities(task)
  return parameters.report_name
    || ASSESSMENT_TASK_NAMES[parameters.task_type]
    || capabilities.map((capability) => CAPABILITY_NAMES[capability] || capability).join(' + ')
    || ({ full: '全量检测', incremental: '增量检测', targeted: '定向检测', scheduled: '定时检测' })[task.task_type]
    || '安全检测'
}

export function scanTaskTarget(task = {}) {
  const parameters = task.parameters || {}
  const summary = task.result_summary || {}
  const value = parameters.target || parameters.targets || summary.target
  return Array.isArray(value) ? value.join(', ') : value || '未记录目标'
}

export function scanTaskSource(task = {}) {
  if (task.parameters?.source === 'assessment_task') return '等保测评'
  if (task.triggered_by === 'scheduled') return '定时任务'
  if (task.triggered_by === 'event') return '系统触发'
  return '手动 / AI'
}

export function scanTaskConclusion(task = {}) {
  const summary = task.result_summary || {}
  const executions = summary.results || []
  const scanAssets = Object.values(summary.scan_results?.asset_results || {})
  const hasUnverifiedVulnerabilityScan = scanAssets.some(item => {
    const result = item?.result || {}
    return item?.capability === 'scan_vulnerabilities'
      && result.reachable !== true
      && !(result.findings || []).length
  })
  const allSkipped = executions.length > 0 && executions.every(item => {
    const result = item?.result || {}
    const totals = result.summary || {}
    return result.skipped === true || (totals.total > 0 && totals.skipped === totals.total)
  })
  if (task.status === 'failed' || task.status === 'cancelled' || task.error_message) return { key: 'failed', label: '无法完成' }
  if (task.status === 'running' || task.status === 'pending') return { key: 'running', label: '执行中' }
  if (summary.outcome === 'not_applicable' || allSkipped) return { key: 'skipped', label: '不适用' }
  if (
    (summary.failed || []).length ||
    (summary.warnings || []).length ||
    summary.status === 'partial' ||
    hasUnverifiedVulnerabilityScan
  ) return { key: 'warning', label: '部分未完成' }
  if (task.findings_count > 0) return { key: 'risk', label: `发现 ${task.findings_count} 项问题` }
  return { key: 'clean', label: '未发现问题' }
}
