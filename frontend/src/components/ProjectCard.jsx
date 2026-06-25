import {
  ArrowRightOutlined,
  SafetyCertificateOutlined,
  LockOutlined,
  DatabaseOutlined,
  CloudServerOutlined,
} from '@ant-design/icons'
import './ProjectCard.css'

const TYPE_COLORS = {
  dengbao: '#00ff88',
  miping: '#a855f7',
  guanji: '#ff6b35',
  data_security: '#00b4d8',
}

const TYPE_ICONS = {
  dengbao: SafetyCertificateOutlined,
  miping: LockOutlined,
  guanji: CloudServerOutlined,
  data_security: DatabaseOutlined,
}

const STATUS_LABELS = {
  not_started: 'NOT STARTED',
  in_progress: 'IN PROGRESS',
  completed: 'COMPLETED',
}

const STATUS_COLORS = {
  not_started: '#666',
  in_progress: '#00ff88',
  completed: '#d4af37',
}

function StatusIndicator({ status }) {
  const color = STATUS_COLORS[status] || '#666'
  return (
    <div className="dash-card-status">
      <span
        className="dash-card-dot"
        style={{
          background: color,
          boxShadow: `0 0 8px ${color}`,
        }}
      />
      <span className="dash-card-status-label" style={{ color }}>
        {STATUS_LABELS[status]}
      </span>
    </div>
  )
}

function AssessmentTag({ assessment }) {
  const IconComp = TYPE_ICONS[assessment.code] || SafetyCertificateOutlined
  const color = TYPE_COLORS[assessment.code] || '#1890ff'
  return (
    <div
      className="dash-card-assess-tag"
      style={{
        borderColor: color + '60',
        color: color,
      }}
    >
      <IconComp style={{ fontSize: 12 }} />
      <span>{assessment.name}</span>
      {assessment.level && <span className="dash-card-level">{assessment.level}</span>}
    </div>
  )
}

export default function ProjectCard({ project, onClick }) {
  const score = project.overall_score
  const status = project.overall_status || 'not_started'

  return (
    <div className="dash-card" onClick={onClick}>
      <div className="dash-card-corners">
        <div className="dash-card-corner-tl" />
        <div className="dash-card-corner-tr" />
        <div className="dash-card-corner-bl" />
        <div className="dash-card-corner-br" />
      </div>
      <div className="dash-card-scanline" />

      <div className="dash-card-header">
        <div className="dash-card-header-left">
          <StatusIndicator status={status} />
          <span className="dash-card-id">DOSSIER #{project.id.toString().padStart(3, '0')}</span>
        </div>
        <ArrowRightOutlined className="dash-card-arrow" />
      </div>

      <div className="dash-card-body">
        <div className="dash-card-name">{project.name}</div>
        {project.system_name && (
          <div className="dash-card-system">SYSTEM: {project.system_name}</div>
        )}
        {project.description && (
          <div className="dash-card-desc">{project.description}</div>
        )}

        {project.assessment_types?.length > 0 && (
          <div className="dash-card-assess-list">
            {project.assessment_types.map((at, idx) => (
              <AssessmentTag key={idx} assessment={at} />
            ))}
          </div>
        )}

        <div className="dash-card-divider" />

        <div className="dash-card-stats">
          <div className="dash-card-stat">
            <span className="dash-card-stat-label">ASSETS</span>
            <span className="dash-card-stat-value">{project.asset_count}</span>
          </div>
          <div className="dash-card-stat">
            <span className="dash-card-stat-label">SCORE</span>
            <span className="dash-card-stat-value">
              {score !== null && score !== undefined ? score.toFixed(0) : '-'}
            </span>
          </div>
        </div>

        <div className="dash-card-progress-bar">
          <div
            className="dash-card-progress-fill"
            style={{
              width: `${score !== null && score !== undefined ? score : 0}%`,
              background: `linear-gradient(90deg, ${STATUS_COLORS[status]}, ${STATUS_COLORS[status]}aa)`,
            }}
          />
        </div>

        <div className="dash-card-footer">
          <span className="dash-card-footer-label">UPDATED</span>
          <span className="dash-card-footer-value">
            {new Date(project.updated_at).toLocaleDateString('zh-CN')}
          </span>
        </div>
      </div>
    </div>
  )
}