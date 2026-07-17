import { Card, Tag, Progress, Button, Space, Typography, Divider, List, Badge, Tooltip } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  WarningOutlined,
  SafetyCertificateOutlined,
  CloudServerOutlined,
  FileTextOutlined,
  RadarChartOutlined,
  ProjectOutlined,
  DownloadOutlined,
  EyeOutlined,
  EditOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import './ToolCard.css'

const { Text, Title } = Typography

// Color mappings
const SEVERITY_COLORS = {
  critical: '#dc2626',
  high: '#ef4444',
  medium: '#f59e0b',
  low: '#3b82f6',
  info: '#64748b',
}

const SEVERITY_LABELS = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '信息',
}

const STATUS_ICONS = {
  pending: <LoadingOutlined style={{ color: '#f59e0b' }} />,
  running: <LoadingOutlined style={{ color: '#6366f1' }} spin />,
  completed: <CheckCircleOutlined style={{ color: '#10b981' }} />,
  failed: <CloseCircleOutlined style={{ color: '#ef4444' }} />,
}

// --- Card Renderers ---

function ProjectListCard({ data }) {
  const projects = data?.projects || []
  return (
    <div className="tool-card-content">
      <List
        size="small"
        dataSource={projects}
        renderItem={(p) => (
          <List.Item className="project-list-item">
            <div className="project-list-info">
              <div className="project-list-name">
                <ProjectOutlined style={{ marginRight: 8, color: '#6366f1' }} />
                {p.name}
              </div>
              <div className="project-list-meta">
                <Tag color={p.compliance_level === '三级' ? 'red' : 'blue'} style={{ borderRadius: 4 }}>
                  {p.compliance_level}
                </Tag>
                {p.compliance_score !== null && p.compliance_score !== undefined ? (
                  <span style={{ color: getScoreColor(p.compliance_score), fontWeight: 600 }}>
                    {p.compliance_score} 分
                  </span>
                ) : (
                  <span style={{ color: 'rgba(255,255,255,0.4)' }}>未检测</span>
                )}
              </div>
            </div>
          </List.Item>
        )}
      />
    </div>
  )
}

function ProjectCreatedCard({ data }) {
  return (
    <div className="tool-card-content">
      <div className="result-row">
        <span className="result-label">项目名称</span>
        <span className="result-value">{data?.project_name}</span>
      </div>
      <div className="result-row">
        <span className="result-label">等保等级</span>
        <span className="result-value">
          <Tag color={data?.compliance_level === '三级' ? 'red' : 'blue'}>
            {data?.compliance_level}
          </Tag>
        </span>
      </div>
      <div className="result-row">
        <span className="result-label">项目 ID</span>
        <span className="result-value" style={{ color: 'rgba(255,255,255,0.4)' }}>#{data?.project_id}</span>
      </div>
    </div>
  )
}

function AssetAddedCard({ data }) {
  const assets = data?.assets || []
  return (
    <div className="tool-card-content">
      <List
        size="small"
        dataSource={assets}
        renderItem={(a) => (
          <List.Item className="asset-list-item">
            <CloudServerOutlined style={{ color: '#10b981', marginRight: 8 }} />
            <span>{a.value}</span>
            <Tag style={{ marginLeft: 'auto', borderRadius: 4 }}>{a.type}</Tag>
          </List.Item>
        )}
      />
      {data?.project_name && (
        <div className="card-footer-text">
          项目：{data.project_name}
        </div>
      )}
    </div>
  )
}

function ScanProgressCard({ data }) {
  const steps = data?.steps || []
  const completedSteps = steps.filter(s => s.status === 'completed').length
  const progress = steps.length > 0 ? Math.round((completedSteps / steps.length) * 100) : 0
  
  return (
    <div className="tool-card-content">
      <div className="scan-target">
        <RadarChartOutlined style={{ marginRight: 8 }} />
        目标：{data?.target}
        <Tag style={{ marginLeft: 8, borderRadius: 4 }}>{data?.scanner}</Tag>
      </div>
      <div className="scan-steps">
        {steps.map((step, i) => (
          <div key={i} className={`scan-step ${step.status}`}>
            <div className="scan-step-icon">
              {step.status === 'completed' && <CheckCircleOutlined style={{ color: '#10b981' }} />}
              {step.status === 'running' && <LoadingOutlined style={{ color: '#6366f1' }} spin />}
              {step.status === 'pending' && <div className="step-dot pending" />}
              {step.status === 'failed' && <CloseCircleOutlined style={{ color: '#ef4444' }} />}
            </div>
            <span className="scan-step-name">{step.name}</span>
            {step.status === 'completed' && <Tag color="success" style={{ marginLeft: 'auto', borderRadius: 4 }}>完成</Tag>}
            {step.status === 'running' && <Tag color="processing" style={{ marginLeft: 'auto', borderRadius: 4 }}>进行中</Tag>}
          </div>
        ))}
      </div>
      <Progress percent={progress} showInfo={false} strokeColor="#6366f1" trailColor="rgba(255,255,255,0.08)" />
    </div>
  )
}

