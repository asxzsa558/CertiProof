import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Layout, Menu, Card, Descriptions, Button, Table, Modal, Form, Input, Select, message, Tag, Avatar, Dropdown, Space, Empty, Spin, Progress, Row, Col } from 'antd'
import {
  ProjectOutlined, LogoutOutlined, PlusOutlined, UserOutlined, SettingOutlined,
  BellOutlined, SafetyCertificateOutlined, CheckCircleOutlined, ClockCircleOutlined,
  ArrowLeftOutlined, CloudServerOutlined, GlobalOutlined, DatabaseOutlined,
  ThunderboltOutlined, DownloadOutlined, ToolOutlined, EyeOutlined, MonitorOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import ChatInterface from '../components/ChatInterface'
import api from '../services/api'
import './ProjectDetail.css'

const { Header, Content, Sider } = Layout

function ProjectDetail() {
  const { projectId } = useParams()
  const [project, setProject] = useState(null)
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(true)
  const [assetModalVisible, setAssetModalVisible] = useState(false)
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const logout = useAuthStore((state) => state.logout)

  useEffect(() => {
    fetchProject()
    fetchAssets()
  }, [projectId])

  const fetchProject = async () => {
    try {
      const response = await api.get(`/projects/${projectId}`)
      setProject(response.data)
    } catch (error) {
      message.error('项目不存在')
      navigate('/projects')
    }
  }

  const fetchAssets = async () => {
    try {
      const response = await api.get(`/projects/${projectId}/assets/`)
      setAssets(response.data)
    } catch (error) {
      console.error('Failed to fetch assets:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateAsset = async (values) => {
    try {
      await api.post(`/projects/${projectId}/assets/`, values)
      message.success('资产添加成功')
      setAssetModalVisible(false)
      form.resetFields()
      fetchAssets()
    } catch (error) {
      message.error(error.response?.data?.detail || '添加失败')
    }
  }

  const [scanning, setScanning] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const handleScan = async () => {
    if (assets.length === 0) {
      message.warning('请先添加资产')
      return
    }
    
    const verifiedAssets = assets.filter(a => a.verification_status === 'verified')
    if (verifiedAssets.length === 0) {
      message.warning('请先验证资产')
      return
    }
    
    setScanning(true)
    try {
      const asset = verifiedAssets[0]
      // Use real scan instead of mock
      const response = await api.post(`/real/scan/${projectId}/${asset.id}`)
      const data = response.data
      message.success(`扫描完成！发现 ${data.findings_count} 个问题，合规分数 ${data.compliance_score}`)
      fetchProject()
      fetchAssets()
    } catch (error) {
      message.error(error.response?.data?.detail || '扫描失败')
    } finally {
      setScanning(false)
    }
  }

  const handleDownloadReport = async () => {
    setDownloading(true)
    try {
      const token = useAuthStore.getState().token
      const response = await fetch(`/api/v1/projects/${projectId}/report`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      
      if (!response.ok) throw new Error('Download failed')
      
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `certiproof_report_${projectId}.pdf`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
      message.success('报告下载成功')
    } catch (error) {
      message.error('报告下载失败')
    } finally {
      setDownloading(false)
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

  const getAssetIcon = (type) => {
    switch (type) {
      case 'ip': return <CloudServerOutlined />
      case 'domain': return <GlobalOutlined />
      case 'cloud_resource': return <DatabaseOutlined />
      default: return <CloudServerOutlined />
    }
  }

  const getAssetColor = (type) => {
    switch (type) {
      case 'ip': return 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)'
      case 'domain': return 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)'
      case 'cloud_resource': return 'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)'
      default: return 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)'
    }
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

  const assetColumns = [
    {
      title: '资产',
      key: 'asset',
      render: (_, record) => (
        <div className="asset-cell">
          <div className="asset-icon" style={{ background: getAssetColor(record.asset_type) }}>
            {getAssetIcon(record.asset_type)}
          </div>
          <div className="asset-info">
            <div className="asset-value">{record.value}</div>
            <div className="asset-name">{record.name || record.asset_type}</div>
          </div>
        </div>
      ),
    },
    {
      title: '验证状态',
      dataIndex: 'verification_status',
      key: 'verification_status',
      render: (status) => {
        const config = {
          verified: { color: 'success', icon: <CheckCircleOutlined />, text: '已验证' },
          pending: { color: 'warning', icon: <ClockCircleOutlined />, text: '待验证' },
          failed: { color: 'error', icon: <ClockCircleOutlined />, text: '验证失败' },
        }[status] || { color: 'warning', icon: <ClockCircleOutlined />, text: '待验证' }
        return <Tag color={config.color} icon={config.icon} className="status-tag">{config.text}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date) => new Date(date).toLocaleDateString(),
    },
  ]

  if (!project) {
    return (
      <Layout className="detail-loading">
        <Spin size="large" />
      </Layout>
    )
  }

  return (
    <Layout className="detail-layout">
      <Sider width={260} className="detail-sider">
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

      <Layout className="detail-main">
        <Header className="detail-header">
          <div className="header-left">
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')} className="back-btn">
              返回
            </Button>
            <div className="header-info">
              <h1 className="page-title">{project.name}</h1>
              <p className="page-subtitle">{project.compliance_level}等保合规项目</p>
            </div>
          </div>
          <Space size="large" className="header-right">
            <Button icon={<ToolOutlined />} onClick={() => navigate(`/projects/${projectId}/remediation`)} className="nav-btn">
              整改看板
            </Button>
            <Button icon={<MonitorOutlined />} onClick={() => navigate(`/projects/${projectId}/monitoring`)} className="nav-btn">
              持续监控
            </Button>
            <Button icon={<BellOutlined />} type="text" className="header-icon-btn" />
            <Dropdown menu={{ items: userMenuItems, onClick: ({ key }) => key === 'logout' && handleLogout() }} placement="bottomRight">
              <Space className="user-menu-trigger">
                <Avatar style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }} icon={<UserOutlined />} />
              </Space>
            </Dropdown>
          </Space>
        </Header>

        <Content className="detail-content">
          <Card className="info-card">
            <Row gutter={[24, 24]}>
              <Col xs={24} md={16}>
                <Descriptions column={1} size="large" className="project-descriptions">
                  <Descriptions.Item label="项目名称">
                    <span className="desc-value">{project.name}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="等保等级">
                    <Tag color={project.compliance_level === '三级' ? 'red' : 'blue'} className="level-tag">
                      {project.compliance_level}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Tag color={project.status === 'active' ? 'success' : 'default'} className="status-tag">
                      {project.status === 'active' ? '活跃' : '已归档'}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="项目描述">
                    <span className="desc-value">{project.description || '暂无描述'}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="创建时间">
                    <span className="desc-value">{new Date(project.created_at).toLocaleString()}</span>
                  </Descriptions.Item>
                </Descriptions>
              </Col>
              <Col xs={24} md={8}>
                <div className="score-card">
                  <SafetyCertificateOutlined className="score-icon" />
                  {project.compliance_score ? (
                    <>
                      <div className="score-number" style={{ color: getScoreColor(project.compliance_score) }}>
                        {project.compliance_score}
                      </div>
                      <div className="score-status">{getScoreStatus(project.compliance_score)}</div>
                      <Progress percent={project.compliance_score} showInfo={false} strokeColor={getScoreColor(project.compliance_score)} trailColor="rgba(255,255,255,0.1)" />
                    </>
                  ) : (
                    <>
                      <div className="no-score-text">未检测</div>
                      <div className="no-score-hint">开始扫描以获取合规分数</div>
                    </>
                  )}
                  <Button
                    type="primary"
                    icon={<ThunderboltOutlined />}
                    onClick={handleScan}
                    loading={scanning}
                    className="scan-btn"
                    style={{ marginTop: '1.5rem' }}
                  >
                    {scanning ? '扫描中...' : '开始扫描'}
                  </Button>
                  {project.compliance_score && (
                    <Button
                      icon={<DownloadOutlined />}
                      onClick={handleDownloadReport}
                      loading={downloading}
                      className="download-btn"
                      style={{ marginTop: '0.75rem', width: '100%' }}
                    >
                      下载报告
                    </Button>
                  )}
                </div>
              </Col>
            </Row>
          </Card>

          <Card
            className="assets-card"
            title="资产管理"
            extra={
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setAssetModalVisible(true)} className="create-btn">
                添加资产
              </Button>
            }
          >
            {assets.length === 0 ? (
              <Empty description={<span className="empty-text">还没有资产，添加您的第一个资产吧</span>} />
            ) : (
              <Table columns={assetColumns} dataSource={assets} rowKey="id" loading={loading} pagination={false} className="assets-table" />
            )}
          </Card>

          {/* AI Chat Interface */}
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
                  针对 {project.name} 的智能对话
                </span>
              </span>
            }
          >
            <div style={{ height: '500px' }}>
              <ChatInterface projectId={projectId} projectName={project.name} />
            </div>
          </Card>
        </Content>
      </Layout>

      <Modal
        title="添加资产"
        open={assetModalVisible}
        onCancel={() => { setAssetModalVisible(false); form.resetFields() }}
        footer={null}
        width={500}
        centered
        className="asset-modal"
      >
        <Form form={form} layout="vertical" onFinish={handleCreateAsset} className="asset-form">
          <Form.Item label="资产类型" name="asset_type" rules={[{ required: true, message: '请选择资产类型' }]}>
            <Select placeholder="请选择资产类型" size="large">
              <Select.Option value="ip"><Space><CloudServerOutlined /><span>IP 地址</span></Space></Select.Option>
              <Select.Option value="domain"><Space><GlobalOutlined /><span>域名</span></Space></Select.Option>
              <Select.Option value="cloud_resource"><Space><DatabaseOutlined /><span>云资源</span></Space></Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="资产值" name="value" rules={[{ required: true, message: '请输入资产值' }]}>
            <Input placeholder="例如：192.168.1.1 或 example.com" size="large" />
          </Form.Item>
          <Form.Item label="资产名称" name="name">
            <Input placeholder="请输入资产名称（可选）" size="large" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block size="large" className="create-btn">添加资产</Button>
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default ProjectDetail
