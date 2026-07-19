import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
  normal: '当前无待处理发现',
  unverified: '未验证或无有效检测',
}

const RISK_FILTERS = [
  { value: 'all', label: '全部资产', title: '显示当前范围内全部受管资产' },
  { value: 'elevated', label: '严重/高风险', title: '显示存在严重或高风险问题的资产' },
  { value: 'warning', label: '待关注', title: '显示存在中风险待处理问题的资产' },
  { value: 'normal', label: '当前无待处理', title: '显示已验证且当前没有待处理风险的资产' },
  { value: 'unverified', label: '未验证', title: '显示权属未验证或没有有效检测记录的资产' },
]

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

function fullTime(value) {
  if (!value) return '暂无记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '暂无记录'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function matchesRiskFilter(asset, filter) {
  if (filter === 'all') return true
  if (filter === 'elevated') return asset.status === 'critical' || asset.status === 'high'
  return asset.status === filter
}

function topologyNodeClass({ nodeKind, riskLevel, verified }) {
  return ['exposure-node', `kind-${nodeKind}`, `risk-${riskLevel || 'normal'}`, riskLevel === 'unverified' || verified === false ? 'is-unverified' : ''].filter(Boolean).join(' ')
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

function TopologyMiniMap({ nodes, edges, selectedNodeId }) {
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
          return <circle key={node.id} className={`topology-map-node kind-${kind} ${node.id === selectedNodeId ? 'is-selected' : ''}`} cx={point.x} cy={point.y} r={radius} />
        })}
      </svg>
    </div>
  )
}