function ScanResultCard({ data, onAction }) {
  const summary = data?.summary || {}
  const score = data?.compliance_score
  
  return (
    <div className="tool-card-content">
      <div className="scan-result-grid">
        <div className="scan-result-score">
          <div className="score-circle" style={{ borderColor: getScoreColor(score) }}>
            <span className="score-number" style={{ color: getScoreColor(score) }}>{score}</span>
            <span className="score-label">合规分数</span>
          </div>
        </div>
        <div className="scan-result-stats">
          <div className="stat-row">
            <span className="stat-label">扫描目标</span>
            <span className="stat-value">{data?.target}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">开放端口</span>
            <span className="stat-value">{data?.open_ports || 0}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">发现问题</span>
            <span className="stat-value">{data?.findings_count || 0}</span>
          </div>
        </div>
      </div>
      
      <Divider style={{ margin: '12px 0', borderColor: 'rgba(255,255,255,0.08)' }} />
      
      <div className="severity-bar">
        {summary.critical > 0 && (
          <div className="severity-item">
            <Badge count={summary.critical} style={{ backgroundColor: SEVERITY_COLORS.critical }} />
            <span>严重</span>
          </div>
        )}
        {summary.high > 0 && (
          <div className="severity-item">
            <Badge count={summary.high} style={{ backgroundColor: SEVERITY_COLORS.high }} />
            <span>高危</span>
          </div>
        )}
        {summary.medium > 0 && (
          <div className="severity-item">
            <Badge count={summary.medium} style={{ backgroundColor: SEVERITY_COLORS.medium }} />
            <span>中危</span>
          </div>
        )}
        {summary.low > 0 && (
          <div className="severity-item">
            <Badge count={summary.low} style={{ backgroundColor: SEVERITY_COLORS.low }} />
            <span>低危</span>
          </div>
        )}
        {summary.critical === 0 && summary.high === 0 && summary.medium === 0 && summary.low === 0 && (
          <div className="severity-item">
            <CheckCircleOutlined style={{ color: '#10b981' }} />
            <span style={{ color: '#10b981' }}>无重大问题</span>
          </div>
        )}
      </div>
      
      {data?.actions && data.actions.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0', borderColor: 'rgba(255,255,255,0.08)' }} />
          <Space className="card-actions">
            {data.actions.includes('view_findings') && (
              <Button size="small" icon={<EyeOutlined />} onClick={() => onAction?.('view_findings')}>
                查看问题
              </Button>
            )}
            {data.actions.includes('download_report') && (
              <Button size="small" icon={<DownloadOutlined />} onClick={() => onAction?.('download_report')}>
                下载报告
              </Button>
            )}
          </Space>
        </>
      )}
    </div>
  )
}

function FindingsListCard({ data }) {
  const findings = data?.findings || []
  const bySeverity = data?.by_severity || {}
  
  return (
    <div className="tool-card-content">
      <div className="findings-summary">
        共 {data?.total || 0} 个问题
        {Object.entries(bySeverity).map(([sev, count]) => (
          <Tag key={sev} color={SEVERITY_COLORS[sev]} style={{ borderRadius: 4, marginLeft: 4 }}>
            {SEVERITY_LABELS[sev] || sev}: {count}
          </Tag>
        ))}
      </div>
      <List
        size="small"
        dataSource={findings}
        renderItem={(f) => (
          <List.Item className="finding-list-item">
            <div className="finding-list-info">
              <Tag color={SEVERITY_COLORS[f.severity]} style={{ borderRadius: 4, fontSize: '0.7rem' }}>
                {SEVERITY_LABELS[f.severity] || f.severity}
              </Tag>
              <span className="finding-clause">{f.clause_id}</span>
              <span className="finding-name">{f.clause_name}</span>
            </div>
            <Tag style={{ borderRadius: 4 }}>
              {f.judgment === 'pass' ? '✅ 符合' : f.judgment === 'fail' ? '❌ 不符合' : '⚠️ 部分符合'}
            </Tag>
          </List.Item>
        )}
      />
    </div>
  )
}

