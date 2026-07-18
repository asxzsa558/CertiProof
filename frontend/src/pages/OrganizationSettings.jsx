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
  message,
  Popconfirm,
  Avatar,
} from 'antd'
import {
  ArrowLeftOutlined,
  BankOutlined,
  UserOutlined,
  MailOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  CheckOutlined,
  CrownOutlined,
  HddOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import './OrganizationSettings.css'

const ROLE_COLORS = {
  admin: '#d4af37',
  manager: '#00b4d8',
  member: '#52c41a',
  viewer: '#666',
}

const ROLE_LABELS = {
  admin: 'ADMIN',
  manager: 'MANAGER',
  member: 'MEMBER',
  viewer: 'VIEWER',
}

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
  'role:read': '查看角色',
  'role:manage': '管理角色',
  'member:manage': '管理成员',
  'system:config': '系统配置',
  'tool:diagnose': '工具诊断',
}

const formatBytes = (value = 0) => {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`
}

function OrgPanel({ label, value, sub, accentColor }) {
  return (
    <div className="org-panel" style={{ '--accent': accentColor }}>
      <div className="org-panel-corner-tl" />
      <div className="org-panel-corner-tr" />
      <div className="org-panel-corner-bl" />
      <div className="org-panel-corner-br" />
      <div className="org-panel-scanline" />
      <div className="org-panel-label">{label}</div>
      <div className="org-panel-value">{value}</div>
      {sub && <div className="org-panel-sub">{sub}</div>}
    </div>
  )
}

export default function OrganizationSettings() {
  const navigate = useNavigate()
  const lastProjectId = localStorage.getItem('lastProjectId')
  const [loading, setLoading] = useState(true)
  const [org, setOrg] = useState(null)
  const [members, setMembers] = useState([])
  const [roles, setRoles] = useState([])
  const [editMode, setEditMode] = useState(false)
  const [editForm] = Form.useForm()
  const [addMemberModalOpen, setAddMemberModalOpen] = useState(false)
  const [addMemberForm] = Form.useForm()
  const [storage, setStorage] = useState(null)
  const [initializing, setInitializing] = useState(false)

  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrg = organizations.find((o) => o.id === currentOrgId)

  const loadOrg = async () => {
    if (!currentOrgId) return
    try {
      const res = await api.get(`/organizations/${currentOrgId}`)
      setOrg(res.data)
      editForm.setFieldsValue({
        name: res.data.name,
        description: res.data.description,
      })
    } catch (err) {
      message.error('加载组织信息失败')
    }
  }

  const loadMembers = async () => {
    if (!currentOrgId) return
    try {
      const res = await api.get(`/organizations/${currentOrgId}/members`)
      setMembers(res.data)
    } catch (err) {
      message.error('加载成员列表失败')
    }
  }

  const loadRoles = async () => {
    if (!currentOrgId) return
    try {
      const res = await api.get(`/organizations/${currentOrgId}/roles`)
      setRoles(res.data || [])
    } catch (err) {
      setRoles([])
    }
  }

  const loadStorage = async () => {
    if (!currentOrgId || currentOrg?.role !== 'admin') return
    try {
      const res = await api.get(`/organizations/${currentOrgId}/storage`)
      setStorage(res.data)
    } catch (err) {
      setStorage({ error: err.response?.data?.detail || '容量信息加载失败' })
    }
  }

  useEffect(() => {
    Promise.all([loadOrg(), loadMembers(), loadRoles(), loadStorage()]).finally(() => setLoading(false))
  }, [currentOrgId, currentOrg?.role])

  const handleSave = async () => {
    try {
      const values = await editForm.validateFields()
      await api.put(`/organizations/${currentOrgId}`, values)
      message.success('组织信息已更新')
      setEditMode(false)
      loadOrg()
    } catch (err) {
      if (err.response) {
        message.error(err.response.data?.detail || '更新失败')
      }
    }
  }

  const handleAddMember = async () => {
    try {
      const values = await addMemberForm.validateFields()
      await api.post(`/organizations/${currentOrgId}/members`, values)
      message.success('成员已添加')
      setAddMemberModalOpen(false)
      addMemberForm.resetFields()
      loadMembers()
    } catch (err) {
      if (err.response) {
        message.error(err.response.data?.detail || '添加失败')
      }
    }
  }

  const handleUpdateRole = async (memberId, newRole) => {
    try {
      await api.put(`/organizations/${currentOrgId}/members/${memberId}`, {
        role: newRole,
      })
      message.success('角色已更新')
      loadMembers()
    } catch (err) {
      message.error(err.response?.data?.detail || '更新失败')
    }
  }

  const handleRemoveMember = async (memberId) => {
    try {
      await api.delete(`/organizations/${currentOrgId}/members/${memberId}`)
      message.success('成员已移除')
      loadMembers()
    } catch (err) {
      message.error(err.response?.data?.detail || '移除失败')
    }
  }

  const handleInitializeBusinessData = () => {
    let confirmation = ''
    Modal.confirm({
      title: '初始化组织业务数据',
      icon: <WarningOutlined />,
      width: 560,
      content: (
        <div className="org-init-confirm">
          <p>该操作会删除组织下全部项目、资产、测评、检测结果、对话、文档、向量和证据图谱。组织成员、角色模板和标准图谱会保留。</p>
          <span>输入组织名称 <b>{org.name}</b> 确认：</span>
          <Input onChange={(event) => { confirmation = event.target.value }} />
        </div>
      ),
      okText: '初始化业务数据',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        if (confirmation !== org.name) {
          message.error('组织名称不匹配')
          return Promise.reject(new Error('confirmation mismatch'))
        }
        setInitializing(true)
        try {
          const response = await api.post(`/organizations/${currentOrgId}/initialize`, { confirmation })
          const failed = response.data?.failed_file_paths?.length || 0
          message.success(failed ? `业务数据已初始化，${failed} 个物理文件待重试` : '组织业务数据已初始化')
          await loadStorage()
        } catch (err) {
          message.error(err.response?.data?.detail || '组织业务数据初始化失败')
          return Promise.reject(err)
        } finally {
          setInitializing(false)
        }
      },
    })
  }

  if (loading || !org) {
    return (
      <div className="org-loading">
        <Spin size="large" />
        <div className="org-loading-text">LOADING ORG DATA...</div>
      </div>
    )
  }

  const adminCount = members.filter((m) => m.role === 'admin').length
  const isAdmin = currentOrg?.role === 'admin'

  return (
    <div className="org-root">
      <div className="org-bg-grid" />
      <div className="org-bg-logo">
        <BankOutlined />
      </div>
      <div className="org-bg-vignette" />

      <header className="org-header">
        <button className="org-back-btn" onClick={() => navigate(lastProjectId ? `/projects/${lastProjectId}` : '/dashboard')}>
          <ArrowLeftOutlined /> {lastProjectId ? '返回项目对话' : '返回 Dashboard'}
        </button>
        <div className="org-header-title">
          <VeriSureLogo size={28} />
          <div className="org-header-text">
            <span className="org-header-name">ORGANIZATION SETTINGS</span>
            <span className="org-header-sub">// {currentOrg?.name || org.name}</span>
          </div>
        </div>
        <button className="org-icon-btn" onClick={() => { loadOrg(); loadMembers(); loadRoles(); }}>
          <ReloadOutlined />
        </button>
      </header>

      <section className="org-section">
        <div className="org-section-header">
          <span className="org-section-tag">// OVERVIEW</span>
          <span className="org-section-title">组织概况</span>
        </div>
        <div className="org-stats-grid">
          <OrgPanel label="ORG NAME" value={org.name} accentColor="#00d4ff" />
          <OrgPanel label="ORG CODE" value={org.code} accentColor="#0ea5e9" />
          <OrgPanel
            label="MEMBERS"
            value={members.length}
            sub={`ADMINS ${adminCount}`}
            accentColor="#fbbf24"
          />
          <OrgPanel
            label="STATUS"
            value={org.is_active ? 'ACTIVE' : 'INACTIVE'}
            accentColor={org.is_active ? '#10b981' : '#ef4444'}
          />
        </div>
      </section>

      <section className="org-section">
        <div className="org-section-header">
          <span className="org-section-tag">// ACCESS MATRIX</span>
          <span className="org-section-title">角色权限矩阵</span>
          <span className="org-section-meta">{roles.length} ROLES</span>
        </div>
        <div className="org-role-matrix">
          {roles.map((role) => (
            <div className="org-role-card" key={role.id}>
              <div className="org-role-head">
                <div>
                  <strong>{role.name}</strong>
                  <span>{role.description || '未配置说明'}</span>
                </div>
                <Tag color={role.is_system ? 'cyan' : 'gold'}>{role.permissions.length} 权限</Tag>
              </div>
              <div className="org-permission-list">
                {role.permissions.map((permission) => (
                  <span key={permission}>{PERMISSION_LABELS[permission] || permission}</span>
                ))}
              </div>
            </div>
          ))}
          {!roles.length && (
            <div className="org-empty">
              <Empty description="暂无可查看角色权限" />
            </div>
          )}
        </div>
      </section>

      <section className="org-section">
        <div className="org-section-header">
          <span className="org-section-tag">// PROFILE</span>
          <span className="org-section-title">组织信息</span>
          {isAdmin && !editMode && (
            <button className="org-edit-btn" onClick={() => setEditMode(true)}>
              <EditOutlined /> 编辑
            </button>
          )}
          {editMode && (
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
              <button
                className="org-cancel-btn"
                onClick={() => {
                  setEditMode(false)
                  editForm.setFieldsValue({ name: org.name, description: org.description })
                }}
              >
                取消
              </button>
              <button className="org-save-btn" onClick={handleSave}>
                <CheckOutlined /> 保存
              </button>
            </div>
          )}
        </div>
        <Form form={editForm} layout="vertical" className="org-info-form">
          <Form.Item label="组织名称" name="name">
            <Input disabled={!editMode} size="large" />
          </Form.Item>
          <Form.Item label="组织代码" name="code">
            <Input disabled size="large" />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea disabled={!editMode} rows={4} placeholder="组织描述（可选）" />
          </Form.Item>
        </Form>
      </section>

      <section className="org-section">
        <div className="org-section-header">
          <span className="org-section-tag">// ROSTER</span>
          <span className="org-section-title">成员列表</span>
          <span className="org-section-meta">{members.length} MEMBERS</span>
          {isAdmin && (
            <button
              className="org-add-btn"
              onClick={() => setAddMemberModalOpen(true)}
              style={{ marginLeft: 'auto' }}
            >
              <PlusOutlined /> 添加成员
            </button>
          )}
        </div>

        <div className="org-members-grid">
          {members.length === 0 ? (
            <div className="org-empty">
              <Empty description="暂无成员" />
            </div>
          ) : (
            members.map((m) => (
              <div className="org-member-card" key={m.id}>
                <div className="org-member-corner-tl" />
                <div className="org-member-corner-tr" />
                <div className="org-member-corner-bl" />
                <div className="org-member-corner-br" />

                <Avatar size={42} icon={<UserOutlined />} className="org-member-avatar" />
                <div className="org-member-info">
                  <div className="org-member-name">
                    {m.username}
                    {m.role === 'admin' && <CrownOutlined className="org-crown" />}
                  </div>
                  <div className="org-member-email">
                    <MailOutlined /> {m.email}
                  </div>
                  <div className="org-member-joined">
                    加入于 {new Date(m.joined_at).toLocaleDateString('zh-CN')}
                  </div>
                </div>

                <div className="org-member-actions">
                  <Select
                    size="small"
                    value={m.role}
                    disabled={!isAdmin}
                    onChange={(v) => handleUpdateRole(m.id, v)}
                    style={{ width: 110 }}
                    options={[
                      { value: 'admin', label: 'ADMIN' },
                      { value: 'manager', label: 'MANAGER' },
                      { value: 'member', label: 'MEMBER' },
                      { value: 'viewer', label: 'VIEWER' },
                    ]}
                  />
                  {isAdmin && m.user_id !== currentOrg?.id && (
                    <Popconfirm
                      title="确认移除该成员？"
                      onConfirm={() => handleRemoveMember(m.id)}
                      okText="移除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                    >
                      <button className="org-member-remove">
                        <DeleteOutlined />
                      </button>
                    </Popconfirm>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      {isAdmin && (
        <section className="org-section org-data-lifecycle">
          <div className="org-section-header">
            <span className="org-section-tag">// DATA LIFECYCLE</span>
            <span className="org-section-title">数据容量与初始化</span>
            <span className="org-section-meta">{storage?.project_count || 0} PROJECTS</span>
          </div>
          {storage?.error ? (
            <div className="org-storage-error">{storage.error}</div>
          ) : (
            <div className="org-storage-grid">
              <div className="org-storage-total">
                <HddOutlined />
                <span>当前逻辑占用</span>
                <strong>{formatBytes(storage?.total_bytes || 0)}</strong>
              </div>
              {Object.entries(storage?.categories || {}).map(([key, item]) => (
                <div key={key}>
                  <span>{item.label}</span>
                  <strong>{formatBytes(item.bytes)}</strong>
                  <em>{item.transient ? '临时' : item.on_demand ? '按需' : `${item.count || 0} 项`}</em>
                </div>
              ))}
            </div>
          )}
          <div className="org-danger-row">
            <div>
              <strong>初始化组织业务数据</strong>
              <span>保留组织、成员、权限角色和全局标准图谱，删除全部项目业务数据。</span>
            </div>
            <button className="org-danger-btn" onClick={handleInitializeBusinessData} disabled={initializing}>
              <DeleteOutlined /> {initializing ? '处理中...' : '初始化'}
            </button>
          </div>
        </section>
      )}

      <Modal
        title={
          <div className="org-modal-title">
            <span className="org-modal-tag">// ADD MEMBER</span>
            <span>添加组织成员</span>
          </div>
        }
        open={addMemberModalOpen}
        onCancel={() => {
          setAddMemberModalOpen(false)
          addMemberForm.resetFields()
        }}
        footer={null}
        width={480}
        className="org-add-modal"
      >
        <Form form={addMemberForm} layout="vertical" onFinish={handleAddMember}>
          <Form.Item
            name="user_email"
            label="用户邮箱"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '请输入有效的邮箱' },
            ]}
          >
            <Input placeholder="用户注册的邮箱" size="large" />
          </Form.Item>
          <Form.Item
            name="role"
            label="角色"
            initialValue="member"
            rules={[{ required: true, message: '请选择角色' }]}
          >
            <Select
              size="large"
              options={[
                { value: 'admin', label: 'ADMIN - 管理员' },
                { value: 'manager', label: 'MANAGER - 经理' },
                { value: 'member', label: 'MEMBER - 成员' },
                { value: 'viewer', label: 'VIEWER - 查看者' },
              ]}
            />
          </Form.Item>
          <Form.Item>
            <div className="org-add-actions">
              <button
                type="button"
                className="org-cancel-btn"
                onClick={() => {
                  setAddMemberModalOpen(false)
                  addMemberForm.resetFields()
                }}
              >
                取消
              </button>
              <button type="submit" className="org-save-btn">
                <PlusOutlined /> 添加
              </button>
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
