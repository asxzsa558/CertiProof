import { useEffect, useMemo, useState } from 'react'
import { Button, Select, Tag, message } from 'antd'
import {
  AlertOutlined,
  ApiOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloudServerOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import OrganizationSettingsLayout from '../components/OrganizationSettingsLayout'
import './OperationsCenter.css'

const serviceLabels = {
  mcp_gateway: 'MCP Gateway', gateway_routes: '工具路由', security_tools: '核心安全工具',
  fast_scanner: '高速扫描', web_tools: 'Web 检测', network_tools: '网络设备检测',
  windows_tools: 'Windows / AD', db_tools: '数据库检测', ssh_checker: 'SSH 基线',
  ocr_server: '文档视觉解析', embedding_server: '本地向量服务',
  interactive: '交互任务 Worker', document: '文档分析 Worker', assessment: '技术测评 Worker',
  verification: '整改复测 Worker', maintenance: '维护归档 Worker',
}

const statusMeta = {
  healthy: { label: '正常', color: 'green' },
  degraded: { label: '降级', color: 'gold' },
  unhealthy: { label: '异常', color: 'red' },
  completed: { label: '检测完成', color: 'green' },
  risk: { label: '发现问题', color: 'red' },
  incomplete: { label: '检测不完整', color: 'gold' },
  failed: { label: '执行失败', color: 'red' },
  running: { label: '执行中', color: 'blue' },
}

const emptySnapshot = {
  release: {}, services: {}, workers: {}, alerts: [], event_log: [],
  scan_nodes: [],
  scan_tasks: { total: 0, by_status: {}, recent: [], failure_rate: 0, stale_leases: 0 },
  runtime_resources: { hardware: {}, pressure: {}, limits: {} },
}

const formatTime = (value) => value ? new Date(value).toLocaleString() : '暂无记录'
const metaFor = (status) => statusMeta[status] || { label: status || '未知', color: 'default' }

export default function OperationsCenter() {
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const currentOrg = useMemo(
    () => organizations.find((org) => org.id === currentOrgId) || organizations[0],
    [organizations, currentOrgId]
  )
  const [snapshot, setSnapshot] = useState(emptySnapshot)
  const [permissions, setPermissions] = useState([])
  const [permissionScope, setPermissionScope] = useState('受限权限')
  const [loading, setLoading] = useState(false)
  const [hours, setHours] = useState(24)
  const [logLevel, setLogLevel] = useState('all')

  const load = async ({ silent = false } = {}) => {
    if (!currentOrg?.id) return
    setLoading(true)
    try {
      const [operations, dashboard] = await Promise.all([
        api.get('/diagnostics/operations', { params: { organization_id: currentOrg.id, hours } }),
        api.get('/dashboard/organization-command', { params: { organization_id: currentOrg.id } }),
      ])
      setSnapshot({ ...emptySnapshot, ...operations.data })
      setPermissions(dashboard.data?.current_role?.permissions || [])
      setPermissionScope(dashboard.data?.current_role?.permission_scope || '受限权限')
    } catch (error) {
      if (!silent) message.error(error.response?.data?.detail || '运行状态暂时不可用')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const timer = window.setInterval(() => load({ silent: true }), 30000)
    return () => window.clearInterval(timer)
  }, [currentOrg?.id, hours])

  const serviceEntries = [
    ...Object.entries(snapshot.services || {}).map(([name, value]) => ({ name, ...value, kind: 'service' })),
    ...Object.entries(snapshot.workers || {}).map(([name, value]) => ({ name, ...value, kind: 'worker' })),
  ]
  const healthyCount = serviceEntries.filter((item) => item.status === 'healthy').length
  const highAlerts = snapshot.alerts.filter((item) => item.severity === 'high').length
  const runningCount = (snapshot.scan_tasks?.by_status?.running || 0) + (snapshot.scan_tasks?.by_status?.pending || 0)
  const filteredLogs = snapshot.event_log.filter((item) => logLevel === 'all' || item.level === logLevel)
  const hardware = snapshot.runtime_resources?.hardware || {}

  return (
    <OrganizationSettingsLayout
      activeKey="operations"
      eyebrow="OPERATIONS & ALERTS"
      title="运行与告警中心"
      description="统一查看服务健康、Worker 心跳、任务质量、资源压力和安全审计事件。"
      permissions={permissions}
      permissionScope={permissionScope}
      loading={loading}
      onRefresh={() => load()}
    >
      <section className="operations-kpis">
        <div><CheckCircleOutlined /><span><strong>{healthyCount}/{serviceEntries.length}</strong><em>健康组件</em></span></div>
        <div className={highAlerts ? 'danger' : ''}><AlertOutlined /><span><strong>{highAlerts}</strong><em>高优先级告警</em></span></div>
        <div><ClockCircleOutlined /><span><strong>{runningCount}</strong><em>等待或执行中</em></span></div>
        <div><CloudServerOutlined /><span><strong>{snapshot.release?.version || 'source'}</strong><em>当前发布版本</em></span></div>
      </section>

      <section className="operations-main-grid">
        <section className="org-panel operations-services-panel">
          <header className="operations-panel-head">
            <div><h2>服务与执行器</h2><p>HTTP 探针与持久化心跳，非静态状态。</p></div>
            <Button type="text" icon={<ReloadOutlined spin={loading} />} onClick={() => load()}>刷新</Button>
          </header>
          <div className="operations-service-grid">
            {serviceEntries.map((item) => {
              const meta = metaFor(item.status)
              return (
                <div className={`operations-service-row ${item.status}`} key={`${item.kind}-${item.name}`}>
                  <span className="operations-service-icon">{item.kind === 'worker' ? <CloudServerOutlined /> : <ApiOutlined />}</span>
                  <div>
                    <strong>{serviceLabels[item.name] || item.name}</strong>
                    <small>{item.kind === 'worker' ? `最后心跳 ${formatTime(item.last_seen)}` : item.error || '健康端点已响应'}</small>
                  </div>
                  <Tag color={meta.color}>{meta.label}</Tag>
                </div>
              )
            })}
          </div>
        </section>

        <section className="org-panel operations-alerts-panel">
          <header className="operations-panel-head">
            <div><h2>当前告警</h2><p>异常服务、过期租约、失败任务与资源背压。</p></div>
            <Tag color={snapshot.alerts.length ? 'gold' : 'green'}>{snapshot.alerts.length} 条</Tag>
          </header>
          <div className="operations-scroll">
            {snapshot.alerts.length ? snapshot.alerts.map((alert) => (
              <div className={`operations-alert-row ${alert.severity}`} key={alert.id}>
                <ExclamationCircleOutlined />
                <div><strong>{alert.title}</strong><p>{alert.detail}</p><small>{formatTime(alert.created_at)}</small></div>
              </div>
            )) : <div className="operations-empty"><CheckCircleOutlined /> 当前没有运行告警</div>}
          </div>
        </section>
      </section>

      <section className="org-panel operations-tasks-panel">
        <header className="operations-panel-head">
          <div><h2>检测执行质量</h2><p>完成、发现问题、检测不完整和执行失败采用统一口径。</p></div>
          <Select value={hours} onChange={setHours} options={[24, 72, 168].map((value) => ({ value, label: `最近 ${value} 小时` }))} />
        </header>
        <div className="operations-task-table operations-scroll">
          {snapshot.scan_tasks?.recent?.length ? snapshot.scan_tasks.recent.map((task) => {
            const meta = metaFor(task.outcome)
            return (
              <div className="operations-task-row" key={task.id}>
                <strong>{task.project_name}</strong>
                <span>{task.capability}</span>
                <Tag color={meta.color}>{meta.label}</Tag>
                <span>{task.findings_count} 项问题</span>
                <time>{formatTime(task.completed_at || task.created_at)}</time>
              </div>
            )
          }) : <div className="operations-empty">当前时间范围内暂无检测任务</div>}
        </div>
      </section>

      <section className="org-panel operations-log-panel">
        <header className="operations-panel-head">
          <div><h2>集中运行日志</h2><p>检测执行与组织审计事件已脱敏汇总。</p></div>
          <Select value={logLevel} onChange={setLogLevel} options={[
            { value: 'all', label: '全部级别' }, { value: 'error', label: '错误' },
            { value: 'warning', label: '警告' }, { value: 'info', label: '信息' },
          ]} />
        </header>
        <div className="operations-log-list operations-scroll">
          {filteredLogs.length ? filteredLogs.map((item) => (
            <div className={`operations-log-row ${item.level}`} key={item.id}>
              <time>{formatTime(item.created_at)}</time>
              <Tag color={item.level === 'error' ? 'red' : item.level === 'warning' ? 'gold' : 'blue'}>{item.type === 'scan' ? '检测' : item.type === 'scan_node' ? '节点' : '审计'}</Tag>
              <strong>{item.title}</strong>
              <span>{item.detail}</span>
            </div>
          )) : <div className="operations-empty">当前筛选条件下暂无日志</div>}
        </div>
      </section>

      <section className="operations-resource-strip">
        <span>CPU {hardware.cpu_count || 0} 核</span>
        <span>CPU 压力 {hardware.cpu_pressure_percent || 0}%</span>
        <span>内存占用 {hardware.memory_percent || 0}%</span>
        <span>资源档位 {snapshot.runtime_resources?.effective_profile || 'unknown'}</span>
        <span>队列背压 {snapshot.runtime_resources?.pressure?.paused ? '已触发' : '未触发'}</span>
        <span>远端节点 {snapshot.scan_nodes.filter((node) => node.status === 'online').length}/{snapshot.scan_nodes.length} 在线</span>
      </section>
    </OrganizationSettingsLayout>
  )
}
