import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Spin,
  Tag,
  Tooltip,
  Empty,
  Modal,
  Form,
  Input,
  Select,
  Checkbox,
  Radio,
  message,
  Dropdown,
  Avatar,
} from 'antd'
import {
  ProjectOutlined,
  RocketOutlined,
  CheckCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  UserOutlined,
  LogoutOutlined,
  SettingOutlined,
  BankOutlined,
  SafetyCertificateOutlined,
  LockOutlined,
  DatabaseOutlined,
  CloudServerOutlined,
  SearchOutlined,
  FilterOutlined,
  AppstoreOutlined,
  BarsOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons'
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip as ReTooltip,
  Legend,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import ProjectCard from '../components/ProjectCard'
import './Dashboard.css'

const SEVERITY_COLORS = ['#ff4d4f', '#fa8c16', '#fadb14', '#52c41a', '#1890ff']

const ASSESSMENT_TYPE_COLORS = {
  dengbao: '#00ff88',
  miping: '#a855f7',
  guanji: '#ff6b35',
  data_security: '#00b4d8',
}

const ASSESSMENT_TYPE_ICONS = {
  dengbao: SafetyCertificateOutlined,
  miping: LockOutlined,
  guanji: CloudServerOutlined,
  data_security: DatabaseOutlined,
}

function StatPanel({ label, value, sub, accentColor, icon }) {
  return (
    <div className="dash-stat-panel" style={{ '--accent-color': accentColor }}>
      <div className="dash-stat-corner-tl" />
      <div className="dash-stat-corner-tr" />
      <div className="dash-stat-corner-bl" />
      <div className="dash-stat-corner-br" />
      <div className="dash-stat-scanline" />
      <div className="dash-stat-top">
        <span className="dash-stat-label">{label}</span>
        {icon && <span className="dash-stat-icon" style={{ color: accentColor }}>{icon}</span>}
      </div>
      <div className="dash-stat-value">{value}</div>
      {sub && <div className="dash-stat-sub">{sub}</div>}
    </div>
  )
}

function StatusDot({ status }) {
  const colorMap = {
    not_started: '#666',
    in_progress: '#00ff88',
    completed: '#d4af37',
  }
  const color = colorMap[status] || '#666'
  return (
    <span className="dash-status-dot" style={{ background: color, boxShadow: `0 0 8px ${color}` }}>
      <span className="dash-status-dot-pulse" style={{ borderColor: color }} />
    </span>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [assessmentTypes, setAssessmentTypes] = useState([])
  const [searchKeyword, setSearchKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const [createForm] = Form.useForm()
  const [selectedAssessmentTypes, setSelectedAssessmentTypes] = useState([])
  const [radarData] = useState([
    { pillar: '物理', dengbao: 85 },
    { pillar: '网络', dengbao: 72 },
    { pillar: '主机', dengbao: 90 },
    { pillar: '应用', dengbao: 68 },
    { pillar: '数据', dengbao: 78 },
    { pillar: '管理', dengbao: 82 },
  ])
  const [trendData] = useState([
    { date: '06-01', score: 65 },
    { date: '06-05', score: 68 },
    { date: '06-10', score: 70 },
    { date: '06-15', score: 72 },
    { date: '06-20', score: 75 },
    { date: '06-25', score: 78 },
  ])

  const token = useAuthStore((state) => state.token)
  const user = useAuthStore((state) => state.user)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const setCurrentOrg = useAuthStore((state) => state.setCurrentOrg)
  const logout = useAuthStore((state) => state.logout)

  const currentOrg = organizations.find((o) => o.id === currentOrgId)

  const loadData = async () => {
    if (!currentOrgId) return
    try {
      setLoading(true)
      setError(null)
      const res = await api.get(`/dashboard/overview?organization_id=${currentOrgId}`)
      setData(res.data)
    } catch (err) {
      console.error('Dashboard load error:', err)
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadAssessmentTypes = async () => {
    try {
      const res = await api.get('/dashboard/assessment-types')
      setAssessmentTypes(res.data.assessment_types || [])
    } catch (err) {
      console.error('Failed to load assessment types:', err)
    }
  }

  useEffect(() => {
    if (currentOrgId) {
      loadData()
      loadAssessmentTypes()
    }
    const t = setInterval(() => {
      if (currentOrgId) loadData()
    }, 60000)
    return () => clearInterval(t)
  }, [currentOrgId])

  const handleOrgSwitch = (orgId) => {
    setCurrentOrg(orgId)
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const handleCreateProject = async (values) => {
    setCreateLoading(true)
    try {
      const payload = {
        name: values.name,
        organization_id: currentOrgId,
        system_name: values.systemName,
        description: values.description,
        assessment_type_ids: selectedAssessmentTypes,
      }
      if (values.assessmentTypeIds?.includes(1) && values.complianceLevel) {
        payload.compliance_level = values.complianceLevel
      }
      await api.post('/projects/', payload)
      message.success('项目创建成功')
      setCreateModalOpen(false)
      createForm.resetFields()
      setSelectedAssessmentTypes([])
      loadData()
    } catch (err) {
      message.error(err.response?.data?.detail || '创建失败')
    } finally {
      setCreateLoading(false)
    }
  }

  const filteredProjects = data?.projects?.filter((p) => {
    if (searchKeyword && !p.name.includes(searchKeyword) && !(p.system_name || '').includes(searchKeyword)) {
      return false
    }
    if (statusFilter !== 'all' && p.overall_status !== statusFilter) {
      return false
    }
    if (typeFilter !== 'all') {
      const hasType = p.assessment_types?.some((at) => at.code === typeFilter)
      if (!hasType) return false
    }
    return true
  }) || []

  const pieData = data ? [
    { name: '未开始', value: data.summary.not_started, color: '#666' },
    { name: '进行中', value: data.summary.in_progress, color: '#00ff88' },
    { name: '已完成', value: data.summary.completed, color: '#d4af37' },
  ] : []

  const orgMenuItems = [
    ...organizations.map((org) => ({
      key: `org-${org.id}`,
      label: (
        <div className="dash-org-menu-item">
          <BankOutlined />
          <span>{org.name}</span>
          <Tag color="default">{org.role}</Tag>
        </div>
      ),
      onClick: () => handleOrgSwitch(org.id),
    })),
  ]

  if (loading && !data) {
    return (
      <div className="dash-loading">
        <Spin size="large" />
        <div className="dash-loading-text">INITIALIZING COMMAND CENTER...</div>
      </div>
    )
  }

  return (
    <div className="dash-root">
      <div className="dash-bg-grid" />
      <div className="dash-bg-logo">
        <VeriSureLogo size={400} />
      </div>
      <div className="dash-bg-scan" />
      <div className="dash-bg-vignette" />

      <header className="dash-header">
        <div className="dash-header-left">
          <VeriSureLogo size={32} />
          <div className="dash-brand">
            <span className="dash-brand-name">VeriSure</span>
            <span className="dash-brand-sub">INTELLIGENCE COMMAND CENTER</span>
          </div>
          <div className="dash-classification">CLASSIFIED // TOP SECRET</div>
        </div>

        <div className="dash-header-center">
          <Dropdown menu={{ items: orgMenuItems }} placement="bottomLeft">
            <div className="dash-org-switcher">
              <BankOutlined />
              <span className="dash-org-name">{currentOrg?.name || '选择组织'}</span>
              <Tag color={currentOrg?.role === 'admin' ? 'gold' : 'default'} className="dash-org-role">
                {currentOrg?.role?.toUpperCase()}
              </Tag>
            </div>
          </Dropdown>
        </div>

        <div className="dash-header-right">
          <div className="dash-user-info">
            <Avatar size="small" icon={<UserOutlined />} className="dash-user-avatar" />
            <span className="dash-user-name">{user?.username || 'User'}</span>
          </div>
          {currentOrg?.role === 'admin' && (
            <button
              className="dash-icon-btn"
              onClick={() => navigate('/settings/organization')}
              title="组织管理"
            >
              <BankOutlined />
            </button>
          )}
          <button
            className="dash-icon-btn"
            onClick={() => navigate('/settings/models')}
            title="系统设置"
          >
            <SettingOutlined />
          </button>
          <button
            className="dash-icon-btn"
            onClick={handleLogout}
            title="退出登录"
          >
            <LogoutOutlined />
          </button>
        </div>
      </header>

      <section className="dash-section">
        <div className="dash-section-header">
          <span className="dash-section-tag">// STATUS OVERVIEW</span>
          <span className="dash-section-title">态势总览</span>
          <span className="dash-section-meta">
            实时监控 · 最后更新：{data ? new Date(data.generated_at).toLocaleString('zh-CN') : '-'}
          </span>
          <button className="dash-icon-btn" onClick={loadData} title="刷新">
            <ReloadOutlined spin={loading} />
          </button>
        </div>
        <div className="dash-stats-grid">
          <StatPanel
            label="PROJECT DOSSIERS"
            value={data?.summary?.total ?? 0}
            sub={`ACTIVE ${data?.summary?.in_progress ?? 0} · COMPLETED ${data?.summary?.completed ?? 0}`}
            accentColor="#00ff88"
            icon={<ProjectOutlined />}
          />
          <StatPanel
            label="AVG COMPLIANCE"
            value={data?.summary?.avg_score?.toFixed(1) ?? '0.0'}
            sub="满分 100 · 系统权重"
            accentColor="#00b4d8"
            icon={<SafetyCertificateOutlined />}
          />
          <StatPanel
            label="IN PROGRESS"
            value={data?.summary?.in_progress ?? 0}
            sub={`NOT STARTED ${data?.summary?.not_started ?? 0}`}
            accentColor="#d4af37"
            icon={<RocketOutlined />}
          />
          <StatPanel
            label="COMPLETED"
            value={data?.summary?.completed ?? 0}
            sub="已完成测评项目"
            accentColor="#a855f7"
            icon={<CheckCircleOutlined />}
          />
        </div>
      </section>

      <section className="dash-section">
        <div className="dash-section-header">
          <span className="dash-section-tag">// ANALYTICS</span>
          <span className="dash-section-title">数据分析</span>
        </div>
        <div className="dash-charts-grid">
          <div className="dash-chart-card">
            <div className="dash-chart-header">
              <span className="dash-chart-title">等保各支柱合规度</span>
              <span className="dash-chart-sub">RADAR ANALYSIS</span>
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <RadarChart data={radarData}>
                <PolarGrid stroke="rgba(0, 255, 136, 0.15)" />
                <PolarAngleAxis dataKey="pillar" tick={{ fill: 'rgba(255,255,255,0.7)', fontSize: 12 }} />
                <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 10 }} />
                <Radar name="等保" dataKey="dengbao" stroke="#00ff88" fill="#00ff88" fillOpacity={0.3} />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          <div className="dash-chart-card">
            <div className="dash-chart-header">
              <span className="dash-chart-title">项目状态分布</span>
              <span className="dash-chart-sub">STATUS BREAKDOWN</span>
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={95}
                  paddingAngle={4}
                  dataKey="value"
                  label={(e) => `${e.name} ${e.value}`}
                  labelLine={false}
                >
                  {pieData.map((entry, i) => (
                    <Cell key={i} fill={entry.color} stroke="#0a0a0b" strokeWidth={2} />
                  ))}
                </Pie>
                <ReTooltip
                  contentStyle={{ background: 'rgba(17,17,19,0.95)', border: '1px solid rgba(0,255,136,0.3)', borderRadius: 8 }}
                  labelStyle={{ color: '#fff' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="dash-chart-card">
            <div className="dash-chart-header">
              <span className="dash-chart-title">合规分数趋势 (30天)</span>
              <span className="dash-chart-sub">TREND ANALYSIS</span>
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0, 255, 136, 0.1)" />
                <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} />
                <YAxis tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }} />
                <ReTooltip
                  contentStyle={{ background: 'rgba(17,17,19,0.95)', border: '1px solid rgba(0,255,136,0.3)', borderRadius: 8 }}
                  labelStyle={{ color: '#fff' }}
                />
                <Line type="monotone" dataKey="score" stroke="#00ff88" strokeWidth={2} dot={{ fill: '#00ff88', r: 4 }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      <section className="dash-section">
        <div className="dash-section-header">
          <span className="dash-section-tag">// DOSSIERS</span>
          <span className="dash-section-title">项目档案</span>
          <div className="dash-filters">
            <Select
              size="small"
              value={typeFilter}
              onChange={setTypeFilter}
              style={{ width: 120 }}
              options={[
                { value: 'all', label: '全部测评' },
                ...assessmentTypes.map((t) => ({ value: t.code, label: t.name })),
              ]}
            />
            <Select
              size="small"
              value={statusFilter}
              onChange={setStatusFilter}
              style={{ width: 100 }}
              options={[
                { value: 'all', label: '全部状态' },
                { value: 'not_started', label: '未开始' },
                { value: 'in_progress', label: '进行中' },
                { value: 'completed', label: '已完成' },
              ]}
            />
            <Input
              size="small"
              prefix={<SearchOutlined />}
              placeholder="搜索项目..."
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              style={{ width: 180 }}
            />
          </div>
          <button
            className="dash-create-btn"
            onClick={() => setCreateModalOpen(true)}
          >
            <PlusOutlined /> 新建项目
          </button>
        </div>

        <div className="dash-projects-grid">
          {filteredProjects.length === 0 ? (
            <div className="dash-empty">
              <Empty description={data ? "暂无符合条件的项目" : "加载中..."} />
              {data && data.summary.total === 0 && (
                <button
                  className="dash-create-btn-large"
                  onClick={() => setCreateModalOpen(true)}
                >
                  <PlusOutlined /> 创建第一个项目
                </button>
              )}
            </div>
          ) : (
            filteredProjects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onClick={() => navigate(`/projects/${project.id}`)}
              />
            ))
          )}
        </div>
      </section>

      <Modal
        title={
          <div className="dash-modal-title">
            <span className="dash-modal-tag">// NEW DOSSIER</span>
            <span>创建新项目</span>
          </div>
        }
        open={createModalOpen}
        onCancel={() => {
          setCreateModalOpen(false)
          createForm.resetFields()
          setSelectedAssessmentTypes([])
        }}
        footer={null}
        width={640}
        className="dash-create-modal"
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreateProject}
          className="dash-create-form"
        >
          <Form.Item
            name="name"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input placeholder="例如：电商平台等保测评" size="large" />
          </Form.Item>

          <Form.Item
            name="systemName"
            label="被测系统名称"
            rules={[{ required: true, message: '请输入被测系统名称' }]}
          >
            <Input placeholder="例如：电商交易系统" size="large" />
          </Form.Item>

          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea placeholder="项目描述" rows={3} />
          </Form.Item>

          <Form.Item label="测评类型" required>
            <div className="dash-type-checkboxes">
              {assessmentTypes.map((t) => (
                <Checkbox
                  key={t.id}
                  value={t.id}
                  checked={selectedAssessmentTypes.includes(t.id)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedAssessmentTypes([...selectedAssessmentTypes, t.id])
                    } else {
                      setSelectedAssessmentTypes(selectedAssessmentTypes.filter((id) => id !== t.id))
                    }
                  }}
                >
                  <span style={{ color: ASSESSMENT_TYPE_COLORS[t.code] || '#fff' }}>
                    {t.name}
                  </span>
                  <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: 11, marginLeft: 6 }}>
                    {t.description}
                  </span>
                </Checkbox>
              ))}
            </div>
          </Form.Item>

          {selectedAssessmentTypes.includes(1) && (
            <Form.Item
              name="complianceLevel"
              label="等保级别"
              rules={[{ required: true, message: '请选择等保级别' }]}
            >
              <Radio.Group>
                <Radio.Button value="二级">二级</Radio.Button>
                <Radio.Button value="三级">三级</Radio.Button>
              </Radio.Group>
            </Form.Item>
          )}

          <Form.Item>
            <div className="dash-create-actions">
              <button
                type="button"
                className="dash-btn-cancel"
                onClick={() => {
                  setCreateModalOpen(false)
                  createForm.resetFields()
                  setSelectedAssessmentTypes([])
                }}
              >
                取消
              </button>
              <button type="submit" className="dash-btn-primary" loading={createLoading}>
                创建项目
              </button>
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}