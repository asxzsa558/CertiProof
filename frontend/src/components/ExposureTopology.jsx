import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  BaseEdge,
  Controls,
  getBezierPath,
  Handle,
  Position,
  ReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  ApiOutlined,
  BankOutlined,
  ClusterOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  FolderOpenOutlined,
  FullscreenOutlined,
  GlobalOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import './ExposureTopology.css'

const ASSET_TYPES = new Set(['ip', 'domain', 'cloud_resource'])
const TYPE_LABELS = {
  organization: '组织',
  project: '项目',
  ip: 'IP 主机',
  domain: '域名',
  cloud_resource: '云资源',
  asset_group: '资产组',
  service: '已验证服务',
}

const TYPE_ICONS = {
  organization: BankOutlined,
  project: FolderOpenOutlined,
  ip: ApiOutlined,
  domain: GlobalOutlined,
  cloud_resource: CloudServerOutlined,
  asset_group: DatabaseOutlined,
  service: ApiOutlined,
}

const RISK_LABELS = {
  critical: '严重风险',
  high: '高风险',
  warning: '待关注',
  normal: '未发现风险',
}

const EVENT_SEVERITY_LABELS = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '信息',
}

function eventTime(value) {
  if (!value) return '暂无时间'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '暂无时间'
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function topologyNodeClass({ nodeKind, riskLevel, verified }) {
  return ['exposure-node', `kind-${nodeKind}`, `risk-${riskLevel || 'normal'}`, verified === false ? 'is-unverified' : ''].filter(Boolean).join(' ')
}

function TopologyNode({ data, selected }) {
  const Icon = TYPE_ICONS[data.nodeKind] || ApiOutlined
  const riskCount = data.risk_count ?? data.riskCount
  const title = riskCount ? `${data.label}：${riskCount} 项待处理风险` : data.label

  return (
    <div className={`${topologyNodeClass(data)} ${data.active ? 'is-active' : ''} ${selected || data.selected ? 'is-selected' : ''}`} title={title}>
      <Handle type="target" position={Position.Left} className="exposure-handle" />
      <div className="exposure-orb"><Icon /></div>
      {data.badge ? <i>{data.badge}</i> : null}
      <div className="exposure-node-copy">
        <strong>{data.label}</strong>
        <span>{data.subtitle || TYPE_LABELS[data.nodeKind]}</span>
      </div>
      <Handle type="source" position={Position.Right} className="exposure-handle" />
    </div>
  )
}

const nodeTypes = { exposure: TopologyNode }

function IntelligenceEdge({ id, sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, data }) {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition: sourcePosition || Position.Right,
    targetX,
    targetY,
    targetPosition: targetPosition || Position.Left,
    curvature: data?.curvature ?? 0.34,
  })
  const kind = data?.kind || 'asset'

  return (
    <g className={`intelligence-edge kind-${kind}`}>
      <BaseEdge id={id} path={edgePath} className="intelligence-edge-path" />
      <circle className="intelligence-edge-anchor source" cx={sourceX} cy={sourceY} r="2.4" />
      <circle className="intelligence-edge-anchor target" cx={targetX} cy={targetY} r="2.8" />
    </g>
  )
}

const edgeTypes = { intelligence: IntelligenceEdge }

function TopologyMiniMap({ nodes, edges, selectedAssetId }) {
  const graphNodes = nodes.filter((node) => node.position)
  if (!graphNodes.length) return null

  const xValues = graphNodes.map((node) => node.position.x)
  const yValues = graphNodes.map((node) => node.position.y)
  const minX = Math.min(...xValues) - 60
  const maxX = Math.max(...xValues) + 140
  const minY = Math.min(...yValues) - 45
  const maxY = Math.max(...yValues) + 90
  const scaleX = (value) => 14 + ((value - minX) / Math.max(maxX - minX, 1)) * 174
  const scaleY = (value) => 14 + ((value - minY) / Math.max(maxY - minY, 1)) * 94
  const points = Object.fromEntries(graphNodes.map((node) => [node.id, { x: scaleX(node.position.x), y: scaleY(node.position.y) }]))

  return (
    <div className="topology-minimap" aria-label="拓扑缩略图" title="拓扑缩略图">
      <svg viewBox="0 0 202 122" role="img" aria-hidden="true">
        <rect className="topology-map-frame" x="5" y="5" width="192" height="112" />
        {edges.map((edge) => {
          const source = points[edge.source]
          const target = points[edge.target]
          if (!source || !target) return null
          const midpoint = (source.x + target.x) / 2
          return <path key={edge.id} className="topology-map-edge" d={`M ${source.x} ${source.y} Q ${midpoint} ${source.y} ${target.x} ${target.y}`} />
        })}
        {graphNodes.map((node) => {
          const point = points[node.id]
          const kind = node.data?.nodeKind || 'asset'
          const radius = kind === 'organization' ? 6 : kind === 'project' ? 5 : kind === 'service' ? 3 : 4
          return <circle key={node.id} className={`topology-map-node kind-${kind} ${node.id === selectedAssetId ? 'is-selected' : ''}`} cx={point.x} cy={point.y} r={radius} />
        })}
      </svg>
    </div>
  )
}

