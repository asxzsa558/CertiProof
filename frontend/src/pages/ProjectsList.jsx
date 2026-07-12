import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Form, Input, Modal, Popconfirm, Select, Tag, message } from 'antd'
import {
  ApiOutlined,
  ArrowLeftOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  GlobalOutlined,
  LeftOutlined,
  PlusOutlined,
  ProjectOutlined,
  ReloadOutlined,
  RightOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import './ProjectsList.css'

const errorMessage = (error, fallback) => {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : error?.message || fallback
}

const assetTypeLabel = { ip: 'IP 主机', domain: '域名', cloud_resource: '云资源' }
const assetIcon = {
  ip: <ApiOutlined />,
  domain: <GlobalOutlined />,
  cloud_resource: <CloudServerOutlined />,
}

function projectState(project) {
  const command = project.command
  if (command && Number.isFinite(command.progress)) {
    if (command.progress >= 100) return { label: '已完成', tone: 'complete' }
    if (command.progress > 0 || command.task_done > 0) return { label: '进行中', tone: 'active' }
    if (command.task_total > 0) return { label: '待启动', tone: 'ready' }
  }
  return project.status === 'archived'
    ? { label: '已归档', tone: 'archived' }
    : { label: '待初始化', tone: 'ready' }
}

function formatProgress(value) {
  return Number.isFinite(value) ? `${Math.round(value)}%` : '暂不可用'
}

function verificationLabel(status) {
  return ({ verified: '已验证', pending: '待验证', failed: '验证失败' })[status] || '待验证'
}

export default function ProjectsList() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [form] = Form.useForm()
  const [createForm] = Form.useForm()
  const [assetForm] = Form.useForm()
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const view = searchParams.get('view') === 'assets' ? 'assets' : 'projects'
  const [projects, setProjects] = useState([])
  const [assets, setAssets] = useState([])
  const [assetSummary, setAssetSummary] = useState({ total: 0, verified: 0, at_risk: 0, services: 0 })
  const [loading, setLoading] = useState(true)
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [projectLoadError, setProjectLoadError] = useState('')
  const [assetLoadError, setAssetLoadError] = useState('')
  const [editingProject, setEditingProject] = useState(null)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [assetModalVisible, setAssetModalVisible] = useState(false)
  const [creatingDemo, setCreatingDemo] = useState(false)
  const [assetMutating, setAssetMutating] = useState(false)
  const [assetSearch, setAssetSearch] = useState('')
  const [assetProjectFilter, setAssetProjectFilter] = useState('all')
  const [assetTypeFilter, setAssetTypeFilter] = useState('all')
  const [assetVerificationFilter, setAssetVerificationFilter] = useState('all')
  const [assetPagination, setAssetPagination] = useState({ page: 1, page_size: 25, total: 0, pages: 0 })
  const [permissions, setPermissions] = useState([])
  const [selectedAssetId, setSelectedAssetId] = useState(null)

  const can = (permission) => permissions.includes(permission)

  const setView = (nextView) => setSearchParams(nextView === 'assets' ? { view: 'assets' } : {})

  const fetchProjects = async ({ silent = false } = {}) => {
    if (!currentOrgId) return
    setLoading(true)
    const [projectsResult, commandResult] = await Promise.allSettled([
      api.get('/projects/', { params: { organization_id: currentOrgId } }),
      api.get('/dashboard/organization-command', { params: { organization_id: currentOrgId } }),
    ])
    if (projectsResult.status === 'fulfilled') {
      setPermissions(commandResult.status === 'fulfilled' ? commandResult.value.data?.current_role?.permissions || [] : [])
      const matrixById = new Map(
        (commandResult.status === 'fulfilled' ? commandResult.value.data?.project_matrix : [])
          .map((project) => [project.project_id, project])
      )
      setProjects((projectsResult.value.data || []).map((project) => ({ ...project, command: matrixById.get(project.id) })))
      setProjectLoadError(commandResult.status === 'rejected' ? '测评明细暂时不可用，项目基础信息仍可正常使用。' : '')
    } else {
      const detail = errorMessage(projectsResult.reason, '项目列表暂时不可用')
      setProjectLoadError(detail)
      if (!silent) message.error(detail)
    }
    setLoading(false)
  }

  const fetchAssets = async ({ silent = false, page = assetPagination.page } = {}) => {
    if (!currentOrgId) return
    setAssetsLoading(true)
    try {
      const response = await api.get('/assets/inventory', {
        params: {
          organization_id: currentOrgId,
          page,
          page_size: assetPagination.page_size,
          project_id: assetProjectFilter === 'all' ? undefined : Number(assetProjectFilter),
          asset_type: assetTypeFilter === 'all' ? undefined : assetTypeFilter,
          verification_status: assetVerificationFilter === 'all' ? undefined : assetVerificationFilter,
          search: assetSearch.trim() || undefined,
        },
      })
      const nextAssets = response.data?.assets || []
      setAssets(nextAssets)
      setAssetSummary(response.data?.summary || { total: 0, verified: 0, at_risk: 0, services: 0 })
      setAssetPagination(response.data?.pagination || { page, page_size: assetPagination.page_size, total: 0, pages: 0 })
      setSelectedAssetId((current) => nextAssets.some((asset) => asset.id === current) ? current : nextAssets[0]?.id || null)
      setAssetLoadError('')
    } catch (error) {
      const detail = errorMessage(error, '资产矩阵暂时不可用')
      setAssetLoadError(detail)
      if (!silent) message.error(detail)
    } finally {
      setAssetsLoading(false)
    }
  }

  useEffect(() => { fetchProjects() }, [currentOrgId])
  useEffect(() => {
    if (view !== 'assets' || !currentOrgId) return undefined
    const timer = window.setTimeout(() => fetchAssets({ silent: true }), assetSearch ? 250 : 0)
    return () => window.clearTimeout(timer)
  }, [currentOrgId, view, assetPagination.page, assetProjectFilter, assetSearch, assetTypeFilter, assetVerificationFilter])

  const projectSummary = useMemo(() => ({
    total: projects.length,
    active: projects.filter((project) => projectState(project).tone === 'active').length,
    risk: projects.reduce((total, project) => total + Number(project.command?.risk_count || 0), 0),
    complete: projects.filter((project) => projectState(project).tone === 'complete').length,
  }), [projects])

  const selectedAsset = assets.find((asset) => asset.id === selectedAssetId) || assets[0] || null
  const typeCounts = assetSummary.type_counts || {}
  const changeAssetFilter = (setter) => (value) => {
    setter(value)
    setAssetPagination((current) => ({ ...current, page: 1 }))
  }

  const handleEdit = (project, event) => {
    event.stopPropagation()
    if (!can('project:update')) return message.warning('当前角色没有编辑项目的权限')
    setEditingProject(project)
    form.setFieldsValue({ name: project.name, description: project.description, system_name: project.system_name, status: project.status || 'active' })
    setEditModalVisible(true)
  }

  const handleUpdate = async () => {
    if (!can('project:update')) return message.warning('当前角色没有编辑项目的权限')
    try {
      const values = await form.validateFields()
      await api.put(`/projects/${editingProject.id}`, values)
      message.success('项目已更新')
      setEditModalVisible(false)
      await fetchProjects({ silent: true })
    } catch (error) {
      message.error(errorMessage(error, '更新项目失败'))
    }
  }

  const handleDeleteProject = async (projectId) => {
    if (!can('project:delete')) return message.warning('当前角色没有删除项目的权限')
    try {
      await api.delete(`/projects/${projectId}`)
      message.success('项目已删除')
      await Promise.all([fetchProjects({ silent: true }), fetchAssets({ silent: true })])
    } catch (error) {
      message.error(errorMessage(error, '删除项目失败'))
    }
  }

  const handleCreate = async () => {
    if (!currentOrgId) return
    if (!can('project:create')) return message.warning('当前角色没有新建项目的权限')
    try {
      const values = await createForm.validateFields()
      const response = await api.post('/projects/', { ...values, organization_id: currentOrgId })
      message.success('项目与 5 阶段测评流程已创建')
      setCreateModalVisible(false)
      createForm.resetFields()
      await fetchProjects({ silent: true })
      navigate(`/projects/${response.data.id}`)
    } catch (error) {
      message.error(errorMessage(error, '创建项目失败'))
    }
  }

  const handleCreateDemo = async () => {
    if (!currentOrgId) return
    if (!can('project:create')) return message.warning('当前角色没有创建演示项目的权限')
    setCreatingDemo(true)
    try {
      const response = await api.post('/projects/demo', { organization_id: currentOrgId })
      message.success(response.data?.message || '演示项目已就绪')
      await fetchProjects({ silent: true })
      navigate(`/projects/${response.data.project_id}`)
    } catch (error) {
      message.error(errorMessage(error, '创建演示项目失败'))
    } finally {
      setCreatingDemo(false)
    }
  }

  const handleCreateAsset = async () => {
    if (!can('asset:create')) return message.warning('当前角色没有添加资产的权限')
    try {
      const values = await assetForm.validateFields()
      setAssetMutating(true)
      const { project_id, ...payload } = values
      await api.post(`/projects/${project_id}/assets/`, payload)
      message.success('资产已添加，待完成验证后可执行检测')
      setAssetModalVisible(false)
      assetForm.resetFields()
      await Promise.all([fetchAssets({ silent: true }), fetchProjects({ silent: true })])
    } catch (error) {
      message.error(errorMessage(error, '添加资产失败'))
    } finally {
      setAssetMutating(false)
    }
  }

  const handleDeleteAsset = async (asset) => {
    if (!can('asset:delete')) return message.warning('当前角色没有删除资产的权限')
    try {
      await api.delete(`/projects/${asset.project_id}/assets/${asset.id}`)
      message.success('资产已删除')
      setSelectedAssetId(null)
      const page = assets.length === 1 && assetPagination.page > 1 ? assetPagination.page - 1 : assetPagination.page
      if (page !== assetPagination.page) setAssetPagination((current) => ({ ...current, page }))
      await Promise.all([fetchAssets({ silent: true, page }), fetchProjects({ silent: true })])
    } catch (error) {
      message.error(errorMessage(error, '删除资产失败'))
    }
  }

  return (
    <main className="projects-page">
      <header className="projects-topbar">
        <Button className="projects-back" type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/dashboard')}>Dashboard</Button>
        <div className="projects-brand">
          <VeriSureLogo size={30} />
          <div><span>项目工作台</span><em>项目组合与资产矩阵</em></div>
        </div>
        <nav className="workspace-tabs" aria-label="工作台视图">
          <button type="button" className={view === 'projects' ? 'active' : ''} onClick={() => setView('projects')}>项目组合</button>
          <button type="button" className={view === 'assets' ? 'active' : ''} onClick={() => setView('assets')}>资产矩阵</button>
        </nav>
        <div className="projects-top-actions">
          <Button icon={<ReloadOutlined spin={view === 'projects' ? loading : assetsLoading} />} onClick={() => view === 'projects' ? fetchProjects() : fetchAssets()}>刷新</Button>
          {view === 'projects' ? <Button icon={<RocketOutlined />} loading={creatingDemo} disabled={!can('project:create')} title={!can('project:create') ? '当前角色没有创建项目的权限' : undefined} onClick={handleCreateDemo}>演示项目</Button> : null}
          <Button type="primary" icon={<PlusOutlined />} disabled={view === 'projects' ? !can('project:create') : !can('asset:create')} title={view === 'projects' ? (!can('project:create') ? '当前角色没有创建项目的权限' : undefined) : (!can('asset:create') ? '当前角色没有添加资产的权限' : undefined)} onClick={() => view === 'projects' ? setCreateModalVisible(true) : setAssetModalVisible(true)}>{view === 'projects' ? '新建项目' : '添加资产'}</Button>
        </div>
      </header>

      {view === 'projects' ? (
        <ProjectsView
          projects={projects}
          summary={projectSummary}
          loading={loading}
          loadError={projectLoadError}
          navigate={navigate}
          onRetry={() => fetchProjects()}
          onEdit={handleEdit}
          onDelete={handleDeleteProject}
          onCreate={() => setCreateModalVisible(true)}
          canCreate={can('project:create')}
          canEdit={can('project:update')}
          canDelete={can('project:delete')}
        />
      ) : (
        <AssetsView
          assets={assets}
          assetSummary={assetSummary}
          typeCounts={typeCounts}
          pagination={assetPagination}
          selectedAsset={selectedAsset}
          loading={assetsLoading}
          loadError={assetLoadError}
          projects={projects}
          filters={{ assetSearch, assetProjectFilter, assetTypeFilter, assetVerificationFilter }}
          onFilterChange={{ setAssetSearch: changeAssetFilter(setAssetSearch), setAssetProjectFilter: changeAssetFilter(setAssetProjectFilter), setAssetTypeFilter: changeAssetFilter(setAssetTypeFilter), setAssetVerificationFilter: changeAssetFilter(setAssetVerificationFilter) }}
          onRetry={() => fetchAssets()}
          onPageChange={(page) => setAssetPagination((current) => ({ ...current, page }))}
          onSelectAsset={setSelectedAssetId}
          onNavigate={navigate}
          onCreate={() => setAssetModalVisible(true)}
          onDelete={handleDeleteAsset}
          canCreate={can('asset:create')}
          canDelete={can('asset:delete')}
        />
      )}

      <Modal title="新建项目" open={createModalVisible} onOk={handleCreate} onCancel={() => setCreateModalVisible(false)} okText="创建项目" cancelText="取消">
        <Form form={createForm} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}><Input placeholder="例如：生产门户系统" /></Form.Item>
          <Form.Item name="system_name" label="系统名称"><Input placeholder="例如：企业客户服务平台" /></Form.Item>
          <Form.Item name="compliance_level" label="等保等级" rules={[{ required: true, message: '请选择等保等级' }]}><Select options={[{ value: '二级', label: '等保二级' }, { value: '三级', label: '等保三级' }]} /></Form.Item>
          <Form.Item name="description" label="项目说明"><Input.TextArea rows={3} placeholder="可选" /></Form.Item>
        </Form>
      </Modal>

      <Modal title="编辑项目" open={editModalVisible} onOk={handleUpdate} onCancel={() => setEditModalVisible(false)} okText="保存" cancelText="取消">
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}><Input /></Form.Item>
          <Form.Item name="system_name" label="系统名称"><Input /></Form.Item>
          <Form.Item name="description" label="项目说明"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="status" label="项目状态"><Select options={[{ value: 'active', label: '启用' }, { value: 'archived', label: '归档' }]} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="添加资产" open={assetModalVisible} onOk={handleCreateAsset} onCancel={() => setAssetModalVisible(false)} okText="添加资产" cancelText="取消" confirmLoading={assetMutating}>
        <Form form={assetForm} layout="vertical">
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true, message: '请选择项目' }]}><Select options={projects.map((project) => ({ value: project.id, label: project.name }))} /></Form.Item>
          <Form.Item name="asset_type" label="资产类型" rules={[{ required: true, message: '请选择资产类型' }]}><Select options={Object.entries(assetTypeLabel).map(([value, label]) => ({ value, label }))} /></Form.Item>
          <Form.Item name="value" label="资产值" rules={[{ required: true, message: '请输入 IP、域名或云资源标识' }]}><Input placeholder="例如：203.0.113.10 或 portal.example.com" /></Form.Item>
          <Form.Item name="name" label="资产名称"><Input placeholder="可选，例如：生产 Web 网关" /></Form.Item>
        </Form>
      </Modal>
    </main>
  )
}

