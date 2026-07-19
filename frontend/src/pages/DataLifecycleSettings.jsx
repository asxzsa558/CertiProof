import { useEffect, useMemo, useState } from 'react'
import { Button, Input, Modal, Spin, Tag, message } from 'antd'
import {
  DatabaseOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  HddOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import OrganizationSettingsLayout from '../components/OrganizationSettingsLayout'
import './DataLifecycleSettings.css'

const formatBytes = (value = 0) => {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`
}

const CATEGORY_ICONS = {
  documents: <FileTextOutlined />,
  reports: <SafetyCertificateOutlined />,
  database: <DatabaseOutlined />,
}

export default function DataLifecycleSettings() {
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrg = organizations.find((org) => org.id === currentOrgId)
  const [loading, setLoading] = useState(true)
  const [initializing, setInitializing] = useState(false)
  const [storage, setStorage] = useState(null)
  const [permissions, setPermissions] = useState([])
  const [permissionScope, setPermissionScope] = useState('受限权限')
  const canConfigure = currentOrg?.role === 'admin' || permissions.includes('system:config')
  const categories = useMemo(() => Object.entries(storage?.categories || {}), [storage])

  const loadData = async () => {
    if (!currentOrgId) return
    setLoading(true)
    try {
      const dashboard = await api.get('/dashboard/organization-command', {
        params: { organization_id: currentOrgId },
      })
      const currentPermissions = dashboard.data?.current_role?.permissions || []
      setPermissions(currentPermissions)
      setPermissionScope(dashboard.data?.current_role?.permission_scope || '受限权限')
      if (currentOrg?.role === 'admin' || currentPermissions.includes('system:config')) {
        const response = await api.get(`/organizations/${currentOrgId}/storage`)
        setStorage(response.data)
      } else {
        setStorage(null)
      }
    } catch (error) {
      message.error(error.response?.data?.detail || '数据容量信息加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [currentOrgId])

  const initializeBusinessData = () => {
    let confirmation = ''
    Modal.confirm({
      title: '初始化组织业务数据',
      icon: <WarningOutlined />,
      width: 580,
      content: (
        <div className="data-init-confirm">
          <p>该操作会永久删除当前组织的项目、资产、测评、检测结果、对话、文档、向量和证据图谱。</p>
          <p>组织成员、角色模板和全局标准图谱会保留。</p>
          <span>输入组织名称 <b>{currentOrg?.name}</b> 确认：</span>
          <Input onChange={(event) => { confirmation = event.target.value }} />
        </div>
      ),
      okText: '确认初始化',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        if (confirmation !== currentOrg?.name) {
          message.error('组织名称不匹配')
          return Promise.reject(new Error('confirmation mismatch'))
        }
        setInitializing(true)
        try {
          const response = await api.post(`/organizations/${currentOrgId}/initialize`, { confirmation })
          const failed = response.data?.failed_file_paths?.length || 0
          message.success(failed ? `业务数据已初始化，${failed} 个物理文件待重试` : '组织业务数据已初始化')
          await loadData()
        } catch (error) {
          message.error(error.response?.data?.detail || '组织业务数据初始化失败')
          return Promise.reject(error)
        } finally {
          setInitializing(false)
        }
      },
    })
  }

  return (
    <OrganizationSettingsLayout
      activeKey="data"
      eyebrow="系统设置 / 数据治理"
      title="数据与生命周期"
      description="查看组织数据占用并执行明确授权的数据初始化操作。"
      permissions={permissions}
      permissionScope={permissionScope}
      loading={loading}
      onRefresh={loadData}
    >
      {loading ? (
        <div className="data-loading"><Spin size="large" /></div>
      ) : !canConfigure ? (
        <div className="settings-access-denied">
          <ExclamationCircleOutlined />
          <h2>无权访问数据与生命周期设置</h2>
          <p>当前角色缺少“系统配置”权限。该页面包含组织级数据清理能力，仅向获授权成员开放。</p>
        </div>
      ) : (
        <>
          <section className="org-panel data-summary-panel">
            <div className="org-panel-head">
              <h2>数据容量</h2>
              <span>{storage?.project_count || 0} 个项目</span>
            </div>
            <div className="data-total">
              <span><HddOutlined /></span>
              <div>
                <em>当前逻辑占用</em>
                <strong>{formatBytes(storage?.total_bytes || 0)}</strong>
              </div>
              <Tag color="cyan">实时统计</Tag>
            </div>
            <div className="data-category-grid">
              {categories.map(([key, item]) => (
                <div key={key} className="data-category">
                  <span>{CATEGORY_ICONS[key] || <DatabaseOutlined />}</span>
                  <div>
                    <strong>{item.label}</strong>
                    <em>{item.transient ? '临时数据' : item.on_demand ? '按需生成' : `${item.count || 0} 项`}</em>
                  </div>
                  <b>{formatBytes(item.bytes)}</b>
                </div>
              ))}
            </div>
          </section>

          <section className="org-panel data-policy-panel">
            <div className="org-panel-head">
              <h2>保留边界</h2>
              <span>当前策略</span>
            </div>
            <div className="data-policy-grid">
              <div><strong>正式测评材料</strong><span>随项目保留，只有删除、完全重置或组织初始化时清理。</span></div>
              <div><strong>归档项目</strong><span>保持只读并保留业务数据，不进行隐式删除。</span></div>
              <div><strong>临时执行数据</strong><span>由任务与上下文清理策略处理，不改变正式测评报告。</span></div>
            </div>
          </section>

          <section className="org-panel data-danger-panel">
            <div className="org-panel-head">
              <h2>危险操作</h2>
              <span>不可撤销</span>
            </div>
            <div className="data-danger-row">
              <div>
                <strong>初始化组织业务数据</strong>
                <span>保留组织、成员、权限角色和全局标准图谱，删除全部项目业务数据及关联文件。</span>
              </div>
              <Button
                danger
                icon={<DeleteOutlined />}
                loading={initializing}
                onClick={initializeBusinessData}
              >
                初始化组织数据
              </Button>
            </div>
          </section>
        </>
      )}
    </OrganizationSettingsLayout>
  )
}