function serviceNodesFor(asset, assetPosition, nodes, edges, offset = 148) {
  const services = (asset.services || []).slice(0, 6)
  services.forEach((service, index) => {
    const serviceId = `service-${asset.id}-${service.id || index}`
    nodes.push({
      id: serviceId,
      type: 'exposure',
      position: { x: assetPosition.x + offset, y: assetPosition.y - 10 + index * 62 },
      draggable: false,
      data: {
        nodeKind: 'service',
        label: service.label,
        subtitle: service.service || '已验证服务',
        verified: true,
      },
    })
    edges.push({
      id: `${asset.id}-${serviceId}`,
      source: asset.id,
      target: serviceId,
      type: 'intelligence',
      data: { kind: 'service', curvature: 0.25 },
    })
  })
}

function buildGraph({ topology, expandedProjectId, expandedGroup, selectedAssetId, projectScope, riskFilter, search }) {
  const allNodes = topology.nodes || []
  const organization = allNodes.find((node) => node.type === 'organization')
  const projects = allNodes.filter((node) => node.type === 'project')
  const assets = allNodes.filter((node) => ASSET_TYPES.has(node.type))
  const normalizedSearch = search.trim().toLowerCase()
  const matchesSearch = (node) => !normalizedSearch || `${node.label} ${node.project_name || ''}`.toLowerCase().includes(normalizedSearch)
  const visibleProjects = projects.filter((project) => projectScope === 'all' || project.id === projectScope)
  const projectMatches = visibleProjects.filter((project) => (
    matchesSearch(project) || assets.some((asset) => asset.project_id === project.project_id && matchesSearch(asset))
  ))
  const scopedProjects = (normalizedSearch ? projectMatches : visibleProjects).slice(0, 12)
  const activeProjectId = expandedProjectId && scopedProjects.some((project) => project.id === expandedProjectId)
    ? expandedProjectId
    : null
  const activeProject = projects.find((project) => project.id === activeProjectId)
  const activeAssets = activeProject
    ? assets.filter((asset) => (
      asset.project_id === activeProject.project_id
      && matchesSearch(asset)
      && (riskFilter === 'all' || asset.status === riskFilter)
    ))
    : []
  const nodes = []
  const edges = []
  const projectCount = Math.max(scopedProjects.length, 1)
  const projectCenterY = Math.max(210, (projectCount - 1) * 72 + 120)

  if (organization) {
    nodes.push({
      id: organization.id,
      type: 'exposure',
      position: { x: 28, y: projectCenterY },
      draggable: false,
      data: { ...organization, nodeKind: 'organization', subtitle: `${projects.length} 个项目` },
    })
  }

  let compactProjectIndex = 0
  scopedProjects.forEach((project) => {
    const isActive = project.id === activeProjectId
    const y = isActive ? projectCenterY : 52 + compactProjectIndex++ * 124
    nodes.push({
      id: project.id,
      type: 'exposure',
      position: { x: isActive ? 310 : 150, y },
      draggable: false,
      data: {
        ...project,
        nodeKind: 'project',
        active: isActive,
        riskLevel: project.status,
        subtitle: `${project.asset_count || 0} 个资产${project.risk_count ? ` · ${project.risk_count} 项风险` : ''}`,
        badge: project.asset_count || undefined,
      },
    })
    if (organization) {
      edges.push({
        id: `${organization.id}-${project.id}`,
        source: organization.id,
        target: project.id,
        type: 'intelligence',
        data: { kind: isActive ? 'project-active' : 'project', curvature: isActive ? 0.42 : 0.3 },
      })
    }
  })

  if (!activeProject) return { nodes, edges, activeProject: null, activeAssets: [] }

  const selectedGroup = expandedGroup && expandedGroup.projectId === activeProject.project_id ? expandedGroup : null
  const groupByType = activeAssets.length > 24 && !selectedGroup
  const displayAssets = selectedGroup
    ? activeAssets.filter((asset) => asset.type === selectedGroup.type)
    : activeAssets

  if (groupByType) {
    const groups = [...ASSET_TYPES].map((type) => ({
      type,
      assets: activeAssets.filter((asset) => asset.type === type),
    })).filter((group) => group.assets.length)
    groups.forEach((group, index) => {
      const id = `asset-group-${activeProject.project_id}-${group.type}`
      nodes.push({
        id,
        type: 'exposure',
        position: { x: 534, y: 70 + index * 128 },
        draggable: false,
        data: {
          nodeKind: 'asset_group',
          label: TYPE_LABELS[group.type],
          subtitle: `${group.assets.length} 个资产，点击展开`,
          badge: group.assets.length,
          projectId: activeProject.project_id,
          groupType: group.type,
          riskLevel: group.assets.some((asset) => asset.status === 'critical') ? 'critical' : group.assets.some((asset) => asset.status === 'high') ? 'high' : group.assets.some((asset) => asset.status === 'warning') ? 'warning' : 'normal',
        },
      })
      edges.push({
        id: `${activeProject.id}-${id}`,
        source: activeProject.id,
        target: id,
        type: 'intelligence',
        data: { kind: 'asset-group', curvature: 0.3 },
      })
    })
    return { nodes, edges, activeProject, activeAssets }
  }

  const columns = displayAssets.length > 7 ? 2 : 1
  const rows = Math.max(Math.ceil(displayAssets.length / columns), 1)
  displayAssets.slice(0, 40).forEach((asset, index) => {
    const column = Math.floor(index / rows)
    const row = index % rows
    const position = { x: 560 + column * 254, y: 44 + row * 112 }
    nodes.push({
      id: asset.id,
      type: 'exposure',
      position,
      draggable: false,
      data: {
        ...asset,
        nodeKind: asset.type,
        riskLevel: asset.status,
        subtitle: asset.risk_count ? `${asset.risk_count} 项待处理风险` : asset.verification === 'verified' ? '已验证资产' : '待验证资产',
        badge: asset.risk_count || undefined,
        verified: asset.verification === 'verified',
        selected: asset.id === selectedAssetId,
      },
    })
    edges.push({
      id: `${activeProject.id}-${asset.id}`,
      source: activeProject.id,
      target: asset.id,
      type: 'intelligence',
      data: { kind: 'asset', curvature: 0.32 },
    })
    if (asset.id === selectedAssetId) serviceNodesFor(asset, position, nodes, edges, columns > 1 && column === 0 ? 500 : 214)
  })

  return { nodes, edges, activeProject, activeAssets }
}

