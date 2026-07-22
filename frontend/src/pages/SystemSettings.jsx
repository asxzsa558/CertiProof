import { useEffect, useState } from 'react'
import { Button, Spin, message } from 'antd'
import { ApiOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import OrganizationSettingsLayout from '../components/OrganizationSettingsLayout'
import SystemConfig from '../components/SystemConfig'
import './SystemSettings.css'

export default function SystemSettings() {
  const navigate = useNavigate()
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrg = organizations.find((org) => org.id === currentOrgId)
  const [permissions, setPermissions] = useState([])
  const [permissionScope, setPermissionScope] = useState('受限权限')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const canConfigure = currentOrg?.role === 'admin' || permissions.includes('system:config')

  const loadAccess = async () => {
    if (!currentOrgId) return
    setLoading(true)
    try {
      const response = await api.get('/dashboard/organization-command', {
        params: { organization_id: currentOrgId },
      })
      setPermissions(response.data?.current_role?.permissions || [])
      setPermissionScope(response.data?.current_role?.permission_scope || '受限权限')
    } catch (error) {
      message.error(error.response?.data?.detail || '系统设置加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAccess()
  }, [currentOrgId])

  return (
    <OrganizationSettingsLayout
      activeKey="system"
      eyebrow="系统设置 / 部署控制"
      title="系统设置"
      description="管理部署级资源调度、模型运行策略、对话上下文和文档分析默认行为。"
      permissions={permissions}
      permissionScope={permissionScope}
      loading={loading}
      onRefresh={() => {
        setRevision((value) => value + 1)
        loadAccess()
      }}
    >
      {loading ? (
        <div className="system-settings-loading"><Spin size="large" /></div>
      ) : !canConfigure ? (
        <section className="settings-access-denied">
          <LockOutlined />
          <h2>没有系统配置权限</h2>
          <p>当前角色只能查看业务页面，不能修改部署级运行参数。</p>
        </section>
      ) : (
        <>
          <section className="system-settings-summary">
            <div>
              <ApiOutlined />
              <span><strong>模型与推理端点</strong><em>提供商、模型能力和连接测试在独立页面维护。</em></span>
            </div>
            <Button onClick={() => navigate('/settings/models')}>管理模型</Button>
          </section>
          <SystemConfig key={`${currentOrgId}-${revision}`} embedded organizationId={currentOrgId} />
        </>
      )}
    </OrganizationSettingsLayout>
  )
}
