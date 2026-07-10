import { useEffect, useMemo, useState } from 'react'
import { Button, Tag, Upload, message } from 'antd'
import {
  BugOutlined,
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

const REMEDIATION_STATUS = [
  { key: 'open', label: '待整改' },
  { key: 'in_progress', label: '整改中' },
  { key: 'resolved', label: '待复测' },
  { key: 'verified', label: '已验证' },
  { key: 'closed', label: '已关闭' },
  { key: 'skipped', label: '已跳过' },
]

const sourceCopy = {
  all: '全部',
  document: '文档',
  technical: '技术',
  manual: '人工',
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
    riskStream,
    evidenceQueue,
    resultCount: resultMessages.length,
  }
}

function ProjectCommandCenter({ project, assets, modelId, onOpenResults }) {
  const [history, setHistory] = useState([])
  const [assessment, setAssessment] = useState(null)
  const [remediationTickets, setRemediationTickets] = useState([])
  const [remediationSummary, setRemediationSummary] = useState(null)
  const [remediationSource, setRemediationSource] = useState('all')
  const [expandedRemediationGroups, setExpandedRemediationGroups] = useState({})
  const [updatingTicket, setUpdatingTicket] = useState(null)
  const [detectedChanges, setDetectedChanges] = useState([])

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
        setRemediationTickets([])
        setRemediationSummary(null)
        setDetectedChanges([])
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

      try {
        const [ticketsResponse, summaryResponse, changesResponse] = await Promise.all([
          api.get(`/projects/${project.id}/remediation/`),
          api.get(`/projects/${project.id}/remediation/summary`),
          api.get(`/projects/${project.id}/monitoring/changes`, { params: { reassessment_only: true } }),
        ])
        if (mounted) {
          setRemediationTickets(ticketsResponse.data || [])
          setRemediationSummary(summaryResponse.data || null)
          setDetectedChanges(changesResponse.data || [])
        }
      } catch {
        if (mounted) {
          setRemediationTickets([])
          setRemediationSummary(null)
          setDetectedChanges([])
        }
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
  const filteredTickets = remediationSource === 'all'
    ? remediationTickets
    : remediationTickets.filter(ticket => ticket.source === remediationSource)
  const sourceCounts = remediationTickets.reduce((acc, ticket) => {
    acc[ticket.source || 'manual'] = (acc[ticket.source || 'manual'] || 0) + 1
    return acc
  }, {})
  const retestCounts = remediationSummary?.counts || {}

  const documentGroupKey = (ticket) => {
    if (ticket.source !== 'document') return `ticket-${ticket.id}`
    const text = ticket.title || ticket.finding_description || ticket.description || '文档问题'
    const documentName = text.split(/[：:]/)[0]?.trim()
    return `doc-${ticket.status}-${documentName || 'unknown'}`
  }

  const makeRemediationItems = (tickets) => {
    const groups = new Map()
    const items = []
    tickets.forEach(ticket => {
      if (ticket.source !== 'document') {
        items.push({ type: 'ticket', id: `ticket-${ticket.id}`, ticket })
        return
      }
      const key = documentGroupKey(ticket)
      if (!groups.has(key)) {
        groups.set(key, {
          type: 'document-group',
          id: key,
          title: (ticket.title || ticket.finding_description || '文档问题').split(/[：:]/)[0],
          tickets: [],
        })
      }
      groups.get(key).tickets.push(ticket)
    })
    return [...items, ...groups.values()]
  }

  const refreshRemediation = async () => {
    if (!project?.id) return
    const [ticketsResponse, summaryResponse] = await Promise.all([
      api.get(`/projects/${project.id}/remediation/`),
      api.get(`/projects/${project.id}/remediation/summary`),
    ])
    setRemediationTickets(ticketsResponse.data || [])
    setRemediationSummary(summaryResponse.data || null)
  }

  useEffect(() => {
    const handleAssessmentReset = (event) => {
      const detail = event.detail || {}
      if (detail.projectId !== project?.id) return
      if (detail.mode === 'reset') {
        setHistory([])
        setRemediationTickets([])
        setRemediationSummary(null)
        setDetectedChanges([])
      }
      refreshRemediation().catch(() => {})
    }

    window.addEventListener('certiproof:assessment-reset', handleAssessmentReset)
    return () => window.removeEventListener('certiproof:assessment-reset', handleAssessmentReset)
  }, [project?.id])

  const updateTicketStatus = async (ticket, nextStatus) => {
    if (!ticket?.id || !project?.id) return
    const payload = { status: nextStatus }
    if (nextStatus === 'resolved') {
      const notes = window.prompt('请输入整改说明或处置结果', ticket.resolution_notes || '')
      if (notes === null) return
      if (!notes.trim()) {
        window.alert('提交整改前需要填写整改说明')
        return
      }
      payload.resolution_notes = notes.trim()
    }
    if (nextStatus === 'skipped') {
      const reason = window.prompt('请输入跳过原因', ticket.skip_reason || '')
      if (reason === null) return
      payload.skip_reason = reason || '已确认跳过'
    }

    setUpdatingTicket(ticket.id)
    try {
      await api.put(`/projects/${project.id}/remediation/${ticket.id}`, payload)
      await refreshRemediation()
    } finally {
      setUpdatingTicket(null)
    }
  }

  const updateTicketGroupStatus = async (tickets, nextStatus) => {
    if (!tickets?.length || !project?.id) return
    const reason = nextStatus === 'skipped'
      ? window.prompt('请输入跳过原因', tickets[0]?.skip_reason || '')
      : null
    if (nextStatus === 'skipped' && reason === null) return

    setUpdatingTicket(`group-${tickets[0].id}`)
    try {
      await Promise.all(tickets.map(ticket => api.put(`/projects/${project.id}/remediation/${ticket.id}`, {
        status: nextStatus,
        ...(nextStatus === 'skipped' ? { skip_reason: reason || '已确认跳过' } : {}),
      })))
      await refreshRemediation()
    } finally {
      setUpdatingTicket(null)
    }
  }

  const submitDocumentRetest = async (ticket, file) => {
    if (!ticket?.id || !project?.id) return false
    if (file.size > 100 * 1024 * 1024) {
      message.error('文件过大，单个文档最大支持 100MB')
      return Upload.LIST_IGNORE
    }

    const formData = new FormData()
    formData.append('file', file)

    setUpdatingTicket(ticket.id)
    try {
      const response = await api.post(`/projects/${project.id}/remediation/${ticket.id}/document-retest`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      message.success(response.data?.message || '新版文档已提交复测，后台分析完成后会自动更新整改项')
      await refreshRemediation()
    } catch (error) {
      message.error(error.response?.data?.detail || '文档复测失败')
    } finally {
      setUpdatingTicket(null)
    }
    return Upload.LIST_IGNORE
  }

  const runTechnicalRetest = async (ticket) => {
    if (!ticket?.id || !project?.id) return
    setUpdatingTicket(ticket.id)
    try {
      await api.post(`/projects/${project.id}/remediation/${ticket.id}/technical-retest`)
      message.success('技术复测已完成，整改状态已自动更新')
      await refreshRemediation()
    } catch (error) {
      message.error(error.response?.data?.detail || '技术复测失败')
    } finally {
      setUpdatingTicket(null)
    }
  }

  const runBatchTechnicalRetest = async () => {
    if (!project?.id) return
    setUpdatingTicket('batch-technical-retest')
    try {
      const response = await api.post(`/projects/${project.id}/remediation/technical-retest-all`)
      message.success(response.data?.message || '批量技术复测已完成')
      await refreshRemediation()
    } catch (error) {
      message.error(error.response?.data?.detail || '批量技术复测失败')
    } finally {
      setUpdatingTicket(null)
    }
  }

  const acknowledgeChange = async (changeId) => {
    await api.post(`/projects/${project.id}/monitoring/changes/${changeId}/acknowledge`)
    setDetectedChanges(items => items.filter(item => item.id !== changeId))
  }

  const toolStatus = (toolKey) => {
    const assetResults = workspace.latestStats.assetResults || {}
    const matched = Object.values(assetResults).filter(item => normalizeCapability(item.capability) === toolKey)
    if (matched.length === 0) return 'idle'
    if (matched.some(item => item.display_status === 'failed' || item.status === 'failed')) return 'failed'
    if (matched.some(item => item.display_status === 'warning' || item.result?.scan_completed === false)) return 'warning'
    return 'success'
  }

  const renderTicketCard = (ticket, compact = false) => (
    <article className={`remediation-card ${ticket.priority || 'medium'} ${compact ? 'compact' : ''}`} key={ticket.id}>
      <div className="remediation-card-top">
        <Tag color={ticket.source === 'document' ? 'cyan' : ticket.source === 'technical' ? 'orange' : 'default'}>
          {ticket.source_label || sourceCopy[ticket.source] || '问题'}
        </Tag>
        <Tag color={ticket.finding_severity === 'high' || ticket.finding_severity === 'critical' ? 'red' : 'gold'}>
          {ticket.finding_severity || ticket.priority}
        </Tag>
      </div>
      <strong>{ticket.title}</strong>
      <p>{ticket.finding_description || ticket.description || ticket.remediation_plan || '等待补充整改说明'}</p>
      {!compact && ticket.remediation_plan && (
        <div className="remediation-note">
          <span>整改建议</span>
          <em>{ticket.remediation_plan}</em>
        </div>
      )}
      {!compact && ticket.resolution_notes && (
        <div className="remediation-note done">
          <span>整改说明</span>
          <em>{ticket.resolution_notes}</em>
        </div>
      )}
      {!compact && (
        <div className="remediation-actions">
          {ticket.status === 'open' && (
            <Button size="small" loading={updatingTicket === ticket.id} onClick={() => updateTicketStatus(ticket, 'in_progress')}>开始整改</Button>
          )}
          {ticket.status === 'in_progress' && (
            ticket.source === 'document' ? (
              <Upload
                showUploadList={false}
                accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff"
                beforeUpload={(file) => submitDocumentRetest(ticket, file)}
                disabled={updatingTicket === ticket.id}
              >
                <Button size="small" loading={updatingTicket === ticket.id}>上传新版文档复测</Button>
              </Upload>
            ) : ticket.source === 'technical' ? (
              <Button size="small" loading={updatingTicket === ticket.id} onClick={() => runTechnicalRetest(ticket)}>重新检测</Button>
            ) : (
              <Button size="small" loading={updatingTicket === ticket.id} onClick={() => updateTicketStatus(ticket, 'resolved')}>提交说明</Button>
            )
          )}
          {ticket.status === 'resolved' && (
            <Button size="small" loading={updatingTicket === ticket.id} onClick={() => updateTicketStatus(ticket, 'verified')}>复测通过</Button>
          )}
          {ticket.status === 'verified' && (
            <Button size="small" loading={updatingTicket === ticket.id} onClick={() => updateTicketStatus(ticket, 'closed')}>关闭工单</Button>
          )}
          {['open', 'in_progress', 'resolved'].includes(ticket.status) && (
            <Button size="small" type="text" loading={updatingTicket === ticket.id} onClick={() => updateTicketStatus(ticket, 'skipped')}>跳过项</Button>
          )}
        </div>
      )}
    </article>
  )

  const renderDocumentGroup = (group) => {
    const firstTicket = group.tickets[0]
    const expanded = expandedRemediationGroups[group.id]
    const loadingKey = `group-${firstTicket.id}`
    return (
      <article className={`remediation-card document-group ${firstTicket.priority || 'medium'}`} key={group.id}>
        <div className="remediation-card-top">
          <Tag color="cyan">文档问题</Tag>
          <Tag color="gold">{group.tickets.length} 项</Tag>
        </div>
        <button
          className="remediation-group-title"
          type="button"
          onClick={() => setExpandedRemediationGroups(prev => ({ ...prev, [group.id]: !prev[group.id] }))}
        >
          <strong>{group.title}</strong>
          <span>{expanded ? '收起' : '展开'}</span>
        </button>
        <p>该文档存在 {group.tickets.length} 个待处理问题，上传新版文档会自动复测并同步本组问题。</p>
        <div className="remediation-actions">
          {firstTicket.status === 'open' && (
            <Button size="small" loading={updatingTicket === loadingKey} onClick={() => updateTicketGroupStatus(group.tickets, 'in_progress')}>开始整改</Button>
          )}
          {firstTicket.status === 'in_progress' && (
            <Upload
              showUploadList={false}
              accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff"
              beforeUpload={(file) => submitDocumentRetest(firstTicket, file)}
              disabled={updatingTicket === firstTicket.id}
            >
              <Button size="small" loading={updatingTicket === firstTicket.id}>上传新版文档复测</Button>
            </Upload>
          )}
          {['open', 'in_progress', 'resolved'].includes(firstTicket.status) && (
            <Button size="small" type="text" loading={updatingTicket === loadingKey} onClick={() => updateTicketGroupStatus(group.tickets, 'skipped')}>整组跳过</Button>
          )}
        </div>
        {expanded && (
          <div className="remediation-group-items">
            {group.tickets.map(ticket => renderTicketCard(ticket, true))}
          </div>
        )}
      </article>
    )
  }

  return (
    <div className="command-center-shell">
      <div className="command-center-topbar">
        <div className="project-identity">
          <h1>{project?.name || '未选择项目'}</h1>
          <div className="identity-meta">
            <Tag color="cyan">{project?.compliance_level || '等保未配置'}</Tag>
            <Tag color={assessment?.status === 'completed' ? 'green' : assessment?.status === 'in_progress' ? 'blue' : 'default'}>
              {assessment?.status === 'completed' ? '测评完成' : assessment?.status === 'in_progress' ? '测评中' : assessment ? '待推进' : '未创建测评'}
            </Tag>
            <span>{assets.length} 个资产</span>
            {detectedChanges.length > 0 && (
              <span className="reassessment-alert">
                <ExclamationCircleFilled />
                {detectedChanges.length} 项变化需重新评估
                <Button size="small" type="link" onClick={() => acknowledgeChange(detectedChanges[0].id)}>知晓</Button>
              </span>
            )}
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

          <section className="intel-panel evidence-panel">
            <div className="panel-heading">
              <span><FileSearchOutlined /> 证据与整改</span>
              <div className="panel-heading-actions">
                <Button
                  size="small"
                  type="text"
                  loading={updatingTicket === 'batch-technical-retest'}
                  onClick={runBatchTechnicalRetest}
                >
                  技术复测
                </Button>
                <Button size="small" type="text" onClick={onOpenResults}>结果库</Button>
              </div>
            </div>
            <div className="risk-brief">
              <span><ExclamationCircleFilled /> 最近风险</span>
              {workspace.riskStream.length ? (
                <div className="risk-brief-list">
                  {workspace.riskStream.slice(0, 3).map((risk, index) => (
                    <b key={`${risk.target}-${risk.capability}-${index}`}>{risk.target}</b>
                  ))}
                </div>
              ) : (
                <em>暂无</em>
              )}
            </div>
            <div className="remediation-summary">
              <div><strong>{retestCounts.fixed || 0}</strong><span>已修复</span></div>
              <div><strong>{retestCounts.still_exists || 0}</strong><span>仍存在</span></div>
              <div><strong>{retestCounts.pending_verification || 0}</strong><span>待复测</span></div>
              <div><strong>{retestCounts.skipped || 0}</strong><span>已跳过</span></div>
            </div>
            <div className="source-filter">
              {Object.entries(sourceCopy).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={remediationSource === key ? 'active' : ''}
                  onClick={() => setRemediationSource(key)}
                >
                  {label}<b>{key === 'all' ? remediationTickets.length : sourceCounts[key] || 0}</b>
                </button>
              ))}
            </div>
            <div className="remediation-board">
              {filteredTickets.length ? REMEDIATION_STATUS.map(column => {
                const columnTickets = filteredTickets.filter(ticket => ticket.status === column.key)
                if (!columnTickets.length) return null
                return (
                  <div className="remediation-column" key={column.key}>
                    <div className="remediation-column-title">
                      <span>{column.label}</span>
                      <b>{columnTickets.length}</b>
                    </div>
                    {makeRemediationItems(columnTickets).map(item => (
                      item.type === 'document-group' ? renderDocumentGroup(item) : renderTicketCard(item.ticket)
                    ))}
                  </div>
                )
              }) : (
                <div className="remediation-empty">
                  <FileProtectOutlined />
                  <strong>整改队列待生成</strong>
                  <span>文档差距、技术风险和人工问题会统一进入这里。</span>
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