function ScoreCard({ data }) {
  const score = data?.score || 0
  return (
    <div className="tool-card-content">
      <div className="score-display">
        <div className="score-big" style={{ color: getScoreColor(score) }}>
          {score}
          <span className="score-unit">分</span>
        </div>
        <div className="score-status-text">{data?.status}</div>
      </div>
      <Divider style={{ margin: '12px 0', borderColor: 'rgba(255,255,255,0.08)' }} />
      <div className="score-stats">
        <div className="score-stat">
          <span className="score-stat-label">总计</span>
          <span className="score-stat-value">{data?.total_findings}</span>
        </div>
        <div className="score-stat">
          <span className="score-stat-label">符合</span>
          <span className="score-stat-value" style={{ color: '#10b981' }}>{data?.pass_count}</span>
        </div>
        <div className="score-stat">
          <span className="score-stat-label">部分符合</span>
          <span className="score-stat-value" style={{ color: '#f59e0b' }}>{data?.partial_count}</span>
        </div>
        <div className="score-stat">
          <span className="score-stat-label">不符合</span>
          <span className="score-stat-value" style={{ color: '#ef4444' }}>{data?.fail_count}</span>
        </div>
      </div>
    </div>
  )
}

function ReportCard({ data }) {
  return (
    <div className="tool-card-content">
      <div className="report-info">
        <div className="result-row">
          <span className="result-label">项目</span>
          <span className="result-value">{data?.project_name}</span>
        </div>
        <div className="result-row">
          <span className="result-label">合规分数</span>
          <span className="result-value" style={{ color: getScoreColor(data?.compliance_score), fontWeight: 700 }}>
            {data?.compliance_score} 分
          </span>
        </div>
      </div>
      <Button
        type="primary"
        icon={<DownloadOutlined />}
        block
        style={{
          marginTop: 12,
          borderRadius: 8,
          background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
          border: 'none',
        }}
        onClick={() => {
          if (data?.download_url) {
            window.open(data.download_url, '_blank')
          }
        }}
      >
        下载 HTML 报告
      </Button>
    </div>
  )
}

function HelpCard({ data }) {
  const commands = data?.commands || []
  return (
    <div className="tool-card-content">
      <List
        size="small"
        dataSource={commands}
        renderItem={(c) => (
          <List.Item className="help-list-item">
            <code className="help-command">{c.command}</code>
            <span className="help-desc">{c.description}</span>
          </List.Item>
        )}
      />
    </div>
  )
}

// --- Main ToolCard Component ---

const CARD_CONFIG = {
  project_list: { icon: <ProjectOutlined />, label: '项目列表', color: '#6366f1', renderer: ProjectListCard },
  project_created: { icon: <RocketOutlined />, label: '项目已创建', color: '#10b981', renderer: ProjectCreatedCard },
  asset_added: { icon: <CloudServerOutlined />, label: '资产已添加', color: '#10b981', renderer: AssetAddedCard },
  scan_progress: { icon: <RadarChartOutlined />, label: '扫描中', color: '#6366f1', renderer: ScanProgressCard },
  scan_result: { icon: <SafetyCertificateOutlined />, label: '扫描结果', color: '#6366f1', renderer: ScanResultCard },
  findings_list: { icon: <WarningOutlined />, label: '问题清单', color: '#ef4444', renderer: FindingsListCard },
  score_card: { icon: <SafetyCertificateOutlined />, label: '合规评分', color: '#6366f1', renderer: ScoreCard },
  report: { icon: <FileTextOutlined />, label: '合规报告', color: '#6366f1', renderer: ReportCard },
  help: { icon: <FileTextOutlined />, label: '功能帮助', color: '#64748b', renderer: HelpCard },
}

function ToolCardComponent({ card, onAction }) {
  const config = CARD_CONFIG[card.type]
  if (!config) return null
  
  const Renderer = config.renderer
  
  return (
    <div className="tool-card-wrapper">
      <div className="tool-card-header">
        <div className="tool-card-header-left">
          <div className="tool-card-icon" style={{ color: config.color }}>
            {STATUS_ICONS[card.status] || config.icon}
          </div>
          <span className="tool-card-label">{card.title}</span>
        </div>
        <Tag
          color={card.status === 'completed' ? 'success' : card.status === 'running' ? 'processing' : card.status === 'failed' ? 'error' : 'default'}
          style={{ borderRadius: 4 }}
        >
          {card.status === 'completed' ? '完成' : card.status === 'running' ? '进行中' : card.status === 'failed' ? '失败' : '等待'}
        </Tag>
      </div>
      {card.data && <Renderer data={card.data} onAction={onAction} />}
    </div>
  )
}

// Helper function
function getScoreColor(score) {
  if (score >= 90) return '#10b981'
  if (score >= 75) return '#6366f1'
  if (score >= 60) return '#f59e0b'
  return '#ef4444'
}

export default ToolCardComponent