export default function ExposureTopology({ topology }) {
  const [expandedProjectId, setExpandedProjectId] = useState(undefined)
  const [expandedGroup, setExpandedGroup] = useState(null)
  const [selectedAssetId, setSelectedAssetId] = useState(null)
  const [projectScope, setProjectScope] = useState('all')
  const [riskFilter, setRiskFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [flow, setFlow] = useState(null)

  const projects = useMemo(() => (topology.nodes || []).filter((node) => node.type === 'project'), [topology.nodes])
  const assets = useMemo(() => (topology.nodes || []).filter((node) => ASSET_TYPES.has(node.type)), [topology.nodes])
  const defaultProjectId = projects.find((project) => project.risk_count)?.id || projects[0]?.id || null
  const effectiveExpandedProjectId = expandedProjectId === undefined ? defaultProjectId : expandedProjectId
  const graph = useMemo(() => buildGraph({
    topology,
    expandedProjectId: effectiveExpandedProjectId,
    expandedGroup,
    selectedAssetId,
    projectScope,
    riskFilter,
    search,
  }), [topology, effectiveExpandedProjectId, expandedGroup, selectedAssetId, projectScope, riskFilter, search])
  const selectedAsset = assets.find((asset) => asset.id === selectedAssetId) || null
  const inspectorAssets = useMemo(() => graph.activeProject
    ? assets.filter((asset) => asset.project_id === graph.activeProject.project_id)
    : assets, [assets, graph.activeProject])
  const assetComposition = useMemo(() => [...ASSET_TYPES].map((type) => ({
    type,
    count: inspectorAssets.filter((asset) => asset.type === type).length,
  })).filter((item) => item.count), [inspectorAssets])
  const verifiedAssetCount = inspectorAssets.filter((asset) => asset.verification === 'verified').length
  const observedServiceCount = inspectorAssets.reduce((count, asset) => count + (asset.services?.length || 0), 0)
  const riskTotal = inspectorAssets.reduce((count, asset) => count + (asset.risk_count || 0), 0)
  const intelligenceItems = useMemo(() => (topology.risk_intelligence || [])
    .filter((item) => (!graph.activeProject || item.project_id === graph.activeProject.project_id) && (!selectedAsset || item.asset_id === selectedAsset.id))
    .slice(0, 8), [topology.risk_intelligence, graph.activeProject, selectedAsset])

  useEffect(() => {
    if (selectedAsset && selectedAsset.project_id !== graph.activeProject?.project_id) setSelectedAssetId(null)
  }, [graph.activeProject?.project_id, selectedAsset])

  useEffect(() => {
    if (!flow || !graph.nodes.length) return undefined
    const frame = requestAnimationFrame(() => flow.fitView({ padding: 0.26, duration: 280, maxZoom: 1.08 }))
    return () => cancelAnimationFrame(frame)
  }, [flow, graph.nodes.length, effectiveExpandedProjectId, expandedGroup])

  const handleNodeClick = (_, node) => {
    const { nodeKind, projectId, groupType } = node.data
    if (nodeKind === 'organization') {
      setExpandedProjectId(null)
      setExpandedGroup(null)
      setSelectedAssetId(null)
      return
    }
    if (nodeKind === 'project') {
      setExpandedProjectId(node.id)
      setExpandedGroup(null)
      setSelectedAssetId(null)
      return
    }
    if (nodeKind === 'asset_group') {
      setExpandedGroup({ projectId, type: groupType })
      setSelectedAssetId(null)
      return
    }
    if (ASSET_TYPES.has(nodeKind)) setSelectedAssetId(node.id)
  }

  const showOverview = () => {
    setExpandedProjectId(null)
    setExpandedGroup(null)
    setSelectedAssetId(null)
  }

  const selectedRiskLabel = selectedAsset?.status ? RISK_LABELS[selectedAsset.status] || '待复核' : ''
  const focusAsset = (asset) => {
    const assetProjectAssets = assets.filter((item) => item.project_id === asset.project_id)
    setProjectScope('all')
    setSearch('')
    setRiskFilter('all')
    setExpandedProjectId(`project-${asset.project_id}`)
    setExpandedGroup(assetProjectAssets.length > 24 ? { projectId: asset.project_id, type: asset.type } : null)
    setSelectedAssetId(asset.id)
  }

  return (
    <div className="exposure-topology">
      <div className="exposure-toolbar">
        <div className="exposure-heading">
          <span><ClusterOutlined /></span>
          <div><strong>资产暴露面拓扑</strong><em>{assets.length} 个受管资产</em></div>
        </div>
        <select className="exposure-project-select" aria-label="项目范围" value={projectScope} onChange={(event) => {
          const value = event.target.value
          setProjectScope(value)
          setExpandedProjectId(value === 'all' ? null : value)
          setExpandedGroup(null)
          setSelectedAssetId(null)
        }}>
          <option value="all">全部项目</option>
          {projects.map((project) => <option key={project.id} value={project.id}>{project.label}</option>)}
        </select>
        <label className="exposure-search">
          <SearchOutlined />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索资产、域名、IP 或项目" />
        </label>
        <select className="exposure-risk-select" aria-label="风险筛选" value={riskFilter} onChange={(event) => {
          setRiskFilter(event.target.value)
          setExpandedGroup(null)
          setSelectedAssetId(null)
        }}>
          <option value="all">全部风险</option>
          <option value="high">高风险</option>
          <option value="warning">待关注</option>
          <option value="normal">未发现风险</option>
        </select>
        <button type="button" className="topology-fit" title="适配视图" onClick={() => flow?.fitView({ padding: 0.26, duration: 280, maxZoom: 1.08 })}><FullscreenOutlined /><span>适配视图</span></button>
      </div>

      <div className="exposure-stage">
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onInit={setFlow}
          onNodeClick={handleNodeClick}
          nodesConnectable={false}
          nodesDraggable={false}
          elementsSelectable
          fitView
          minZoom={0.3}
          maxZoom={1.6}
          proOptions={{ hideAttribution: true }}
          defaultEdgeOptions={{ type: 'intelligence' }}
        >
          <Background gap={28} size={1} color="rgba(34, 211, 238, 0.09)" />
          <Controls showInteractive={false} />
        </ReactFlow>
        <TopologyMiniMap nodes={graph.nodes} edges={graph.edges} selectedAssetId={selectedAssetId} />
        {!graph.nodes.length ? <div className="exposure-empty">暂无资产拓扑。添加资产并执行检测后会自动生成真实关系。</div> : null}
      </div>

      <div className="exposure-footer">
        <div className="exposure-path">
          <button type="button" onClick={showOverview}>全部项目</button>
          {graph.activeProject ? <><span>/</span><button type="button" onClick={() => { setExpandedGroup(null); setSelectedAssetId(null) }}>{graph.activeProject.label}</button></> : null}
          {expandedGroup ? <><span>/</span><button type="button" onClick={() => { setExpandedGroup(null); setSelectedAssetId(null) }}>{TYPE_LABELS[expandedGroup.type]}</button></> : null}
        </div>
        <div className="exposure-legend"><span className="legend-project" />项目 <span className="legend-asset" />资产 <span className="legend-service" />已验证服务 <span className="legend-risk" />风险</div>
      </div>

      <aside className="exposure-inspector">
        {selectedAsset ? <>
          <div className="inspector-title"><span>{TYPE_LABELS[selectedAsset.type]}</span><strong>{selectedAsset.label}</strong></div>
          <dl>
            <div><dt>所属项目</dt><dd>{selectedAsset.project_name || graph.activeProject?.label || '未关联'}</dd></div>
            <div><dt>验证状态</dt><dd>{selectedAsset.verification === 'verified' ? '已验证' : '待验证'}</dd></div>
            <div><dt>风险状态</dt><dd className={['critical', 'high'].includes(selectedAsset.status) ? 'risk-text-high' : selectedAsset.status === 'warning' ? 'risk-text-warning' : ''}>{selectedRiskLabel}</dd></div>
          </dl>
          <div className="inspector-metrics">
            <div><strong>{selectedAsset.risk_count || 0}</strong><span>待处理风险</span></div>
            <div><strong>{selectedAsset.services?.length || 0}</strong><span>已验证服务</span></div>
          </div>
          <div className="inspector-section"><span>已验证服务</span>{selectedAsset.services?.length ? selectedAsset.services.map((service) => <b key={service.id || service.label}>{service.label}{service.service ? ` · ${service.service}` : ''}</b>) : <em>暂无端口或服务检测证据</em>}</div>
        </> : <>
          <div className="inspector-title"><span>{graph.activeProject ? '项目资产概览' : '组织资产概览'}</span><strong>{graph.activeProject?.label || '全部项目'}</strong></div>
          <div className="inspector-metrics">
            <div><strong>{inspectorAssets.length}</strong><span>纳管资产</span></div>
            <div><strong>{verifiedAssetCount}</strong><span>已验证</span></div>
            <div><strong>{observedServiceCount}</strong><span>已验证服务</span></div>
            <div><strong className={riskTotal ? 'risk-text-warning' : ''}>{riskTotal}</strong><span>待处理风险</span></div>
          </div>
          <div className="inspector-section inspector-composition"><span>资产构成</span><div>{assetComposition.length ? assetComposition.map((item) => <b key={item.type}>{TYPE_LABELS[item.type]} <em>{item.count}</em></b>) : <em>暂无资产</em>}</div></div>
        </>}
        <div className="inspector-section intelligence-stream">
          <div className="intelligence-head"><span>风险情报流</span><em>{intelligenceItems.length} 条</em></div>
          <div className="intelligence-list">
            {intelligenceItems.length ? intelligenceItems.map((item) => <button key={item.id} type="button" className={`intelligence-row severity-${item.severity || 'info'}`} onClick={() => {
              const asset = assets.find((entry) => entry.id === item.asset_id)
              if (asset) focusAsset(asset)
            }}>
              <i />
              <div>
                <header><b>{EVENT_SEVERITY_LABELS[item.severity] || '信息'}</b><time>{eventTime(item.observed_at)}</time><strong>{item.asset}</strong></header>
                <p><b>{item.title}</b>{item.description && item.description !== item.title ? ` · ${item.description}` : ''}</p>
              </div>
            </button>) : <em>暂无有资产归属的待处理风险</em>}
          </div>
        </div>
      </aside>
    </div>
  )
}
