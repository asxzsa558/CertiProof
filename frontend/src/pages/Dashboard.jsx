import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Menu, Card, Row, Col, Avatar, Dropdown, Space, Tag, Empty, Spin, Button, Progress } from 'antd'
import {
  DashboardOutlined, ProjectOutlined, LogoutOutlined, PlusOutlined,
  SafetyCertificateOutlined, CheckCircleOutlined, WarningOutlined,
  UserOutlined, SettingOutlined, BellOutlined, ArrowRightOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import api from '../services/api'
import ChatInterface from '../components/ChatInterface'
import './Dashboard.css'

const { Header, Content, Sider } = Layout

function Dashboard() {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  useEffect(() => { fetchProjects() }, [])

  const fetchProjects = async () => {
    try {
      const response = await api.get('/projects/')
      setProjects(response.data)
    } catch (error) {
      console.error('Failed to fetch projects:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleLogout = () => { logout(); navigate('/login') }

  const totalProjects = projects.length
  const activeProjects = projects.filter(p => p.status === 'active').length
  const avgScore = projects.length > 0 
    ? Math.round(projects.reduce((sum, p) => sum + (p.compliance_score || 0), 0) / projects.length) : 0
  const highRiskProjects = projects.filter(p => p.compliance_score && p.compliance_score < 60).length

  const menuItems = [
    { key: 'dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
    { key: 'projects', icon: <ProjectOutlined />, label: '项目管理' },
  ]

  const userMenuItems = [
    { key: 'profile', icon: <UserOutlined />, label: '个人资料' },
    { key: 'settings', icon: <SettingOutlined />, label: '设置' },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ]

  const getScoreColor = (score) => {
    if (score >= 90) return '#10b981'
    if (score >= 75) return '#6366f1'
    if (score >= 60) return '#f59e0b'
    return '#ef4444'
  }

  const getScoreStatus = (score) => {
    if (score >= 90) return '优秀'
    if (score >= 75) return '良好'
    if (score >= 60) return '一般'
    if (score >= 40) return '较差'
    return '危险'
  }

  return (
    <Layout className="dashboard-layout">
      <Sider width={260} className="dashboard-sider">
        <div className="sider-logo">
          <div className="logo-mark"></div>
          <span className="logo-text">CertiProof</span>
        </div>
        <Menu
          mode="inline"
          defaultSelectedKeys={['dashboard']}
          items={menuItems}
          onClick={({ key }) => { if (key === 'projects') navigate('/projects') }}
          className="sider-menu"
        />
      </Sider>

      <Layout className="dashboard-main">
        <Header className="dashboard-header">
          <div className="header-left">
            <h1 className="page-title">仪表盘</h1>
            <p className="page-subtitle">欢迎回来，{user?.full_name || user?.username}</p>
          </div>
          <Space size="large" className="header-right">
            <Button icon={<BellOutlined />} type="text" className="header-icon-btn" />
            <Dropdown menu={{ items: userMenuItems, onClick: ({ key }) => key === 'logout' && handleLogout() }} placement="bottomRight">
              <Space className="user-menu-trigger">
                <Avatar style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }} icon={<UserOutlined />} />
                <span className="user-name">{user?.username}</span>
              </Space>
            </Dropdown>
          </Space>
        </Header>

        <Content className="dashboard-content">
          <Spin spinning={loading}>
            <Row gutter={[24, 24]} className="stats-row">
              {[
                { label: '项目总数', value: totalProjects, icon: <ProjectOutlined />, gradient: 'primary', footer: `${activeProjects} 个活跃项目` },
                { label: '活跃项目', value: activeProjects, icon: <CheckCircleOutlined />, gradient: 'success', footer: '正在进行合规检查' },
                { label: '平均合规分数', value: avgScore, unit: '分', icon: <SafetyCertificateOutlined />, gradient: 'warning', footer: getScoreStatus(avgScore) },
                { label: '高风险项目', value: highRiskProjects, icon: <WarningOutlined />, gradient: 'danger', footer: '需要立即关注' },
              ].map((stat, i) => (
                <Col xs={24} sm={12} lg={6} key={i}>
                  <Card className={`stat-card stat-card-${stat.gradient}`}>
                    <div className="stat-card-content">
                      <div className="stat-info">
                        <div className="stat-label">{stat.label}</div>
                        <div className="stat-value">
                          {stat.value}{stat.unit && <span className="stat-unit">{stat.unit}</span>}
                        </div>
                      </div>
                      <div className="stat-icon">{stat.icon}</div>
                    </div>
                    <div className="stat-footer">{stat.footer}</div>
                  </Card>
                </Col>
              ))}
            </Row>

            <Row gutter={[24, 24]}>
              <Col xs={24} lg={8}>
                <Card className="action-card" title="快速开始">
                  <div className="action-buttons">
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/projects')} block size="large" className="action-btn-primary">
                      创建新项目
                    </Button>
                    <Button icon={<ProjectOutlined />} onClick={() => navigate('/projects')} block size="large" className="action-btn-secondary">
                      查看项目列表
                    </Button>
                  </div>
                </Card>
              </Col>

              <Col xs={24} lg={16}>
                <Card className="projects-card" title="最近项目" extra={
                  <Button type="link" onClick={() => navigate('/projects')} className="view-all-link">
                    查看全部 <ArrowRightOutlined />
                  </Button>
                }>
                  {projects.length === 0 ? (
                    <Empty description={<span className="empty-text">还没有项目，创建您的第一个合规项目吧</span>} />
                  ) : (
                    <div className="projects-list">
                      {projects.slice(0, 5).map((project) => (
                        <div key={project.id} onClick={() => navigate(`/projects/${project.id}`)} className="project-item">
                          <div className="project-info">
                            <div className="project-name">{project.name}</div>
                            <div className="project-meta">
                              {project.compliance_level} · 创建于 {new Date(project.created_at).toLocaleDateString()}
                            </div>
                          </div>
                          <div className="project-score">
                            {project.compliance_score ? (
                              <>
                                <div className="score-value" style={{ color: getScoreColor(project.compliance_score) }}>
                                  {project.compliance_score}
                                </div>
                                <div className="score-label">{getScoreStatus(project.compliance_score)}</div>
                              </>
                            ) : (
                              <Tag color="default" className="score-tag">未检测</Tag>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </Col>
            </Row>

            {/* AI Chat Interface */}
            <Row gutter={[24, 24]} style={{ marginTop: '24px' }}>
              <Col xs={24} lg={24}>
                <Card 
                  className="chat-card"
                  title={
                    <span>
                      <span style={{ 
                        background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', 
                        WebkitBackgroundClip: 'text',
                        WebkitTextFillColor: 'transparent',
                        fontWeight: 600 
                      }}>
                        AI 安全助手
                      </span>
                      <span style={{ 
                        marginLeft: '0.75rem', 
                        fontSize: '0.8125rem', 
                        color: 'rgba(255,255,255,0.5)',
                        fontWeight: 'normal' 
                      }}>
                        自然语言驱动 · 智能识别意图 · 自动执行操作
                      </span>
                    </span>
                  }
                >
                  <div style={{ height: '500px' }}>
                    <ChatInterface />
                  </div>
                </Card>
              </Col>
            </Row>
          </Spin>
        </Content>
      </Layout>
    </Layout>
  )
}

export default Dashboard
