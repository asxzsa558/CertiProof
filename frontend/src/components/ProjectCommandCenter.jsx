import { useEffect, useMemo, useState } from 'react'
import { Button, Checkbox, Drawer, message, Modal, Progress, Tag, Tooltip } from 'antd'
import {
  BarChartOutlined,
  BugOutlined,
  CloseOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  DeleteOutlined,
  ExclamationCircleFilled,
  EyeOutlined,
  FileProtectOutlined,
  FileSearchOutlined,
  GlobalOutlined,
  HistoryOutlined,
  KeyOutlined,
  LockOutlined,
  RadarChartOutlined,
  RightOutlined,
  SwapOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import ChatWorkspace from './ChatWorkspace'
import MiniLineChart from './MiniLineChart'
import VerificationWorkspace from './VerificationWorkspace'
import { severityLabel } from './resultRendererUtils'
import { scanTaskCapabilities, scanTaskConclusion } from './toolCatalog'
import './ProjectCommandCenter.css'

const TOOL_GROUPS = [
  { key: 'scan_ports', label: '端口', icon: <RadarChartOutlined /> },
  { key: 'scan_ssl', label: 'SSL', icon: <LockOutlined /> },
  { key: 'scan_vulnerabilities', label: '漏洞', icon: <BugOutlined /> },
  { key: 'scan_weak_passwords', label: '弱口令', icon: <KeyOutlined /> },
  { key: 'database_security_scan', label: '数据库', icon: <DatabaseOutlined /> },
  { key: 'web_discovery_scan', label: 'Web', icon: <GlobalOutlined /> },
]

const statusCopy = { success: '检测完成', risk: '发现问题', warning: '检测不完整', failed: '执行失败', skipped: '检测不完整', idle: '待执行' }
const keepIfUnchanged = (previous, next) => JSON.stringify(previous) === JSON.stringify(next) ? previous : next

const normalizeCapability = (capability = '') => {
  if (['ping_asset', 'ping_host'].includes(capability)) return 'ping_host'
  if (capability === 'testssl_scan') return 'scan_ssl'
  if (capability === 'nuclei_scan') return 'scan_vulnerabilities'
  if (capability === 'hydra_bruteforce') return 'scan_weak_passwords'
  if (['gobuster_scan', 'ffuf_scan', 'nikto_scan', 'sqlmap_scan'].includes(capability)) return 'web_discovery_scan'
  if (['redis_check', 'mysql_check', 'mongodb_check', 'memcached_check', 'oracle_check'].includes(capability)) return 'database_security_scan'
  return capability
}

const flattenIssues = (workspace) => [
  ...(workspace?.document_groups || []).flatMap(group => group.findings.map(finding => ({ ...finding, group: group.title }))),
  ...(workspace?.technical_groups || []).flatMap(group => group.findings.map(finding => ({ ...finding, group: group.target || group.title }))),
]

const findingIsUnable = finding => finding.status === 'open' && (
  finding.judgment === 'not_tested' || finding.latest_verification?.outcome === 'unable'
)

const executionHasRisk = (result = {}) => {
  const values = ['findings', 'vulnerabilities', 'issues', 'found', 'credentials', 'found_credentials', 'injection_points', 'failed_checks']
  return values.some(key => Array.isArray(result[key]) && result[key].length > 0)
    || result.unauthorized === true
    || result.empty_password === true
    || Number(result.summary?.non_compliant || 0) > 0
}

function ProjectCommandCenter({ project, assets, assetsLoading = false, assessmentCollapsed = false, modelId, onOpenResults, onWorkspaceSummary }) {
  const [scanTasks, setScanTasks] = useState([])
  const [assessment, setAssessment] = useState(null)
  const [verification, setVerification] = useState(null)
  const [detectedChanges, setDetectedChanges] = useState([])
  const [scoreSummary, setScoreSummary] = useState(null)
  const [reportHistory, setReportHistory] = useState([])
  const [reportComparison, setReportComparison] = useState(null)
  const [selectedReportVersions, setSelectedReportVersions] = useState([])
  const [deletingReports, setDeletingReports] = useState(false)
  const [detailTab, setDetailTab] = useState('history')
  const [detailCollapsed, setDetailCollapsed] = useState(false)
  const [verificationVisible, setVerificationVisible] = useState(false)
  const [verificationFilter, setVerificationFilter] = useState('all')
  const [workspaceLoading, setWorkspaceLoading] = useState(true)

  useEffect(() => {
    document.body.classList.add('command-center-active')
    return () => document.body.classList.remove('command-center-active')
  }, [])

  useEffect(() => {
    let mounted = true
    setWorkspaceLoading(true)
    const fetchWorkspace = async () => {
      if (!project?.id) return
      const [scansResult, assessmentResult, verificationResult, changesResult, reportsResult] = await Promise.allSettled([
        api.get(`/results/projects/${project.id}/scans`),
        api.get(`/assessments/projects/${project.id}`),
        api.get(`/projects/${project.id}/verification/workspace`),
        api.get(`/projects/${project.id}/monitoring/changes`, { params: { reassessment_only: true } }),
        api.get(`/projects/${project.id}/reports`),
      ])
      if (!mounted) return
      const nextScans = scansResult.status === 'fulfilled' ? scansResult.value.data || [] : []
      setScanTasks(previous => keepIfUnchanged(previous, nextScans))
      const assessments = assessmentResult.status === 'fulfilled' ? assessmentResult.value.data : null
      const latestAssessment = Array.isArray(assessments) ? assessments[0] || null : assessments
      setAssessment(previous => keepIfUnchanged(previous, latestAssessment))
      setVerification(previous => keepIfUnchanged(previous, verificationResult.status === 'fulfilled' ? verificationResult.value.data : null))
      setDetectedChanges(previous => keepIfUnchanged(previous, changesResult.status === 'fulfilled' ? changesResult.value.data || [] : []))
      setReportHistory(previous => keepIfUnchanged(previous, reportsResult.status === 'fulfilled' ? reportsResult.value.data || [] : []))
      if (latestAssessment?.id) {
        try {
          const summaryResult = await api.get(`/assessments/${latestAssessment.id}/summary`)
          if (mounted) setScoreSummary(previous => keepIfUnchanged(previous, summaryResult.data))
        } catch {
          if (mounted) setScoreSummary(null)
        }
      } else {
        setScoreSummary(null)
      }
      setWorkspaceLoading(false)
    }
    fetchWorkspace()
    const timer = window.setInterval(fetchWorkspace, 8000)
    const reset = event => {
      if (event.detail?.projectId === project?.id) fetchWorkspace()
    }
    window.addEventListener('certiproof:assessment-reset', reset)
    return () => {
      mounted = false
      window.clearInterval(timer)
      window.removeEventListener('certiproof:assessment-reset', reset)
    }
  }, [project?.id])

  const issues = useMemo(() => flattenIssues(verification), [verification])
  const issueCounts = useMemo(() => ({
    all: issues.length,
    open: issues.filter(item => item.status === 'open' && !findingIsUnable(item)).length,
    fixed: issues.filter(item => item.status === 'fixed').length,
    unable: issues.filter(findingIsUnable).length,
  }), [issues])
  const openIssues = issues.filter(item => item.status === 'open' && !findingIsUnable(item))
  const assessmentProgress = Math.round(assessment?.progress || 0)
  const scoreMetrics = scoreSummary?.score_metrics || {}
  const currentScore = scoreSummary?.project?.score
  const scoreTrend = useMemo(() => [...reportHistory]
    .reverse()
    .filter(item => Number.isFinite(item.score))
    .map(item => ({
      version: `V${item.version}`,
      score: item.score,
      date: item.generated_at
        ? new Date(item.generated_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
        : '',
    })), [reportHistory])
  const visibleScoreTrend = scoreTrend.length
    ? scoreTrend
    : Number.isFinite(currentScore)
      ? [{ version: '当前', score: currentScore, date: '' }]
      : []

  useEffect(() => {
    onWorkspaceSummary?.({
      progress: assessmentProgress,
      score: currentScore,
      coverage: scoreMetrics.coverage,
      open: issueCounts.open,
      unable: issueCounts.unable,
      fixed: issueCounts.fixed,
    })
  }, [assessmentProgress, currentScore, scoreMetrics.coverage, issueCounts.open, issueCounts.unable, issueCounts.fixed, onWorkspaceSummary])

  const toolStatus = key => {
    if (workspaceLoading) return { state: 'idle', label: '加载中' }
    const latest = scanTasks.find(task => scanTaskCapabilities(task).some(capability => normalizeCapability(capability) === key))
    if (!latest) return { state: 'idle', label: statusCopy.idle }
    const summary = latest.result_summary || {}
    const execution = [...(summary.results || []), ...(summary.failed || [])]
      .find(item => normalizeCapability(item?.capability) === key)
    if (execution) {
      const result = execution.result || {}
      const totals = result.summary || {}
      if (result.skipped === true || (totals.total > 0 && totals.skipped === totals.total)) {
        return { state: 'warning', label: '检测不完整' }
      }
      if (execution.status === 'failed') return { state: 'failed', label: '执行失败' }
      if (execution.status === 'warning' || result.scan_completed === false) return { state: 'warning', label: '检测不完整' }
      if (key === 'scan_vulnerabilities' && result.reachable !== true && !(result.findings || []).length) {
        return { state: 'warning', label: '检测不完整' }
      }
      if (executionHasRisk(result)) return { state: 'risk', label: '发现问题' }
      return { state: 'success', label: '检测完成' }
    }
    const conclusion = scanTaskConclusion(latest)
    if (conclusion.key === 'failed') return { state: 'failed', label: '执行失败' }
    if (conclusion.key === 'risk') return { state: 'risk', label: '发现问题' }
    if (conclusion.key === 'warning' || conclusion.key === 'running') return { state: 'warning', label: conclusion.label }
    return { state: 'success', label: '检测完成' }
  }

  const acknowledgeChange = async changeId => {
    await api.post(`/projects/${project.id}/monitoring/changes/${changeId}/acknowledge`)
    setDetectedChanges(items => items.filter(item => item.id !== changeId))
  }

  const openReportVersion = async (version, download = false) => {
    try {
      const response = await api.get(`/projects/${project.id}/reports/${version}`, {
        params: { download },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(new Blob([response.data], { type: 'text/html' }))
      if (download) {
        const link = document.createElement('a')
        link.href = url
        link.download = `certiproof-report-${project.id}-v${version}.html`
        link.click()
      } else {
        window.open(url, '_blank', 'noopener,noreferrer')
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (error) {
      message.error(error.response?.data?.detail || '报告版本读取失败')
    }
  }

  const deleteSelectedReports = () => {
    if (!selectedReportVersions.length) return
    const labels = selectedReportVersions.sort((a, b) => b - a).map(version => `V${version}`).join('、')
    Modal.confirm({
      title: `彻底删除 ${labels}？`,
      content: '数据库快照和 HTML 文件都会删除，操作不可恢复；后续报告不会复用这些版本号。',
      okText: '彻底删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      async onOk() {
        setDeletingReports(true)
        try {
          await api.delete(`/projects/${project.id}/reports`, { data: { versions: selectedReportVersions } })
          setReportHistory(items => items.filter(item => !selectedReportVersions.includes(item.version)))
          setReportComparison(null)
          setSelectedReportVersions([])
          message.success(`已彻底删除 ${labels}`)
        } catch (error) {
          message.error(error.response?.data?.detail || '报告版本删除失败')
          throw error
        } finally {
          setDeletingReports(false)
        }
      },
    })
  }

  const applicable = Number(scoreMetrics.reliable || 0) + Number(scoreMetrics.unable || 0)
  const unablePercent = applicable ? Math.round(Number(scoreMetrics.unable || 0) / applicable * 100) : 0
  const openVerification = (filter = 'all') => {
    setVerificationFilter(filter)
    setVerificationVisible(true)
  }

  return (
    <div className={`command-center-shell ${assessmentCollapsed ? 'assessment-panel-collapsed' : ''} ${detailCollapsed ? 'detail-panel-collapsed' : ''}`}>
      <div className={`command-center-grid ${detailCollapsed ? 'detail-collapsed' : ''}`}>
        <main className="ai-command-core">
          {detectedChanges.length > 0 && (
            <div className="reassessment-banner">
              <span><ExclamationCircleFilled /> {detectedChanges.length} 项资产或端口变化需要重新评估</span>
              <Button size="small" type="text" onClick={() => acknowledgeChange(detectedChanges[0].id)}>知晓</Button>
            </div>
          )}
          <div className="chat-glass-frame">
            <ChatWorkspace
              key={project?.id || 'default'}
              projectId={project?.id}
              projectName={project?.name}
              modelId={modelId}
              onOpenResults={onOpenResults}
            />
          </div>
          {detailCollapsed && (
            <Tooltip title="展开测评详情">
              <Button className="detail-reopen-button" type="text" icon={<RightOutlined />} onClick={() => setDetailCollapsed(false)} aria-label="展开测评详情" />
            </Tooltip>
          )}
        </main>
        {!detailCollapsed && <aside className="detail-workbench">
          <div className="detail-workbench-header">
            <div><strong>测评详情</strong><span>{workspaceLoading ? '数据同步中' : assessment?.status === 'completed' ? '本轮测评已结束' : '实时同步'}</span></div>
            <div className="detail-workbench-actions">
              <Tooltip title="检测记录">
                <Button size="small" type="text" aria-label="检测记录" icon={<FileSearchOutlined />} onClick={onOpenResults} />
              </Tooltip>
              <Tooltip title="收起测评详情">
                <Button size="small" type="text" aria-label="收起测评详情" icon={<CloseOutlined />} onClick={() => setDetailCollapsed(true)} />
              </Tooltip>
            </div>
          </div>
          <div className="detail-workbench-tabs" role="tablist">
            {[
              ['current', '当前结果'],
              ['score', '评分解释'],
              ['history', '历史与报告'],
            ].map(([key, label]) => <button key={key} type="button" className={detailTab === key ? 'active' : ''} onClick={() => setDetailTab(key)}>{label}</button>)}
          </div>
          <div className="detail-workbench-body">
            {detailTab === 'current' && <>
              <section className="detail-section tool-section">
                <div className="detail-section-heading"><span><ThunderboltOutlined /> 工具状态</span><small>{scanTasks.length ? `${scanTasks.length} 条记录` : '等待检测'}</small></div>
                <div className="tool-grid">
                  {TOOL_GROUPS.map(tool => {
                    const status = toolStatus(tool.key)
                    return <div key={tool.key} className={`tool-cell ${status.state}`}><span>{tool.icon}</span><strong>{tool.label}</strong><i>{status.label}</i></div>
                  })}
                </div>
              </section>
              <section className="detail-section issue-section">
                <button type="button" className="detail-section-heading issue-detail-trigger" onClick={() => openVerification('all')}>
                  <span><FileSearchOutlined /> 问题与复测</span><small>查看全部 {issueCounts.all} 项</small>
                </button>
                <div className="remediation-summary">
                  <button type="button" onClick={() => openVerification('all')}><strong>{issueCounts.all}</strong><span>全部</span></button>
                  <button type="button" onClick={() => openVerification('open')}><strong>{issueCounts.open}</strong><span>待处理</span></button>
                  <button type="button" onClick={() => openVerification('fixed')}><strong>{issueCounts.fixed}</strong><span>已修复</span></button>
                  <button type="button" onClick={() => openVerification('unable')}><strong>{issueCounts.unable}</strong><span>无法完成</span></button>
                </div>
                <div className="remediation-board">
                  {workspaceLoading ? (
                    <div className="remediation-empty"><FileProtectOutlined /><strong>正在加载项目数据</strong><span>检测结果与整改状态加载完成后显示。</span></div>
                  ) : openIssues.length ? openIssues.map(item => (
                    <article className={`remediation-card ${item.severity || 'medium'} compact`} key={item.id}>
                      <div className="remediation-card-top">
                        <Tag color={item.source_type === 'document' ? 'cyan' : 'orange'}>{item.source_type === 'document' ? '文档' : '技术'}</Tag>
                        <Tag color={['critical', 'high'].includes(item.severity) ? 'red' : 'gold'}>{severityLabel(item.severity)}</Tag>
                      </div>
                      <strong>{item.clause_name || item.group || item.clause_id}</strong>
                      <p>{item.description || '待补充问题说明'}</p>
                      {item.latest_verification?.outcome === 'unable' && <span className="remediation-waiting">{item.latest_verification.error}</span>}
                    </article>
                  )) : (
                    <div className="remediation-empty"><FileProtectOutlined /><strong>当前没有待处理问题</strong><span>已修复问题和复测记录仍保留在检测记录与正式报告中。</span></div>
                  )}
                </div>
              </section>
            </>}

            {detailTab === 'score' && <div className="score-explainer">
              <section className="score-hero">
                <div><span>当前合规分</span><strong>{currentScore ?? '—'}</strong><small>{scoreSummary?.project?.grade || '尚未形成结论'}</small></div>
                <Progress type="circle" size={108} percent={currentScore || 0} strokeColor={currentScore >= 75 ? '#10b981' : '#f59e0b'} format={() => `${scoreMetrics.coverage ?? 0}%`} />
              </section>
              <section className="score-metric-grid">
                <div><strong>{scoreMetrics.reliable ?? 0}</strong><span>可靠判定</span></div>
                <div><strong>{scoreMetrics.unable ?? 0}</strong><span>失败/无法验证</span></div>
                <div><strong>{scoreMetrics.not_applicable ?? 0}</strong><span>不适用</span></div>
                <div><strong>{assessmentProgress}%</strong><span>流程进度</span></div>
              </section>
              <section className="score-rule-list">
                <h3><BarChartOutlined /> 评分构成</h3>
                <div><i className="pass" /><span><b>符合或真实复测修复</b><small>计满分</small></span></div>
                <div><i className="partial" /><span><b>部分符合</b><small>计半分</small></span></div>
                <div><i className="failed" /><span><b>不符合、失败或无法验证</b><small>计 0 分，进入分母</small></span></div>
                <div><i className="na" /><span><b>明确不适用</b><small>排除评分</small></span></div>
              </section>
              {unablePercent > 0 && <div className="score-warning">当前有 {scoreMetrics.unable} 项失败或无法验证，约占适用检查的 {unablePercent}%，已经按 0 分扣分。</div>}
            </div>}

            {detailTab === 'history' && <div className="report-history">
              <section className="history-trend-panel">
                <div className="history-trend-heading">
                  <span>合规分趋势</span>
                  <strong>{Number.isFinite(currentScore) ? currentScore : '—'}</strong>
                </div>
                {visibleScoreTrend.length ? (
                  <div className="history-trend-chart">
                    <div className="history-trend-scale"><span>100</span><span>50</span><span>0</span></div>
                    <div className="history-trend-plot">
                      <MiniLineChart data={visibleScoreTrend.map(item => item.score)} height={112} />
                      <div className="history-trend-labels">
                        {visibleScoreTrend.map(item => <span key={item.version}>{item.version}</span>)}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="history-trend-empty">生成至少两个报告版本后显示评分趋势</div>
                )}
              </section>
              <section className="history-heading">
                <div><HistoryOutlined /><span><strong>评分与报告版本</strong><small>每份报告使用生成时的不可变数据快照</small></span></div>
                <div className="history-selection-actions">
                  {reportHistory.some(item => item.stale) && <Button type="text" size="small" onClick={() => setSelectedReportVersions(reportHistory.filter(item => item.stale).map(item => item.version))}>选择已过期</Button>}
                  <Button danger type="text" size="small" icon={<DeleteOutlined />} disabled={!selectedReportVersions.length} loading={deletingReports} onClick={deleteSelectedReports}>删除 {selectedReportVersions.length || ''}</Button>
                  <b>{reportHistory.length} 个版本</b>
                </div>
              </section>
              {reportComparison && <section className="report-comparison-strip">
                <span>V{reportComparison.previous.version}</span>
                <SwapOutlined />
                <span>V{reportComparison.current.version}</span>
                <strong>{reportComparison.delta >= 0 ? '+' : ''}{reportComparison.delta} 分</strong>
                <small>未解决问题 {reportComparison.previous.open_findings ?? 0} → {reportComparison.current.open_findings ?? 0}</small>
                <Button type="text" size="small" onClick={() => setReportComparison(null)}>关闭</Button>
              </section>}
              {reportHistory.length ? reportHistory.map((item, index) => {
                const older = reportHistory[index + 1]
                const delta = Number.isFinite(item.score) && Number.isFinite(older?.score) ? Number((item.score - older.score).toFixed(1)) : null
                const selected = selectedReportVersions.includes(item.version)
                return <article className={`report-version-row ${item.stale ? 'stale' : 'current'} ${selected ? 'selected' : ''}`} key={item.id}>
                  <Checkbox checked={selected} onChange={event => setSelectedReportVersions(values => event.target.checked ? [...values, item.version] : values.filter(version => version !== item.version))} aria-label={`选择报告 V${item.version}`} />
                  <div className="report-version-state"><span>{item.stale ? '已过期' : '当前'}</span><strong>V{item.version}</strong></div>
                  <div className="report-version-score"><strong>{item.score ?? '未出具'}</strong>{delta !== null && <small className={delta >= 0 ? 'up' : 'down'}>{delta >= 0 ? '+' : ''}{delta}</small>}</div>
                  <dl>
                    <div><dt>生成时间</dt><dd>{item.generated_at ? new Date(item.generated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'}</dd></div>
                    <div><dt>覆盖率</dt><dd>{item.coverage == null ? '-' : `${item.coverage}%`}</dd></div>
                    <div><dt>未解决</dt><dd>{item.open_findings ?? 0}</dd></div>
                  </dl>
                  <div className="report-version-actions">
                    <Tooltip title="预览"><Button type="text" icon={<EyeOutlined />} onClick={() => openReportVersion(item.version)} aria-label={`预览报告 V${item.version}`} /></Tooltip>
                    <Tooltip title="下载"><Button type="text" icon={<DownloadOutlined />} onClick={() => openReportVersion(item.version, true)} aria-label={`下载报告 V${item.version}`} /></Tooltip>
                    <Tooltip title={older ? `与 V${older.version} 对比` : '没有更早版本'}><Button type="text" disabled={!older || delta === null} icon={<SwapOutlined />} onClick={() => setReportComparison({ current: item, previous: older, delta })} aria-label={`对比报告 V${item.version}`} /></Tooltip>
                  </div>
                  {item.stale && item.stale_reason && <p>{item.stale_reason}</p>}
                </article>
              }) : <div className="remediation-empty"><HistoryOutlined /><strong>尚未生成正式报告</strong><span>完成前置阶段并生成报告后，这里会形成可追溯的评分版本。</span></div>}
              <section className="history-score-rules">
                <div className="history-score-ring" style={{ '--score': Number(currentScore || 0) }}>
                  <span><strong>{currentScore ?? '—'}</strong><small>当前合规分</small></span>
                </div>
                <div className="history-score-copy">
                  <div className="history-score-copy-heading">
                    <span><strong>评分构成说明</strong><small>当前版本的自动评分口径</small></span>
                    <em>可靠 {scoreMetrics.reliable ?? 0} · 无法验证 {scoreMetrics.unable ?? 0}</em>
                  </div>
                  <dl>
                    <div><dt className="pass" /> <dd><b>符合 / 已修复</b><small>计满分</small></dd></div>
                    <div><dt className="partial" /> <dd><b>部分符合</b><small>计半分</small></dd></div>
                    <div><dt className="failed" /> <dd><b>不符合 / 无法验证</b><small>计 0 分</small></dd></div>
                    <div><dt className="na" /> <dd><b>明确不适用</b><small>排除评分</small></dd></div>
                  </dl>
                </div>
              </section>
              {reportHistory.some(item => item.stale) && <div className="stale-report-warning"><ExclamationCircleFilled /> 过期报告只用于追溯，不能作为当前测评结论。</div>}
            </div>}
          </div>
        </aside>}
      </div>
      <Drawer
        title="问题与复测"
        placement="right"
        width="min(960px, 96vw)"
        open={verificationVisible}
        onClose={() => setVerificationVisible(false)}
        destroyOnClose
        rootClassName="verification-detail-drawer"
      >
        {verificationVisible && (
          <VerificationWorkspace
            key={project?.id || 'project'}
            projectId={project?.id}
            initialFilter={verificationFilter}
          />
        )}
      </Drawer>
    </div>
  )
}

export default ProjectCommandCenter
