import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Avatar, Button, Dropdown, Select, Tag, Tooltip, message } from 'antd'
import {
  AlertOutlined,
  ApiOutlined,
  BellOutlined,
  BugOutlined,
  ClusterOutlined,
  CheckCircleFilled,
  CloudServerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  GlobalOutlined,
  KeyOutlined,
  LockOutlined,
  LogoutOutlined,
  ProjectOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import ExposureTopology from '../components/ExposureTopology'
import '../styles/theme.css'
import './Dashboard.css'

const NAV_ITEMS = [
  { key: 'overview', group: '组织态势', label: '全局 Dashboard', icon: <DashboardOutlined />, path: '/dashboard' },
  { key: 'projects', group: '项目执行', label: '项目工作台', icon: <ProjectOutlined />, path: '/projects', permission: 'project:read' },
  { key: 'assets', group: '项目执行', label: '资产矩阵', icon: <DatabaseOutlined />, path: '/projects?view=assets', permission: 'asset:read' },
  { key: 'assessment', group: '测评中心', label: '等保测评', icon: <SafetyCertificateOutlined />, path: '/projects', permission: 'assessment:read' },
  { key: 'password-assessment', group: '测评中心', label: '密码测评', icon: <LockOutlined />, path: '/projects?assessment=miping', permission: 'assessment:read' },
  { key: 'reports', group: '治理中心', label: '报告中心', icon: <FileTextOutlined />, path: '/reports', permission: 'report:read' },
  { key: 'operations', group: '治理中心', label: '运行与告警', icon: <AlertOutlined />, path: '/operations', permission: 'tool:diagnose' },
  { key: 'scan-nodes', group: '治理中心', label: '扫描节点', icon: <CloudServerOutlined />, path: '/settings/scan-nodes', permission: 'node:read' },
  { key: 'access', group: '治理中心', label: '角色权限', icon: <TeamOutlined />, path: '/settings/access', permission: 'role:read' },
  { key: 'data', group: '系统', label: '数据与生命周期', icon: <DatabaseOutlined />, path: '/settings/data-lifecycle', permission: 'system:config' },
  { key: 'settings', group: '系统', label: '系统设置', icon: <SettingOutlined />, path: '/settings/models', permission: 'system:config' },
]

const statusLabel = {
  open: '待确认',
  in_progress: '处理中',
  fixed: '已修复',
  verified: '已验证',
  closed: '已关闭',
  skipped: '已跳过',
  false_positive: '误报',
}

const closedRiskStatuses = new Set(['fixed', 'verified', 'closed', 'skipped', 'false_positive'])

const severityLabel = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '提示',
}

const toolIconFor = (name = '') => {
  if (name.includes('端口')) return <ApiOutlined />
  if (name.includes('漏洞')) return <BugOutlined />
  if (name.includes('弱口令')) return <KeyOutlined />
  if (name.includes('Web')) return <GlobalOutlined />
  if (name.includes('数据库')) return <DatabaseOutlined />
  if (name.includes('网络')) return <ClusterOutlined />
  if (name.includes('Windows')) return <CloudServerOutlined />
  if (name.includes('SSH')) return <LockOutlined />
  if (name.includes('OCR')) return <FileTextOutlined />
  return <ToolOutlined />
}

function emptyDashboard() {
  return {
    summary: {
      project_count: 0,
      asset_count: 0,
      high_risk_count: 0,
      unknown_count: 0,
      average_progress: 0,
      todo_count: 0,
    },
    current_role: { base_role: 'viewer', permission_scope: '受限权限' },
    project_matrix: [],
    exposure_topology: { nodes: [], edges: [], top_risky_assets: [] },
    tool_health: [],
    risk_queue: [],
    rbac: { roles: [], members: [], audits: [] },
  }
}

const emptyOperations = {
  overall_status: 'unknown', services: {}, workers: {}, alerts: [],
  scan_tasks: { by_status: {}, stale_leases: 0 },
}

function errorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : error?.message || fallback
}

