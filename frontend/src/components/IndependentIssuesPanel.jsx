import { useEffect, useMemo, useState } from 'react'
import { Button, Tag, Tooltip, message } from 'antd'
import {
  AimOutlined,
  CheckCircleOutlined,
  FileAddOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { severityLabel } from './resultRendererUtils'

const statusLabel = { open: '待处理', fixed: '已修复', false_positive: '误报' }

function IndependentIssuesPanel({ project, initialFindingId, onSummary }) {
  const [payload, setPayload] = useState({ summary: {}, items: [] })
  const [filter, setFilter] = useState(initialFindingId ? 'all' : 'open')
  const [loading, setLoading] = useState(true)
  const [actionKey, setActionKey] = useState('')

  const refresh = async ({ quiet = false } = {}) => {
    if (!project?.id) return
    if (!quiet) setLoading(true)
    try {
      const response = await api.get(`/projects/${project.id}/issues/independent`)
      setPayload(response.data || { summary: {}, items: [] })
    } catch (error) {
      if (!quiet) message.error(error.response?.data?.detail || '独立检测问题读取失败')
    } finally {
      if (!quiet) setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    const timer = window.setInterval(() => refresh({ quiet: true }), 8000)
    return () => window.clearInterval(timer)
  }, [project?.id])

  useEffect(() => {
    onSummary?.({
      total: payload.summary?.total || 0,
      open: payload.summary?.open || 0,
      fixed: payload.summary?.fixed || 0,
      criticalHigh: payload.summary?.critical_high || 0,
    })
  }, [payload.summary?.total, payload.summary?.open, payload.summary?.fixed, payload.summary?.critical_high, onSummary])

  const assessmentCodes = useMemo(() => new Set(
    (project?.assessment_types || []).map(item => item.assessment_type?.code).filter(Boolean)
  ), [project?.assessment_types])
  const items = filter === 'all' ? payload.items || [] : (payload.items || []).filter(item => item.status === filter)

  const retest = async item => {
    if (!item.asset?.id || !item.source_key) return
    setActionKey(`retest-${item.id}`)
    try {
      await api.post(`/projects/${project.id}/scans/`, {
        task_type: 'targeted',
        asset_id: item.asset.id,
        parameters: { capability: item.source_key },
      })
      message.success(`已开始复测 ${item.asset.value} · ${item.tool_label}`)
    } catch (error) {
      message.error(error.response?.data?.detail || '复测任务创建失败')
    } finally {
      setActionKey('')
    }
  }

  const promote = async (item, assessmentCode) => {
    setActionKey(`promote-${item.id}-${assessmentCode}`)
    try {
      const response = await api.post(`/projects/${project.id}/issues/${item.id}/promote`, {
        assessment_code: assessmentCode,
      })
      message.success(response.data?.status === 'exists' ? '该问题已在本轮测评中' : `已纳入${assessmentCode === 'miping' ? '密评' : '等保'}问题闭环`)
    } catch (error) {
      message.error(error.response?.data?.detail || '纳入测评失败')
    } finally {
      setActionKey('')
    }
  }

  return (
    <div className="independent-issues-panel">
      <div className="independent-summary">
        <div><strong>{payload.summary?.total || 0}</strong><span>全部问题</span></div>
        <div className="open"><strong>{payload.summary?.open || 0}</strong><span>待处理</span></div>
        <div className="danger"><strong>{payload.summary?.critical_high || 0}</strong><span>严重 / 高危</span></div>
        <div className="fixed"><strong>{payload.summary?.fixed || 0}</strong><span>已修复</span></div>
      </div>

      <div className="independent-filter-bar">
        {[
          ['all', '全部', payload.summary?.total || 0],
          ['open', '待处理', payload.summary?.open || 0],
          ['fixed', '已修复', payload.summary?.fixed || 0],
        ].map(([key, label, count]) => (
          <button key={key} type="button" className={filter === key ? 'active' : ''} onClick={() => setFilter(key)}>
            {label}<span>{count}</span>
          </button>
        ))}
        <Tooltip title="刷新问题状态">
          <Button type="text" size="small" icon={<ReloadOutlined spin={loading} />} onClick={() => refresh()} aria-label="刷新独立检测问题" />
        </Tooltip>
      </div>

      <div className="independent-issue-list">
        {items.length ? items.map(item => (
          <article key={item.id} className={`independent-issue-card ${item.severity} ${Number(initialFindingId) === item.id ? 'focused' : ''}`}>
            <div className="independent-issue-head">
              <span className="independent-asset"><AimOutlined /><strong>{item.asset?.value || '项目级问题'}</strong></span>
              <div>
                <Tag color={['critical', 'high'].includes(item.severity) ? 'red' : item.severity === 'medium' ? 'gold' : 'blue'}>{severityLabel(item.severity)}</Tag>
                <Tag color={item.status === 'fixed' ? 'green' : 'orange'}>{statusLabel[item.status] || item.status}</Tag>
              </div>
            </div>
            <h3>{item.title}</h3>
            <p>{item.description}</p>
            <dl>
              <div><dt>资产名称</dt><dd>{item.asset?.name || '未设置'}</dd></div>
              <div><dt>检测来源</dt><dd>{item.source_label} · {item.tool_label}</dd></div>
              <div><dt>出现次数</dt><dd>{item.occurrence_count || 1} 次</dd></div>
              <div><dt>最近发现</dt><dd>{item.last_seen_at ? new Date(item.last_seen_at).toLocaleString('zh-CN') : '-'}</dd></div>
            </dl>
            <div className="independent-remediation">
              <span>建议</span>
              <p>{item.remediation_suggestion || '确认业务必要性，修复后重新执行同一检测。'}</p>
            </div>
            <div className="independent-issue-actions">
              <Button
                size="small"
                icon={item.status === 'fixed' ? <CheckCircleOutlined /> : <ReloadOutlined />}
                disabled={!item.asset?.id || !item.source_key}
                loading={actionKey === `retest-${item.id}`}
                onClick={() => retest(item)}
              >重新检测</Button>
              {assessmentCodes.has('dengbao') && <Button size="small" type="text" icon={<SafetyCertificateOutlined />} loading={actionKey === `promote-${item.id}-dengbao`} onClick={() => promote(item, 'dengbao')}>纳入等保</Button>}
              {assessmentCodes.has('miping') && <Button size="small" type="text" icon={<FileAddOutlined />} loading={actionKey === `promote-${item.id}-miping`} onClick={() => promote(item, 'miping')}>纳入密评</Button>}
            </div>
          </article>
        )) : (
          <div className="independent-empty">
            <CheckCircleOutlined />
            <strong>{loading ? '正在读取独立检测问题' : filter === 'open' ? '当前没有待处理问题' : '当前筛选条件下暂无记录'}</strong>
            <span>对话、快捷指令或定时检测发现的真实问题会按资产自动归并到这里。</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default IndependentIssuesPanel