function ProjectsView({ projects, summary, loading, loadError, navigate, onRetry, onEdit, onDelete, onCreate, canCreate, canEdit, canDelete }) {
  return <>
    {loadError ? <LoadError text={loadError} onRetry={onRetry} /> : null}
    <section className="projects-summary" aria-label="项目摘要">
      <SummaryItem label="项目总数" value={summary.total} icon={<ProjectOutlined />} />
      <SummaryItem label="进行中" value={summary.active} icon={<SafetyCertificateOutlined />} tone="cyan" />
      <SummaryItem label="待处置风险" value={summary.risk} icon={<SafetyCertificateOutlined />} tone="danger" />
      <SummaryItem label="已完成" value={summary.complete} icon={<SafetyCertificateOutlined />} tone="green" />
    </section>
    <section className="projects-heading"><div><span>项目组合</span><p>测评进度、合规得分和风险数量分别来自独立数据口径。</p></div><em>{loading ? '正在同步' : `${projects.length} 个项目`}</em></section>
    <section className="projects-grid" aria-busy={loading}>
      {projects.map((project) => {
        const state = projectState(project)
        const progress = project.command?.progress
        const taskDone = project.command?.task_done
        const taskTotal = project.command?.task_total
        return <article key={project.id} className="project-card" onClick={() => navigate(`/projects/${project.id}`)}>
          <div className="project-card-head"><span className="project-id">P-{String(project.id).padStart(3, '0')}</span><div><Tag color={project.compliance_level === '三级' ? 'blue' : 'cyan'}>{project.compliance_level || '未定级'}</Tag><span className={`project-state ${state.tone}`}>{state.label}</span></div></div>
          <div className="project-card-title"><h2>{project.name}</h2><p>{project.system_name || '未填写系统名称'}</p></div>
          <div className="project-stage"><span>{project.command?.stage || '测评流程暂未初始化'}</span><strong>{formatProgress(progress)}</strong></div>
          <div className="project-progress"><i style={{ width: `${Math.max(0, Math.min(100, progress || 0))}%` }} /></div>
          <dl className="project-metrics"><div><dt>测评任务</dt><dd>{Number.isFinite(taskDone) ? `${taskDone}/${taskTotal || 0}` : '-'}</dd></div><div><dt>待处置风险</dt><dd className={project.command?.risk_count ? 'danger' : ''}>{Number.isFinite(project.command?.risk_count) ? project.command.risk_count : '-'}</dd></div><div><dt>合规得分</dt><dd>{Number.isFinite(project.compliance_score) ? `${Math.round(project.compliance_score)} 分` : '-'}</dd></div></dl>
          <div className="project-card-actions" onClick={(event) => event.stopPropagation()}><Button type="text" icon={<EditOutlined />} disabled={!canEdit} title={!canEdit ? '当前角色没有编辑项目的权限' : undefined} onClick={(event) => onEdit(project, event)}>编辑</Button><Popconfirm disabled={!canDelete} title="确认删除项目？" description="项目、检测结果与整改记录将一并删除。" onConfirm={() => onDelete(project.id)} okText="删除" cancelText="取消" okButtonProps={{ danger: true }}><Button type="text" danger icon={<DeleteOutlined />} disabled={!canDelete} title={!canDelete ? '当前角色没有删除项目的权限' : undefined}>删除</Button></Popconfirm><Button type="primary" onClick={() => navigate(`/projects/${project.id}`)}>进入项目</Button></div>
        </article>
      })}
      {!loading && !projects.length ? <EmptyState icon={<ProjectOutlined />} title="还没有项目" action={canCreate ? '新建项目' : undefined} onAction={onCreate} /> : null}
    </section>
  </>
}