function Dashboard() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const setCurrentOrg = useAuthStore((state) => state.setCurrentOrg)
  const [dashboard, setDashboard] = useState(emptyDashboard())
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [selectedToolIndex, setSelectedToolIndex] = useState(0)
  const [riskFilter, setRiskFilter] = useState('all')
  const [riskActionId, setRiskActionId] = useState(null)
  const [operations, setOperations] = useState(emptyOperations)
  const [operationsState, setOperationsState] = useState('loading')

  const currentOrg = useMemo(
    () => organizations.find((org) => org.id === currentOrgId) || organizations[0],
    [organizations, currentOrgId]
  )

  const currentPermissions = dashboard.current_role?.permissions || []
  const permissionScope = dashboard.current_role?.permission_scope || (currentOrg?.role === 'admin' ? '全局权限' : '受限权限')
  const canManageAssessments = currentPermissions.includes('assessment:manage') || currentOrg?.role === 'admin'
  const canViewOperations = currentPermissions.includes('tool:diagnose') || currentOrg?.role === 'admin'
  const visibleNavItems = NAV_ITEMS.filter((item) => (
    !item.permission || currentOrg?.role === 'admin' || currentPermissions.includes(item.permission)
  ))

  const fetchDashboard = async ({ silent = false } = {}) => {
    if (!currentOrg?.id) return
    setLoading(true)
    try {
      const response = await api.get('/dashboard/organization-command', {
        params: { organization_id: currentOrg.id },
      })
      setDashboard({ ...emptyDashboard(), ...response.data })
      const responsePermissions = response.data?.current_role?.permissions || []
      if (currentOrg?.role === 'admin' || responsePermissions.includes('tool:diagnose')) {
        api.get('/diagnostics/operations', {
          params: { organization_id: currentOrg.id, hours: 24 },
        }).then((operationsResponse) => {
          setOperations({ ...emptyOperations, ...operationsResponse.data })
          setOperationsState('ready')
        }).catch(() => setOperationsState('error'))
      } else {
        setOperations(emptyOperations)
        setOperationsState('ready')
      }
      setLoadError('')
    } catch (error) {
      setOperationsState('error')
      const detail = errorMessage(error, '组织态势数据暂时不可用')
      setLoadError(detail)
      if (!silent) message.error(detail)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setOperations(emptyOperations)
    setOperationsState('loading')
    fetchDashboard()
    const refreshTimer = window.setInterval(() => fetchDashboard({ silent: true }), 45000)
    return () => window.clearInterval(refreshTimer)
  }, [currentOrg?.id])

  const handleRiskAction = (risk) => {
    if (!risk.project_id) return
    navigate(`/projects/${risk.project_id}`)
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const summary = dashboard.summary || emptyDashboard().summary
  const topology = dashboard.exposure_topology || emptyDashboard().exposure_topology
  const selectedTool = dashboard.tool_health[selectedToolIndex] || dashboard.tool_health[0]
  const riskFilters = [
    { key: 'all', label: '全部', count: dashboard.risk_queue.length },
    { key: 'open', label: '待确认', count: dashboard.risk_queue.filter((risk) => risk.status === 'open').length },
    { key: 'in_progress', label: '处理中', count: dashboard.risk_queue.filter((risk) => risk.status === 'in_progress').length },
    { key: 'closed', label: '已处置', count: dashboard.risk_queue.filter((risk) => closedRiskStatuses.has(risk.status)).length },
  ]
  const filteredRisks = riskFilter === 'all'
    ? dashboard.risk_queue
    : riskFilter === 'closed'
      ? dashboard.risk_queue.filter((risk) => closedRiskStatuses.has(risk.status))
      : dashboard.risk_queue.filter((risk) => risk.status === riskFilter)
  const operationComponents = [
    ...Object.values(operations.services || {}),
    ...Object.values(operations.workers || {}),
  ]
  const operationHealthy = operationComponents.filter((item) => item.status === 'healthy').length
  const operationIssues = operationComponents.length - operationHealthy
  const operationRunning = (operations.scan_tasks?.by_status?.running || 0) + (operations.scan_tasks?.by_status?.pending || 0)
  const userMenu = {
    items: [
      { key: 'profile', icon: <UserOutlined />, label: user?.username || '账户' },
      { type: 'divider' },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true, onClick: handleLogout },
    ],
  }

  return (
    <div className="org-dashboard">
      <aside className="org-sidebar">
        <div className="org-brand">
          <div className="org-brand-mark"><VeriSureLogo size={46} /></div>
          <div>
            <span>CertiProof</span>
            <em>安全合规运营</em>
          </div>
        </div>
        <nav className="org-nav">
          {Object.entries(visibleNavItems.reduce((groups, item) => {
            groups[item.group] = [...(groups[item.group] || []), item]
            return groups
          }, {})).map(([group, items]) => (
            <div className="org-nav-group" key={group}>
              <em>{group}</em>
              {items.map((item) => (
                <button
                  key={item.key}
                  className={`${item.key === 'overview' ? 'active' : ''}${item.upcoming ? ' upcoming' : ''}`}
                  onClick={() => {
                    if (item.upcoming) {
                      message.info('下个版本更新，暂未开启')
                      return
                    }
                    navigate(item.path)
                  }}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <main className="org-main">
        <header className="org-topbar">
          <div className="org-title-block">
            <span>组织工作空间</span>
            <h1>组织安全合规态势</h1>
            <p>按项目推进等保测评、资产暴露面、工具链与权限治理。</p>
          </div>
          <div className="org-top-actions">
            <Select
              value={currentOrg?.id}
              onChange={setCurrentOrg}
              options={organizations.map((org) => ({ value: org.id, label: org.name }))}
              className="org-select"
            />
            <Tag color="cyan">{currentOrg?.role === 'admin' ? '管理员' : currentOrg?.role || '成员'}</Tag>
            <Tag color={permissionScope === '全局权限' ? 'green' : 'gold'}>{permissionScope}</Tag>
            <span className={`sync-state ${loading ? 'is-syncing' : ''}`}><i />{loading ? '同步中' : '已同步'}</span>
            <Button className="org-refresh" type="text" icon={<ReloadOutlined spin={loading} />} onClick={() => fetchDashboard()}>
              刷新
            </Button>
            <Tooltip title="通知">
              <Button type="text" icon={<BellOutlined />} aria-label="通知" />
            </Tooltip>
            <Dropdown menu={userMenu} placement="bottomRight">
              <Avatar className="org-avatar" icon={<UserOutlined />} />
            </Dropdown>
          </div>
        </header>

        {loadError ? (
          <div className="dashboard-load-error" role="status">
            <AlertOutlined />
            <span>数据同步暂不可用：{loadError}</span>
            <Button size="small" type="text" onClick={() => fetchDashboard()}>重新连接</Button>
          </div>
        ) : null}

        <section className="org-kpis">
          <Kpi label="项目" value={summary.project_count} icon={<ProjectOutlined />} />
          <Kpi label="资产" value={summary.asset_count} icon={<DatabaseOutlined />} />
          <Kpi label="高风险" value={summary.high_risk_count} icon={<AlertOutlined />} tone="danger" />
          <Kpi label="平均测评进度" value={`${summary.average_progress}%`} icon={<SafetyCertificateOutlined />} />
          <Kpi label="待处理事项" value={summary.todo_count} icon={<CheckCircleFilled />} tone="warning" />
        </section>

        <section className="org-grid">
          <Panel className="project-matrix-panel" title="项目测评进度矩阵" meta={loading ? '同步中' : `${dashboard.project_matrix.length} 个项目`}>
            <div className="project-matrix">
              <div className="matrix-header">
                <span>项目与等级</span>
                <span>当前阶段</span>
                <span>测评进度</span>
                <span className="numeric">风险</span>
                <span className="numeric">任务完成</span>
                <span>负责人</span>
                <span>项目操作</span>
              </div>
              {dashboard.project_matrix.length ? dashboard.project_matrix.map((project) => (
                <div key={project.project_id} className="matrix-row">
                  <div className="matrix-project">
                    <strong>{project.name}</strong>
                    <Tag color={project.level === '三级' ? 'blue' : 'cyan'}>{project.level}</Tag>
                  </div>
                  <span className="matrix-stage">{project.stage}</span>
                  <div className="matrix-progress-cell">
                    <div className="mini-progress"><b style={{ width: `${project.progress}%` }} /></div>
                    <em>{project.progress}%</em>
                  </div>
                  <span className={project.risk_count ? 'risk-count hot' : 'risk-count'}>{project.risk_count}</span>
                  <span className="matrix-task-count">{project.task_done || 0}/{project.task_total || 0}</span>
                  <span>{project.owner}</span>
                  <Button size="small" type="text" onClick={() => navigate(`/projects/${project.project_id}`)}>{project.next_action}</Button>
                </div>
              )) : (
                <div className="empty-panel">暂无项目。创建项目后，这里会按项目展示测评阶段、风险和任务完成情况。</div>
              )}
            </div>
          </Panel>

          <section className="topology-workspace">
            <Panel className="topology-panel" bare>
              <ExposureTopology topology={topology} />
            </Panel>

            <div className="ops-column">
            <Panel className="ops-tools-panel" title="工具遥测" meta={selectedTool ? `${dashboard.tool_health.length} 个工具` : '暂无数据'}>
              <div className="tool-telemetry-panel">
                <div className="tool-health-grid scroll-region scroll-fade">
                {dashboard.tool_health.map((tool) => (
                  <button
                    type="button"
                    key={tool.name}
                    className={`tool-health ${tool.status} ${selectedTool?.name === tool.name ? 'active' : ''}`}
                    onClick={() => setSelectedToolIndex(dashboard.tool_health.findIndex((item) => item.name === tool.name))}
                  >
                    {toolIconFor(tool.name)}
                    <strong>{tool.name}</strong>
                    <span>{tool.status === 'healthy' ? '链路可用' : tool.status === 'running' ? '执行中' : tool.status === 'idle' ? '暂无记录' : '需要复核'} · {tool.latency}</span>
                  </button>
                ))}
                </div>
                <div className="tool-telemetry-detail">
                  {selectedTool ? (
                    <>
                      <div>
                        <strong>{selectedTool.name}</strong>
                        <Tag color={selectedTool.status === 'healthy' ? 'green' : selectedTool.status === 'running' ? 'blue' : selectedTool.status === 'idle' ? 'default' : 'gold'}>
                          {selectedTool.status === 'healthy' ? '链路正常' : selectedTool.status === 'running' ? '执行中' : selectedTool.status === 'idle' ? '暂无记录' : '需要复核'}
                        </Tag>
                      </div>
                      <p>最近执行：{selectedTool.last_run ? new Date(selectedTool.last_run).toLocaleString() : '暂无运行记录'}</p>
                      <p>失败次数：{selectedTool.failure_count || 0}，响应延迟：{selectedTool.latency}</p>
                      <Button size="small" type="text" onClick={() => navigate('/projects')}>进入工具执行</Button>
                    </>
                  ) : (
                    <div className="empty-panel">暂无工具遥测数据。执行扫描后会显示工具状态、延迟和最近运行记录。</div>
                  )}
                </div>
              </div>
            </Panel>

          <Panel className="ops-alert-summary-panel" title="运行与告警" meta={canViewOperations ? (operationsState === 'loading' ? '正在同步' : '组织级实时状态') : '权限受限'}>
              {canViewOperations ? (
                <div className="ops-alert-summary">
                  <div className="ops-alert-metrics">
                    <span><strong>{operationsState === 'ready' ? `${operationHealthy}/${operationComponents.length}` : '--'}</strong><em>健康组件</em></span>
                    <span className={operationIssues ? 'hot' : ''}><strong>{operationsState === 'ready' ? operationIssues : '--'}</strong><em>异常或降级</em></span>
                    <span><strong>{operationsState === 'ready' ? operationRunning : '--'}</strong><em>执行中</em></span>
                  </div>
                  <div className="ops-alert-list scroll-region">
                    {operationsState === 'loading' ? <div className="ops-alert-clear">正在读取运行状态...</div>
                      : operationsState === 'error' ? <div className="empty-panel">运行状态暂时不可用，请进入运行中心重试。</div>
                      : operations.alerts?.length ? operations.alerts.slice(0, 3).map((alert) => (
                      <div key={alert.id}>
                        <AlertOutlined />
                        <span><strong>{alert.title}</strong><small>{alert.detail}</small></span>
                      </div>
                    )) : <div className="ops-alert-clear"><CheckCircleFilled /> 当前无运行告警</div>}
                  </div>
                  <Button size="small" type="text" onClick={() => navigate('/operations')}>打开运行中心</Button>
                </div>
              ) : <div className="empty-panel">需要“工具诊断”权限才能查看组织运行状态。</div>}
            </Panel>

            </div>
          </section>

          <Panel className="risk-panel" title="风险处置队列" meta={`${filteredRisks.length}/${dashboard.risk_queue.length} 项`}>
            <div className="risk-filter-bar">
              {riskFilters.map((filter) => (
                <button
                  type="button"
                  key={filter.key}
                  className={riskFilter === filter.key ? 'active' : ''}
                  onClick={() => setRiskFilter(filter.key)}
                >
                  {filter.label}<span>{filter.count}</span>
                </button>
              ))}
            </div>
            <div className="risk-table scroll-region scroll-fade">
              {filteredRisks.length ? filteredRisks.map((risk, index) => (
                <div key={risk.finding_id || `${risk.control}-${index}`} className="risk-row">
                  <strong>{risk.asset}</strong>
                  <span>{risk.risk}</span>
                  <Tag color="blue">{risk.control}</Tag>
                  <Tag color={risk.severity === 'high' || risk.severity === 'critical' ? 'red' : 'gold'}>
                    {severityLabel[risk.severity] || risk.severity}
                  </Tag>
                  <em>{statusLabel[risk.status] || risk.status}</em>
                  <Button
                    size="small"
                    type="text"
                    disabled={!canManageAssessments && risk.action === '整改与复测'}
                    loading={riskActionId === risk.finding_id}
                    onClick={() => handleRiskAction(risk)}
                  >
                    {risk.action}
                  </Button>
                </div>
              )) : (
                <div className="empty-panel">当前筛选条件下暂无风险。切换状态或执行检测后会按资产、控制点和整改状态汇总。</div>
              )}
            </div>
          </Panel>
        </section>
      </main>

    </div>
  )
}

function Kpi({ label, value, icon, tone = '' }) {
  return (
    <div className={`org-kpi ${tone}`}>
      <span>{icon}</span>
      <div>
        <strong>{value}</strong>
        <em>{label}</em>
      </div>
    </div>
  )
}

function Panel({ title, meta, className = '', children, bare = false }) {
  return (
    <section className={`org-panel ${className}`}>
      {!bare ? <div className="org-panel-head">
        <h2>{title}</h2>
        <span>{meta}</span>
      </div> : null}
      {children}
    </section>
  )
}

export default Dashboard
