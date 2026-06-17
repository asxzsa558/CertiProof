import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Layout, Menu, Card, Button, Table, Tag, Avatar, Dropdown, Space, Spin, Modal, Select, Input, message, Progress, Badge } from 'antd'
import { 
  ProjectOutlined, LogoutOutlined, UserOutlined, SettingOutlined,
  BellOutlined, SafetyCertificateOutlined, ArrowLeftOutlined,
  CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined,
  PlayCircleOutlined, EditOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import api from '../services/api'
import './Remediation.css'

const { Header, Content, Sider } = Layout

function Remediation() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [tickets, setTickets] = useState([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState(null)
  const logout = useAuthStore((state) => state.logout)

  useEffect(() => {
    fetchProject()
    fetchTickets()
  }, [projectId, statusFilter])

  const fetchProject = async () => {
    try {
      const response = await api.get(`/projects/${projectId}`)
      setProject(response.data)
    } catch (error) {
      message.error('项目不存在')
      navigate('/projects')
    }
  }

  const fetchTickets = async () => {
    setLoading(true)
    try {
      const params = statusFilter ? `?status_filter=${statusFilter}` : ''
      const response = await api.get(`/projects/${projectId}/remediation/${params}`)
      setTickets(response.data)
    } catch (error) {
      console.error('Failed to fetch tickets:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleUpdateStatus = async (ticketId, newStatus) => {
    try {
      await api.put(`/projects/${projectId}/remediation/${ticketId}`, {
        status: newStatus,
      })
      message.success('状态更新成功')
      fetchTickets()
    } catch (error) {
      message.error('更新失败')
    }
  }

  const handleLogout = () => { logout(); navigate('/login') }

  const getStatusColor = (status) => {
    const colors = {
      open: 'red',
      in_progress: 'orange',
      resolved: 'blue',
      verified: 'green',
      closed: 'default',
    }
    return colors[status] || 'default'
  }

  const getStatusText = (status) => {
    const texts = {
      open: '待处理',
      in_progress: '处理中',
      resolved: '已解决',
      verified: '已验证',
      closed: '已关闭',
    }
    return texts[status] || status
  }

  const getPriorityColor = (priority) => {
    const colors = {
      critical: '#dc2626',
      high: '#ef4444',
      medium: '#f59e0b',
      low: '#3b82f6',
    }
    return colors[priority] || '#64748b'
  }

  // Calculate statistics
  const totalTickets = tickets.length
  const openTickets = tickets.filter(t => t.status === 'open').length
  const inProgressTickets = tickets.filter(t => t.status === 'in_progress').length
  const resolvedTickets = tickets.filter(t => t.status === 'resolved' || t.status === 'verified').length
  const completionRate = totalTickets > 0 ? Math.round((resolvedTickets / totalTickets) * 100) : 0

  const columns = [
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 100,
      render: (priority) => (
        <Tag style={{ 
          background: getPriorityColor(priority),
          border: 'none',
          color: '#fff',
          fontWeight: 600,
        }}>
          {priority.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: '问题',
      dataIndex: 'title',
      key: 'title',
      render: (title, record) => (
        <div>
          <div style={{ fontWeight: 600, color: '#fff', marginBottom: '0.25rem' }}>{title}</div>
          <div style={{ fontSize: '0.8125rem', color: 'rgba(255,255,255,0.5)' }}>
            {record.description?.substring(0, 80)}...
          </div>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status) => (
        <Tag color={getStatusColor(status)}>{getStatusText(status)}</Tag>
      ),
    },
    {
      title: '截止日期',
      dataIndex: 'due_date',
      key: 'due_date',
      width: 120,
      render: (date) => {
        if (!date) return '-'
        const dueDate = new Date(date)
        const isOverdue = dueDate < new Date()
        return (
          <span style={{ color: isOverdue ? '#ef4444' : 'rgba(255,255,255,0.7)' }}>
            {dueDate.toLocaleDateString()}
            {isOverdue && <ExclamationCircleOutlined style={{ marginLeft: '0.5rem' }} />}
          </span>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_, record) => (
        <Space>
          {record.status === 'open' && (
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleUpdateStatus(record.id, 'in_progress')}
              className="action-btn"
            >
              开始处理
            </Button>
          )}
          {record.status === 'in_progress' && (
            <Button
              type="primary"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handleUpdateStatus(record.id, 'resolved')}
              className="action-btn"
            >
              标记完成
            </Button>
          )}
          {record.status === 'resolved' && (
            <Button
              type="primary"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handleUpdateStatus(record.id, 'verified')}
              className="action-btn"
            >
              验证
            </Button>
          )}
        </Space>
      ),
    },
  ]

  const menuItems = [
    { key: 'dashboard', icon: <ProjectOutlined />, label: '仪表盘' },
    { key: 'projects', icon: <ProjectOutlined />, label: '项目管理' },
  ]

  const userMenuItems = [
    { key: 'profile', icon: <UserOutlined />, label: '个人资料' },
    { key: 'settings', icon: <SettingOutlined />, label: '设置' },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ]

  if (!project) {
    return (
      <Layout className="remediation-loading">
        <Spin size="large" />
      </Layout>
    )
  }

  return (
    <Layout className="remediation-layout">
      <Sider width={260} className="remediation-sider">
        <div className="sider-logo">
          <div className="logo-mark"></div>
          <span className="logo-text">CertiProof</span>
        </div>
        <Menu
          mode="inline"
          defaultSelectedKeys={['projects']}
          items={menuItems}
          onClick={({ key }) => {
            if (key === 'dashboard') navigate('/')
            if (key === 'projects') navigate('/projects')
          }}
          className="sider-menu"
        />
      </Sider>

      <Layout className="remediation-main">
        <Header className="remediation-header">
          <div className="header-left">
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/projects/${projectId}`)} className="back-btn">
              返回
            </Button>
            <div className="header-info">
              <h1 className="page-title">整改看板</h1>
              <p className="page-subtitle">{project.name} - 问题跟踪与整改</p>
            </div>
          </div>
          <Space size="large" className="header-right">
            <Button icon={<BellOutlined />} type="text" className="header-icon-btn" />
            <Dropdown menu={{ items: userMenuItems, onClick: ({ key }) => key === 'logout' && handleLogout() }} placement="bottomRight">
              <Space className="user-menu-trigger">
                <Avatar style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }} icon={<UserOutlined />} />
              </Space>
            </Dropdown>
          </Space>
        </Header>

        <Content className="remediation-content">
          {/* Statistics Cards */}
          <div className="stats-grid">
            <Card className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444' }}>
                <ExclamationCircleOutlined />
              </div>
              <div className="stat-info">
                <div className="stat-value">{openTickets}</div>
                <div className="stat-label">待处理</div>
              </div>
            </Card>
            <Card className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' }}>
                <ClockCircleOutlined />
              </div>
              <div className="stat-info">
                <div className="stat-value">{inProgressTickets}</div>
                <div className="stat-label">处理中</div>
              </div>
            </Card>
            <Card className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
                <CheckCircleOutlined />
              </div>
              <div className="stat-info">
                <div className="stat-value">{resolvedTickets}</div>
                <div className="stat-label">已完成</div>
              </div>
            </Card>
            <Card className="stat-card">
              <div className="stat-icon" style={{ background: 'rgba(99, 102, 241, 0.15)', color: '#6366f1' }}>
                <SafetyCertificateOutlined />
              </div>
              <div className="stat-info">
                <div className="stat-value">{completionRate}%</div>
                <div className="stat-label">完成率</div>
              </div>
            </Card>
          </div>

          {/* Progress Bar */}
          <Card className="progress-card">
            <div className="progress-header">
              <span>整改进度</span>
              <span>{resolvedTickets} / {totalTickets}</span>
            </div>
            <Progress 
              percent={completionRate} 
              showInfo={false}
              strokeColor={{
                '0%': '#10b981',
                '100%': '#06b6d4',
              }}
              trailColor="rgba(255,255,255,0.1)"
            />
          </Card>

          {/* Filter */}
          <Card className="filter-card">
            <Space>
              <span style={{ color: 'rgba(255,255,255,0.7)' }}>状态筛选：</span>
              <Select
                placeholder="全部状态"
                allowClear
                style={{ width: 150 }}
                onChange={(value) => setStatusFilter(value)}
                options={[
                  { value: 'open', label: '待处理' },
                  { value: 'in_progress', label: '处理中' },
                  { value: 'resolved', label: '已解决' },
                  { value: 'verified', label: '已验证' },
                ]}
              />
            </Space>
          </Card>

          {/* Tickets Table */}
          <Card className="tickets-card">
            <Table
              columns={columns}
              dataSource={tickets}
              rowKey="id"
              loading={loading}
              pagination={{ pageSize: 10 }}
              className="tickets-table"
            />
          </Card>
        </Content>
      </Layout>
    </Layout>
  )
}

export default Remediation
