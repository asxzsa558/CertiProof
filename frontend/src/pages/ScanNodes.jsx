import { useEffect, useMemo, useState } from 'react'
import {
  Button, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select, Spin, Switch, Tag, message,
} from 'antd'
import {
  ApiOutlined, CheckCircleOutlined, CloudServerOutlined, CopyOutlined, DeleteOutlined,
  DisconnectOutlined, EditOutlined, KeyOutlined, PlusOutlined, ReloadOutlined, SendOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import OrganizationSettingsLayout from '../components/OrganizationSettingsLayout'
import './ScanNodes.css'

const statusMeta = {
  online: { label: '在线', color: 'green', icon: <CheckCircleOutlined /> },
  offline: { label: '离线', color: 'red', icon: <DisconnectOutlined /> },
  unenrolled: { label: '待注册', color: 'gold', icon: <KeyOutlined /> },
  disabled: { label: '已停用', color: 'default', icon: <DisconnectOutlined /> },
}

const capabilityLabels = {
  scan_ports: '端口扫描', masscan_scan: '高速扫描', fping_scan: '批量存活', scan_ssl: 'SSL/TLS',
  scan_vulnerabilities: '漏洞扫描', scan_weak_passwords: '弱口令', nikto_scan: 'Web 漏洞',
  web_discovery_scan: 'Web 发现', database_security_scan: '数据库安全', network_device_scan: '网络设备',
  windows_security_scan: 'Windows/AD/SMB', baseline_check: '主机基线', full_compliance_scan: '完整合规检测',
  tech_assessment: '技术测评组合', ping_asset: '主机可达性',
}

const splitLines = (value = '') => value.split(/[\n,，]+/).map((item) => item.trim()).filter(Boolean)
const formatTime = (value) => value ? new Date(value).toLocaleString() : '尚未连接'

export default function ScanNodes() {
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrg = organizations.find((org) => org.id === currentOrgId) || organizations[0]
  const [nodes, setNodes] = useState([])
  const [projects, setProjects] = useState([])
  const [capabilities, setCapabilities] = useState([])
  const [permissions, setPermissions] = useState([])
  const [permissionScope, setPermissionScope] = useState('受限权限')
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [enrollment, setEnrollment] = useState(null)
  const [jobs, setJobs] = useState(null)
  const [routeResult, setRouteResult] = useState(null)
  const [form] = Form.useForm()
  const [routeForm] = Form.useForm()

  const canManage = currentOrg?.role === 'admin' || permissions.includes('node:manage')
  const onlineCount = nodes.filter((node) => node.status === 'online').length
  const activeJobs = nodes.reduce((sum, node) => sum + (node.active_jobs || 0), 0)
  const configuredRoutes = nodes.reduce((sum, node) => sum + node.allowed_cidrs.length + node.project_ids.length, 0)
  const projectOptions = useMemo(() => projects.map((project) => ({ value: project.id, label: project.name })), [projects])

  const load = async () => {
    if (!currentOrgId) return
    setLoading(true)
    try {
      const [nodeResult, projectResult, dashboardResult, capabilityResult] = await Promise.all([
        api.get(`/scan-nodes/${currentOrgId}`),
        api.get('/projects/', { params: { organization_id: currentOrgId } }),
        api.get('/dashboard/organization-command', { params: { organization_id: currentOrgId } }),
        api.get('/scan-nodes/capabilities'),
      ])
      setNodes(nodeResult.data || [])
      setProjects(projectResult.data || [])
      setPermissions(dashboardResult.data?.current_role?.permissions || [])
      setPermissionScope(dashboardResult.data?.current_role?.permission_scope || '受限权限')
      setCapabilities(capabilityResult.data?.capabilities || [])
    } catch (error) {
      message.error(error.response?.data?.detail || '扫描节点信息加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 30000)
    return () => window.clearInterval(timer)
  }, [currentOrgId])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ max_concurrency: 2, priority: 100, enabled: true, capabilities: [] })
    setModalOpen(true)
  }

  const openEdit = (node) => {
    setEditing(node)
    form.setFieldsValue({
      ...node,
      allowed_cidrs: node.allowed_cidrs.join('\n'),
    })
    setModalOpen(true)
  }

  const saveNode = async () => {
    const values = await form.validateFields()
    const payload = { ...values, allowed_cidrs: splitLines(values.allowed_cidrs) }
    try {
      if (editing) {
        await api.put(`/scan-nodes/${currentOrgId}/${editing.id}`, payload)
        message.success('节点配置已更新')
      } else {
        const response = await api.post(`/scan-nodes/${currentOrgId}`, payload)
        setEnrollment(response.data)
      }
      setRouteResult(null)
      setModalOpen(false)
      await load()
    } catch (error) {
      message.error(error.response?.data?.detail || '节点保存失败')
    }
  }

  const rotate = async (node) => {
    try {
      const response = await api.post(`/scan-nodes/${currentOrgId}/${node.id}/rotate-enrollment`)
      setEnrollment({ node, ...response.data })
      setRouteResult(null)
      await load()
    } catch (error) {
      message.error(error.response?.data?.detail || '注册凭证轮换失败')
    }
  }

  const remove = async (node) => {
    try {
      await api.delete(`/scan-nodes/${currentOrgId}/${node.id}`)
      setRouteResult(null)
      message.success('扫描节点及其执行记录已删除')
      await load()
    } catch (error) {
      message.error(error.response?.data?.detail || '扫描节点删除失败')
    }
  }

  const viewJobs = async (node) => {
    try {
      const response = await api.get(`/scan-nodes/${currentOrgId}/${node.id}/jobs`)
      setJobs({ node, rows: response.data || [] })
    } catch (error) {
      message.error(error.response?.data?.detail || '节点任务加载失败')
    }
  }

  const testRoute = async () => {
    const values = await routeForm.validateFields()
    try {
      const response = await api.post(`/scan-nodes/${currentOrgId}/route-test`, values)
      setRouteResult(response.data)
    } catch (error) {
      message.error(error.response?.data?.detail || '路由测试失败')
    }
  }

  const token = enrollment?.enrollment_token
  const controlPlane = ['localhost', '127.0.0.1'].includes(window.location.hostname)
    ? 'https://certiproof.example.com'
    : window.location.origin
  const startCommand = token ? `cp .env.example .env\nCONTROL_PLANE_URL=${controlPlane} ENROLL_TOKEN=${token} NODE_LOCAL_SECRET=$(openssl rand -hex 32) ./start-node.sh` : ''

  return (
    <OrganizationSettingsLayout
      activeKey="scan-nodes"
      eyebrow="REMOTE EXECUTION FABRIC"
      title="远端扫描节点"
      description="把安全工具部署到目标 VPC 内，由控制平面统一路由、审计和回收结果。"
      permissions={permissions}
      permissionScope={permissionScope}
      loading={loading}
      onRefresh={load}
    >
      <section className="node-kpis">
        <div><CloudServerOutlined /><span><strong>{nodes.length}</strong><em>节点总数</em></span></div>
        <div><CheckCircleOutlined /><span><strong>{onlineCount}</strong><em>在线节点</em></span></div>
        <div><ApiOutlined /><span><strong>{activeJobs}</strong><em>执行中任务</em></span></div>
        <div><SendOutlined /><span><strong>{configuredRoutes}</strong><em>路由规则</em></span></div>
      </section>

      <section className="node-toolbar">
        <div><h2>执行节点</h2><p>节点仅主动连接控制平面，不需要开放入站管理端口。</p></div>
        {canManage ? <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>添加节点</Button> : null}
      </section>

      <Spin spinning={loading}>
        <section className="node-grid">
          {nodes.length ? nodes.map((node) => {
            const meta = statusMeta[node.status] || statusMeta.offline
            return (
              <article className={`node-card ${node.status}`} key={node.id}>
                <header>
                  <span className="node-card-icon"><CloudServerOutlined /></span>
                  <div><h3>{node.name}</h3><p>{node.location || '未填写部署位置'}</p></div>
                  <Tag color={meta.color} icon={meta.icon}>{meta.label}</Tag>
                </header>
                <div className="node-card-stats">
                  <span><strong>{node.project_ids.length}</strong><em>绑定项目</em></span>
                  <span><strong>{node.allowed_cidrs.length}</strong><em>负责网段</em></span>
                  <span><strong>{node.active_jobs}/{node.max_concurrency}</strong><em>任务并发</em></span>
                </div>
                <div className="node-route-tags">
                  {node.project_ids.slice(0, 3).map((id) => <Tag key={id}>{projects.find((item) => item.id === id)?.name || `项目 #${id}`}</Tag>)}
                  {node.allowed_cidrs.slice(0, 3).map((cidr) => <Tag color="blue" key={cidr}>{cidr}</Tag>)}
                  {!node.project_ids.length && !node.allowed_cidrs.length ? <em>尚未配置路由，不会接收任务</em> : null}
                </div>
                <dl>
                  <div><dt>最后心跳</dt><dd>{formatTime(node.last_seen_at)}</dd></div>
                  <div><dt>运行环境</dt><dd>{node.runtime_info?.architecture || '等待注册'} · {node.runtime_info?.version || '未知版本'}</dd></div>
                  <div><dt>能力范围</dt><dd>{node.capabilities.length} 项安全能力</dd></div>
                </dl>
                <footer>
                  <Button type="text" onClick={() => viewJobs(node)}>执行记录</Button>
                  {canManage ? <>
                    <Button type="text" icon={<EditOutlined />} onClick={() => openEdit(node)}>配置</Button>
                    <Button type="text" icon={<KeyOutlined />} onClick={() => rotate(node)}>重新注册</Button>
                    <Popconfirm title="删除扫描节点？" description="已完成的远端执行记录也会一并删除。" onConfirm={() => remove(node)}>
                      <Button type="text" danger icon={<DeleteOutlined />} aria-label="删除节点" />
                    </Popconfirm>
                  </> : null}
                </footer>
              </article>
            )
          }) : <Empty className="node-empty" description="尚未配置远端扫描节点" />}
        </section>
      </Spin>

      <section className="org-panel node-route-test">
        <header><div><h2>路由验证</h2><p>部署前确认指定项目与目标会由哪个执行节点处理。</p></div></header>
        <Form form={routeForm} layout="inline" initialValues={{ capability: 'scan_ports' }}>
          <Form.Item name="target" rules={[{ required: true, message: '请输入 IP、域名或 URL' }]}><Input placeholder="10.20.0.15" /></Form.Item>
          <Form.Item name="project_id"><Select allowClear placeholder="可选：项目" options={projectOptions} /></Form.Item>
          <Form.Item name="capability"><Select options={capabilities.map((value) => ({ value, label: capabilityLabels[value] || value }))} /></Form.Item>
          <Button icon={<SendOutlined />} onClick={testRoute}>验证</Button>
        </Form>
        {routeResult ? <div className={`node-route-result ${routeResult.route}`}><strong>{routeResult.route === 'local' ? '中心执行' : routeResult.route === 'remote_offline' ? '远端不可用' : '远端执行'}</strong><span>{routeResult.message}</span></div> : null}
      </section>

      <Modal title={editing ? '配置扫描节点' : '添加扫描节点'} open={modalOpen} onOk={saveNode} onCancel={() => setModalOpen(false)} okText="保存">
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="节点名称" rules={[{ required: true }]}><Input placeholder="生产 VPC A 扫描节点" /></Form.Item>
          <Form.Item name="location" label="部署位置"><Input placeholder="华东 1 / 生产 VPC" /></Form.Item>
          <Form.Item name="project_ids" label="绑定项目" extra="绑定后，该项目的域名资产也可路由到此节点。"><Select mode="multiple" allowClear options={projectOptions} /></Form.Item>
          <Form.Item name="allowed_cidrs" label="负责网段" extra="每行或逗号分隔，例如 10.20.0.0/16。只匹配 IP 目标。"><Input.TextArea rows={3} placeholder={'10.20.0.0/16\n172.18.4.0/24'} /></Form.Item>
          <Form.Item name="capabilities" label="能力范围" extra="留空表示启用全部网络检测能力。"><Select mode="multiple" allowClear options={capabilities.map((value) => ({ value, label: capabilityLabels[value] || value }))} /></Form.Item>
          <div className="node-form-row">
            <Form.Item name="max_concurrency" label="最大并发"><InputNumber min={1} max={16} /></Form.Item>
            <Form.Item name="priority" label="路由优先级"><InputNumber min={1} max={1000} /></Form.Item>
            {editing ? <Form.Item name="enabled" label="启用节点" valuePropName="checked"><Switch /></Form.Item> : null}
          </div>
        </Form>
      </Modal>

      <Modal title="节点注册信息" open={Boolean(enrollment)} footer={<Button type="primary" onClick={() => setEnrollment(null)}>我已保存</Button>} closable={false}>
        <p>注册令牌只显示这一次，有效期 30 分钟。在目标 VPC 的 Linux 主机解压节点部署包、确认固定镜像版本后执行：</p>
        <pre className="node-command">{startCommand}</pre>
        <Button icon={<CopyOutlined />} onClick={() => navigator.clipboard.writeText(startCommand).then(() => message.success('启动命令已复制'))}>复制启动命令</Button>
      </Modal>

      <Modal title={jobs ? `${jobs.node.name} · 执行记录` : '执行记录'} open={Boolean(jobs)} onCancel={() => setJobs(null)} footer={null} width={760}>
        <div className="node-job-list">
          {jobs?.rows?.length ? jobs.rows.map((job) => (
            <div key={job.id}>
              <Tag color={job.status === 'completed' ? 'green' : job.status === 'failed' ? 'red' : job.status === 'running' ? 'blue' : 'default'}>{job.status}</Tag>
              <strong>{capabilityLabels[job.capability] || job.capability}</strong>
              <span>{job.target}</span>
              <small>{job.error || job.progress?.stage || formatTime(job.created_at)}</small>
            </div>
          )) : <Empty description="暂无远端执行记录" />}
        </div>
      </Modal>
    </OrganizationSettingsLayout>
  )
}
