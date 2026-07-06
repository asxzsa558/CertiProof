import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Avatar, Button, Checkbox, Dropdown, Form, Input, Modal, Select, Tag, message } from 'antd'
import {
  AlertOutlined,
  ApiOutlined,
  AuditOutlined,
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
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import '../styles/theme.css'
import './Dashboard.css'

const NAV_ITEMS = [
  { key: 'overview', group: '组织态势', label: '全局 Dashboard', icon: <DashboardOutlined />, path: '/dashboard' },
  { key: 'projects', group: '项目执行', label: '项目工作台', icon: <ProjectOutlined />, path: '/projects' },
  { key: 'assets', group: '项目执行', label: '资产矩阵', icon: <DatabaseOutlined />, path: '/assets' },
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
  resolved: '已关闭',
  false_positive: '误报',
}

const severityLabel = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '提示',
}

const topologyGlyph = {
  organization: 'ORG',
  project: 'PRJ',
  ip: 'IP',
  domain: 'DNS',
  cloud_resource: 'CLD',
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
  const [roleModalOpen, setRoleModalOpen] = useState(false)
  const [selectedToolIndex, setSelectedToolIndex] = useState(0)
  const [riskFilter, setRiskFilter] = useState('all')
  const [evidenceView, setEvidenceView] = useState('enabled')

  const currentOrg = useMemo(
    () => organizations.find((org) => org.id === currentOrgId) || organizations[0],
    [organizations, currentOrgId]
  )

  const currentPermissions = dashboard.current_role?.permissions || []
  const permissionScope = dashboard.current_role?.permission_scope || (currentOrg?.role === 'admin' ? '全局权限' : '受限权限')
  const canManageRoles = currentPermissions.includes('role:manage') || currentOrg?.role === 'admin'
  const canManageMembers = currentPermissions.includes('member:manage') || currentOrg?.role === 'admin'

  const fetchDashboard = async () => {
    if (!currentOrg?.id) return
    setLoading(true)
    try {
      const [dashboardRes, rolesRes, membersRes] = await Promise.all([
        api.get('/dashboard/organization-command', { params: { organization_id: currentOrg.id } }),
        api.get(`/organizations/${currentOrg.id}/roles`),
        api.get(`/organizations/${currentOrg.id}/members`),
      ])
      setDashboard({ ...emptyDashboard(), ...dashboardRes.data })
      setRoles(rolesRes.data || [])
      setMembers(membersRes.data || [])
    } catch (error) {
      message.error(error.response?.data?.detail || '加载组织态势失败')
      setDashboard(emptyDashboard())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDashboard()
  }, [currentOrg?.id])

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
      message.error(error.response?.data?.detail || '创建角色失败')
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
      message.error(error.response?.data?.detail || '更新成员权限失败')
    }
  }

  const summary = dashboard.summary || emptyDashboard().summary
  const topology = dashboard.exposure_topology || emptyDashboard().exposure_topology
  const visibleNodes = topology.nodes.slice(0, 18)
  const nodeLayout = useMemo(() => {
    const columnsByType = {
      organization: 12,
      project: 42,
    }
    const typeRows = {}
    let assetIndex = 0
    const assetCount = visibleNodes.filter((node) => ['ip', 'domain', 'cloud_resource'].includes(node.type)).length
    const assetRows = Math.ceil(assetCount / 2)
    return Object.fromEntries(visibleNodes.map((node, index) => {
      const row = typeRows[node.type] || 0
      typeRows[node.type] = row + 1
      const typeCount = visibleNodes.filter(item => item.type === node.type).length || 1
      const isAsset = ['ip', 'domain', 'cloud_resource'].includes(node.type)
      const currentAssetIndex = isAsset ? assetIndex++ : 0
      const y = isAsset
        ? assetRows === 1 ? 50 : 18 + (Math.floor(currentAssetIndex / 2) * (64 / Math.max(1, assetRows - 1)))
        : typeCount === 1 ? 50 : 18 + (row * (64 / Math.max(1, typeCount - 1)))
      const x = isAsset ? 68 + ((currentAssetIndex % 2) * 15) : columnsByType[node.type] || (18 + ((index * 23) % 68))
      return [node.id, { x, y }]
    }))
  }, [visibleNodes])
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id))
  const visibleEdges = (topology.edges || []).filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
  const selectedTool = dashboard.tool_health[selectedToolIndex] || dashboard.tool_health[0]
  const riskFilters = [
    { key: 'all', label: '全部', count: dashboard.risk_queue.length },
    { key: 'open', label: '待确认', count: dashboard.risk_queue.filter((risk) => risk.status === 'open').length },
    { key: 'in_progress', label: '处理中', count: dashboard.risk_queue.filter((risk) => risk.status === 'in_progress').length },
    { key: 'resolved', label: '已关闭', count: dashboard.risk_queue.filter((risk) => risk.status === 'resolved').length },
  ]
  const filteredRisks = riskFilter === 'all'
    ? dashboard.risk_queue
    : dashboard.risk_queue.filter((risk) => risk.status === riskFilter)
  const evidenceStages = [
    { key: 'enabled', title: '已启用', body: '项目、资产、测评、检测结果、角色权限', action: '进入项目工作台', path: '/projects' },
    { key: 'hardening', title: '强化中', body: '报告导出、整改队列、任务持久化', action: '查看检测结果', path: '/projects' },
    { key: 'next', title: '二期', body: '连续监控、OCR 证据识别、日志审计分析', action: '查看报告中心', path: '/reports' },
  ]
  const selectedEvidenceStage = evidenceStages.find((stage) => stage.key === evidenceView) || evidenceStages[0]
  const evidenceQueue = [
    ...dashboard.project_matrix.map((project) => ({
      key: `project-${project.project_id}`,
      title: project.name,
      meta: `${project.stage} / 证据 ${project.evidence_rate}%`,
      status: project.evidence_rate >= 80 ? 'complete' : project.evidence_rate > 0 ? 'active' : 'pending',
    })),
    ...dashboard.risk_queue.map((risk, index) => ({
      key: `risk-${risk.control}-${index}`,
      title: risk.asset,
      meta: `${risk.control} / ${risk.action}`,
      status: risk.status === 'resolved' ? 'complete' : 'blocked',
    })),
  ]

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
          <VeriSureLogo size={48} />
          <span>VeriSure</span>
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
          <div>
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
            <Button type="text" icon={<BellOutlined />} />
            <Dropdown menu={userMenu} placement="bottomRight">
              <Avatar className="org-avatar" icon={<UserOutlined />} />
            </Dropdown>
          </div>
        </header>

        <section className="org-kpis">
          <Kpi label="项目" value={summary.project_count} icon={<ProjectOutlined />} />
          <Kpi label="资产" value={summary.asset_count} icon={<DatabaseOutlined />} />
          <Kpi label="高风险" value={summary.high_risk_count} icon={<AlertOutlined />} tone="danger" />
          <Kpi label="未判定" value={summary.unknown_count} icon={<AuditOutlined />} tone="warning" />
          <Kpi label="平均测评进度" value={`${summary.average_progress}%`} icon={<SafetyCertificateOutlined />} />
          <Kpi label="待办" value={summary.todo_count} icon={<CheckCircleFilled />} />
        </section>

        <section className="org-grid">
          <Panel className="project-matrix-panel" title="项目测评进度矩阵" meta={loading ? '同步中' : `${dashboard.project_matrix.length} 个项目`}>
            <div className="project-matrix">
              <div className="matrix-header">
                <span>项目</span>
                <span>等级</span>
                <span>当前阶段</span>
                <span>总进度</span>
                <span>风险</span>
                <span>证据</span>
                <span>负责人</span>
                <span>下一步</span>
              </div>
              {dashboard.project_matrix.length ? dashboard.project_matrix.map((project) => (
                <div key={project.project_id} className="matrix-row">
                  <strong>{project.name}</strong>
                  <Tag color={project.level === '三级' ? 'blue' : 'cyan'}>{project.level}</Tag>
                  <span>{project.stage}</span>
                  <div className="mini-progress"><b style={{ width: `${project.progress}%` }} /><em>{project.progress}%</em></div>
                  <span className={project.risk_count ? 'risk-count hot' : 'risk-count'}>{project.risk_count}</span>
                  <span>{project.evidence_rate}%</span>
                  <span>{project.owner}</span>
                  <Button size="small" type="text" onClick={() => navigate(`/projects/${project.project_id}`)}>{project.next_action}</Button>
                </div>
              )) : (
                <div className="empty-panel">暂无项目。创建项目后，这里会按项目展示测评阶段、风险和证据完成率。</div>
              )}
            </div>
          </Panel>

          <Panel className="topology-panel" title="资产暴露面拓扑" meta={`${visibleNodes.length} 节点`}>
            <div className="topology-canvas">
              <div className="topology-lane lane-org">组织</div>
              <div className="topology-lane lane-project">项目</div>
              <div className="topology-lane lane-asset">资产</div>
              {visibleEdges.length ? (
                <svg className="topology-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                  {visibleEdges.map((edge, index) => {
                    const source = nodeLayout[edge.source]
                    const target = nodeLayout[edge.target]
                    if (!source || !target) return null
                    const midX = (source.x + target.x) / 2
                    return (
                      <path
                        key={`${edge.source}-${edge.target}-${index}`}
                        d={`M ${source.x} ${source.y} C ${midX} ${source.y}, ${midX} ${target.y}, ${target.x} ${target.y}`}
                      />
                    )
                  })}
                </svg>
              ) : null}
              {visibleNodes.length ? visibleNodes.map((node, index) => (
                <div
                  key={node.id}
                  className={`topology-node ${node.type} ${node.status}`}
                  style={{
                    left: `${nodeLayout[node.id]?.x || 50}%`,
                    top: `${nodeLayout[node.id]?.y || 50}%`,
                    width: node.size + 12,
                    height: node.size + 12,
                  }}
                  title={node.label}
                >
                  <b>{topologyGlyph[node.type] || 'N'}</b>
                  <span>{node.label}</span>
                </div>
              )) : <div className="empty-panel">暂无资产拓扑。添加资产并执行检测后会自动生成暴露面关系。</div>}
            </div>
            <div className="top-risk-list">
              <strong>Top 风险资产</strong>
              {topology.top_risky_assets.length ? topology.top_risky_assets.map((asset) => (
                <div key={`${asset.asset}-${asset.project}`}>
                  <span>{asset.asset}</span>
                  <em>{asset.risk_count} 项</em>
                </div>
              )) : <small>暂无高风险资产</small>}
            </div>
          </Panel>

          <div className="ops-column">
            <Panel title="工具遥测" meta={selectedTool ? `${dashboard.tool_health.length} 个工具` : '暂无数据'}>
              <div className="tool-telemetry-panel">
                <div className="tool-health-grid scroll-region">
                {dashboard.tool_health.map((tool) => (
                  <button
                    type="button"
                    key={tool.name}
                    className={`tool-health ${tool.status} ${selectedTool?.name === tool.name ? 'active' : ''}`}
                    onClick={() => setSelectedToolIndex(dashboard.tool_health.findIndex((item) => item.name === tool.name))}
                  >
                    {toolIconFor(tool.name)}
                    <strong>{tool.name}</strong>
                    <span>{tool.status === 'healthy' ? '链路可用' : '需要复核'} · {tool.latency}</span>
                  </button>
                ))}
                </div>
                <div className="tool-telemetry-detail">
                  {selectedTool ? (
                    <>
                      <div>
                        <strong>{selectedTool.name}</strong>
                        <Tag color={selectedTool.status === 'healthy' ? 'green' : 'gold'}>
                          {selectedTool.status === 'healthy' ? '链路正常' : '需要复核'}
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

          <Panel title="角色与权限治理" meta={canManageRoles || canManageMembers ? '可配置' : '只读'}>
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

            <Panel title="证据与整改" meta={selectedEvidenceStage.title}>
              <div className="governance-readiness evidence-remediation-panel">
                <div className="evidence-stage-list">
                  {evidenceStages.map((stage) => (
                    <button
                      type="button"
                      key={stage.key}
                      className={stage.key === evidenceView ? 'active' : ''}
                      onClick={() => setEvidenceView(stage.key)}
                    >
                      <strong>{stage.title}</strong>
                      <span>{stage.body}</span>
                    </button>
                  ))}
                </div>
                <div className="evidence-stage-detail">
                  <strong>{selectedEvidenceStage.title}</strong>
                  <span>{selectedEvidenceStage.body}</span>
                  <Button size="small" type="text" onClick={() => navigate(selectedEvidenceStage.path)}>
                    {selectedEvidenceStage.action}
                  </Button>
                </div>
                <div className="evidence-queue scroll-region">
                  {evidenceQueue.length ? evidenceQueue.map((item) => (
                    <div key={item.key} className={`evidence-queue-row ${item.status}`}>
                      <strong>{item.title}</strong>
                      <span>{item.meta}</span>
                    </div>
                  )) : (
                    <div className="empty-panel">暂无证据或整改队列。执行测评后会按项目和控制点汇总。</div>
                  )}
                </div>
              </div>
            </Panel>
          </div>

          <Panel className="risk-panel" title="风险情报流" meta={`${filteredRisks.length}/${dashboard.risk_queue.length} 项`}>
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
            <div className="risk-table scroll-region">
              {filteredRisks.length ? filteredRisks.map((risk, index) => (
                <div key={`${risk.control}-${index}`} className="risk-row">
                  <strong>{risk.asset}</strong>
                  <span>{risk.risk}</span>
                  <Tag color="blue">{risk.control}</Tag>
                  <Tag color={risk.severity === 'high' || risk.severity === 'critical' ? 'red' : 'gold'}>
                    {severityLabel[risk.severity] || risk.severity}
                  </Tag>
                  <em>{statusLabel[risk.status] || risk.status}</em>
                  <Button size="small" type="text">{risk.action}</Button>
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

function Panel({ title, meta, className = '', children }) {
  return (
    <section className={`org-panel ${className}`}>
      <div className="org-panel-head">
        <h2>{title}</h2>
        <span>{meta}</span>
      </div>
      {children}
    </section>
  )
}

export default Dashboard
