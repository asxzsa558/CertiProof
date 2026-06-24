import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Avatar, Dropdown, Space, Button, Tooltip, Modal, Form, Input, Select, message, Tag, Popconfirm, Table, Badge, Tabs } from 'antd'
import {
  ProjectOutlined,
  LogoutOutlined,
  UserOutlined,
  SettingOutlined,
  BellOutlined,
  HistoryOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  FileSearchOutlined,
  CloudServerOutlined,
  DeleteOutlined,
  EditOutlined,
  ArrowLeftOutlined,
  AppstoreOutlined,
  UpOutlined,
  DownOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import ChatWorkspace from '../components/ChatWorkspace'
import SystemConfig from '../components/SystemConfig'
import AssessmentProgress from '../components/AssessmentProgress'
import VeriSureLogo from '../components/VeriSureLogo'
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
  const [showManager, setShowManager] = useState(false)
  const [managerProject, setManagerProject] = useState(null)
  const [projectModalVisible, setProjectModalVisible] = useState(false)
  const [projectModalMode, setProjectModalMode] = useState('create')
  const [projectForm] = Form.useForm()
  const [assets, setAssets] = useState([])
  const [assetModalVisible, setAssetModalVisible] = useState(false)
  const [assetForm] = Form.useForm()
  const [managerAssets, setManagerAssets] = useState([])
  const [batchAssets, setBatchAssets] = useState('')
  const [assetsExpanded, setAssetsExpanded] = useState(true)

  useEffect(() => {
    fetchProjects()
  }, [])

  useEffect(() => {
    if (selectedProject) {
      fetchAssets(selectedProject.id)
    } else {
      setAssets([])
    }
  }, [selectedProject])

  useEffect(() => {
    if (managerProject) {
      fetchManagerAssets(managerProject.id)
    }
  }, [managerProject])

  const fetchProjects = async () => {
    try {
      const response = await api.get('/projects/')
      setProjects(response.data)
      if (response.data.length > 0 && !selectedProject) {
        setSelectedProject(response.data[0])
      }
    } catch (error) {
      console.error('Failed to fetch projects:', error)
    }
  }

  const fetchAssets = async (projectId) => {
    try {
      const response = await api.get(`/projects/${projectId}/assets/`)
      setAssets(response.data)
    } catch (error) {
      console.error('Failed to fetch assets:', error)
      setAssets([])
    }
  }

  const fetchManagerAssets = async (projectId) => {
    try {
      const response = await api.get(`/projects/${projectId}/assets/`)
      setManagerAssets(response.data)
    } catch (error) {
      console.error('Failed to fetch assets:', error)
      setManagerAssets([])
    }
  }

  const handleNewAsset = () => {
    assetForm.resetFields()
    setAssetModalVisible(true)
  }

  const handleSubmitNewAsset = async () => {
    try {
      const values = await assetForm.validateFields()
      const targetProject = managerProject || selectedProject
      await api.post(`/projects/${targetProject.id}/assets/`, values)
      message.success('资产添加成功')
      setAssetModalVisible(false)
      if (managerProject) {
        fetchManagerAssets(managerProject.id)
      }
      if (selectedProject) {
        fetchAssets(selectedProject.id)
      }
    } catch (error) {
      message.error(error.response?.data?.detail || '添加失败')
    }
  }

  const handleDeleteAsset = async (assetId) => {
    try {
      const targetProject = managerProject || selectedProject
      await api.delete(`/projects/${targetProject.id}/assets/${assetId}`)
      message.success('资产已删除')
      if (managerProject) {
        fetchManagerAssets(managerProject.id)
      }
      if (selectedProject) {
        fetchAssets(selectedProject.id)
      }
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handleSubmitBatchAssets = async () => {
    const targetProject = managerProject || selectedProject
    if (!targetProject) {
      message.error('请先选择项目')
      return
    }
    
    const lines = batchAssets.split('\n').filter(line => line.trim())
    if (lines.length === 0) {
      message.error('请输入资产信息')
      return
    }
    
    let successCount = 0
    let failCount = 0
    
    for (const line of lines) {
      const parts = line.trim().split(/\s+/)
      if (parts.length < 2) {
        failCount++
        continue
      }
      
      const assetType = parts[0].toLowerCase()
      const value = parts[1]
      const name = parts.slice(2).join(' ') || ''
      
      if (!['ip', 'domain', 'cloud_resource'].includes(assetType)) {
        failCount++
        continue
      }
      
      try {
        await api.post(`/projects/${targetProject.id}/assets/`, {
          asset_type: assetType,
          value: value,
          name: name,
        })
        successCount++
      } catch (error) {
        failCount++
      }
    }
    
    if (successCount > 0) {
      message.success(`成功添加 ${successCount} 个资产`)
      if (managerProject) {
        fetchManagerAssets(managerProject.id)
      }
      if (selectedProject) {
        fetchAssets(selectedProject.id)
      }
    }
    if (failCount > 0) {
      message.warning(`${failCount} 个资产添加失败`)
    }
    
    setBatchAssets('')
    setAssetModalVisible(false)
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const handleSelectProject = (project) => {
    setSelectedProject(project)
  }

  const handleNewProject = () => {
    projectForm.resetFields()
    setProjectModalMode('create')
    setProjectModalVisible(true)
  }

  const handleEditProject = (project) => {
    projectForm.setFieldsValue({
      name: project.name,
      description: project.description,
      compliance_level: project.compliance_level,
    })
    setProjectModalMode('edit')
    setProjectModalVisible(true)
  }

  const handleSubmitProject = async () => {
    try {
      const values = await projectForm.validateFields()
      if (projectModalMode === 'create') {
        const response = await api.post('/projects/', values)
        message.success('项目创建成功')
        setSelectedProject(response.data)
      } else {
        await api.put(`/projects/${managerProject.id}`, values)
        message.success('项目更新成功')
        const updated = { ...managerProject, ...values }
        setManagerProject(updated)
        setSelectedProject(updated)
      }
      setProjectModalVisible(false)
      fetchProjects()
    } catch (error) {
      message.error(error.response?.data?.detail || '操作失败')
    }
  }

  const handleDeleteProject = async (projectId) => {
    try {
      await api.delete(`/projects/${projectId}`)
      message.success('项目已删除')
      if (managerProject?.id === projectId) {
        setManagerProject(null)
      }
      if (selectedProject?.id === projectId) {
        setSelectedProject(null)
      }
      fetchProjects()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handleOpenManager = (project) => {
    setManagerProject(project)
    setShowManager(true)
  }

  const handleCloseManager = () => {
    setShowManager(false)
    setManagerProject(null)
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

  const managerAssetColumns = [
    {
      title: '类型',
      dataIndex: 'asset_type',
      key: 'asset_type',
      width: 80,
      render: (type) => (
        <Tag color={type === 'ip' ? 'blue' : type === 'domain' ? 'green' : 'purple'}>
          {type === 'ip' ? 'IP' : type === 'domain' ? '域名' : '云资源'}
        </Tag>
      ),
    },
    {
      title: '资产值',
      dataIndex: 'value',
      key: 'value',
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name) => name || '-',
    },
    {
      title: '验证状态',
      dataIndex: 'verification_status',
      key: 'verification_status',
      width: 100,
      render: (status) => (
        <Tag color={status === 'verified' ? 'success' : status === 'failed' ? 'error' : 'default'}>
          {status === 'verified' ? '已验证' : status === 'failed' ? '失败' : '待验证'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_, record) => (
        <Popconfirm
          title="确定删除此资产？"
          onConfirm={() => handleDeleteAsset(record.id)}
          okText="删除"
          cancelText="取消"
        >
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <Layout className="chat-page-layout">
      {/* Left Sidebar */}
      <Sider
        width={280}
        collapsed={siderCollapsed}
        collapsedWidth={0}
        trigger={null}
        className="chat-sider"
      >
        <div className="sider-header">
          <div className="sider-logo">
            <VeriSureLogo size={56} />
            <span className="logo-text">VeriSure</span>
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
              <div key={project.id}>
                <div
                  className={`project-item ${selectedProject?.id === project.id && !showManager ? 'active' : ''}`}
                  onClick={() => {
                    handleSelectProject(project)
                    if (showManager) setShowManager(false)
                  }}
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
                  <Space size={0}>
                    <Tooltip title="管理项目">
                      <Button
                        type="text"
                        size="small"
                        icon={<SettingOutlined />}
                        onClick={(e) => {
                          e.stopPropagation()
                          handleOpenManager(project)
                        }}
                        className="project-manage-btn"
                      />
                    </Tooltip>
                    <Tooltip title="查看扫描结果">
                      <Button
                        type="text"
                        size="small"
                        icon={<FileSearchOutlined />}
                        onClick={(e) => {
                          e.stopPropagation()
                          navigate(`/projects/${project.id}/results`)
                        }}
                        className="project-results-btn"
                      />
                    </Tooltip>
                  </Space>
                </div>
                {/* Inline assets for selected project */}
                {selectedProject?.id === project.id && !showManager && (
                  <div className="inline-assets">
                    <div className="inline-assets-header">
                      <CloudServerOutlined style={{ marginRight: 4 }} />
                      <span>资产</span>
                      <Badge count={assets.length} size="small" style={{ backgroundColor: '#6366f1', marginLeft: 4 }} />
                      <Button
                        type="text"
                        size="small"
                        icon={<PlusOutlined />}
                        onClick={(e) => {
                          e.stopPropagation()
                          handleNewAsset()
                        }}
                        className="add-asset-btn"
                      />
                      <Button
                        type="text"
                        size="small"
                        icon={assetsExpanded ? <UpOutlined /> : <DownOutlined />}
                        onClick={(e) => {
                          e.stopPropagation()
                          setAssetsExpanded(!assetsExpanded)
                        }}
                        className="toggle-assets-btn"
                      />
                    </div>
                    {assetsExpanded && (
                      <>
                        {assets.length === 0 ? (
                          <div className="empty-assets-inline">
                            <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); handleNewAsset() }}>
                              + 添加资产
                            </Button>
                          </div>
                        ) : (
                          assets.slice(0, 5).map((asset) => (
                            <div key={asset.id} className="asset-item-inline" onClick={(e) => e.stopPropagation()}>
                              <Tag color={asset.asset_type === 'ip' ? 'blue' : asset.asset_type === 'domain' ? 'green' : 'purple'} className="asset-type-tag">
                                {asset.asset_type === 'ip' ? 'IP' : asset.asset_type === 'domain' ? '域名' : '云'}
                              </Tag>
                              <span className="asset-value">{asset.value}</span>
                              <Popconfirm
                                title="确定删除？"
                                onConfirm={() => handleDeleteAsset(asset.id)}
                                okText="删除"
                                cancelText="取消"
                              >
                                <Button type="text" size="small" icon={<DeleteOutlined />} className="delete-asset-btn" />
                              </Popconfirm>
                            </div>
                          ))
                        )}
                        {assets.length > 5 && (
                          <div className="more-assets-hint" onClick={(e) => { e.stopPropagation(); handleOpenManager(project) }}>
                            还有 {assets.length - 5} 个资产...
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
            {projects.length === 0 && (
              <div className="empty-projects">
                <p>还没有项目</p>
                <p>点击"新建项目"开始</p>
              </div>
            )}
          </div>
          
          {/* Assessment Progress - 显示在侧边栏底部 */}
          {selectedProject && !showManager && (
            <div className="sider-assessment-section">
              <AssessmentProgress 
                projectId={selectedProject.id} 
                projectName={selectedProject.name} 
              />
            </div>
          )}
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
            {showManager ? (
              <div className="current-project">
                <Button
                  type="text"
                  icon={<ArrowLeftOutlined />}
                  onClick={handleCloseManager}
                  className="back-to-chat-btn"
                >
                  返回对话
                </Button>
                <span className="current-project-name">{managerProject?.name} - 项目管理</span>
              </div>
            ) : selectedProject && (
              <div className="current-project">
                <span className="current-project-name">{selectedProject.name}</span>
                <span className="current-project-level">{selectedProject.compliance_level}</span>
              </div>
            )}
          </div>
          {!showManager && (
            <Space size="middle">
              <SystemConfig value={selectedModel} onChange={setSelectedModel} />
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
          )}
        </Header>

        {/* Content */}
        <Content className="chat-page-content">
          {showManager ? (
            <div className="project-manager">
              <div className="manager-section">
                <div className="manager-section-header">
                  <h3>项目信息</h3>
                  <Space>
                    <Button icon={<EditOutlined />} onClick={() => handleEditProject(managerProject)}>
                      编辑项目
                    </Button>
                    <Popconfirm
                      title="确定删除此项目？所有相关数据将一并删除。"
                      onConfirm={() => {
                        handleDeleteProject(managerProject.id)
                        handleCloseManager()
                      }}
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                    >
                      <Button danger icon={<DeleteOutlined />}>
                        删除项目
                      </Button>
                    </Popconfirm>
                  </Space>
                </div>
                <div className="project-info-grid">
                  <div className="info-item">
                    <span className="info-label">项目名称</span>
                    <span className="info-value">{managerProject?.name}</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">等保等级</span>
                    <span className="info-value">{managerProject?.compliance_level}</span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">合规分数</span>
                    <span className="info-value" style={{ color: getScoreColor(managerProject?.compliance_score || 0) }}>
                      {managerProject?.compliance_score ?? '未检测'} 分
                    </span>
                  </div>
                  <div className="info-item">
                    <span className="info-label">描述</span>
                    <span className="info-value">{managerProject?.description || '无'}</span>
                  </div>
                </div>
              </div>

              <div className="manager-section">
                <div className="manager-section-header">
                  <h3>
                    <CloudServerOutlined style={{ marginRight: 8 }} />
                    资产管理
                    <Badge count={managerAssets.length} size="small" style={{ backgroundColor: '#6366f1', marginLeft: 8 }} />
                  </h3>
                  <Button type="primary" icon={<PlusOutlined />} onClick={handleNewAsset}>
                    添加资产
                  </Button>
                </div>
                <Table
                  columns={managerAssetColumns}
                  dataSource={managerAssets}
                  rowKey="id"
                  pagination={false}
                  size="small"
                  className="manager-table"
                  locale={{ emptyText: '暂无资产，点击上方按钮添加' }}
                />
              </div>
            </div>
          ) : (
            <ChatWorkspace
              key={selectedProject?.id || 'default'}
              projectId={selectedProject?.id}
              projectName={selectedProject?.name}
              modelId={selectedModel}
            />
          )}
        </Content>
      </Layout>

      {/* Project Modal (Create/Edit) */}
      <Modal
        title={projectModalMode === 'create' ? '新建项目' : '编辑项目'}
        open={projectModalVisible}
        onOk={handleSubmitProject}
        onCancel={() => setProjectModalVisible(false)}
        okText={projectModalMode === 'create' ? '创建' : '保存'}
        cancelText="取消"
      >
        <Form form={projectForm} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="例如：我的电商网站" />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea placeholder="描述项目的用途和特点（可选）" rows={3} />
          </Form.Item>
          <Form.Item name="compliance_level" label="等保等级" rules={[{ required: true, message: '请选择等保等级' }]}>
            <Select placeholder="选择等保等级">
              <Select.Option value="二级">等保二级</Select.Option>
              <Select.Option value="三级">等保三级</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* Asset Modal */}
      <Modal
        title="添加资产"
        open={assetModalVisible}
        onOk={handleSubmitNewAsset}
        onCancel={() => { setAssetModalVisible(false); setBatchAssets('') }}
        okText="添加"
        cancelText="取消"
        footer={null}
      >
        <Tabs
          defaultActiveKey="single"
          items={[
            {
              key: 'single',
              label: '单个添加',
              children: (
                <Form form={assetForm} layout="vertical">
                  <Form.Item name="asset_type" label="资产类型" rules={[{ required: true, message: '请选择资产类型' }]}>
                    <Select placeholder="选择资产类型">
                      <Select.Option value="ip">IP 地址</Select.Option>
                      <Select.Option value="domain">域名</Select.Option>
                      <Select.Option value="cloud_resource">云资源</Select.Option>
                    </Select>
                  </Form.Item>
                  <Form.Item name="value" label="资产值" rules={[{ required: true, message: '请输入资产值' }]}>
                    <Input placeholder="例如：192.168.1.1 或 example.com" />
                  </Form.Item>
                  <Form.Item name="name" label="资产名称">
                    <Input placeholder="可选，例如：生产服务器" />
                  </Form.Item>
                  <Form.Item>
                    <Button type="primary" onClick={async () => {
                      try {
                        await handleSubmitNewAsset()
                        assetForm.resetFields()
                      } catch (e) {}
                    }}>
                      添加
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
            {
              key: 'batch',
              label: '批量添加',
              children: (
                <div>
                  <p style={{ color: 'rgba(255,255,255,0.6)', marginBottom: 12 }}>
                    每行一个资产，格式：<code>类型 值 [名称]</code>
                  </p>
                  <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: 12, marginBottom: 12 }}>
                    类型：ip / domain / cloud_resource
                  </p>
                  <Input.TextArea
                    rows={8}
                    value={batchAssets}
                    onChange={(e) => setBatchAssets(e.target.value)}
                    placeholder={`ip 192.168.1.1 生产服务器
domain example.com 官网
ip 10.0.0.1 内网服务器`}
                  />
                  <Button type="primary" style={{ marginTop: 16 }} onClick={handleSubmitBatchAssets}>
                    批量添加
                  </Button>
                </div>
              ),
            },
          ]}
        />
      </Modal>
    </Layout>
  )
}

export default ChatPage
