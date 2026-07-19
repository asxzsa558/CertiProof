import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Layout, Avatar, Dropdown, Space, Button, Tooltip, Modal, Form, Input, Select, message, Tag, Popconfirm, Table, Badge, Tabs } from 'antd'
import {
  ProjectOutlined,
  LogoutOutlined,
  UserOutlined,
  SettingOutlined,
  BellOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  FileSearchOutlined,
  CloudServerOutlined,
  DeleteOutlined,
  EditOutlined,
  ArrowLeftOutlined,
  DashboardOutlined,
  ControlOutlined,
  FileTextOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import SystemConfig from '../components/SystemConfig'
import AssessmentProgress from '../components/AssessmentProgress'
import ProjectCommandCenter from '../components/ProjectCommandCenter'
import VeriSureLogo from '../components/VeriSureLogo'
import api from '../services/api'
import './ChatPage.css'

const { Header, Sider, Content } = Layout

const PERMISSION_LABELS = {
  'project:read': '查看项目',
  'project:create': '创建项目',
  'project:update': '编辑项目',
  'project:delete': '删除项目',
  'asset:read': '查看资产',
  'asset:create': '添加资产',
  'asset:update': '编辑资产',
  'asset:delete': '删除资产',
  'scan:execute': '执行检测',
  'scan:read': '查看检测',
  'scan:cancel': '取消检测',
  'assessment:read': '查看测评',
  'assessment:manage': '管理测评',
  'evidence:manage': '管理证据',
  'report:read': '查看报告',
  'report:export': '导出报告',
  'report:delete': '删除报告版本',
  'role:read': '查看角色',
  'role:manage': '管理角色',
  'member:manage': '管理成员',
  'system:config': '系统配置',
  'tool:diagnose': '工具诊断',
}

function ChatPage() {
  const navigate = useNavigate()
  const { projectId: urlProjectId } = useParams()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const organizations = useAuthStore((state) => state.organizations)
  const [selectedProject, setSelectedProject] = useState(null)
  const [selectedModel, setSelectedModel] = useState(null)
  const [siderCollapsed, setSiderCollapsed] = useState(false)
  const [showManager, setShowManager] = useState(false)
  const [managerProject, setManagerProject] = useState(null)
  const [projectModalVisible, setProjectModalVisible] = useState(false)
  const [projectForm] = Form.useForm()
  const [assets, setAssets] = useState([])
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [assetModalVisible, setAssetModalVisible] = useState(false)
  const [assetForm] = Form.useForm()
  const [managerAssets, setManagerAssets] = useState([])
  const [batchAssets, setBatchAssets] = useState('')
  const [workspaceSummary, setWorkspaceSummary] = useState({})
  const [profileVisible, setProfileVisible] = useState(false)
  const [currentPermissions, setCurrentPermissions] = useState([])

  useEffect(() => {
    fetchProjects()
  }, [urlProjectId, currentOrgId])

  useEffect(() => {
    if (!currentOrgId) {
      setCurrentPermissions([])
      return
    }
    api.get('/dashboard/organization-command', { params: { organization_id: currentOrgId } })
      .then((response) => setCurrentPermissions(response.data?.current_role?.permissions || []))
      .catch(() => setCurrentPermissions([]))
  }, [currentOrgId])

  useEffect(() => {
    if (selectedProject) {
      localStorage.setItem('lastProjectId', String(selectedProject.id))
      fetchAssets(selectedProject.id)
    } else {
      setAssets([])
      setAssetsLoading(false)
    }
  }, [selectedProject])

  useEffect(() => {
    if (managerProject) {
      fetchManagerAssets(managerProject.id)
    }
  }, [managerProject])

  const fetchProjects = async () => {
    try {
      const response = await api.get('/projects/', {
        params: currentOrgId ? { organization_id: currentOrgId } : undefined,
      })
      // 如果 URL 中有 projectId，优先选择该项目
      if (urlProjectId) {
        const urlProject = response.data.find(p => p.id === parseInt(urlProjectId))
        if (urlProject) {
          setSelectedProject(urlProject)
          return
        }
      }
      
      // 从 localStorage 读取上次访问的项目
      const lastProjectId = localStorage.getItem('lastProjectId')
      if (lastProjectId && response.data.length > 0) {
        const lastProject = response.data.find(p => p.id === parseInt(lastProjectId))
        if (lastProject) {
          setSelectedProject(lastProject)
          if (urlProjectId) navigate(`/projects/${lastProject.id}`, { replace: true })
          return
        }
      }
      
      // 否则选择第一个项目
      if (response.data.length > 0 && !selectedProject) {
        setSelectedProject(response.data[0])
        if (urlProjectId) navigate(`/projects/${response.data[0].id}`, { replace: true })
      } else if (response.data.length === 0) {
        setSelectedProject(null)
        navigate('/projects', { replace: true })
      }
    } catch (error) {
      console.error('Failed to fetch projects:', error)
    }
  }

  const fetchAssets = async (projectId) => {
    setAssetsLoading(true)
    try {
      const response = await api.get(`/projects/${projectId}/assets/`)
      setAssets(response.data)
    } catch (error) {
      console.error('Failed to fetch assets:', error)
      message.error('获取资产列表失败，请检查项目是否存在')
      setAssets([])
    } finally {
      setAssetsLoading(false)
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

  const handleUserMenu = ({ key }) => {
    if (key === 'profile') setProfileVisible(true)
    if (key === 'settings') navigate('/settings/models')
    if (key === 'logout') handleLogout()
  }

  const handleEditProject = (project) => {
    projectForm.setFieldsValue({
      name: project.name,
      description: project.description,
      compliance_level: project.compliance_level,
    })
    setProjectModalVisible(true)
  }

  const handleSubmitProject = async () => {
    try {
      const values = await projectForm.validateFields()
      await api.put(`/projects/${managerProject.id}`, values)
      message.success('项目更新成功')
      const updated = { ...managerProject, ...values }
      setManagerProject(updated)
      setSelectedProject(updated)
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
      const status = error.response?.status
      const detail = error.response?.data?.detail
      if (status === 404) {
        message.error('项目不存在或您无权删除')
      } else if (status === 403) {
        message.error('权限不足')
      } else {
        message.error(detail || '删除失败')
      }
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
      title: '资产类型',
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
      title: '所属项目',
      key: 'project',
      width: 150,
      render: () => managerProject?.name || selectedProject?.name || '-',
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

  const navItems = [
    { key: 'dashboard', title: '态势总览', label: '总览', icon: <DashboardOutlined />, action: () => navigate('/dashboard') },
    { key: 'projects', title: '项目与资产', label: '项目', icon: <ProjectOutlined />, action: () => navigate('/projects') },
    { key: 'assets', title: '资产清单', label: '资产', icon: <CloudServerOutlined />, action: () => navigate('/projects?view=assets') },
    { key: 'assessment', title: '等保测评', label: '测评', icon: <SafetyCertificateOutlined />, active: true, action: () => setSiderCollapsed(false) },
    { key: 'results', title: '检测结果', label: '结果', icon: <FileSearchOutlined />, action: () => selectedProject && navigate(`/projects/${selectedProject.id}/results`) },
    { key: 'reports', title: '报告中心', label: '报告', icon: <FileTextOutlined />, action: () => navigate('/reports') },
  ]

  return (
    <Layout className="chat-page-layout workspace-page-layout">
      <Header className="chat-page-header workspace-global-header">
        <div className="workspace-global-brand">
          <VeriSureLogo size={38} className="workspace-flat-logo" />
          <strong>CertiProof</strong>
        </div>
        <div className="header-left">
          {showManager ? (
            <div className="current-project">
              <Button type="text" icon={<ArrowLeftOutlined />} onClick={handleCloseManager} className="back-to-chat-btn">
                返回项目对话
              </Button>
              <span className="current-project-name">{managerProject?.name} - 项目管理</span>
            </div>
          ) : selectedProject && (
            <div className="workspace-breadcrumb">
              <span>项目</span><i>/</i><strong>{selectedProject.name}</strong>
            </div>
          )}
        </div>
        {!showManager && (
          <>
            <div className="workspace-header-metrics">
              <div className="workspace-online"><i />在线</div>
              <div><span>合规分</span><strong style={{ color: getScoreColor(workspaceSummary.score ?? selectedProject?.compliance_score ?? 0) }}>{workspaceSummary.score ?? selectedProject?.compliance_score ?? '—'}</strong></div>
              <div><span>可靠覆盖率</span><strong className="good">{Number.isFinite(workspaceSummary.coverage) ? `${workspaceSummary.coverage}%` : '—'}</strong></div>
              <div><span>待处理</span><strong className="danger">{workspaceSummary.open ?? '—'}</strong></div>
            </div>
            <Space size="small" className="workspace-header-actions">
              <Tooltip title="检测记录">
                <Button icon={<FileSearchOutlined />} type="text" className="header-icon-btn" onClick={() => selectedProject && navigate(`/projects/${selectedProject.id}/results`)} />
              </Tooltip>
              <SystemConfig
                value={selectedModel}
                onChange={setSelectedModel}
                projectId={selectedProject?.id}
                projectName={selectedProject?.name}
                organizationId={currentOrgId}
              />
              <Tooltip title="通知">
                <Button icon={<BellOutlined />} type="text" className="header-icon-btn" />
              </Tooltip>
              <Dropdown
                menu={{
                  items: userMenuItems,
                  onClick: handleUserMenu,
                }}
                placement="bottomRight"
              >
                <Space className="user-menu-trigger" role="button" tabIndex={0} aria-label="打开账户菜单">
                  <Avatar size={32} style={{ background: '#153249' }} icon={<UserOutlined />} />
                  <span className="user-name">{user?.username}</span>
                </Space>
              </Dropdown>
            </Space>
          </>
        )}
      </Header>

      <Layout className="workspace-body-layout">
      <Sider width={84} trigger={null} className="workspace-nav-rail">
        <nav className="workspace-rail-nav" aria-label="项目工作台导航">
          {navItems.map(item => (
            <Tooltip key={item.key} title={item.title} placement="right">
              <Button
                type="text"
                icon={item.icon}
                onClick={item.action}
                className={`workspace-rail-button ${item.active ? 'active' : ''}`}
                aria-label={item.title}
              >
                <span>{item.label || item.title.replace('（待完善）', '')}</span>
              </Button>
            </Tooltip>
          ))}
        </nav>
        <div className="workspace-rail-footer">
          <Tooltip title="项目设置" placement="right">
            <Button
              type="text"
              icon={<ControlOutlined />}
              onClick={() => selectedProject && handleOpenManager(selectedProject)}
              className={`workspace-rail-button ${showManager ? 'active' : ''}`}
              aria-label="项目设置"
            >
              <span>设置</span>
            </Button>
          </Tooltip>
        </div>
      </Sider>

      {siderCollapsed && (
        <div className="assessment-reopen-rail">
          <Tooltip title="展开等保自查流程" placement="right">
            <Button
              type="text"
              icon={<MenuUnfoldOutlined />}
              onClick={() => setSiderCollapsed(false)}
              aria-label="展开等保自查流程"
            />
          </Tooltip>
        </div>
      )}

      {!siderCollapsed && (
        <Sider
          width={360}
          trigger={null}
          className="workspace-assessment-sider"
        >
          <div className="assessment-drawer-header">
            <strong className="assessment-drawer-kicker">等保自查流程</strong>
            <Tooltip title="收起测评栏">
              <Button type="text" icon={<MenuFoldOutlined />} onClick={() => setSiderCollapsed(true)} aria-label="收起测评栏" />
            </Tooltip>
          </div>
          <div className="assessment-drawer-scroll">
            {selectedProject && (
              <div className="assessment-drawer-flow">
                <AssessmentProgress
                  projectId={selectedProject.id}
                  projectName={selectedProject.name}
                  variant="cockpit"
                  openIssues={workspaceSummary.open}
                />
              </div>
            )}
          </div>
        </Sider>
      )}

      <Layout className="chat-main-layout">
        <Content className="chat-page-content">
          {showManager ? (
            <div className="project-manager">
              <div className="project-manager-toolbar">
                <Button type="primary" icon={<ArrowLeftOutlined />} onClick={handleCloseManager}>
                  返回项目对话
                </Button>
                <div>
                  <strong>项目设置</strong>
                  <span>{managerProject?.name} · {managerProject?.compliance_level || '未设置等级'} · {managerAssets.length} 个资产</span>
                </div>
              </div>
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
                  <div>
                    <h3>
                      <CloudServerOutlined style={{ marginRight: 8 }} />
                      项目资产
                      <Badge count={managerAssets.length} size="small" style={{ backgroundColor: '#6366f1', marginLeft: 8 }} />
                    </h3>
                    <p className="manager-section-context">所属项目：{managerProject?.name || '-'}</p>
                  </div>
                  <Button type="primary" icon={<PlusOutlined />} onClick={handleNewAsset}>
                    添加资产
                  </Button>
                </div>
                <Table
                  columns={managerAssetColumns}
                  dataSource={managerAssets}
                  rowKey="id"
                  pagination={false}
                  scroll={{ x: 720 }}
                  size="small"
                  className="manager-table"
                  locale={{ emptyText: '暂无资产，点击上方按钮添加' }}
                />
              </div>
            </div>
          ) : (
            <ProjectCommandCenter
              project={selectedProject}
              assets={assets}
              assetsLoading={assetsLoading}
              assessmentCollapsed={siderCollapsed}
              modelId={selectedModel}
              onOpenResults={() => selectedProject && navigate(`/projects/${selectedProject.id}/results`)}
              onWorkspaceSummary={setWorkspaceSummary}
            />
          )}
        </Content>
      </Layout>
      </Layout>

      {/* Project settings belong to the current project; creation lives in 项目工作台. */}
      <Modal
        title="编辑项目"
        open={projectModalVisible}
        onOk={handleSubmitProject}
        onCancel={() => setProjectModalVisible(false)}
        okText="保存"
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

      <Modal
        title="个人资料"
        open={profileVisible}
        onCancel={() => setProfileVisible(false)}
        footer={[
          <Button key="close" type="primary" onClick={() => setProfileVisible(false)}>
            完成
          </Button>,
        ]}
        width={460}
        className="workspace-profile-modal"
      >
        <div className="workspace-profile-hero">
          <Avatar size={58} style={{ background: '#123a52' }} icon={<UserOutlined />} />
          <div>
            <strong>{user?.full_name || user?.username || '当前用户'}</strong>
            <span>{user?.email || '未设置邮箱'}</span>
          </div>
        </div>
        <dl className="workspace-profile-grid">
          <div><dt>用户名</dt><dd>{user?.username || '—'}</dd></div>
          <div><dt>组织角色</dt><dd>{organizations.find(org => org.id === currentOrgId)?.role || '组织成员'}</dd></div>
          <div><dt>当前组织</dt><dd>{organizations.find(org => org.id === currentOrgId)?.name || '—'}</dd></div>
          <div><dt>有效权限</dt><dd>{currentPermissions.length} 项</dd></div>
        </dl>
        <div className="workspace-profile-permissions">
          <strong>我的有效权限</strong>
          <div>
            {currentPermissions.length
              ? currentPermissions.map((permission) => (
                <span key={permission}>{PERMISSION_LABELS[permission] || permission}</span>
              ))
              : <em>当前组织未授予可用权限</em>}
          </div>
        </div>
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
