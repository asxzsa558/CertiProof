import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Avatar, Button, Checkbox, Dropdown, Form, Input, Modal, Select, Tag, Tooltip, message } from 'antd'
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
  RadarChartOutlined,
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
  { key: 'projects', group: '项目执行', label: '项目工作台', icon: <ProjectOutlined />, path: '/projects' },
  { key: 'assets', group: '项目执行', label: '资产矩阵', icon: <DatabaseOutlined />, path: '/projects?view=assets' },
  { key: 'assessment', group: '测评中心', label: '等保测评', icon: <SafetyCertificateOutlined />, path: '/projects' },
  { key: 'results', group: '测评中心', label: '检测结果', icon: <RadarChartOutlined />, path: '/projects' },
  { key: 'reports', group: '治理中心', label: '报告中心', icon: <FileTextOutlined />, path: '/reports' },
  { key: 'roles', group: '治理中心', label: '角色权限', icon: <TeamOutlined />, path: '/settings/organization' },
  { key: 'settings', group: '系统', label: '系统设置', icon: <SettingOutlined />, path: '/settings/models' },
]

const PERMISSION_GROUPS = [
  { key: 'project', label: '项目管理', permissions: ['project:read', 'project:create', 'project:update', 'project:delete'] },
  { key: 'asset', label: '资产管理', permissions: ['asset:read', 'asset:create', 'asset:update', 'asset:delete'] },
  { key: 'scan', label: '执行检测', permissions: ['scan:execute', 'scan:read', 'scan:cancel'] },
  { key: 'assessment', label: '测评证据', permissions: ['assessment:read', 'assessment:manage', 'evidence:manage'] },
  { key: 'report', label: '报告中心', permissions: ['report:read', 'report:export'] },
  { key: 'rbac', label: '角色授权', permissions: ['role:read', 'role:manage', 'member:manage'] },
  { key: 'system', label: '系统配置', permissions: ['system:config', 'tool:diagnose'] },
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

function errorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : error?.message || fallback
}

