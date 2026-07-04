import { useEffect, useMemo, useState } from 'react'
import { Button, Tag } from 'antd'
import {
  ApiOutlined,
  BugOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  DatabaseOutlined,
  ExclamationCircleFilled,
  FileProtectOutlined,
  FileSearchOutlined,
  GlobalOutlined,
  KeyOutlined,
  LockOutlined,
  RadarChartOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import ChatWorkspace from './ChatWorkspace'
import './ProjectCommandCenter.css'

const TOOL_GROUPS = [
  { key: 'scan_ports', label: '端口', icon: <RadarChartOutlined /> },
  { key: 'scan_ssl', label: 'SSL', icon: <LockOutlined /> },
  { key: 'scan_vulnerabilities', label: '漏洞', icon: <BugOutlined /> },
  { key: 'scan_weak_passwords', label: '弱口令', icon: <KeyOutlined /> },
  { key: 'database_security_scan', label: '数据库', icon: <DatabaseOutlined /> },
  { key: 'web_discovery_scan', label: 'Web', icon: <GlobalOutlined /> },
]

const statusCopy = {
  success: '通过',
  warning: '待判定',
  failed: '风险',
  skipped: '跳过',
}

const normalizeCapability = (capability = '') => {
  if (['ping_asset', 'ping_host'].includes(capability)) return 'ping_host'
  if (['testssl_scan'].includes(capability)) return 'scan_ssl'
  if (['nuclei_scan'].includes(capability)) return 'scan_vulnerabilities'
  if (['hydra_bruteforce'].includes(capability)) return 'scan_weak_passwords'
  if (['gobuster_scan', 'ffuf_scan', 'nikto_scan', 'sqlmap_scan'].includes(capability)) return 'web_discovery_scan'
  if (['redis_check', 'mysql_check', 'mongodb_check', 'memcached_check', 'oracle_check'].includes(capability)) return 'database_security_scan'
  return capability
}

const getAssetValue = (asset) => asset?.value || asset?.target || asset?.name || '-'

const deriveFindingStats = (scanResults) => {
  const assetResults = scanResults?.asset_results || {}
  const assetEntries = Object.entries(assetResults)
  const warnings = assetEntries.filter(([, item]) => item.display_status === 'warning').length
  const failures = assetEntries.filter(([, item]) => item.display_status === 'failed' || item.status === 'failed').length
  const successes = assetEntries.filter(([, item]) => (item.display_status || item.status) === 'success').length

  return {
    assetResults,
    successes,
    warnings,
    failures,
    openPorts: scanResults?.open_ports?.length || 0,
    vulnerabilities: (scanResults?.vulnerabilities?.length || 0) + (scanResults?.web_vulnerabilities?.length || 0),
    weakPasswords: scanResults?.weak_passwords?.length || 0,
    databaseIssues: scanResults?.database_issues?.length || 0,
    sslIssues: scanResults?.ssl_issues?.length || 0,
  }
}

const extractHistorySignals = (history) => {
  const resultMessages = history
    .filter(item => item.context_snapshot?.scan_results)
    .slice(-8)
    .reverse()

  const latestResults = resultMessages[0]?.context_snapshot?.scan_results || {}
  const latestStats = deriveFindingStats(latestResults)

  const riskStream = []
  const evidenceQueue = []

  resultMessages.forEach((item) => {
    const scanResults = item.context_snapshot.scan_results || {}
    const stats = deriveFindingStats(scanResults)
    const createdAt = item.created_at ? new Date(item.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '历史'

    Object.entries(stats.assetResults).forEach(([target, assetData]) => {
      const capability = normalizeCapability(assetData.capability)
      const status = assetData.display_status || (assetData.status === 'success' ? 'success' : 'failed')
      const result = assetData.result || {}
      const reason = assetData.error || result.tool_error || result.error || item.content

      if (status !== 'success' || result.scan_completed === false || result.reachable === false) {
        riskStream.push({
          target,
          capability,
          status: result.scan_completed === false || status === 'warning' ? 'warning' : 'failed',
          reason,
          time: createdAt,
        })
      }

      evidenceQueue.push({
        target,
        capability,
        status,
        time: createdAt,
      })
    })
  })

  return {
    latestStats,
    riskStream: riskStream.slice(0, 6),
    evidenceQueue: evidenceQueue.slice(0, 8),
    resultCount: resultMessages.length,
  }
}

function ProjectCommandCenter({ project, assets, modelId, onOpenResults }) {
  const [history, setHistory] = useState([])
  const [assessment, setAssessment] = useState(null)

  useEffect(() => {
    document.body.classList.add('command-center-active')
    return () => document.body.classList.remove('command-center-active')
  }, [])

  useEffect(() => {
    let mounted = true

    const fetchWorkspaceData = async () => {
      if (!project?.id) {
        setHistory([])
        setAssessment(null)
        return
      }

      try {
        const historyResponse = await api.get('/chat/history', { params: { project_id: project.id, limit: 80 } })
        if (mounted) setHistory(historyResponse.data || [])
      } catch {
        if (mounted) setHistory([])
      }

      try {
        const assessmentResponse = await api.get(`/assessments/projects/${project.id}`)
        const latestAssessment = Array.isArray(assessmentResponse.data)
          ? assessmentResponse.data[0]
          : assessmentResponse.data
        if (!latestAssessment) {
          if (mounted) setAssessment(null)
          return
        }

        if (mounted) setAssessment(latestAssessment)
      } catch {
        if (mounted) setAssessment(null)
      }
    }

    fetchWorkspaceData()
    const timer = window.setInterval(fetchWorkspaceData, 30000)
    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [project?.id])

  const workspace = useMemo(() => extractHistorySignals(history), [history])
  const assessmentProgress = Math.round(assessment?.progress || project?.compliance_score || 0)
  const riskTotal = workspace.latestStats.failures + workspace.latestStats.vulnerabilities + workspace.latestStats.weakPasswords + workspace.latestStats.databaseIssues
  const unknownTotal = workspace.latestStats.warnings
  const hasSignals = workspace.resultCount > 0

  const toolStatus = (toolKey) => {
    const assetResults = workspace.latestStats.assetResults || {}
    const matched = Object.values(assetResults).filter(item => normalizeCapability(item.capability) === toolKey)
    if (matched.length === 0) return 'idle'
    if (matched.some(item => item.display_status === 'failed' || item.status === 'failed')) return 'failed'
    if (matched.some(item => item.display_status === 'warning' || item.result?.scan_completed === false)) return 'warning'
    return 'success'
  }

  return (
    <div className="command-center-shell">
      <div className="command-center-topbar">
        <div className="project-identity">
          <span className="identity-kicker">CertiProof Intelligence Workspace</span>
          <h1>{project?.name || '未选择项目'}</h1>
          <div className="identity-meta">
            <Tag color="cyan">{project?.compliance_level || '等保未配置'}</Tag>
            <Tag color={assessment?.status === 'completed' ? 'green' : assessment?.status === 'in_progress' ? 'blue' : 'default'}>
              {assessment?.status === 'completed' ? '测评完成' : assessment?.status === 'in_progress' ? '测评中' : assessment ? '待推进' : '未创建测评'}
            </Tag>
            <span>{assets.length} 个资产</span>
          </div>
        </div>

        <div className="posture-strip">
          <div className="posture-tile primary">
            <span>测评进度</span>
            <strong>{assessmentProgress}%</strong>
          </div>
          <div className="posture-tile danger">
            <span>风险项</span>
            <strong>{riskTotal}</strong>
          </div>
          <div className="posture-tile warning">
            <span>无法判定</span>
            <strong>{unknownTotal}</strong>
          </div>
          <div className="posture-tile">
            <span>证据记录</span>
            <strong>{workspace.evidenceQueue.length}</strong>
          </div>
        </div>
      </div>

      <div className="command-center-grid">
        <main className="ai-command-core">
          <div className="core-header">
            <div>
              <span className="identity-kicker">AI Command Console</span>
              <h2>对话式安全检测指挥台</h2>
            </div>
            <div className="core-status">
              <Tag color="cyan" icon={<ApiOutlined />}>快捷命令</Tag>
              <Tag color="blue" icon={<ThunderboltOutlined />}>多资产执行</Tag>
            </div>
          </div>
          <div className="chat-glass-frame">
            <ChatWorkspace
              key={project?.id || 'default'}
              projectId={project?.id}
              projectName={project?.name}
              modelId={modelId}
            />
          </div>
        </main>

        <aside className="intel-rail right">
          <section className="intel-panel tool-panel">
            <div className="panel-heading">
              <span><ThunderboltOutlined /> 工具遥测</span>
              <small>{hasSignals ? '最近结果' : '等待检测'}</small>
            </div>
            <div className="tool-grid">
              {TOOL_GROUPS.map(tool => {
                const status = toolStatus(tool.key)
                return (
                  <div key={tool.key} className={`tool-cell ${status}`}>
                    <span>{tool.icon}</span>
                    <strong>{tool.label}</strong>
                    <i>{status === 'idle' ? '待执行' : statusCopy[status]}</i>
                  </div>
                )
              })}
            </div>
          </section>

          <section className="intel-panel risk-panel">
            <div className="panel-heading">
              <span><ExclamationCircleFilled /> 风险情报流</span>
              <small>{workspace.riskStream.length}</small>
            </div>
            <div className="risk-stream">
              {workspace.riskStream.length ? workspace.riskStream.map((risk, index) => (
                <div key={`${risk.target}-${risk.capability}-${index}`} className={`risk-item ${risk.status}`}>
                  <div className="risk-time">{risk.time}</div>
                  <div>
                    <strong>{risk.target}</strong>
                    <span>{risk.reason || '工具返回无法判定状态'}</span>
                  </div>
                </div>
              )) : (
                <div className="empty-intel">暂无风险流。执行扫描后，这里会按资产沉淀风险和无法判定项。</div>
              )}
            </div>
          </section>

          <section className="intel-panel evidence-panel">
            <div className="panel-heading">
              <span><FileSearchOutlined /> 证据与整改</span>
              <Button size="small" type="text" onClick={onOpenResults}>结果库</Button>
            </div>
            <div className="evidence-list">
              {workspace.evidenceQueue.length ? workspace.evidenceQueue.slice(0, 5).map((item, index) => (
                <div key={`${item.target}-${item.capability}-${index}`} className="evidence-row">
                  <span className={`evidence-status ${item.status}`}>
                    {item.status === 'success' ? <CheckCircleFilled /> : item.status === 'warning' ? <ClockCircleOutlined /> : <ExclamationCircleFilled />}
                  </span>
                  <div>
                    <strong>{item.target}</strong>
                    <span>{TOOL_GROUPS.find(tool => tool.key === normalizeCapability(item.capability))?.label || item.capability} · {item.time}</span>
                  </div>
                </div>
              )) : (
                <div className="remediation-empty">
                  <FileProtectOutlined />
                  <strong>整改队列待生成</strong>
                  <span>风险发现、无法判定项和复测建议会进入这里。</span>
                </div>
              )}
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}

export default ProjectCommandCenter
