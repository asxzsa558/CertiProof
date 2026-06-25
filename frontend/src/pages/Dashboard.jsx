import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Spin, Tag, Tooltip, Progress, Empty } from 'antd'
import {
  ProjectOutlined,
  SafetyCertificateOutlined,
  AlertOutlined,
  RocketOutlined,
  CloudServerOutlined,
  TeamOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  FireOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import VeriSureLogo from '../components/VeriSureLogo'
import './Dashboard.css'

const SEVERITY_COLORS = {
  critical: '#ff4d4f',
  high: '#fa8c16',
  medium: '#fadb14',
  low: '#52c41a',
  info: '#1890ff',
}

const STATUS_COLORS = {
  active: '#52c41a',
  pending: '#faad14',
  running: '#1890ff',
  completed: '#52c41a',
  failed: '#ff4d4f',
  archived: '#8c8c8c',
  open: '#ff4d4f',
  resolved: '#52c41a',
  in_progress: '#1890ff',
}

function StatCard({ icon, label, value, sub, color, accent }) {
  return (
    <div className="dash-stat-card" style={{ '--accent': accent || color }}>
      <div className="dash-stat-icon" style={{ color }}>{icon}</div>
      <div className="dash-stat-body">
        <div className="dash-stat-label">{label}</div>
        <div className="dash-stat-value">{value}</div>
        {sub && <div className="dash-stat-sub">{sub}</div>}
      </div>
    </div>
  )
}

function GaugeRing({ percent, color, label, size = 140 }) {
  const r = (size - 16) / 2
  const c = 2 * Math.PI * r
  const offset = c - (Math.min(100, Math.max(0, percent)) / 100) * c
  return (
    <div className="dash-gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <defs>
          <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={color} stopOpacity="0.9" />
            <stop offset="100%" stopColor={color} stopOpacity="0.4" />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="url(#gaugeGrad)"
          strokeWidth="8"
          strokeDasharray={c}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="dash-gauge-center">
        <div className="dash-gauge-value">{Math.round(percent)}%</div>
        <div className="dash-gauge-label">{label}</div>
      </div>
    </div>
  )
}

function BarRow({ section, total, passed, failed, passRate }) {
  return (
    <div className="dash-bar-row">
      <div className="dash-bar-section">{section}</div>
      <div className="dash-bar-track">
        <div
          className="dash-bar-fill"
          style={{
            width: `${passRate}%`,
            background: `linear-gradient(90deg, #52c41a, #95de64)`,
          }}
        />
        <div
          className="dash-bar-fail"
          style={{
            width: `${100 - passRate}%`,
            left: `${passRate}%`,
            background: `linear-gradient(90deg, #ff4d4f, #ff7875)`,
          }}
        />
      </div>
      <div className="dash-bar-numbers">
        <span style={{ color: '#52c41a' }}>{passed}</span>
        <span style={{ color: '#666' }}>/</span>
        <span style={{ color: '#ff4d4f' }}>{failed}</span>
        <span className="dash-bar-rate">{passRate.toFixed(0)}%</span>
      </div>
    </div>
  )
}

function RiskBar({ label, count, color, total }) {
  const pct = total > 0 ? (count / total) * 100 : 0
  return (
    <div className="dash-risk-row">
      <div className="dash-risk-label">{label}</div>
      <div className="dash-risk-track">
        <div
          className="dash-risk-fill"
          style={{ width: `${pct}%`, background: color, boxShadow: `0 0 12px ${color}40` }}
        />
      </div>
      <div className="dash-risk-count" style={{ color }}>{count}</div>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.get('/dashboard/overview')
      setData(res.data)
    } catch (err) {
      console.error('Dashboard load error:', err)
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    const t = setInterval(loadData, 60000)
    return () => clearInterval(t)
  }, [])

  if (loading && !data) {
    return (
      <div className="dash-loading">
        <Spin size="large" />
        <div className="dash-loading-text">加载态势数据...</div>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="dash-error">
        <Empty description={error} />
        <button className="dash-retry-btn" onClick={loadData}>
          <ReloadOutlined /> 重试
        </button>
      </div>
    )
  }

  if (!data) return null

  const { overview, compliance, risk, progress, assets, users, generated_at } = data
  const totalRisk = risk.critical + risk.high + risk.medium + risk.low + risk.info
  const totalUsers = users.total_users || 1

  return (
    <div className="dash-root">
      <div className="dash-bg-grid" />
      <div className="dash-bg-glow" />

      <header className="dash-header">
        <div className="dash-header-left">
          <VeriSureLogo size={36} />
          <div>
            <div className="dash-title">态势总览</div>
            <div className="dash-subtitle">等保测评合规态势 · 实时监控</div>
          </div>
        </div>
        <div className="dash-header-right">
          <div className="dash-updated">
            <ClockCircleOutlined /> 最后更新：{new Date(generated_at).toLocaleString('zh-CN')}
          </div>
          <button className="dash-icon-btn" onClick={loadData} title="刷新">
            <ReloadOutlined spin={loading} />
          </button>
        </div>
      </header>

      <section className="dash-section">
        <div className="dash-section-header">
          <ProjectOutlined className="dash-section-icon" />
          <span>项目总览</span>
        </div>
        <div className="dash-stats-grid">
          <StatCard
            icon={<ProjectOutlined />}
            label="项目总数"
            value={overview.total}
            sub={<><ArrowUpOutlined /> 7 天新增 {overview.recent_7d}</>}
            color="#6366f1"
            accent="rgba(99,102,241,0.3)"
          />
          <StatCard
            icon={<SafetyCertificateOutlined />}
            label="进行中"
            value={overview.active}
            sub={`已归档 ${overview.archived}`}
            color="#52c41a"
            accent="rgba(82,196,26,0.3)"
          />
          <StatCard
            icon={<RocketOutlined />}
            label="二级项目"
            value={overview.level2_count}
            sub={`三级项目 ${overview.level3_count}`}
            color="#fa8c16"
            accent="rgba(250,140,22,0.3)"
          />
          <StatCard
            icon={<SafetyCertificateOutlined />}
            label="平均合规分"
            value={overview.avg_score ? overview.avg_score.toFixed(1) : '-'}
            sub="满分 100"
            color="#722ed1"
            accent="rgba(114,46,209,0.3)"
          />
        </div>
      </section>

      <section className="dash-section dash-row-2">
        <div className="dash-card dash-compliance">
          <div className="dash-card-header">
            <SafetyCertificateOutlined className="dash-card-icon" style={{ color: '#52c41a' }} />
            <span>合规态势</span>
            <Tag color="green" style={{ marginLeft: 'auto' }}>实时</Tag>
          </div>
          <div className="dash-card-body dash-compliance-body">
            <GaugeRing percent={compliance.pass_rate} color="#52c41a" label="通过率" />
            <GaugeRing percent={compliance.score} color="#1890ff" label="综合得分" size={120} />
            <div className="dash-compliance-meta">
              <div className="dash-meta-row">
                <span className="dash-meta-label">已测条款</span>
                <span className="dash-meta-value">{compliance.tested}</span>
              </div>
              <div className="dash-meta-row">
                <span className="dash-meta-label">未测条款</span>
                <span className="dash-meta-value">{compliance.not_tested}</span>
              </div>
              <div className="dash-meta-row">
                <span className="dash-meta-label">部分符合</span>
                <span className="dash-meta-value" style={{ color: '#faad14' }}>{compliance.partial}</span>
              </div>
              <div className="dash-meta-row">
                <span className="dash-meta-label">形式符合</span>
                <span className="dash-meta-value" style={{ color: '#1890ff' }}>{compliance.paper_compliant}</span>
              </div>
            </div>
          </div>
          <div className="dash-card-footer">
            <div className="dash-bars">
              {compliance.by_pillar.length === 0 ? (
                <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                compliance.by_pillar.map((p) => (
                  <BarRow key={p.section} {...p} />
                ))
              )}
            </div>
          </div>
        </div>

        <div className="dash-card dash-risk">
          <div className="dash-card-header">
            <AlertOutlined className="dash-card-icon" style={{ color: '#ff4d4f' }} />
            <span>风险地图</span>
            <Tag color="red" style={{ marginLeft: 'auto' }}>{totalRisk} 项</Tag>
          </div>
          <div className="dash-card-body">
            <div className="dash-risk-list">
              <RiskBar label="严重" count={risk.critical} color={SEVERITY_COLORS.critical} total={totalRisk} />
              <RiskBar label="高危" count={risk.high} color={SEVERITY_COLORS.high} total={totalRisk} />
              <RiskBar label="中危" count={risk.medium} color={SEVERITY_COLORS.medium} total={totalRisk} />
              <RiskBar label="低危" count={risk.low} color={SEVERITY_COLORS.low} total={totalRisk} />
              <RiskBar label="提示" count={risk.info} color={SEVERITY_COLORS.info} total={totalRisk} />
            </div>
            <div className="dash-divider" />
            <div className="dash-risk-status">
              <Tooltip title="待处理">
                <div className="dash-status-chip" style={{ borderColor: STATUS_COLORS.open }}>
                  <CloseCircleOutlined style={{ color: STATUS_COLORS.open }} />
                  <span>{risk.open}</span>
                  <em>待处理</em>
                </div>
              </Tooltip>
              <Tooltip title="处理中">
                <div className="dash-status-chip" style={{ borderColor: STATUS_COLORS.in_progress }}>
                  <ClockCircleOutlined style={{ color: STATUS_COLORS.in_progress }} />
                  <span>{risk.in_progress}</span>
                  <em>进行</em>
                </div>
              </Tooltip>
              <Tooltip title="已解决">
                <div className="dash-status-chip" style={{ borderColor: STATUS_COLORS.resolved }}>
                  <CheckCircleOutlined style={{ color: STATUS_COLORS.resolved }} />
                  <span>{risk.resolved}</span>
                  <em>已解决</em>
                </div>
              </Tooltip>
            </div>
            <div className="dash-divider" />
            <div className="dash-top-clauses">
              <div className="dash-top-title">失分条款 TOP 10</div>
              {risk.top_clauses.length === 0 ? (
                <Empty description="暂无失分条款" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                risk.top_clauses.map((c, i) => (
                  <div className="dash-top-row" key={c.clause_id}>
                    <span className="dash-top-rank" data-rank={i + 1}>{i + 1}</span>
                    <span className="dash-top-id">{c.clause_id}</span>
                    <Tooltip title={c.name}>
                      <span className="dash-top-name">{c.name}</span>
                    </Tooltip>
                    <Tag color="red">{c.count}</Tag>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="dash-section dash-row-3">
        <div className="dash-card">
          <div className="dash-card-header">
            <RocketOutlined className="dash-card-icon" style={{ color: '#1890ff' }} />
            <span>测评进度</span>
          </div>
          <div className="dash-card-body">
            <div className="dash-progress-grid">
              <div className="dash-progress-cell">
                <div className="dash-progress-label">活跃任务</div>
                <div className="dash-progress-value" style={{ color: '#1890ff' }}>{progress.active_tasks}</div>
                <div className="dash-progress-sub">待 {progress.pending} · 跑 {progress.running}</div>
              </div>
              <div className="dash-progress-cell">
                <div className="dash-progress-label">7 天完成</div>
                <div className="dash-progress-value" style={{ color: '#52c41a' }}>{progress.completed_7d}</div>
                <div className="dash-progress-sub">失败 {progress.failed_7d}</div>
              </div>
              <div className="dash-progress-cell">
                <div className="dash-progress-label">问卷</div>
                <div className="dash-progress-value" style={{ color: '#722ed1' }}>{progress.questionnaires_completed}</div>
                <Progress
                  percent={progress.questionnaires_total ? Math.round(progress.questionnaires_completed / progress.questionnaires_total * 100) : 0}
                  size="small"
                  showInfo={false}
                  strokeColor="#722ed1"
                  trailColor="rgba(255,255,255,0.06)"
                />
                <div className="dash-progress-sub">/{progress.questionnaires_total}</div>
              </div>
              <div className="dash-progress-cell">
                <div className="dash-progress-label">整改</div>
                <div className="dash-progress-value" style={{ color: '#fa8c16' }}>{progress.remediation_completed}</div>
                <Progress
                  percent={progress.remediation_total ? Math.round(progress.remediation_completed / progress.remediation_total * 100) : 0}
                  size="small"
                  showInfo={false}
                  strokeColor="#fa8c16"
                  trailColor="rgba(255,255,255,0.06)"
                />
                <div className="dash-progress-sub">/{progress.remediation_total}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="dash-card">
          <div className="dash-card-header">
            <CloudServerOutlined className="dash-card-icon" style={{ color: '#13c2c2' }} />
            <span>资产态势</span>
          </div>
          <div className="dash-card-body">
            <div className="dash-asset-summary">
              <div className="dash-asset-big">{assets.total}</div>
              <div className="dash-asset-label">资产总数 · 7 天新增 {assets.new_7d}</div>
            </div>
            <div className="dash-asset-types">
              <div className="dash-asset-type">
                <div className="dash-asset-type-label">IP 资产</div>
                <div className="dash-asset-type-value">{assets.by_type.ip || 0}</div>
              </div>
              <div className="dash-asset-type">
                <div className="dash-asset-type-label">域名</div>
                <div className="dash-asset-type-value">{assets.by_type.domain || 0}</div>
              </div>
              <div className="dash-asset-type">
                <div className="dash-asset-type-label">云资源</div>
                <div className="dash-asset-type-value">{assets.by_type.cloud_resource || 0}</div>
              </div>
            </div>
            <div className="dash-divider" />
            <div className="dash-asset-verify">
              <Tooltip title="已验证">
                <div className="dash-status-chip" style={{ borderColor: '#52c41a' }}>
                  <CheckCircleOutlined style={{ color: '#52c41a' }} />
                  <span>{assets.verified}</span>
                  <em>已验证</em>
                </div>
              </Tooltip>
              <Tooltip title="待验证">
                <div className="dash-status-chip" style={{ borderColor: '#faad14' }}>
                  <ClockCircleOutlined style={{ color: '#faad14' }} />
                  <span>{assets.pending}</span>
                  <em>待验证</em>
                </div>
              </Tooltip>
              <Tooltip title="验证失败">
                <div className="dash-status-chip" style={{ borderColor: '#ff4d4f' }}>
                  <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                  <span>{assets.failed}</span>
                  <em>失败</em>
                </div>
              </Tooltip>
            </div>
          </div>
        </div>

        <div className="dash-card">
          <div className="dash-card-header">
            <TeamOutlined className="dash-card-icon" style={{ color: '#eb2f96' }} />
            <span>人员负载</span>
          </div>
          <div className="dash-card-body">
            <div className="dash-user-summary">
              <div className="dash-user-big">{users.total_users}</div>
              <div className="dash-user-label">总用户 · 7 天活跃 {users.active_users_7d}</div>
            </div>
            <div className="dash-divider" />
            <div className="dash-roles">
              {Object.entries(users.by_role).map(([role, count]) => {
                const pct = totalUsers > 0 ? Math.round(count / totalUsers * 100) : 0
                return (
                  <div className="dash-role-row" key={role}>
                    <Tag color={role === 'admin' ? 'red' : role === 'operator' ? 'blue' : role === 'approver' ? 'purple' : 'default'}>
                      {role}
                    </Tag>
                    <div className="dash-role-track">
                      <div className="dash-role-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="dash-role-count">{count}</span>
                  </div>
                )
              })}
            </div>
            <div className="dash-divider" />
            <div className="dash-load-stats">
              <div className="dash-load-stat">
                <FireOutlined style={{ color: '#ff4d4f' }} />
                <span>已分派漏洞</span>
                <strong>{users.assigned_findings}</strong>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}