function Dashboard() {
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const setCurrentOrg = useAuthStore((state) => state.setCurrentOrg)
  const [dashboard, setDashboard] = useState(emptyDashboard())
  const [roles, setRoles] = useState([])
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [roleModalOpen, setRoleModalOpen] = useState(false)
  const [selectedToolIndex, setSelectedToolIndex] = useState(0)
  const [riskFilter, setRiskFilter] = useState('all')
  const [riskActionId, setRiskActionId] = useState(null)

  const currentOrg = useMemo(
    () => organizations.find((org) => org.id === currentOrgId) || organizations[0],
    [organizations, currentOrgId]
  )

  const currentPermissions = dashboard.current_role?.permissions || []
  const permissionScope = dashboard.current_role?.permission_scope || (currentOrg?.role === 'admin' ? '全局权限' : '受限权限')
  const canManageRoles = currentPermissions.includes('role:manage') || currentOrg?.role === 'admin'
  const canManageMembers = currentPermissions.includes('member:manage') || currentOrg?.role === 'admin'
  const canManageAssessments = currentPermissions.includes('assessment:manage') || currentOrg?.role === 'admin'

  const fetchDashboard = async ({ silent = false } = {}) => {
    if (!currentOrg?.id) return
    setLoading(true)
    const [dashboardResult, rolesResult, membersResult] = await Promise.allSettled([
      api.get('/dashboard/organization-command', { params: { organization_id: currentOrg.id } }),
      api.get(`/organizations/${currentOrg.id}/roles`),
      api.get(`/organizations/${currentOrg.id}/members`),
    ])
    if (dashboardResult.status === 'fulfilled') {
      setDashboard({ ...emptyDashboard(), ...dashboardResult.value.data })
      setLoadError('')
    } else {
      const detail = errorMessage(dashboardResult.reason, '组织态势数据暂时不可用')
      setLoadError(detail)
      if (!silent) message.error(detail)
    }
    if (rolesResult.status === 'fulfilled') setRoles(rolesResult.value.data || [])
    if (membersResult.status === 'fulfilled') setMembers(membersResult.value.data || [])
    if (!silent && dashboardResult.status === 'fulfilled' && (rolesResult.status === 'rejected' || membersResult.status === 'rejected')) {
      message.warning('部分权限数据未同步，当前态势数据不受影响')
    }
    setLoading(false)
  }

  useEffect(() => {
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

  const handleCreateRole = async (values) => {
    if (!currentOrg?.id) return
    try {
      await api.post(`/organizations/${currentOrg.id}/roles`, {
        name: values.name,
        description: values.description,
        permissions: values.permissions || [],
      })
      message.success('角色已创建')
      setRoleModalOpen(false)
      form.resetFields()
      fetchDashboard()
    } catch (error) {
      message.error(errorMessage(error, '创建角色失败'))
    }
  }

  const handleAssignRole = async (member, customRoleId) => {
    if (!currentOrg?.id) return
    try {
      await api.put(`/organizations/${currentOrg.id}/members/${member.id}`, {
        role: member.role,
        custom_role_id: customRoleId || null,
      })
      message.success('成员权限已更新')
      fetchDashboard()
    } catch (error) {
      message.error(errorMessage(error, '更新成员权限失败'))
    }
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
          {Object.entries(NAV_ITEMS.reduce((groups, item) => {
            groups[item.group] = [...(groups[item.group] || []), item]
            return groups
          }, {})).map(([group, items]) => (
            <div className="org-nav-group" key={group}>
              <em>{group}</em>
              {items.map((item) => (
                <button
                  key={item.key}
                  className={item.key === 'overview' ? 'active' : ''}
                  onClick={() => navigate(item.path)}
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

          <Panel className="ops-rbac-panel" title="角色与权限治理" meta={canManageRoles || canManageMembers ? '可配置' : '只读'}>
              <div className="rbac-head">
                <div>
                  <strong>{roles.length} 个角色模板</strong>
                  <span>{members.length} 名成员已纳入组织权限管理</span>
                </div>
                <Button size="small" type="primary" disabled={!canManageRoles} onClick={() => setRoleModalOpen(true)}>
                  新建角色
                </Button>
              </div>
              <div className="role-list">
                {roles.slice(0, 4).map((role) => (
                  <div key={role.id}>
                    <span>{role.name}</span>
                    <em>{role.permissions?.length ?? role.permission_count ?? 0} 权限</em>
                  </div>
                ))}
              </div>
              <div className="member-role-list">
                {members.slice(0, 3).map((member) => (
                  <div key={member.id}>
                    <span>{member.username || member.email}</span>
                    <Select
                      size="small"
                      value={member.custom_role_id}
                      placeholder="选择角色"
                      disabled={!canManageMembers}
                      allowClear
                      onChange={(value) => handleAssignRole(member, value)}
                      options={roles.map((role) => ({ value: role.id, label: role.name }))}
                    />
                  </div>
                ))}
              </div>
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

      <Modal
        title="新建角色"
        open={roleModalOpen}
        onCancel={() => setRoleModalOpen(false)}
        onOk={() => form.submit()}
        okText="创建角色"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onFinish={handleCreateRole}>
          <Form.Item name="name" label="角色名称" rules={[{ required: true, message: '请输入角色名称' }]}>
            <Input placeholder="例如：整改负责人" />
          </Form.Item>
          <Form.Item name="description" label="角色说明">
            <Input.TextArea rows={2} placeholder="描述该角色负责的工作范围" />
          </Form.Item>
          <Form.Item name="permissions" label="权限范围">
            <Checkbox.Group className="permission-checks">
              {PERMISSION_GROUPS.map((group) => (
                <div key={group.key} className="permission-group">
                  <strong>{group.label}</strong>
                  {group.permissions.map((permission) => (
                    <Checkbox key={permission} value={permission}>{permission}</Checkbox>
                  ))}
                </div>
              ))}
            </Checkbox.Group>
          </Form.Item>
        </Form>
      </Modal>
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
