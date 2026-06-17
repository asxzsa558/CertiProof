import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Layout, Menu, Card, Button, Table, Tag, Avatar, Dropdown, Space, Spin, Modal, Form, Input, Select, Switch, message, Badge, Timeline } from 'antd'
import { 
  ProjectOutlined, LogoutOutlined, UserOutlined, SettingOutlined,
  BellOutlined, SafetyCertificateOutlined, ArrowLeftOutlined,
  PlusOutlined, PlayCircleOutlined, PauseCircleOutlined, DeleteOutlined,
  ClockCircleOutlined, CheckCircleOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import api from '../services/api'
import './Monitoring.css'

const { Header, Content, Sider } = Layout

function Monitoring() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [assets, setAssets] = useState([])
  const [scheduledScans, setScheduledScans] = useState([])
  const [scanHistory, setScanHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()
  const logout = useAuthStore((state) => state.logout)

  useEffect(() => {
    fetchProject()
    fetchAssets()
    fetchScheduledScans()
    fetchScanHistory()
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
    }
  }

  const fetchScheduledScans = async () => {
    try {
      const response = await api.get(`/projects/${projectId}/monitoring/scheduled`)
      setScheduledScans(response.data)
    } catch (error) {
      console.error('Failed to fetch scheduled scans:', error)
    }
  }

  const fetchScanHistory = async () => {
    try {
      const response = await api.get(`/projects/${projectId}/monitoring/history`)
      setScanHistory(response.data)
    } catch (error) {
      console.error('Failed to fetch scan history:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateScheduledScan = async (values) => {
    try {
      await api.post(`/projects/${projectId}/monitoring/scheduled`, values)
      message.success('定时扫描创建成功')
      setModalVisible(false)
      form.resetFields()
      fetchScheduledScans()
    } catch (error) {
      message.error(error.response?.data?.detail || '创建失败')
    }
  }

  const handleToggleActive = async (scanId, isActive) => {
    try {
      await api.put(`/projects/${projectId}/monitoring/scheduled/${scanId}`, {
        is_active: isActive,
      })
      message.success(isActive ? '已启用' : '已暂停')
      fetchScheduledScans()
    } catch (error) {
      message.error('操作失败')
    }
  }

  const handleRunNow = async (scanId) => {
    try {
      const response = await api.post(`/projects/${projectId}/monitoring/scheduled/${scanId}/run`)
      message.success(`扫描完成！发现 ${response.data.findings_count} 个问题`)
      fetchScheduledScans()
      fetchScanHistory()
    } catch (error) {
      message.error(error.response?.data?.detail || '扫描失败')
    }
  }

  const handleDelete = async (scanId) => {
    try {
      await api.delete(`/projects/${projectId}/monitoring/scheduled/${scanId}`)
      message.success('已删除')
      fetchScheduledScans()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handleLogout = () => { logout(); navigate('/login') }

  const getFrequencyText = (freq) => {
    const texts = { daily: '每天', weekly: '每周', monthly: '每月' }
    return texts[freq] || freq
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <div>
          <div style={{ fontWeight: 600, color: '#fff' }}>{name}</div>
          <div style={{ fontSize: '0.8125rem', color: 'rgba(255,255,255,0.5)' }}>
            {getFrequencyText(record.frequency)}执行
          </div>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (isActive, record) => (
        <Switch
          checked={isActive}
          onChange={(checked) => handleToggleActive(record.id, checked)}
          checkedChildren="启用"
          unCheckedChildren="暂停"
        />
      ),
    },
    {
      title: '上次执行',
      dataIndex: 'last_run_at',
      key: 'last_run_at',
      width: 150,
      render: (date) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: '下次执行',
      dataIndex: 'next_run_at',
      key: 'next_run_at',
      width: 150,
      render: (date) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, record) => (
        <Space>
          <Button
            type="primary"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => handleRunNow(record.id)}
            className="action-btn"
          >
            立即执行
          </Button>
          <Button
            size="small"
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.id)}
            danger
          />
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
      <Layout className="monitoring-loading">
        <Spin size="large" />
      </Layout>
    )
  }

  return (
    <Layout className="monitoring-layout">
      <Sider width={260} className="monitoring-sider">
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

      <Layout className="monitoring-main">
        <Header className="monitoring-header">
          <div className="header-left">
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/projects/${projectId}`)} className="back-btn">
              返回
            </Button>
            <div className="header-info">
              <h1 className="page-title">持续监控</h1>
              <p className="page-subtitle">{project.name} - 定时扫描与变更检测</p>
            </div>
          </div>
          <Space size="large" className="header-right">
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setModalVisible(true)}
              className="create-btn"
            >
              创建定时扫描
            </Button>
            <Button icon={<BellOutlined />} type="text" className="header-icon-btn" />
            <Dropdown menu={{ items: userMenuItems, onClick: ({ key }) => key === 'logout' && handleLogout() }} placement="bottomRight">
              <Space className="user-menu-trigger">
                <Avatar style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }} icon={<UserOutlined />} />
              </Space>
            </Dropdown>
          </Space>
        </Header>

        <Content className="monitoring-content">
          {/* Scheduled Scans */}
          <Card className="scheduled-card" title="定时扫描任务">
            <Table
              columns={columns}
              dataSource={scheduledScans}
              rowKey="id"
              loading={loading}
              pagination={false}
              className="scheduled-table"
            />
          </Card>

          {/* Scan History */}
          <Card className="history-card" title="扫描历史">
            {scanHistory.length === 0 ? (
              <div className="empty-history">暂无扫描历史</div>
            ) : (
              <Timeline className="scan-timeline">
                {scanHistory.map((history) => (
                  <Timeline.Item
                    key={history.id}
                    color={history.changes_detected ? 'orange' : 'green'}
                    dot={history.changes_detected ? <WarningOutlined /> : <CheckCircleOutlined />}
                  >
                    <div className="timeline-content">
                      <div className="timeline-header">
                        <span>扫描任务 #{history.scan_task_id}</span>
                        <span className="timeline-time">
                          {new Date(history.executed_at).toLocaleString()}
                        </span>
                      </div>
                      {history.changes_detected && (
                        <div className="timeline-changes">
                          <Tag color="orange">检测到变更</Tag>
                          {history.changes_summary && (
                            <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.8125rem' }}>
                              开放端口: {history.changes_summary.open_ports || 0}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </Timeline.Item>
                ))}
              </Timeline>
            )}
          </Card>
        </Content>
      </Layout>

      {/* Create Scheduled Scan Modal */}
      <Modal
        title="创建定时扫描"
        open={modalVisible}
        onCancel={() => { setModalVisible(false); form.resetFields() }}
        footer={null}
        width={500}
        centered
        className="create-modal"
      >
        <Form form={form} layout="vertical" onFinish={handleCreateScheduledScan} className="create-form">
          <Form.Item label="任务名称" name="name" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input placeholder="例如：每日安全扫描" size="large" />
          </Form.Item>
          <Form.Item label="扫描资产" name="asset_id" rules={[{ required: true, message: '请选择资产' }]}>
            <Select placeholder="选择要扫描的资产" size="large">
              {assets.filter(a => a.verification_status === 'verified').map(asset => (
                <Select.Option key={asset.id} value={asset.id}>
                  {asset.value} ({asset.name || asset.asset_type})
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item label="执行频率" name="frequency" rules={[{ required: true, message: '请选择频率' }]}>
            <Select placeholder="选择执行频率" size="large">
              <Select.Option value="daily">每天</Select.Option>
              <Select.Option value="weekly">每周</Select.Option>
              <Select.Option value="monthly">每月</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="变更通知" name="notify_on_change" valuePropName="checked" initialValue={true}>
            <Switch checkedChildren="开启" unCheckedChildren="关闭" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block size="large" className="create-btn">
              创建
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default Monitoring
