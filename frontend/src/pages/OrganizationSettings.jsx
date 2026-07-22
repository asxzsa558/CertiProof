import { useEffect, useMemo, useState } from 'react'
import {
  Avatar,
  Button,
  Checkbox,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Spin,
  Tag,
  message,
} from 'antd'
import {
  CrownOutlined,
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  LockOutlined,
  MailOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import OrganizationSettingsLayout from '../components/OrganizationSettingsLayout'
import './OrganizationSettings.css'

const ROLE_LABELS = {
  admin: '组织管理员',
  manager: '组织经理',
  member: '组织成员',
  viewer: '只读成员',
}

const ROLE_COLORS = {
  admin: 'gold',
  manager: 'cyan',
  member: 'green',
  viewer: 'default',
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
  'node:read': '查看扫描节点',
  'node:manage': '管理扫描节点',
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

const PERMISSION_GROUP_LABELS = {
  project: '项目管理',
  asset: '资产管理',
  scan: '安全检测',
  node: '远端扫描节点',
  assessment: '测评与证据',
  report: '报告中心',
  rbac: '角色授权',
  system: '系统配置',
}

const AUDIT_LABELS = {
  create_role: '创建角色',
  update_role: '更新角色',
  delete_role: '删除角色',
  add_member: '添加成员',
  assign_member_role: '调整成员权限',
  remove_member: '移除成员',
}

export default function OrganizationSettings() {
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const organizations = useAuthStore((state) => state.organizations)
  const user = useAuthStore((state) => state.user)
  const currentOrg = organizations.find((org) => org.id === currentOrgId)
  const [loading, setLoading] = useState(true)
  const [org, setOrg] = useState(null)
  const [roles, setRoles] = useState([])
  const [members, setMembers] = useState([])
  const [audits, setAudits] = useState([])
  const [permissionGroups, setPermissionGroups] = useState({})
  const [permissions, setPermissions] = useState([])
  const [permissionScope, setPermissionScope] = useState('受限权限')
  const [roleModalOpen, setRoleModalOpen] = useState(false)
  const [editingRole, setEditingRole] = useState(null)
  const [memberModalOpen, setMemberModalOpen] = useState(false)
  const [profileModalOpen, setProfileModalOpen] = useState(false)
  const [roleForm] = Form.useForm()
  const [memberForm] = Form.useForm()
  const [profileForm] = Form.useForm()

  const permissionSet = useMemo(() => new Set(permissions), [permissions])
  const canReadRoles = currentOrg?.role === 'admin' || permissionSet.has('role:read')
  const canManageRoles = currentOrg?.role === 'admin' || permissionSet.has('role:manage')
  const canManageMembers = currentOrg?.role === 'admin' || permissionSet.has('member:manage')
  const canEditOrganization = currentOrg?.role === 'admin'
  const adminCount = members.filter((member) => member.role === 'admin').length

  const loadData = async () => {
    if (!currentOrgId) return
    setLoading(true)
    try {
      const [dashboardResult, orgResult] = await Promise.all([
        api.get('/dashboard/organization-command', { params: { organization_id: currentOrgId } }),
        api.get(`/organizations/${currentOrgId}`),
      ])
      const currentPermissions = dashboardResult.data?.current_role?.permissions || []
      const mayReadRoles = currentOrg?.role === 'admin' || currentPermissions.includes('role:read')
      setPermissions(currentPermissions)
      setPermissionScope(dashboardResult.data?.current_role?.permission_scope || '受限权限')
      setOrg(orgResult.data)
      profileForm.setFieldsValue({
        name: orgResult.data.name,
        description: orgResult.data.description,
      })

      if (!mayReadRoles) {
        setRoles([])
        setMembers([])
        setAudits([])
        setPermissionGroups({})
        return
      }

      const [rolesResult, membersResult, permissionsResult, auditsResult] = await Promise.all([
        api.get(`/organizations/${currentOrgId}/roles`),
        api.get(`/organizations/${currentOrgId}/members`),
        api.get(`/organizations/${currentOrgId}/permissions`),
        api.get(`/organizations/${currentOrgId}/role-audits`),
      ])
      setRoles(rolesResult.data || [])
      setMembers(membersResult.data || [])
      setPermissionGroups(permissionsResult.data?.permission_groups || {})
      setAudits(auditsResult.data || [])
    } catch (error) {
      message.error(error.response?.data?.detail || '组织权限信息加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [currentOrgId])

  const openRoleModal = (role = null) => {
    setEditingRole(role)
    roleForm.setFieldsValue({
      name: role?.name || '',
      description: role?.description || '',
      permissions: role?.permissions || [],
    })
    setRoleModalOpen(true)
  }

  const saveRole = async () => {
    try {
      const values = await roleForm.validateFields()
      if (editingRole) {
        await api.put(`/organizations/${currentOrgId}/roles/${editingRole.id}`, values)
        message.success('角色模板已更新')
      } else {
        await api.post(`/organizations/${currentOrgId}/roles`, values)
        message.success('角色模板已创建')
      }
      setRoleModalOpen(false)
      setEditingRole(null)
      roleForm.resetFields()
      await loadData()
    } catch (error) {
      if (error.response) message.error(error.response.data?.detail || '角色保存失败')
    }
  }

  const deleteRole = async (role) => {
    try {
      await api.delete(`/organizations/${currentOrgId}/roles/${role.id}`)
      message.success('角色模板已删除，相关成员已恢复为基础角色权限')
      await loadData()
    } catch (error) {
      message.error(error.response?.data?.detail || '角色删除失败')
    }
  }

  const updateMember = async (member, changes) => {
    const role = changes.role ?? member.role
    const customRoleId = role === 'admin'
      ? null
      : Object.prototype.hasOwnProperty.call(changes, 'custom_role_id')
        ? changes.custom_role_id
        : member.custom_role_id
    try {
      await api.put(`/organizations/${currentOrgId}/members/${member.id}`, {
        role,
        custom_role_id: customRoleId || null,
      })
      message.success('成员权限已更新')
      await loadData()
    } catch (error) {
      message.error(error.response?.data?.detail || '成员权限更新失败')
    }
  }

  const addMember = async () => {
    try {
      const values = await memberForm.validateFields()
      await api.post(`/organizations/${currentOrgId}/members`, {
        ...values,
        custom_role_id: values.role === 'admin' ? null : values.custom_role_id || null,
      })
      message.success('成员已添加')
      setMemberModalOpen(false)
      memberForm.resetFields()
      await loadData()
    } catch (error) {
      if (error.response) message.error(error.response.data?.detail || '成员添加失败')
    }
  }

  const removeMember = async (member) => {
    try {
      await api.delete(`/organizations/${currentOrgId}/members/${member.id}`)
      message.success('成员已移除')
      await loadData()
    } catch (error) {
      message.error(error.response?.data?.detail || '成员移除失败')
    }
  }

  const saveOrganization = async () => {
    try {
      const values = await profileForm.validateFields()
      await api.put(`/organizations/${currentOrgId}`, values)
      message.success('组织信息已更新')
      setProfileModalOpen(false)
      await loadData()
    } catch (error) {
      if (error.response) message.error(error.response.data?.detail || '组织信息更新失败')
    }
  }

  return (
    <OrganizationSettingsLayout
      activeKey="access"
      eyebrow="治理中心 / 访问控制"
      title="组织与角色权限"
      description="统一管理角色模板、成员授权和权限变更记录。"
      permissions={permissions}
      permissionScope={permissionScope}
      loading={loading}
      onRefresh={loadData}
    >
      {loading ? (
        <div className="access-loading"><Spin size="large" /></div>
      ) : !canReadRoles ? (
        <div className="settings-access-denied">
          <ExclamationCircleOutlined />
          <h2>无权访问角色权限</h2>
          <p>当前角色缺少“查看角色”权限。你仍可在个人资料中查看自己的有效权限。</p>
        </div>
      ) : (
        <>
          <section className="access-kpis">
            <div><TeamOutlined /><span><strong>{members.length}</strong><em>组织成员</em></span></div>
            <div><SafetyCertificateOutlined /><span><strong>{roles.length}</strong><em>角色模板</em></span></div>
            <div><LockOutlined /><span><strong>{permissions.length}</strong><em>我的有效权限</em></span></div>
            <div><CrownOutlined /><span><strong>{adminCount}</strong><em>组织管理员</em></span></div>
          </section>

          <section className="org-panel access-organization-panel">
            <div className="org-panel-head">
              <h2>当前组织</h2>
              <Button
                size="small"
                icon={<EditOutlined />}
                disabled={!canEditOrganization}
                title={!canEditOrganization ? '只有组织管理员可以编辑组织信息' : undefined}
                onClick={() => setProfileModalOpen(true)}
              >
                编辑组织
              </Button>
            </div>
            <div className="access-org-summary">
              <div><span>组织名称</span><strong>{org?.name}</strong></div>
              <div><span>组织代码</span><strong>{org?.code}</strong></div>
              <div><span>状态</span><Tag color={org?.is_active ? 'green' : 'red'}>{org?.is_active ? '正常' : '停用'}</Tag></div>
              <div><span>我的角色</span><Tag color={ROLE_COLORS[currentOrg?.role]}>{ROLE_LABELS[currentOrg?.role] || currentOrg?.role}</Tag></div>
            </div>
          </section>

          <section className="org-panel access-role-panel">
            <div className="org-panel-head">
              <h2>角色与权限矩阵</h2>
              <Button
                type="primary"
                size="small"
                icon={<PlusOutlined />}
                disabled={!canManageRoles}
                onClick={() => openRoleModal()}
              >
                新建角色
              </Button>
            </div>
            <div className="access-role-grid">
              {roles.map((role) => (
                <article className="access-role-card" key={role.id}>
                  <header>
                    <div>
                      <strong>{role.name}</strong>
                      <span>{role.description || '未配置角色说明'}</span>
                    </div>
                    <Tag color={role.is_system ? 'cyan' : 'gold'}>{role.is_system ? '系统模板' : '自定义'}</Tag>
                  </header>
                  <div className="access-role-meta">
                    <span>{role.permissions.length} 项权限</span>
                    <span>{role.member_count || 0} 名成员</span>
                  </div>
                  <div className="access-permission-list">
                    {role.permissions.map((permission) => (
                      <span key={permission}>{PERMISSION_LABELS[permission] || permission}</span>
                    ))}
                  </div>
                  <footer>
                    {role.is_system ? (
                      <span>系统模板固定，只能分配给成员</span>
                    ) : (
                      <>
                        <Button size="small" type="text" icon={<EditOutlined />} disabled={!canManageRoles} onClick={() => openRoleModal(role)}>
                          编辑
                        </Button>
                        <Popconfirm
                          title="删除该角色模板？"
                          description="已分配成员将恢复为其基础角色权限。"
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => deleteRole(role)}
                        >
                          <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={!canManageRoles}>
                            删除
                          </Button>
                        </Popconfirm>
                      </>
                    )}
                  </footer>
                </article>
              ))}
            </div>
          </section>

          <section className="org-panel access-member-panel">
            <div className="org-panel-head">
              <h2>成员授权</h2>
              <Button
                type="primary"
                size="small"
                icon={<PlusOutlined />}
                disabled={!canManageMembers}
                onClick={() => setMemberModalOpen(true)}
              >
                添加成员
              </Button>
            </div>
            <div className="access-member-table">
              <div className="access-member-head">
                <span>成员</span><span>基础身份</span><span>权限模板</span><span>有效权限</span><span>操作</span>
              </div>
              {members.map((member) => {
                const isSelf = member.user_id === user?.id
                const isLastAdmin = member.role === 'admin' && adminCount <= 1
                const assignedRole = roles.find((role) => role.id === member.custom_role_id)
                return (
                  <div className="access-member-row" key={member.id}>
                    <div className="access-member-identity">
                      <Avatar icon={<UserOutlined />} />
                      <span><strong>{member.username}</strong><em><MailOutlined /> {member.email}</em></span>
                      {isSelf ? <Tag color="blue">我</Tag> : null}
                    </div>
                    <Select
                      size="small"
                      value={member.role}
                      disabled={!canManageMembers || isLastAdmin}
                      onChange={(role) => updateMember(member, { role })}
                      options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))}
                    />
                    {member.role === 'admin' ? (
                      <span className="access-template-na">不使用权限模板</span>
                    ) : (
                      <Select
                        size="small"
                        value={member.custom_role_id}
                        placeholder="使用基础角色权限"
                        allowClear
                        disabled={!canManageMembers}
                        onChange={(customRoleId) => updateMember(member, { custom_role_id: customRoleId || null })}
                        options={roles.map((role) => ({ value: role.id, label: role.name }))}
                      />
                    )}
                    <span className="access-effective-role">
                      {member.role === 'admin' ? '全部权限' : assignedRole ? `${assignedRole.permissions.length} 项` : '基础权限'}
                    </span>
                    <Popconfirm
                      title="移除该组织成员？"
                      okText="移除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => removeMember(member)}
                    >
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        disabled={!canManageMembers || isSelf || isLastAdmin}
                        title={isSelf ? '不能在此移除自己' : isLastAdmin ? '不能移除最后一名管理员' : undefined}
                      />
                    </Popconfirm>
                  </div>
                )
              })}
            </div>
          </section>

          <section className="org-panel access-audit-panel">
            <div className="org-panel-head">
              <h2>权限变更审计</h2>
              <span>最近 {audits.length} 条</span>
            </div>
            <div className="access-audit-list">
              {audits.length ? audits.map((audit) => (
                <div key={audit.id}>
                  <span>{AUDIT_LABELS[audit.action] || audit.action}</span>
                  <strong>{audit.detail || '未记录详情'}</strong>
                  <time>{new Date(audit.created_at).toLocaleString('zh-CN')}</time>
                </div>
              )) : <Empty description="暂无权限变更记录" />}
            </div>
          </section>
        </>
      )}

      <Modal
        title={editingRole ? '编辑角色模板' : '新建角色模板'}
        open={roleModalOpen}
        onCancel={() => {
          setRoleModalOpen(false)
          setEditingRole(null)
          roleForm.resetFields()
        }}
        onOk={saveRole}
        okText="保存"
        cancelText="取消"
        width={720}
        className="access-modal"
      >
        <Form form={roleForm} layout="vertical">
          <Form.Item name="name" label="角色名称" rules={[{ required: true, message: '请输入角色名称' }]}>
            <Input maxLength={80} placeholder="例如：项目安全负责人" />
          </Form.Item>
          <Form.Item name="description" label="角色说明">
            <Input placeholder="说明该角色的职责边界" />
          </Form.Item>
          <Form.Item name="permissions" label="权限范围">
            <Checkbox.Group className="access-permission-groups">
              {Object.entries(permissionGroups).map(([group, values]) => (
                <div key={group}>
                  <strong>{PERMISSION_GROUP_LABELS[group] || group}</strong>
                  <section>
                    {values.map((permission) => (
                      <Checkbox key={permission} value={permission}>
                        {PERMISSION_LABELS[permission] || permission}
                      </Checkbox>
                    ))}
                  </section>
                </div>
              ))}
            </Checkbox.Group>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="添加组织成员"
        open={memberModalOpen}
        onCancel={() => {
          setMemberModalOpen(false)
          memberForm.resetFields()
        }}
        onOk={addMember}
        okText="添加"
        cancelText="取消"
        className="access-modal"
      >
        <Form form={memberForm} layout="vertical">
          <Form.Item
            name="user_email"
            label="用户邮箱"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '请输入有效邮箱' },
            ]}
          >
            <Input placeholder="已注册用户的邮箱" />
          </Form.Item>
          <Form.Item name="role" label="基础身份" initialValue="member" rules={[{ required: true }]}>
            <Select options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(previous, current) => previous.role !== current.role}
          >
            {({ getFieldValue }) => (
              <Form.Item name="custom_role_id" label="权限模板">
                <Select
                  allowClear
                  disabled={getFieldValue('role') === 'admin'}
                  placeholder={getFieldValue('role') === 'admin' ? '管理员自动拥有全部权限' : '可选，不选择则使用基础角色权限'}
                  options={roles.map((role) => ({ value: role.id, label: role.name }))}
                />
              </Form.Item>
            )}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑组织信息"
        open={profileModalOpen}
        onCancel={() => setProfileModalOpen(false)}
        onOk={saveOrganization}
        okText="保存"
        cancelText="取消"
        className="access-modal"
      >
        <Form form={profileForm} layout="vertical">
          <Form.Item name="name" label="组织名称" rules={[{ required: true, message: '请输入组织名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="组织说明">
            <Input.TextArea rows={4} />
          </Form.Item>
        </Form>
      </Modal>
    </OrganizationSettingsLayout>
  )
}
