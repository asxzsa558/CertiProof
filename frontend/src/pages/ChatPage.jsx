import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Avatar, Dropdown, Space, Button, Tooltip } from 'antd'
import {
  ProjectOutlined,
  LogoutOutlined,
  UserOutlined,
  SettingOutlined,
  BellOutlined,
  HistoryOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import ChatWorkspace from '../components/ChatWorkspace'
import ModelSelector from '../components/ModelSelector'
import api from '../services/api'
import './ChatPage.css'

const { Header, Sider, Content } = Layout

function ChatPage() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const [projects, setProjects] = useState([])
  const [selectedProject, setSelectedProject] = useState(null)
  const [selectedModel, setSelectedModel] = useState(null)
  const [siderCollapsed, setSiderCollapsed] = useState(false)

  useEffect(() => {
    fetchProjects()
  }, [])

  const fetchProjects = async () => {
    try {
      const response = await api.get('/projects/')
      setProjects(response.data)
      // Auto-select first project if none selected
      if (response.data.length > 0 && !selectedProject) {
        setSelectedProject(response.data[0])
      }
    } catch (error) {
      console.error('Failed to fetch projects:', error)
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const handleSelectProject = (project) => {
    setSelectedProject(project)
  }

  const handleNewProject = () => {
    // Trigger new project creation via chat
    setSelectedProject(null)
  }

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

  return (
    <Layout className="chat-page-layout">
      {/* Left Sidebar - Project List */}
      <Sider
        width={280}
        collapsed={siderCollapsed}
        collapsedWidth={0}
        trigger={null}
        className="chat-sider"
      >
        <div className="sider-header">
          <div className="sider-logo">
            <SafetyCertificateOutlined style={{ fontSize: 20, color: '#6366f1' }} />
            <span className="logo-text">CertiProof</span>
          </div>
        </div>

        <div className="sider-actions">
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleNewProject}
            block
            className="new-project-btn"
          >
            新建项目
          </Button>
        </div>

        <div className="sider-section">
          <div className="section-title">
            <HistoryOutlined style={{ marginRight: 8 }} />
            项目列表
          </div>
          <div className="project-list">
            {projects.map((project) => (
              <div
                key={project.id}
                className={`project-item ${selectedProject?.id === project.id ? 'active' : ''}`}
                onClick={() => handleSelectProject(project)}
              >
                <div className="project-item-info">
                  <div className="project-item-name">{project.name}</div>
                  <div className="project-item-meta">
                    <span className="project-level">
                      {project.compliance_level}
                    </span>
                    {project.compliance_score !== null && project.compliance_score !== undefined ? (
                      <span className="project-score" style={{ color: getScoreColor(project.compliance_score) }}>
                        {project.compliance_score} 分
                      </span>
                    ) : (
                      <span className="project-score-unchecked">未检测</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {projects.length === 0 && (
              <div className="empty-projects">
                <p>还没有项目</p>
                <p>点击"新建项目"开始</p>
              </div>
            )}
          </div>
        </div>
      </Sider>

      {/* Main Content */}
      <Layout className="chat-main-layout">
        {/* Top Header */}
        <Header className="chat-page-header">
          <div className="header-left">
            <Button
              type="text"
              icon={<ProjectOutlined />}
              onClick={() => setSiderCollapsed(!siderCollapsed)}
              className="sider-toggle-btn"
            />
            {selectedProject && (
              <div className="current-project">
                <span className="current-project-name">{selectedProject.name}</span>
                <span className="current-project-level">{selectedProject.compliance_level}</span>
              </div>
            )}
          </div>
          <Space size="middle">
            <ModelSelector value={selectedModel} onChange={setSelectedModel} />
            <Tooltip title="通知">
              <Button icon={<BellOutlined />} type="text" className="header-icon-btn" />
            </Tooltip>
            <Dropdown
              menu={{
                items: userMenuItems,
                onClick: ({ key }) => key === 'logout' && handleLogout(),
              }}
              placement="bottomRight"
            >
              <Space className="user-menu-trigger">
                <Avatar
                  size={32}
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
                  icon={<UserOutlined />}
                />
                <span className="user-name">{user?.username}</span>
              </Space>
            </Dropdown>
          </Space>
        </Header>

        {/* Chat Content */}
        <Content className="chat-page-content">
          <ChatWorkspace
            projectId={selectedProject?.id}
            projectName={selectedProject?.name}
            modelId={selectedModel}
          />
        </Content>
      </Layout>
    </Layout>
  )
}

export default ChatPage
