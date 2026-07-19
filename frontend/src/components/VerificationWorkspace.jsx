import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Modal, Segmented, Spin, Tag, Upload, message } from 'antd'
import {
  CheckCircleFilled,
  FileTextOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  UploadOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import './VerificationWorkspace.css'

const { TextArea } = Input

const outcomeCopy = {
  queued: '排队中', running: '重新检查中', fixed: '已修复', still_present: '未解决',
  new: '新增问题', unable: '无法完成', cancelled: '已停止',
}

const capabilityCopy = {
  scan_ports: '端口扫描', scan_ssl: 'SSL/TLS 检测', scan_vulnerabilities: '漏洞扫描',
  scan_weak_passwords: '弱口令检测', baseline_check: '安全基线核查', nikto_scan: 'Web 安全扫描',
  web_discovery_scan: 'Web 目录发现', database_security_scan: '数据库安全检测',
  network_device_scan: '网络设备检测', windows_security_scan: 'Windows/AD/SMB 检测',
}

function readableObservation(item) {
  if (item.error) return item.error
  const observation = item.current_observation || {}
  const risk = observation.risk || {}
  if (risk.description) return risk.description
  if (risk.title || risk.name) return risk.title || risk.name
  if (observation.description) return observation.description
  if (item.outcome === 'fixed') return '本次检测未再发现原问题。'
  if (item.outcome === 'still_present') return '本次检测仍发现原问题。'
  if (item.outcome === 'new') return '本次检测发现了新的问题。'
  if (item.outcome === 'queued') return '等待 Worker 接收。'
  if (item.outcome === 'running') return '正在执行检测并比对结果。'
  return '本次运行未返回可展示的检测明细。'
}

function RunItems({ run }) {
  return (
    <div className="verification-run-items">
      {(run.items || []).map(item => (
        <div className="verification-run-item" key={item.id}>
          <div>
            <strong>{item.target || '文档材料'}</strong>
            <span>{capabilityCopy[item.capability] || (item.source_type === 'document' ? '文档合规检查' : item.capability || '技术检测')}</span>
          </div>
          <Tag color={item.outcome === 'fixed' ? 'success' : item.outcome === 'unable' ? 'error' : item.outcome === 'still_present' || item.outcome === 'new' ? 'warning' : 'processing'}>
            {outcomeCopy[item.outcome] || item.outcome}
          </Tag>
          <p>{readableObservation(item)}</p>
          {(item.current_scan_task_id || item.current_document_run_id) && (
            <small>{item.current_scan_task_id ? `检测任务 #${item.current_scan_task_id}` : `文档分析 #${item.current_document_run_id}`}</small>
          )}
        </div>
      ))}
    </div>
  )
}

function FindingRow({ finding }) {
  const latest = finding.latest_verification
  const notTested = finding.judgment === 'not_tested'
  const analysisUnable = finding.source_type === 'document' && notTested
  const state = finding.status === 'fixed'
    ? { color: 'success', text: '已修复' }
    : finding.status === 'false_positive'
      ? { color: 'default', text: '已确认误报' }
      : latest?.outcome === 'still_present'
      ? { color: 'warning', text: '复测后仍存在' }
      : latest?.outcome === 'unable'
        ? { color: 'error', text: '无法验证' }
        : latest?.outcome === 'new'
          ? { color: 'warning', text: '复测新增' }
          : ['queued', 'running'].includes(latest?.outcome)
            ? { color: 'processing', text: outcomeCopy[latest.outcome] }
            : analysisUnable
                  ? { color: 'error', text: '分析未完成' }
                  : notTested
                    ? { color: 'error', text: '检测未完成' }
                    : { color: 'warning', text: '待处理' }
  return (
    <div className="verification-finding-row">
      <div className="verification-finding-main">
        <span className={`severity-dot ${finding.severity}`} />
        <div>
          <strong>{finding.clause_name || finding.clause_id}</strong>
          <p>{finding.description || '未提供问题说明'}</p>
          {finding.remediation_suggestion && <em>{finding.remediation_suggestion}</em>}
          {finding.remediation_plan && (
            <details className="controlled-remediation">
              <summary>查看整改步骤与验证方法</summary>
              <div><b>适用条件</b><span>{finding.remediation_plan.applicability}</span></div>
              <div><b>执行前</b><ul>{(finding.remediation_plan.prerequisites || []).map(item => <li key={item}>{item}</li>)}</ul></div>
              <div><b>整改步骤</b><ol>{(finding.remediation_plan.steps || []).map(item => <li key={item}>{item}</li>)}</ol></div>
              <div><b>验证方法</b><span>{finding.remediation_plan.verification}</span></div>
              <div><b>回滚方案</b><span>{finding.remediation_plan.rollback}</span></div>
              {finding.remediation_plan.requires_context && <small>技术栈尚未确认，执行前需由系统负责人选择实际配置位置。</small>}
            </details>
          )}
        </div>
      </div>
      <div className="verification-finding-state">
        <Tag color={state.color}>{state.text}</Tag>
      </div>
      {latest?.error && <Alert type="error" showIcon message={latest.error} />}
      {latest?.comparison && Object.keys(latest.comparison).length > 0 && (
        <div className="verification-comparison">
          <span>整改前：{latest.comparison.before || '存在问题'}</span>
          <i />
          <span>复测后：{latest.comparison.after || latest.outcome}</span>
        </div>
      )}
    </div>
  )
}

function VerificationWorkspace({ projectId, onChanged, onContinue, refreshKey, initialFilter = null }) {
  const [workspace, setWorkspace] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null)
  const [expanded, setExpanded] = useState({})
  const [documentModal, setDocumentModal] = useState(null)
  const [technicalModal, setTechnicalModal] = useState(null)
  const [watchedRunId, setWatchedRunId] = useState(null)
  const [expandedRuns, setExpandedRuns] = useState({})
  const [historyVisible, setHistoryVisible] = useState(false)
  const [files, setFiles] = useState([])
  const [replaceFileIds, setReplaceFileIds] = useState([])
  const [notes, setNotes] = useState('')
  const [username, setUsername] = useState('root')
  const [password, setPassword] = useState('')
  const [filter, setFilter] = useState(initialFilter)
  const refreshKeyRef = useRef(refreshKey)

  const fetchWorkspace = useCallback(async (silent = false) => {
    if (!projectId) return
    if (!silent) setLoading(true)
    try {
      const response = await api.get(`/projects/${projectId}/verification/workspace`)
      setWorkspace(response.data)
      onChanged?.({ silent: true })
    } catch (error) {
      if (!silent) message.error(error.response?.data?.detail || '加载整改与复测工作区失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [projectId, onChanged])

  useEffect(() => {
    fetchWorkspace()
  }, [fetchWorkspace])

  useEffect(() => {
    setFilter(initialFilter)
  }, [initialFilter])

  useEffect(() => {
    if (refreshKeyRef.current === refreshKey) return
    refreshKeyRef.current = refreshKey
    fetchWorkspace(true)
  }, [fetchWorkspace, refreshKey])

  const activeRuns = useMemo(
    () => (workspace?.runs || []).filter(run => ['queued', 'running'].includes(run.status)),
    [workspace],
  )

  useEffect(() => {
    if (!activeRuns.length && !watchedRunId) return undefined
    const timer = window.setInterval(() => fetchWorkspace(true), 3000)
    return () => window.clearInterval(timer)
  }, [activeRuns.length, fetchWorkspace, watchedRunId])

  useEffect(() => {
    if (!watchedRunId || !workspace) return
    const watched = (workspace.runs || []).find(run => run.id === watchedRunId)
    if (watched && !['queued', 'running'].includes(watched.status)) {
      setExpandedRuns(value => ({ ...value, [watched.id]: true }))
      setWatchedRunId(null)
      message.success(watched.status === 'completed' ? '重新检查完成，结果已更新' : '重新检查结束，请查看受限或失败项')
    }
  }, [watchedRunId, workspace])

  const openGroupAction = group => {
    setNotes('')
    setPassword('')
    if ('task_id' in group) {
      setDocumentModal(group)
      setFiles([])
      setReplaceFileIds((group.files || []).map(file => file.id))
    } else {
      setTechnicalModal(group)
    }
  }

  const submitDocument = async () => {
    const finding = documentModal?.findings?.find(item => item.status === 'open')
    if (!finding) return message.warning('本组没有待处理问题')
    if (!files.length) return message.warning('请上传改进后的文档')
    const data = new FormData()
    data.append('finding_id', finding.id)
    data.append('notes', notes)
    data.append('replace_file_ids', JSON.stringify(replaceFileIds))
    files.forEach(file => data.append('files', file.originFileObj || file))
    setBusy(`document-${documentModal.key}`)
    try {
      const response = await api.post(`/projects/${projectId}/verification/document`, data, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      message.success(response.data?.message || '文档重新检查已进入队列')
      setWatchedRunId(response.data?.verification_run_id)
      setDocumentModal(null)
      setFiles([])
      setReplaceFileIds([])
      setNotes('')
      await fetchWorkspace(true)
    } catch (error) {
      message.error(error.response?.data?.detail || '提交文档复测失败')
    } finally {
      setBusy(null)
    }
  }

  const reanalyzeDocument = async group => {
    const finding = group.findings.find(item => item.status === 'open' && item.judgment === 'not_tested')
      || group.findings.find(item => item.status === 'open')
    if (!finding) return message.warning('本组没有可重新分析的问题')
    setBusy(`reanalyze-${group.key}`)
    try {
      const response = await api.post(`/projects/${projectId}/verification/document/reanalyze`, {
        finding_id: finding.id,
        notes: '使用当前有效材料重新执行完整文档分析。',
      })
      message.success(response.data?.message || '文档重新分析已进入队列')
      setWatchedRunId(response.data?.verification_run_id)
      await fetchWorkspace(true)
    } catch (error) {
      message.error(error.response?.data?.detail || '重新分析文档失败')
    } finally {
      setBusy(null)
    }
  }

  const submitTechnical = async () => {
    const findings = technicalModal?.findings?.filter(item => item.status === 'open') || []
    if (!findings.length) return message.warning('本组没有待处理问题')
    const credentials = {}
    if (['baseline_check', 'scan_weak_passwords'].includes(technicalModal.capability) && (username || password)) {
      credentials[technicalModal.target] = { username, password }
    }
    setBusy(`technical-${technicalModal.key}`)
    try {
      const response = await api.post(`/projects/${projectId}/verification/technical`, {
        finding_ids: findings.map(item => item.id), notes, credentials,
      })
      message.success(response.data?.message || '技术重新检测已进入队列')
      setWatchedRunId(response.data?.run_id)
      setTechnicalModal(null)
      setNotes('')
      setPassword('')
      await fetchWorkspace(true)
    } catch (error) {
      message.error(error.response?.data?.detail || '技术复测失败')
    } finally {
      setBusy(null)
    }
  }

  const stopRun = async run => {
    setBusy(`run-${run.id}`)
    try {
      await api.post(`/projects/${projectId}/verification/runs/${run.id}/stop`)
      await fetchWorkspace(true)
    } catch (error) {
      message.error(error.response?.data?.detail || '停止复测失败')
    } finally {
      setBusy(null)
    }
  }

  const resumeRun = async run => {
    setBusy(`run-${run.id}`)
    try {
      await api.post(`/projects/${projectId}/verification/runs/${run.id}/resume`)
      setWatchedRunId(run.id)
      await fetchWorkspace(true)
    } catch (error) {
      message.error(error.response?.data?.detail || '继续复测失败')
    } finally {
      setBusy(null)
    }
  }

  const continueToReport = async () => {
    if (!onContinue) return
    setBusy('continue-report')
    try {
      await onContinue()
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="verification-loading"><Spin /><span>正在加载问题和复测记录</span></div>
  const groups = [...(workspace?.document_groups || []), ...(workspace?.technical_groups || [])]
  const findingUnable = finding => finding.status === 'open' && (
    finding.judgment === 'not_tested' || finding.latest_verification?.outcome === 'unable'
  )
  const findingMatches = (finding, key) => {
    if (key === 'all') return true
    if (key === 'open') return finding.status === 'open' && !findingUnable(finding)
    if (key === 'fixed') return finding.status === 'fixed'
    if (key === 'unable') return findingUnable(finding)
    return false
  }
  const allFindings = groups.flatMap(group => group.findings)
  const filterCounts = {
    open: allFindings.filter(finding => findingMatches(finding, 'open')).length,
    fixed: allFindings.filter(finding => findingMatches(finding, 'fixed')).length,
    unable: allFindings.filter(finding => findingMatches(finding, 'unable')).length,
    all: allFindings.length,
  }
  const activeFilter = filter || (filterCounts.open > 0 ? 'open' : filterCounts.unable > 0 ? 'unable' : 'all')
  const filteredGroups = groups
    .map(group => ({
      ...group,
      displayFindings: group.findings.filter(finding => findingMatches(finding, activeFilter)),
    }))
    .filter(group => group.displayFindings.length)
  const filterOptions = [
    { label: `待处理 ${filterCounts.open}`, value: 'open' },
    { label: `已修复 ${filterCounts.fixed}`, value: 'fixed' },
    { label: `无法完成 ${filterCounts.unable}`, value: 'unable' },
    { label: `全部 ${filterCounts.all}`, value: 'all' },
  ]
  const terminalRuns = (workspace?.runs || []).filter(run => !['queued', 'running'].includes(run.status))
  const latestTerminalRun = terminalRuns[0]
  const documentOpen = (workspace?.document_groups || []).flatMap(group => group.findings).filter(item => findingMatches(item, 'open')).length
  const technicalOpen = (workspace?.technical_groups || []).flatMap(group => group.findings).filter(item => findingMatches(item, 'open')).length
  const nextStep = activeRuns.length
    ? { title: '正在重新检查', detail: `系统正在处理 ${activeRuns.length} 个任务，完成后会自动刷新逐项结果。` }
    : filterCounts.open > 0
      ? { title: '下一步：处理未解决问题', detail: `文档问题 ${documentOpen} 项请上传修改后的文件；技术问题 ${technicalOpen} 项请重新执行对应检测。${filterCounts.unable ? `另有 ${filterCounts.unable} 项无法验证，请重新分析或检测。` : ''}` }
      : filterCounts.unable > 0
        ? { title: '下一步：重试无法验证项', detail: `有 ${filterCounts.unable} 项未获得可靠结论，请重新分析材料或执行对应检测。` }
        : { title: '本轮整改已完成', detail: '当前没有待处理问题，可查看重新检查记录或继续生成报告。' }

  return (
    <div className="verification-workspace">
      <div className="verification-next-step">
        <span><SafetyCertificateOutlined /></span>
        <div><strong>{nextStep.title}</strong><p>{nextStep.detail}</p></div>
      </div>
      <div className="verification-summary">
        <div><strong>{filterCounts.all}</strong><span>全部</span></div>
        <div className="warning"><strong>{filterCounts.open}</strong><span>待处理</span></div>
        <div className="success"><strong>{filterCounts.fixed}</strong><span>已修复</span></div>
        <div className="danger"><strong>{filterCounts.unable}</strong><span>无法完成</span></div>
      </div>

      {(workspace?.execution_blockers || []).length > 0 && (
        <section className="verification-blockers">
          <div className="verification-section-heading"><span><WarningOutlined /> 前序检测未完成</span><em>{workspace.execution_blockers.length} 项阻断报告</em></div>
          {workspace.execution_blockers.map(item => (
            <Alert
              key={item.task_id}
              type="error"
              showIcon
              message={`${item.phase} · ${item.name}`}
              description={item.error}
            />
          ))}
        </section>
      )}

      {activeRuns.length > 0 && (
        <section className="verification-runs">
          <div className="verification-section-heading"><span><SafetyCertificateOutlined /> 正在执行</span><em>{activeRuns.length} 个运行</em></div>
          {activeRuns.map(run => (
            <article className="verification-run-card" key={run.id}>
              <div className="verification-run">
                <Spin size="small" />
                <div><strong>{run.source_type === 'document' ? '文档重新分析' : '技术重新检测'} #{run.id}</strong><span>{run.status === 'queued' ? '等待 Worker 接收' : `正在处理 ${run.summary?.completed || 0}/${run.summary?.total || run.items.length}`}</span></div>
                <Button size="small" type="text" danger icon={<StopOutlined />} loading={busy === `run-${run.id}`} onClick={() => stopRun(run)}>停止</Button>
              </div>
              <RunItems run={run} />
            </article>
          ))}
        </section>
      )}

      <section className="verification-groups">
        <div className="verification-section-heading"><span><FileTextOutlined /> 问题处理与重新检查</span><em>{filteredGroups.length} 组</em></div>
        <div className="verification-filter"><Segmented options={filterOptions} value={activeFilter} onChange={setFilter} /></div>
        <div className="verification-group-list">
        {filteredGroups.length ? filteredGroups.map(group => {
          const document = 'task_id' in group
          const displayFindings = group.displayFindings
          const open = displayFindings.filter(item => item.status === 'open').length
          const fixed = group.findings.filter(item => item.status === 'fixed').length
          const falsePositive = group.findings.filter(item => item.status === 'false_positive').length
          const analysisUnable = group.findings.some(item => item.status === 'open' && item.judgment === 'not_tested')
          const groupState = activeFilter === 'open'
            ? { color: 'warning', text: `待处理 ${displayFindings.length}` }
            : activeFilter === 'fixed'
              ? { color: 'success', text: `已修复 ${displayFindings.length}` }
              : activeFilter === 'unable'
                ? { color: 'error', text: `无法完成 ${displayFindings.length}` }
                : open
                  ? { color: analysisUnable ? 'error' : 'warning', text: analysisUnable ? (document ? '需重新分析' : '需重新检测') : `待处理 ${open}` }
                  : fixed === group.findings.length
                    ? { color: 'success', text: '已修复' }
                    : falsePositive === group.findings.length
                        ? { color: 'default', text: '已确认误报' }
                        : { color: 'processing', text: '已完成处置' }
          const isExpanded = expanded[group.key]
          const countCopy = activeFilter === 'all'
            ? `${group.findings.length} 项`
            : `显示 ${displayFindings.length} / 共 ${group.findings.length} 项`
          return (
            <article className={`verification-group ${document ? 'document' : 'technical'}`} key={group.key}>
              <button className="verification-group-head" type="button" onClick={() => setExpanded(value => ({ ...value, [group.key]: !value[group.key] }))}>
                <span>{document ? <FileTextOutlined /> : <SafetyCertificateOutlined />}</span>
                <div><strong>{group.title || group.target}</strong><p>{document ? `文档检查 · ${countCopy}` : `${group.target || '-'} · ${capabilityCopy[group.capability] || group.capability || '-'} · ${countCopy}`}</p></div>
                <Tag color={groupState.color}>{groupState.text}</Tag>
              </button>
              {isExpanded && (
                <div className="verification-group-body">
                  {open > 0 && (
                    <div className="verification-group-action">
                      {document ? (
                        <>
                          <Button type="primary" icon={<UploadOutlined />} onClick={() => openGroupAction(group)}>上传改进文档并重新检查</Button>
                          {analysisUnable && <Button icon={<ReloadOutlined />} loading={busy === `reanalyze-${group.key}`} onClick={() => reanalyzeDocument(group)}>重新分析现有材料</Button>}
                        </>
                      ) : (
                        <Button type="primary" icon={<ReloadOutlined />} onClick={() => openGroupAction(group)}>重新执行该项检测</Button>
                      )}
                    </div>
                  )}
                  {displayFindings.map(finding => (
                    <FindingRow key={finding.id} finding={finding} />
                  ))}
                </div>
              )}
            </article>
          )
        }) : (
          <div className="verification-empty"><CheckCircleFilled /><strong>该状态下没有问题</strong><span>可切换其他状态查看完整处置记录。</span></div>
        )}
        </div>
      </section>

      {onContinue && (
        <section className="verification-report-next">
          <div>
            <strong>以当前结果生成报告</strong>
            <p>报告将如实保留 {filterCounts.open} 项待处理和 {filterCounts.unable} 项无法验证，不会将它们标记为合规。</p>
          </div>
          <Button
            type="primary"
            loading={busy === 'continue-report'}
            disabled={activeRuns.length > 0}
            onClick={continueToReport}
          >
            {activeRuns.length ? '等待重新检查完成' : '继续生成报告'}
          </Button>
        </section>
      )}

      {terminalRuns.length > 0 && (
        <section className="verification-history-summary">
          <HistoryOutlined />
          <div>
            <strong>最近复测：{latestTerminalRun.source_type === 'document' ? '文档重新检查' : '技术重新检测'} #{latestTerminalRun.id}</strong>
            <span>已修复 {latestTerminalRun.summary?.fixed || 0} · 仍存在 {latestTerminalRun.summary?.still_present || 0} · 无法验证 {latestTerminalRun.summary?.unable || 0}</span>
          </div>
          <Button size="small" onClick={() => setHistoryVisible(true)}>查看全部 {terminalRuns.length} 次</Button>
        </section>
      )}

      <Modal
        title="复测记录"
        open={historyVisible}
        onCancel={() => setHistoryVisible(false)}
        footer={null}
        width={820}
        className="verification-history-modal"
      >
        <div className="verification-history-list">
          {terminalRuns.map(run => (
            <article className="verification-run-card" key={run.id}>
              <button className="verification-run verification-run-toggle" type="button" onClick={() => setExpandedRuns(value => ({ ...value, [run.id]: !value[run.id] }))}>
                {run.status === 'completed' ? <CheckCircleFilled /> : <WarningOutlined />}
                <div>
                  <strong>{run.source_type === 'document' ? '文档重新检查' : '技术重新检测'} #{run.id} · {run.status === 'completed' ? '已完成' : run.status === 'partial' ? '部分完成' : run.status === 'cancelled' ? '已停止' : '失败'}</strong>
                  <span>已修复 {run.summary?.fixed || 0} · 仍存在 {run.summary?.still_present || 0} · 新增 {run.summary?.new || 0} · 无法验证 {run.summary?.unable || 0}</span>
                </div>
                <span>{expandedRuns[run.id] ? '收起明细' : '展开明细'}</span>
              </button>
              {expandedRuns[run.id] && <RunItems run={run} />}
              {['partial', 'failed', 'cancelled'].includes(run.status) && <div className="verification-run-retry"><Button size="small" icon={<ReloadOutlined />} loading={busy === `run-${run.id}`} onClick={() => resumeRun(run)}>继续未完成项</Button></div>}
            </article>
          ))}
        </div>
      </Modal>

      <Modal title={`上传整改后的文档${documentModal?.title ? ` · ${documentModal.title}` : ''}`} open={Boolean(documentModal)} onCancel={() => { setDocumentModal(null); setReplaceFileIds([]) }} onOk={submitDocument} confirmLoading={busy?.startsWith('document-')} okText="开始重新判断" cancelText="取消">
        <p className="verification-modal-copy">系统将重新检查该类文档的全部检查点，并自动生成整改前后对比。</p>
        {(documentModal?.files || []).length > 0 && (
          <div className="verification-replace-files">
            <strong>本次替换的现有材料</strong>
            <Checkbox.Group
              value={replaceFileIds}
              onChange={values => setReplaceFileIds(values)}
              options={documentModal.files.map(file => ({ label: file.file_name, value: file.id }))}
            />
            <span>{replaceFileIds.length ? '已勾选的旧版本会停用并保留审计记录。' : '未勾选旧材料，本次文件将作为补充材料加入。'}</span>
          </div>
        )}
        <Upload.Dragger multiple beforeUpload={() => false} fileList={files} onChange={({ fileList }) => setFiles(fileList)}>
          <UploadOutlined /><p>选择改进后的 DOCX、PDF、文本或图片</p>
        </Upload.Dragger>
        <TextArea rows={3} value={notes} onChange={event => setNotes(event.target.value)} placeholder="本次修改说明（可选）" />
      </Modal>

      <Modal title="重新执行技术检测" open={Boolean(technicalModal)} onCancel={() => setTechnicalModal(null)} onOk={submitTechnical} confirmLoading={busy?.startsWith('technical-')} okText="开始检测">
        <p className="verification-modal-copy">资产：{technicalModal?.target || '-'} · 工具：{capabilityCopy[technicalModal?.capability] || technicalModal?.capability || '-'}</p>
        {['baseline_check', 'scan_weak_passwords'].includes(technicalModal?.capability) && (
          <div className="verification-credentials">
            <Input value={username} onChange={event => setUsername(event.target.value)} placeholder="用户名" />
            <Input.Password value={password} onChange={event => setPassword(event.target.value)} placeholder="密码" />
          </div>
        )}
        <TextArea rows={3} value={notes} onChange={event => setNotes(event.target.value)} placeholder="本次整改说明（可选）" />
      </Modal>

    </div>
  )
}

export default VerificationWorkspace