function serviceNodesFor(asset, assetPosition, nodes, edges, selectedNodeId, offset = 148) {
  const services = (asset.services || []).slice(0, 6)
  services.forEach((service, index) => {
    const serviceId = `service-${asset.id}-${service.id || index}`
    nodes.push({
      id: serviceId,
      type: 'exposure',
      position: { x: assetPosition.x + offset, y: assetPosition.y - 10 + index * 62 },
      draggable: false,
      data: {
        ...service,
        nodeKind: 'service',
        label: service.label,
        subtitle: service.service || '已验证服务',
        assetId: asset.id,
        assetLabel: asset.asset_name || asset.label,
        assetValue: asset.value || asset.label,
        projectId: asset.project_id,
        projectName: asset.project_name,
        observedAt: service.observed_at || asset.last_scan?.observed_at,
        riskLevel: 'normal',
        verified: true,
        selected: serviceId === selectedNodeId,
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

function buildGraph({ topology, expandedProjectId, expandedGroup, selectedNodeId, selectedAssetId, projectScope, riskFilter, search }) {
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
      && matchesRiskFilter(asset, riskFilter)
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
      data: {
        ...organization,
        nodeKind: 'organization',
        riskLevel: organization.status,
        subtitle: `${projects.length} 个项目`,
        selected: organization.id === selectedNodeId,
      },
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
        subtitle: `${project.asset_count || 0} 个资产${project.risk_count ? ` · ${project.risk_count} 项待处理` : ''}`,
        badge: project.asset_count || undefined,
        selected: project.id === selectedNodeId,
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
          subtitle: `${group.assets.length} 个资产，点击查看`,
          badge: group.assets.length,
          projectId: activeProject.project_id,
          projectName: activeProject.label,
          groupType: group.type,
          assetCount: group.assets.length,
          verifiedCount: group.assets.filter((asset) => asset.verification === 'verified').length,
          serviceCount: group.assets.reduce((count, asset) => count + (asset.services?.length || 0), 0),
          riskCount: group.assets.reduce((count, asset) => count + (asset.risk_count || 0), 0),
          elevatedCount: group.assets.filter((asset) => ['critical', 'high'].includes(asset.status)).length,
          unverifiedCount: group.assets.filter((asset) => asset.status === 'unverified').length,
          riskLevel: group.assets.some((asset) => asset.status === 'critical') ? 'critical' : group.assets.some((asset) => asset.status === 'high') ? 'high' : group.assets.some((asset) => asset.status === 'warning') ? 'warning' : group.assets.every((asset) => asset.status === 'unverified') ? 'unverified' : 'normal',
          selected: id === selectedNodeId,
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
        selected: asset.id === selectedNodeId,
      },
    })
    edges.push({
      id: `${activeProject.id}-${asset.id}`,
      source: activeProject.id,
      target: asset.id,
      type: 'intelligence',
      data: { kind: 'asset', curvature: 0.32 },
    })
    if (asset.id === selectedAssetId) serviceNodesFor(asset, position, nodes, edges, selectedNodeId, columns > 1 && column === 0 ? 500 : 214)
  })

  return { nodes, edges, activeProject, activeAssets }
}

function InspectorMetrics({ items }) {
  return <div className="inspector-metrics">{items.map((item) => <div key={item.label}><strong className={item.tone || ''}>{item.value}</strong><span>{item.label}</span></div>)}</div>
}

function AssetComposition({ assets }) {
  const items = [...ASSET_TYPES].map((type) => ({
    type,
    count: assets.filter((asset) => asset.type === type).length,
  })).filter((item) => item.count)
  return <div className="inspector-section inspector-composition"><span>资产构成</span><div>{items.length ? items.map((item) => <b key={item.type}>{TYPE_LABELS[item.type]} <em>{item.count}</em></b>) : <em>暂无资产</em>}</div></div>
}

export default function ExposureTopology({ topology }) {
  const navigate = useNavigate()
  const [expandedProjectId, setExpandedProjectId] = useState(undefined)
  const [expandedGroup, setExpandedGroup] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [projectScope, setProjectScope] = useState('all')
  const [riskFilter, setRiskFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [flow, setFlow] = useState(null)

  const allNodes = topology.nodes || []
  const organization = allNodes.find((node) => node.type === 'organization') || null
  const projects = useMemo(() => allNodes.filter((node) => node.type === 'project'), [allNodes])
  const assets = useMemo(() => allNodes.filter((node) => ASSET_TYPES.has(node.type)), [allNodes])
  const defaultProjectId = projects.find((project) => project.risk_count)?.id || projects[0]?.id || null
  const effectiveExpandedProjectId = expandedProjectId === undefined ? defaultProjectId : expandedProjectId
  const selectedNodeId = selectedNode?.id || effectiveExpandedProjectId || organization?.id || null
  const selectedAssetId = selectedNode?.kind && ASSET_TYPES.has(selectedNode.kind)
    ? selectedNode.id
    : selectedNode?.kind === 'service' ? selectedNode.assetId : null
  const graph = useMemo(() => buildGraph({
    topology,
    expandedProjectId: effectiveExpandedProjectId,
    expandedGroup,
    selectedNodeId,
    selectedAssetId,
    projectScope,
    riskFilter,
    search,
  }), [topology, effectiveExpandedProjectId, expandedGroup, selectedNodeId, selectedAssetId, projectScope, riskFilter, search])

  const inspectorKind = selectedNode?.kind || (graph.activeProject ? 'project' : 'organization')
  const selectedAsset = assets.find((asset) => asset.id === selectedAssetId) || null
  const selectedProjectId = selectedNode?.projectId || selectedAsset?.project_id || graph.activeProject?.project_id
  const selectedProject = projects.find((project) => project.project_id === selectedProjectId) || graph.activeProject || null
  const selectedService = selectedNode?.kind === 'service'
    ? selectedAsset?.services?.find((service) => service.id === selectedNode.serviceId) || null
    : null
  const groupAssets = selectedNode?.kind === 'asset_group'
    ? assets.filter((asset) => asset.project_id === selectedNode.projectId && asset.type === selectedNode.groupType)
    : []
  const inspectorAssets = inspectorKind === 'organization'
    ? assets
    : selectedAsset ? [selectedAsset]
      : inspectorKind === 'asset_group' ? groupAssets
        : assets.filter((asset) => asset.project_id === selectedProject?.project_id)
  const filterAssets = graph.activeProject
    ? assets.filter((asset) => asset.project_id === graph.activeProject.project_id)
    : assets
  const filterCounts = Object.fromEntries(RISK_FILTERS.map((filter) => [
    filter.value,
    filterAssets.filter((asset) => matchesRiskFilter(asset, filter.value)).length,
  ]))
  const assetRiskTotal = inspectorAssets.reduce((count, asset) => count + (asset.risk_count || 0), 0)
  const scopeAssetIds = new Set(inspectorAssets.map((asset) => asset.id))
  const intelligenceTotal = selectedAsset?.risk_count
    ?? (inspectorKind === 'asset_group' ? assetRiskTotal
      : inspectorKind === 'project' ? selectedProject?.asset_risk_count
        : organization?.asset_risk_count) ?? 0
  const intelligenceItems = useMemo(() => (topology.risk_intelligence || [])
    .filter((item) => scopeAssetIds.has(item.asset_id)), [topology.risk_intelligence, scopeAssetIds])

  useEffect(() => {
    if (selectedAsset && selectedAsset.project_id !== graph.activeProject?.project_id) {
      setSelectedNode(graph.activeProject ? { kind: 'project', id: graph.activeProject.id, projectId: graph.activeProject.project_id } : null)
    }
  }, [graph.activeProject, selectedAsset])

  useEffect(() => {
    if (!flow || !graph.nodes.length) return undefined
    const frame = requestAnimationFrame(() => flow.fitView({ padding: 0.26, duration: 280, maxZoom: 1.08 }))
    return () => cancelAnimationFrame(frame)
  }, [flow, graph.nodes.length, effectiveExpandedProjectId, expandedGroup, riskFilter])

  const selectProjectOverview = (project = selectedProject || graph.activeProject) => {
    if (!project) return
    setExpandedProjectId(project.id)
    setExpandedGroup(null)
    setSelectedNode({ kind: 'project', id: project.id, projectId: project.project_id })
  }

  const showOverview = () => {
    setProjectScope('all')
    setExpandedProjectId(null)
    setExpandedGroup(null)
    setSelectedNode(organization ? { kind: 'organization', id: organization.id } : null)
  }

  const focusAsset = (asset) => {
    const projectAssets = assets.filter((item) => item.project_id === asset.project_id)
    setProjectScope('all')
    setSearch('')
    setRiskFilter('all')
    setExpandedProjectId(`project-${asset.project_id}`)
    setExpandedGroup(projectAssets.length > 24 ? { projectId: asset.project_id, type: asset.type } : null)
    setSelectedNode({ kind: asset.type, id: asset.id, projectId: asset.project_id })
  }

  const handleNodeClick = (_, node) => {
    const { nodeKind, projectId, groupType, assetId, id: serviceId } = node.data
    if (nodeKind === 'organization') return showOverview()
    if (nodeKind === 'project') {
      setExpandedProjectId(node.id)
      setExpandedGroup(null)
      setSelectedNode({ kind: 'project', id: node.id, projectId: node.data.project_id })
      return
    }
    if (nodeKind === 'asset_group') {
      setSelectedNode({ kind: 'asset_group', id: node.id, projectId, groupType })
      return
    }
    if (nodeKind === 'service') {
      setSelectedNode({ kind: 'service', id: node.id, projectId, assetId, serviceId })
      return
    }
    if (ASSET_TYPES.has(nodeKind)) setSelectedNode({ kind: nodeKind, id: node.id, projectId: node.data.project_id })
  }

  const changeProjectScope = (value) => {
    setProjectScope(value)
    setExpandedGroup(null)
    if (value === 'all') return showOverview()
    const project = projects.find((item) => item.id === value)
    if (project) selectProjectOverview(project)
  }

  const changeRiskFilter = (value) => {
    setRiskFilter(value)
    setExpandedGroup(null)
    if (graph.activeProject) selectProjectOverview(graph.activeProject)
    else showOverview()
  }

  const selectedRiskLabel = selectedAsset?.status ? RISK_LABELS[selectedAsset.status] || '待复核' : ''
  const selectedAssetProject = projects.find((project) => project.project_id === selectedAsset?.project_id) || selectedProject

  return (
    <div className="exposure-topology">
      <div className="exposure-toolbar">
        <div className="exposure-heading">
          <span><ClusterOutlined /></span>
          <div><strong>资产暴露面拓扑</strong><em>{graph.activeProject ? `当前展开 ${filterAssets.length} / 全部 ${assets.length} 个资产` : `${assets.length} 个受管资产`}</em></div>
        </div>
        <select className="exposure-project-select" aria-label="项目范围" value={projectScope} onChange={(event) => changeProjectScope(event.target.value)}>
          <option value="all">全部项目</option>
          {projects.map((project) => <option key={project.id} value={project.id}>{project.label}</option>)}
        </select>
        <label className="exposure-search">
          <SearchOutlined />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索资产、域名、IP 或项目" />
        </label>
        <div className="exposure-risk-filter" role="group" aria-label="资产风险筛选">
          {RISK_FILTERS.map((filter) => <button key={filter.value} type="button" className={`risk-filter-${filter.value} ${riskFilter === filter.value ? 'is-active' : ''}`} title={filter.title} aria-pressed={riskFilter === filter.value} onClick={() => changeRiskFilter(filter.value)}><i /><span>{filter.label}</span><b>{filterCounts[filter.value] || 0}</b></button>)}
        </div>
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
        <TopologyMiniMap nodes={graph.nodes} edges={graph.edges} selectedNodeId={selectedNodeId} />
        {!graph.nodes.length ? <div className="exposure-empty">暂无资产拓扑。添加资产并执行检测后会自动生成真实关系。</div> : null}
      </div>

      <div className="exposure-footer">
        <div className="exposure-path">
          <button type="button" onClick={showOverview}>全部项目</button>
          {graph.activeProject ? <><span>/</span><button type="button" onClick={() => selectProjectOverview(graph.activeProject)}>{graph.activeProject.label}</button></> : null}
          {expandedGroup ? <><span>/</span><button type="button" onClick={() => setExpandedGroup(null)}>{TYPE_LABELS[expandedGroup.type]}</button></> : null}
        </div>
        <div className="exposure-legend"><span className="legend-project" />项目 <span className="legend-asset" />资产 <span className="legend-service" />已验证服务 <span className="legend-risk" />待处理风险</div>
      </div>

      <aside className="exposure-inspector">
        {inspectorKind === 'organization' && organization ? <>
          <div className="inspector-title"><span>组织资产概览</span><strong>{organization.label}</strong></div>
          <InspectorMetrics items={[
            { label: '项目', value: organization.project_count || projects.length },
            { label: '纳管资产', value: organization.asset_count || assets.length },
            { label: '全部待处理', value: organization.risk_count || 0, tone: organization.risk_count ? 'risk-text-warning' : '' },
            { label: '资产归属风险', value: organization.asset_risk_count || 0 },
            { label: '未归属资产', value: organization.unassigned_risk_count || 0 },
            { label: '已验证服务', value: organization.observed_service_count || 0 },
          ]} />
          <AssetComposition assets={assets} />
        </> : null}

        {inspectorKind === 'project' && selectedProject ? <>
          <div className="inspector-title"><span>项目节点</span><strong>{selectedProject.label}</strong></div>
          <dl>
            <div><dt>当前阶段</dt><dd>{selectedProject.stage || '差距分析'}</dd></div>
            <div><dt>测评进度</dt><dd>{selectedProject.progress || 0}%</dd></div>
            <div><dt>风险口径</dt><dd>全部待处理包含文档与技术问题；资产归属风险仅统计可追溯到具体资产的问题</dd></div>
          </dl>
          <InspectorMetrics items={[
            { label: '全部待处理', value: selectedProject.risk_count || 0, tone: selectedProject.risk_count ? 'risk-text-warning' : '' },
            { label: '资产归属风险', value: selectedProject.asset_risk_count || 0 },
            { label: '未归属资产', value: selectedProject.unassigned_risk_count || 0 },
            { label: '已验证资产', value: selectedProject.verified_asset_count || 0 },
          ]} />
          <AssetComposition assets={inspectorAssets} />
          <div className="inspector-actions"><button type="button" onClick={() => navigate(`/projects/${selectedProject.project_id}`)}>进入项目工作台</button></div>
        </> : null}

        {inspectorKind === 'asset_group' && selectedNode ? <>
          <div className="inspector-title"><span>资产组 · {selectedNode.projectName || selectedProject?.label}</span><strong>{TYPE_LABELS[selectedNode.groupType]}</strong></div>
          <InspectorMetrics items={[
            { label: '资产', value: groupAssets.length },
            { label: '资产归属风险', value: assetRiskTotal, tone: assetRiskTotal ? 'risk-text-warning' : '' },
            { label: '严重/高风险资产', value: groupAssets.filter((asset) => ['critical', 'high'].includes(asset.status)).length },
            { label: '未验证资产', value: groupAssets.filter((asset) => asset.status === 'unverified').length },
          ]} />
          <div className="inspector-actions">
            <button type="button" onClick={() => setExpandedGroup({ projectId: selectedNode.projectId, type: selectedNode.groupType })}>展开资产组</button>
            <button type="button" onClick={() => selectProjectOverview(selectedProject)}>查看项目汇总</button>
          </div>
        </> : null}

        {selectedAsset && inspectorKind !== 'service' ? <>
          <div className="inspector-title">
            <span>资产节点 · {TYPE_LABELS[selectedAsset.type]}</span>
            <strong>{selectedAsset.asset_name || selectedAsset.label}</strong>
            {selectedAsset.asset_name ? <em>{selectedAsset.value || selectedAsset.label}</em> : null}
          </div>
          <dl>
            <div><dt>所属项目</dt><dd>{selectedAsset.project_name || selectedProject?.label || '未关联'}</dd></div>
            <div><dt>资产地址</dt><dd>{selectedAsset.value || selectedAsset.label}</dd></div>
            <div><dt>纳管状态</dt><dd>{selectedAsset.is_active === false ? '已停用' : '正常纳管'}</dd></div>
            <div><dt>权属验证</dt><dd>{selectedAsset.verification === 'verified' ? `已验证${selectedAsset.verified_at ? ` · ${fullTime(selectedAsset.verified_at)}` : ''}` : selectedAsset.verification === 'failed' ? '验证失败' : '待验证'}</dd></div>
            <div><dt>风险结论</dt><dd className={['critical', 'high'].includes(selectedAsset.status) ? 'risk-text-high' : selectedAsset.status === 'warning' ? 'risk-text-warning' : ''}>{selectedRiskLabel}</dd></div>
            <div><dt>最近检测</dt><dd>{selectedAsset.last_scan ? `${fullTime(selectedAsset.last_scan.observed_at)} · ${selectedAsset.last_scan.status || '状态未知'}` : '尚无有效检测记录'}</dd></div>
          </dl>
          <InspectorMetrics items={[
            { label: '待处理风险', value: selectedAsset.risk_count || 0, tone: selectedAsset.risk_count ? 'risk-text-warning' : '' },
            { label: '严重/高风险', value: (selectedAsset.critical_count || 0) + (selectedAsset.high_count || 0) },
            { label: '中风险', value: selectedAsset.medium_count || 0 },
            { label: '已验证服务', value: selectedAsset.services?.length || 0 },
          ]} />
          <div className="inspector-section"><span>最近观测到的开放服务</span>{selectedAsset.services?.length ? selectedAsset.services.map((service) => <button className="inspector-service" type="button" key={service.id || service.label} onClick={() => setSelectedNode({ kind: 'service', id: `service-${selectedAsset.id}-${service.id}`, projectId: selectedAsset.project_id, assetId: selectedAsset.id, serviceId: service.id })}>{service.label}{service.service ? ` · ${service.service}` : ' · 服务类型未知'}</button>) : <em>尚无明确开放端口证据，不等于端口全部关闭</em>}</div>
          <div className="inspector-actions">
            <button type="button" onClick={() => navigate(`/projects/${selectedAsset.project_id}`)}>进入所属项目</button>
            <button type="button" onClick={() => selectProjectOverview(selectedAssetProject)}>查看项目汇总</button>
          </div>
        </> : null}

        {inspectorKind === 'service' && selectedAsset ? <>
          <div className="inspector-title"><span>已验证服务节点</span><strong>{selectedService?.service || selectedService?.label || selectedNode?.serviceId}</strong><em>{selectedService?.label || selectedNode?.serviceId}</em></div>
          <dl>
            <div><dt>来源资产</dt><dd>{selectedAsset.asset_name || selectedAsset.value || selectedAsset.label}</dd></div>
            <div><dt>所属项目</dt><dd>{selectedAsset.project_name || selectedProject?.label}</dd></div>
            <div><dt>端口</dt><dd>{selectedService?.port ?? selectedService?.label ?? '未知'}</dd></div>
            <div><dt>协议</dt><dd>{selectedService?.protocol || 'tcp'}</dd></div>
            <div><dt>最近观测</dt><dd>{fullTime(selectedService?.observed_at || selectedAsset.last_scan?.observed_at)}</dd></div>
          </dl>
          <div className="inspector-actions">
            <button type="button" onClick={() => focusAsset(selectedAsset)}>返回资产详情</button>
            <button type="button" onClick={() => selectProjectOverview(selectedAssetProject)}>查看项目汇总</button>
          </div>
        </> : null}

        <div className="inspector-section intelligence-stream">
          <div className="intelligence-head"><span>可归属资产风险</span><em>共 {intelligenceTotal} 项</em></div>
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
            </button>) : <em>当前范围暂无可归属到具体资产的待处理风险</em>}
          </div>
        </div>
      </aside>
    </div>
  )
}