function AssetsView({ assets, assetSummary, typeCounts, pagination, selectedAsset, loading, loadError, projects, filters, onFilterChange, onRetry, onPageChange, onSelectAsset, onNavigate, onCreate, onDelete, canCreate, canDelete }) {
  const projectOptions = [{ value: 'all', label: '全部项目' }, ...projects.map((project) => ({ value: String(project.id), label: project.name }))]
  return <>
    {loadError ? <LoadError text={loadError} onRetry={onRetry} /> : null}
    <section className="projects-summary asset-summary" aria-label="资产摘要">
      <SummaryItem label="纳管资产" value={assetSummary.total} icon={<DatabaseOutlined />} />
      <SummaryItem label="已验证" value={assetSummary.verified} icon={<SafetyCertificateOutlined />} tone="green" />
      <SummaryItem label="关联风险资产" value={assetSummary.at_risk} icon={<SafetyCertificateOutlined />} tone="danger" />
      <SummaryItem label="已发现服务" value={assetSummary.services} icon={<ApiOutlined />} tone="cyan" />
    </section>
    <section className="asset-heading"><div><span>资产矩阵</span><p>按所属项目、资产类型、验证状态和已发现服务统一查看。</p></div><em>{loading ? '正在同步' : `${assets.length} / ${pagination.total} 个匹配资产`}</em></section>
    <section className="asset-toolbar">
      <Select value={filters.assetProjectFilter} onChange={onFilterChange.setAssetProjectFilter} options={projectOptions} />
      <Select value={filters.assetTypeFilter} onChange={onFilterChange.setAssetTypeFilter} options={[{ value: 'all', label: '全部类型' }, ...Object.entries(assetTypeLabel).map(([value, label]) => ({ value, label }))]} />
      <Select value={filters.assetVerificationFilter} onChange={onFilterChange.setAssetVerificationFilter} options={[{ value: 'all', label: '全部验证状态' }, { value: 'verified', label: '已验证' }, { value: 'pending', label: '待验证' }, { value: 'failed', label: '验证失败' }]} />
      <Input prefix={<SearchOutlined />} value={filters.assetSearch} onChange={(event) => onFilterChange.setAssetSearch(event.target.value)} placeholder="搜索 IP、域名、资产名称或项目" />
      <Button type="primary" icon={<PlusOutlined />} disabled={!canCreate} title={!canCreate ? '当前角色没有添加资产的权限' : undefined} onClick={onCreate}>添加资产</Button>
    </section>
    <section className="asset-flow" aria-label="资产关系概览">
      <FlowNode label="所属项目" value={projects.length} /><i /><FlowNode label="域名" value={typeCounts.domain || 0} icon={<GlobalOutlined />} /><i /><FlowNode label="IP 主机" value={typeCounts.ip || 0} icon={<ApiOutlined />} /><i /><FlowNode label="云资源" value={typeCounts.cloud_resource || 0} icon={<CloudServerOutlined />} /><i /><FlowNode label="已验证资产" value={assetSummary.verified} tone="green" />
    </section>
    <section className="asset-workspace">
      <div className="asset-table-shell">
        <div className="asset-table-head"><span>资产名称 / IP</span><span>资产类型</span><span>所属项目</span><span>验证状态</span><span>已发现服务</span><span>风险</span></div>
        <div className="asset-table-rows">
          {assets.map((asset) => <button type="button" key={asset.id} className={`asset-row ${selectedAsset?.id === asset.id ? 'selected' : ''}`} onClick={() => onSelectAsset(asset.id)}>
            <span className="asset-main"><i className={`asset-type-icon ${asset.asset_type}`}>{assetIcon[asset.asset_type] || <DatabaseOutlined />}</i><b>{asset.value}</b><em>{asset.name || '未命名资产'}</em></span>
            <span>{assetTypeLabel[asset.asset_type] || asset.asset_type}</span>
            <span className="asset-project-name">{asset.project_name}</span>
            <span className={`asset-verification ${asset.verification_status}`}>{verificationLabel(asset.verification_status)}</span>
            <span>{asset.services?.length ? asset.services.map((service) => service.label).join(' / ') : '-'}</span>
            <span className={asset.risk_count ? 'asset-risk hot' : 'asset-risk'}>{asset.risk_count ? `${asset.risk_count} 项` : '无'}</span>
          </button>)}
          {!loading && !assets.length ? <EmptyState icon={<DatabaseOutlined />} title="当前筛选条件下没有资产" action={canCreate ? '添加资产' : undefined} onAction={onCreate} /> : null}
        </div>
        <div className="asset-pagination" aria-label="资产分页">
          <span>共 {pagination.total} 项</span>
          <div><Button type="text" size="small" icon={<LeftOutlined />} disabled={pagination.page <= 1 || loading} onClick={() => onPageChange(pagination.page - 1)} /><em>{pagination.page} / {Math.max(1, pagination.pages)}</em><Button type="text" size="small" icon={<RightOutlined />} disabled={pagination.page >= pagination.pages || loading} onClick={() => onPageChange(pagination.page + 1)} /></div>
        </div>
      </div>
      <aside className="asset-inspector">
        {selectedAsset ? <>
          <div className="asset-inspector-title"><span>资产详情</span><strong>{selectedAsset.value}</strong><em>{selectedAsset.project_name}</em></div>
          <dl><div><dt>资产类型</dt><dd>{assetTypeLabel[selectedAsset.asset_type]}</dd></div><div><dt>验证状态</dt><dd className={`asset-verification ${selectedAsset.verification_status}`}>{verificationLabel(selectedAsset.verification_status)}</dd></div><div><dt>待处置风险</dt><dd className={selectedAsset.risk_count ? 'danger' : ''}>{selectedAsset.risk_count} 项</dd></div><div><dt>历史发现</dt><dd>{selectedAsset.finding_count} 项</dd></div></dl>
          <div className="asset-services"><span>已发现服务</span>{selectedAsset.services?.length ? selectedAsset.services.map((service) => <div key={service.id}><b>{service.label}</b><em>{service.service || '服务未识别'}</em></div>) : <p>尚未从扫描结果中发现开放服务。</p>}</div>
          <div className="asset-inspector-actions"><Button onClick={() => onNavigate(`/projects/${selectedAsset.project_id}`)}>进入项目</Button><Popconfirm disabled={!canDelete} title="确认删除该资产？" description="关联资产记录将不可恢复。" onConfirm={() => onDelete(selectedAsset)} okText="删除" cancelText="取消" okButtonProps={{ danger: true }}><Button danger icon={<DeleteOutlined />} disabled={!canDelete} title={!canDelete ? '当前角色没有删除资产的权限' : undefined}>删除资产</Button></Popconfirm></div>
        </> : <div className="asset-inspector-empty">选择资产以查看归属、验证状态、风险和服务。</div>}
      </aside>
    </section>
  </>
}

function SummaryItem({ label, value, icon, tone = '' }) { return <div className={`projects-summary-item ${tone}`}><span>{icon}</span><div><strong>{value}</strong><em>{label}</em></div></div> }
function LoadError({ text, onRetry }) { return <div className="projects-load-error">{text}<Button type="link" size="small" onClick={onRetry}>重试</Button></div> }
function EmptyState({ icon, title, action, onAction }) { return <div className="projects-empty">{icon}<strong>{title}</strong>{action ? <Button type="primary" icon={<PlusOutlined />} onClick={onAction}>{action}</Button> : null}</div> }
function FlowNode({ label, value, icon, tone = '' }) { return <div className={`asset-flow-node ${tone}`}>{icon || <ProjectOutlined />}<div><span>{label}</span><strong>{value}</strong></div></div> }
