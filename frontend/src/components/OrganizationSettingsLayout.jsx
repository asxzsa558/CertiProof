import { Avatar, Button, Dropdown, Select, Tag, message } from 'antd'
import {
  DashboardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  LockOutlined,
  LogoutOutlined,
  ProjectOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from './VeriSureLogo'
import '../styles/theme.css'
import '../pages/Dashboard.css'
import './OrganizationSettingsLayout.css'

const NAV_ITEMS = [
  { key: 'overview', group: '组织态势', label: '全局 Dashboard', icon: <DashboardOutlined />, path: '/dashboard' },
  { key: 'projects', group: '项目执行', label: '项目工作台', icon: <ProjectOutlined />, path: '/projects', permission: 'project:read' },
  { key: 'assets', group: '项目执行', label: '资产矩阵', icon: <DatabaseOutlined />, path: '/projects?view=assets', permission: 'asset:read' },
  { key: 'assessment', group: '测评中心', label: '等保测评', icon: <SafetyCertificateOutlined />, path: '/projects', permission: 'assessment:read' },
  { key: 'password-assessment', group: '测评中心', label: '密码测评', icon: <LockOutlined />, upcoming: true, permission: 'assessment:read' },
  { key: 'reports', group: '治理中心', label: '报告中心', icon: <FileTextOutlined />, path: '/reports', permission: 'report:read' },
  { key: 'access', group: '治理中心', label: '角色权限', icon: <TeamOutlined />, path: '/settings/access', permission: 'role:read' },
  { key: 'data', group: '系统', label: '数据与生命周期', icon: <DatabaseOutlined />, path: '/settings/data-lifecycle', permission: 'system:config' },
  { key: 'models', group: '系统', label: '系统设置', icon: <SettingOutlined />, path: '/settings/models', permission: 'system:config' },
]

export default function OrganizationSettingsLayout({
  activeKey,
  eyebrow,
  title,
  description,
  permissions = [],
  permissionScope = '受限权限',
  loading = false,
  onRefresh,
  children,
}) {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const setCurrentOrg = useAuthStore((state) => state.setCurrentOrg)
  const currentOrg = organizations.find((org) => org.id === currentOrgId) || organizations[0]
  const effectivePermissions = new Set(permissions)
  const visibleItems = NAV_ITEMS.filter((item) => (
    !item.permission
    || currentOrg?.role === 'admin'
    || effectivePermissions.has(item.permission)
  ))
  const groupedItems = visibleItems.reduce((groups, item) => {
    groups[item.group] = [...(groups[item.group] || []), item]
    return groups
  }, {})
  const userMenu = {
    items: [
      { key: 'profile', icon: <UserOutlined />, label: user?.username || '账户' },
      { type: 'divider' },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        danger: true,
        onClick: () => {
          logout()
          navigate('/login')
        },
      },
    ],
  }

  return (
    <div className="org-dashboard settings-dashboard">
      <aside className="org-sidebar">
        <div className="org-brand">
          <div className="org-brand-mark"><VeriSureLogo size={46} /></div>
          <div>
            <span>CertiProof</span>
            <em>安全合规运营</em>
          </div>
        </div>
        <nav className="org-nav">
          {Object.entries(groupedItems).map(([group, items]) => (
            <div className="org-nav-group" key={group}>
              <em>{group}</em>
              {items.map((item) => (
                <button
                  type="button"
                  key={item.key}
                  className={`${item.key === activeKey ? 'active' : ''}${item.upcoming ? ' upcoming' : ''}`}
                  onClick={() => {
                    if (item.upcoming) {
                      message.info('下个版本更新，暂未开启')
                      return
                    }
                    navigate(item.path)
                  }}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <main className="org-main settings-main">
        <header className="org-topbar">
          <div className="org-title-block">
            <span>{eyebrow}</span>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
          <div className="org-top-actions">
            <Select
              value={currentOrg?.id}
              onChange={setCurrentOrg}
              options={organizations.map((org) => ({ value: org.id, label: org.name }))}
              className="org-select"
            />
            <Tag color="cyan">{currentOrg?.role === 'admin' ? '管理员' : currentOrg?.role || '成员'}</Tag>
            <Tag color={permissionScope === '全局权限' ? 'green' : 'gold'}>{permissionScope}</Tag>
            {onRefresh ? (
              <Button
                className="org-refresh"
                type="text"
                icon={<ReloadOutlined spin={loading} />}
                onClick={onRefresh}
              >
                刷新
              </Button>
            ) : null}
            <Dropdown menu={userMenu} placement="bottomRight">
              <Avatar className="org-avatar" icon={<UserOutlined />} />
            </Dropdown>
          </div>
        </header>
        <div className="settings-shell-content">{children}</div>
      </main>
    </div>
  )
}
