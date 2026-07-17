import { useEffect, useMemo, useState } from 'react'
import { Button, Tag } from 'antd'
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

const statusCopy = { success: '正常', warning: '待判定', failed: '失败', skipped: '不适用', idle: '待执行' }

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

const executionHasRisk = (result = {}) => {
  const values = ['findings', 'vulnerabilities', 'issues', 'found', 'credentials', 'found_credentials', 'injection_points', 'failed_checks']
  return values.some(key => Array.isArray(result[key]) && result[key].length > 0)
    || result.unauthorized === true
    || result.empty_password === true
    || Number(result.summary?.non_compliant || 0) > 0
}

function ProjectCommandCenter({ project, assets, assetsLoading = false, modelId, onOpenResults }) {
  const [scanTasks, setScanTasks] = useState([])
  const [assessment, setAssessment] = useState(null)
  const [verification, setVerification] = useState(null)
  const [detectedChanges, setDetectedChanges] = useState([])
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
      const [scansResult, assessmentResult, verificationResult, changesResult] = await Promise.allSettled([
        api.get(`/results/projects/${project.id}/scans`),
        api.get(`/assessments/projects/${project.id}`),
        api.get(`/projects/${project.id}/verification/workspace`),
        api.get(`/projects/${project.id}/monitoring/changes`, { params: { reassessment_only: true } }),
      ])
      if (!mounted) return
      setScanTasks(scansResult.status === 'fulfilled' ? scansResult.value.data || [] : [])
      const assessments = assessmentResult.status === 'fulfilled' ? assessmentResult.value.data : null
      setAssessment(Array.isArray(assessments) ? assessments[0] || null : assessments)
      setVerification(verificationResult.status === 'fulfilled' ? verificationResult.value.data : null)
      setDetectedChanges(changesResult.status === 'fulfilled' ? changesResult.value.data || [] : [])
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
  const openIssues = issues.filter(item => item.status === 'open')
  const summary = verification?.summary || {}
  const assessmentProgress = Math.round(assessment?.progress || 0)

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
        return { state: 'skipped', label: key === 'database_security_scan' ? '未发现数据库服务' : '不适用' }
      }
      if (execution.status === 'failed') return { state: 'failed', label: '失败' }
      if (execution.status === 'warning' || result.scan_completed === false) return { state: 'warning', label: '未完整' }
      if (executionHasRisk(result)) return { state: 'warning', label: '发现风险' }
      return { state: 'success', label: '正常' }
    }
    const conclusion = scanTaskConclusion(latest)
    if (conclusion.key === 'failed') return { state: 'failed', label: '失败' }
    if (conclusion.key === 'skipped') return { state: 'skipped', label: key === 'database_security_scan' ? '未发现数据库服务' : '不适用' }
    if (conclusion.key === 'risk') return { state: 'warning', label: '发现风险' }
    if (conclusion.key === 'warning' || conclusion.key === 'running') return { state: 'warning', label: conclusion.label }
    return { state: 'success', label: '正常' }
  }

  const acknowledgeChange = async changeId => {
    await api.post(`/projects/${project.id}/monitoring/changes/${changeId}/acknowledge`)
    setDetectedChanges(items => items.filter(item => item.id !== changeId))
  }

  return (
    <div className="command-center-shell">
      <div className="command-center-topbar">
        <div className="project-identity">
          <h1>{project?.name || '未选择项目'}</h1>
          <div className="identity-meta">
            <Tag color="cyan">{project?.compliance_level || '等保未配置'}</Tag>
            <Tag color={workspaceLoading ? 'processing' : assessment?.status === 'completed' ? 'green' : assessment?.status === 'in_progress' ? 'blue' : 'default'}>
              {workspaceLoading ? '数据加载中' : assessment?.status === 'completed' ? '测评完成' : assessment?.status === 'in_progress' ? '测评中' : assessment ? '待推进' : '未创建测评'}
            </Tag>
            <span>{assetsLoading ? '资产加载中' : `${assets.length} 个资产`}</span>
            {detectedChanges.length > 0 && (
              <span className="reassessment-alert">
                <ExclamationCircleFilled /> {detectedChanges.length} 项变化需重新评估
                <Button size="small" type="link" onClick={() => acknowledgeChange(detectedChanges[0].id)}>知晓</Button>
              </span>
            )}
          </div>
        </div>
        <div className="posture-strip">
          <div className="posture-tile primary"><span>测评进度</span><strong>{workspaceLoading ? '—' : `${assessmentProgress}%`}</strong></div>
          <div className="posture-tile danger"><span>待处理问题</span><strong>{workspaceLoading ? '—' : summary.open || 0}</strong></div>
          <div className="posture-tile warning"><span>无法验证</span><strong>{workspaceLoading ? '—' : summary.unable || 0}</strong></div>
          <div className="posture-tile"><span>已修复</span><strong>{workspaceLoading ? '—' : summary.fixed || 0}</strong></div>
        </div>
      </div>

      <div className="command-center-grid">
        <main className="ai-command-core">
          <div className="chat-glass-frame">
            <ChatWorkspace key={project?.id || 'default'} projectId={project?.id} projectName={project?.name} modelId={modelId} />
          </div>
        </main>
        <aside className="intel-rail right">
          <section className="intel-panel tool-panel">
            <div className="panel-heading"><span><ThunderboltOutlined /> 工具遥测</span><small>{workspaceLoading ? '加载中' : scanTasks.length ? '最近结果' : '等待检测'}</small></div>
            <div className="tool-grid">
              {TOOL_GROUPS.map(tool => {
                const status = toolStatus(tool.key)
                return <div key={tool.key} className={`tool-cell ${status.state}`}><span>{tool.icon}</span><strong>{tool.label}</strong><i>{status.label}</i></div>
              })}
            </div>
          </section>
          <section className="intel-panel evidence-panel">
            <div className="panel-heading">
              <span><FileSearchOutlined /> 整改与复测</span>
              <Button size="small" type="text" onClick={onOpenResults}>检测记录</Button>
            </div>
            <div className="remediation-summary">
              <div><strong>{summary.open || 0}</strong><span>待处理</span></div>
              <div><strong>{summary.fixed || 0}</strong><span>已修复</span></div>
              <div><strong>{summary.unable || 0}</strong><span>无法完成</span></div>
              <div><strong>{summary.total || 0}</strong><span>问题总数</span></div>
            </div>
            <div className="remediation-board">
              {workspaceLoading ? (
                <div className="remediation-empty"><FileProtectOutlined /><strong>正在加载项目数据</strong><span>检测结果与整改状态加载完成后显示。</span></div>
              ) : openIssues.length ? openIssues.slice(0, 12).map(item => (
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
                <div className="remediation-empty"><FileProtectOutlined /><strong>当前没有待处理问题</strong><span>已修复问题和复测记录仍保留在测评结果与 HTML 报告中。</span></div>
              )}
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}

export default ProjectCommandCenter
