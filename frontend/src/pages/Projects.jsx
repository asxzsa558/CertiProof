import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Menu, Button, Card, Row, Col, Modal, Form, Input, Select, message, Tag, Avatar, Dropdown, Space, Empty, Spin, Progress } from 'antd'
import { 
  ProjectOutlined, PlusOutlined, LogoutOutlined, UserOutlined, SettingOutlined,
  BellOutlined, SafetyCertificateOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import api from '../services/api'
import './Projects.css'

const { Header, Content, Sider } = Layout

function Projects() {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()
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

  const handleCreateProject = async (values) => {
    try {
      await api.post('/projects/', values)
      message.success('项目创建成功')
      setModalVisible(false)
      form.resetFields()
      fetchProjects()
    } catch (error) {
      message.error(error.response?.data?.detail || '创建失败')
    }
  }

  const handleLogout = () => { logout(); navigate('/login') }

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

  const userMenuItems = [
    { key: 'profile', icon: <UserOutlined />, label: '个人资料' },
    { key: 'settings', icon: <SettingOutlined />, label: '设置' },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ]

  const menuItems = [
    { key: 'dashboard', icon: <ProjectOutlined />, label: '仪表盘' },
    { key: 'projects', icon: <ProjectOutlined />, label: '项目管理' },
  ]

  return (
    <Layout className="projects-layout">
      <Sider width={260} className="projects-sider">
        <div className="sider-logo">
          <div className="logo-mark"></div>
          <span className="logo-text">CertiProof</span>
        </div>
        <Menu
          mode="inline"
          defaultSelectedKeys={['projects']}
          items={menuItems}
          onClick={({ key }) => { if (key === 'dashboard') navigate('/') }}
          className="sider-menu"
        />
      </Sider>

      <Layout className="projects-main">
        <Header className="projects-header">
          <div className="header-left">
            <h1 className="page-title">项目管理</h1>
            <p className="page-subtitle">管理您的等保合规项目</p>
          </div>
          <Space size="large" className="header-right">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)} size="large" className="create-btn">
              创建项目
            </Button>
            <Button icon={<BellOutlined />} type="text" className="header-icon-btn" />
            <Dropdown menu={{ items: userMenuItems, onClick: ({ key }) => key === 'logout' && handleLogout() }} placement="bottomRight">
              <Space className="user-menu-trigger">
                <Avatar style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }} icon={<UserOutlined />} />
                <span className="user-name">{user?.username}</span>
              </Space>
            </Dropdown>
          </Space>
        </Header>

        <Content className="projects-content">
          <Spin spinning={loading}>
            {projects.length === 0 ? (
              <Card className="empty-card">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={<span className="empty-text">还没有项目，创建您的第一个等保合规项目吧</span>}
                >
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)} size="large" className="create-btn">
                    创建项目
                  </Button>
                </Empty>
              </Card>
            ) : (
              <Row gutter={[24, 24]}>
                {projects.map((project) => (
                  <Col xs={24} sm={12} lg={8} xl={6} key={project.id}>
                    <Card className="project-card" onClick={() => navigate(`/projects/${project.id}`)}>
                      <div className="project-card-header">
                        <div className="project-icon">
                          <SafetyCertificateOutlined />
                        </div>
                        <Tag color={project.compliance_level === '三级' ? 'red' : 'blue'} className="level-tag">
                          {project.compliance_level}
                        </Tag>
                      </div>
                      <h3 className="project-title">{project.name}</h3>
                      <p className="project-description">{project.description || '暂无描述'}</p>
                      <div className="project-score-section">
                        {project.compliance_score ? (
                          <>
                            <div className="score-header">
                              <span className="score-label">合规分数</span>
                              <span className="score-value" style={{ color: getScoreColor(project.compliance_score) }}>
                                {project.compliance_score}
                              </span>
                            </div>
                            <Progress percent={project.compliance_score} showInfo={false} strokeColor={getScoreColor(project.compliance_score)} trailColor="rgba(255,255,255,0.1)" />
                            <div className="score-status">{getScoreStatus(project.compliance_score)}</div>
                          </>
                        ) : (
                          <div className="no-score">
                            <ClockCircleOutlined />
                            <span>未检测</span>
                          </div>
                        )}
                      </div>
                      <div className="project-footer">
                        <span className="project-date">创建于 {new Date(project.created_at).toLocaleDateString()}</span>
                        <Tag color={project.status === 'active' ? 'green' : 'default'} className="status-tag">
                          {project.status === 'active' ? '活跃' : '已归档'}
                        </Tag>
                      </div>
                    </Card>
                  </Col>
                ))}
              </Row>
            )}
          </Spin>
        </Content>
      </Layout>

      <Modal
        title="创建项目"
        open={modalVisible}
        onCancel={() => { setModalVisible(false); form.resetFields() }}
        footer={null}
        width={500}
        centered
        className="create-modal"
      >
        <Form form={form} layout="vertical" onFinish={handleCreateProject} className="create-form">
          <Form.Item label="项目名称" name="name" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="请输入项目名称" size="large" />
          </Form.Item>
          <Form.Item label="等保等级" name="compliance_level" rules={[{ required: true, message: '请选择等保等级' }]}>
            <Select placeholder="请选择等保等级" size="large">
              <Select.Option value="二级"><Space><Tag color="blue">二级</Tag><span>基础合规要求</span></Space></Select.Option>
              <Select.Option value="三级"><Space><Tag color="red">三级</Tag><span>重要系统合规要求</span></Space></Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="项目描述" name="description">
            <Input.TextArea placeholder="请输入项目描述（可选）" rows={4} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block size="large" className="create-btn">创建项目</Button>
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default Projects
