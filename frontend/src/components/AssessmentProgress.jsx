import { useState, useEffect } from 'react'
import { Progress, Tag, Tooltip, Drawer, Button, Steps, Empty, Spin } from 'antd'
import {
  CheckCircleFilled,
  ClockCircleFilled,
  CloseCircleFilled,
  MinusCircleFilled,
  PlayCircleFilled,
  RocketOutlined,
  SafetyCertificateOutlined,
  FileProtectOutlined,
  BugOutlined,
  TeamOutlined,
  FileTextOutlined,
  RadarChartOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import './AssessmentProgress.css'

const { Step } = Steps

// 任务类型图标映射
const TASK_TYPE_ICONS = {
  asset_discovery: <RadarChartOutlined />,
  config_check: <SettingOutlined />,
  vuln_scan: <BugOutlined />,
  pentest: <ThunderboltOutlined />,
  doc_review: <FileTextOutlined />,
  interview: <TeamOutlined />,
}

// 阶段图标映射
const PHASE_ICONS = {
  1: <SafetyCertificateOutlined />,
  2: <FileProtectOutlined />,
  3: <RadarChartOutlined />,
  4: <BugOutlined />,
  5: <SettingOutlined />,
  6: <CheckCircleFilled />,
  7: <FileTextOutlined />,
}

// 状态配置
const STATUS_CONFIG = {
  not_started: { color: '#64748b', text: '未开始', icon: <ClockCircleFilled /> },
  in_progress: { color: '#6366f1', text: '进行中', icon: <PlayCircleFilled /> },
  paused: { color: '#f59e0b', text: '已暂停', icon: <ClockCircleFilled /> },
  completed: { color: '#10b981', text: '已完成', icon: <CheckCircleFilled /> },
  failed: { color: '#ef4444', text: '失败', icon: <CloseCircleFilled /> },
}

const PHASE_STATUS_CONFIG = {
  pending: { color: '#64748b', text: '待开始', className: 'pending' },
  active: { color: '#6366f1', text: '进行中', className: 'active' },
  completed: { color: '#10b981', text: '已完成', className: 'completed' },
  skipped: { color: '#94a3b8', text: '已跳过', className: 'skipped' },
  failed: { color: '#ef4444', text: '失败', className: 'failed' },
}

const TASK_STATUS_CONFIG = {
  todo: { color: '#64748b', text: '待办', className: 'todo' },
  in_progress: { color: '#6366f1', text: '进行中', className: 'in-progress' },
  completed: { color: '#10b981', text: '已完成', className: 'completed' },
  failed: { color: '#ef4444', text: '失败', className: 'failed' },
  cancelled: { color: '#94a3b8', text: '已取消', className: 'cancelled' },
}

function AssessmentProgress({ projectId, projectName }) {
  const [assessment, setAssessment] = useState(null)
  const [phases, setPhases] = useState([])
  const [loading, setLoading] = useState(false)
  const [drawerVisible, setDrawerVisible] = useState(false)
  const [selectedPhase, setSelectedPhase] = useState(null)
  const [tasks, setTasks] = useState([])
  const [tasksLoading, setTasksLoading] = useState(false)

  useEffect(() => {
    if (projectId) {
      fetchAssessment()
    }
  }, [projectId])

  const fetchAssessment = async () => {
    setLoading(true)
    try {
      // 获取项目的测评列表
      const response = await api.get(`/assessments/projects/${projectId}`)
      if (response.data && response.data.length > 0) {
        // 获取最新的测评
        const latestAssessment = response.data[0]
        setAssessment(latestAssessment)
        
        // 获取阶段列表
        const phasesResponse = await api.get(`/assessments/${latestAssessment.id}/phases`)
        setPhases(phasesResponse.data)
      } else {
        setAssessment(null)
        setPhases([])
      }
    } catch (error) {
      console.error('Failed to fetch assessment:', error)
      setAssessment(null)
      setPhases([])
    } finally {
      setLoading(false)
    }
  }

  const handlePhaseClick = async (phase) => {
    setSelectedPhase(phase)
    setDrawerVisible(true)
    setTasksLoading(true)
    
    try {
      const response = await api.get(`/assessments/phases/${phase.id}/tasks`)
      setTasks(response.data)
    } catch (error) {
      console.error('Failed to fetch tasks:', error)
      setTasks([])
    } finally {
      setTasksLoading(false)
    }
  }

  const handleStartAssessment = async () => {
    if (!assessment) return
    
    try {
      await api.post(`/assessments/${assessment.id}/start`)
      fetchAssessment()
    } catch (error) {
      console.error('Failed to start assessment:', error)
    }
  }

  const handleCompletePhase = async (phaseId) => {
    try {
      await api.post(`/assessments/phases/${phaseId}/complete`, {})
      fetchAssessment()
      if (selectedPhase && selectedPhase.id === phaseId) {
        const response = await api.get(`/assessments/phases/${phaseId}`)
        setSelectedPhase(response.data)
      }
    } catch (error) {
      console.error('Failed to complete phase:', error)
    }
  }

  const handleStartTask = async (taskId) => {
    try {
      await api.post(`/assessments/tasks/${taskId}/start`)
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
    } catch (error) {
      console.error('Failed to start task:', error)
    }
  }

  const handleCompleteTask = async (taskId) => {
    try {
      await api.post(`/assessments/tasks/${taskId}/complete`, { result: {} })
      const response = await api.get(`/assessments/phases/${selectedPhase.id}/tasks`)
      setTasks(response.data)
      fetchAssessment()
    } catch (error) {
      console.error('Failed to complete task:', error)
    }
  }

  if (loading) {
    return (
      <div className="assessment-progress-container loading">
        <Spin size="small" />
      </div>
    )
  }

  if (!assessment) {
    return null
  }

  const statusConfig = STATUS_CONFIG[assessment.status] || STATUS_CONFIG.not_started

  return (
    <>
      <div className="assessment-progress-container">
        {/* Header */}
        <div className="assessment-header">
          <div className="assessment-title">
            <RocketOutlined className="assessment-icon" />
            <span>测评进度</span>
          </div>
          <Tag 
            color={statusConfig.color} 
            icon={statusConfig.icon}
            className="assessment-status-tag"
          >
            {statusConfig.text}
          </Tag>
        </div>

        {/* Progress Ring */}
        <div className="assessment-progress-ring">
          <Progress
            type="circle"
            percent={Math.round(assessment.progress)}
            size={80}
            strokeColor={{
              '0%': '#6366f1',
              '100%': '#8b5cf6',
            }}
            format={(percent) => (
              <div className="progress-content">
                <span className="progress-percent">{percent}%</span>
              </div>
            )}
          />
          <div className="progress-stats">
            <div className="stat-item">
              <span className="stat-value">{assessment.completed_phases}</span>
              <span className="stat-label">/ {assessment.total_phases} 阶段</span>
            </div>
          </div>
        </div>

        {/* Phase List */}
        <div className="assessment-phases">
          {phases.map((phase, index) => {
            const phaseStatus = PHASE_STATUS_CONFIG[phase.status] || PHASE_STATUS_CONFIG.pending
            const isActive = phase.status === 'active'
            const isCompleted = phase.status === 'completed'
            const isPending = phase.status === 'pending'
            
            return (
              <div
                key={phase.id}
                className={`phase-item ${phaseStatus.className} ${isActive ? 'active' : ''}`}
                onClick={() => handlePhaseClick(phase)}
              >
                <div className="phase-connector">
                  {index > 0 && <div className="connector-line" />}
                  <div className={`phase-dot ${phaseStatus.className}`}>
                    {isCompleted ? (
                      <CheckCircleFilled />
                    ) : isActive ? (
                      <div className="pulse-dot" />
                    ) : (
                      <div className="empty-dot" />
                    )}
                  </div>
                </div>
                <div className="phase-content">
                  <div className="phase-header">
                    <span className="phase-name">{phase.name}</span>
                    {isActive && (
                      <Tag color="#6366f1" className="phase-progress-tag">
                        {Math.round(phase.progress)}%
                      </Tag>
                    )}
                    {isCompleted && (
                      <Tag color="#10b981" icon={<CheckCircleFilled />} className="phase-done-tag">
                        完成
                      </Tag>
                    )}
                  </div>
                  {isActive && (
                    <div className="phase-progress-bar">
                      <Progress
                        percent={Math.round(phase.progress)}
                        showInfo={false}
                        strokeColor="#6366f1"
                        size="small"
                      />
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* Start Button */}
        {assessment.status === 'not_started' && (
          <Button
            type="primary"
            block
            icon={<PlayCircleFilled />}
            onClick={handleStartAssessment}
            className="start-assessment-btn"
          >
            开始测评
          </Button>
        )}
      </div>

      {/* Phase Detail Drawer */}
      <Drawer
        title={
          <div className="drawer-title">
            <span>{selectedPhase?.name}</span>
            <Tag color={PHASE_STATUS_CONFIG[selectedPhase?.status]?.color}>
              {PHASE_STATUS_CONFIG[selectedPhase?.status]?.text}
            </Tag>
          </div>
        }
        placement="right"
        width={400}
        onClose={() => setDrawerVisible(false)}
        open={drawerVisible}
        className="phase-detail-drawer"
      >
        {selectedPhase && (
          <div className="phase-detail-content">
            {/* Phase Info */}
            <div className="phase-info-card">
              <div className="info-row">
                <span className="info-label">阶段描述</span>
                <span className="info-value">{selectedPhase.description || '-'}</span>
              </div>
              <div className="info-row">
                <span className="info-label">任务进度</span>
                <span className="info-value">
                  {selectedPhase.completed_tasks} / {selectedPhase.total_tasks}
                </span>
              </div>
              <div className="info-row">
                <span className="info-label">完成时间</span>
                <span className="info-value">
                  {selectedPhase.completed_at 
                    ? new Date(selectedPhase.completed_at).toLocaleString('zh-CN')
                    : '-'
                  }
                </span>
              </div>
            </div>

            {/* Tasks List */}
            <div className="tasks-section">
              <h4>任务列表</h4>
              {tasksLoading ? (
                <div className="tasks-loading">
                  <Spin />
                </div>
              ) : tasks.length === 0 ? (
                <Empty description="暂无任务" />
              ) : (
                <div className="tasks-list">
                  {tasks.map(task => {
                    const taskStatus = TASK_STATUS_CONFIG[task.status] || TASK_STATUS_CONFIG.todo
                    const taskIcon = TASK_TYPE_ICONS[task.task_type] || <FileTextOutlined />
                    
                    return (
                      <div key={task.id} className={`task-item ${taskStatus.className}`}>
                        <div className="task-icon">
                          {task.status === 'completed' ? (
                            <CheckCircleFilled style={{ color: '#10b981' }} />
                          ) : task.status === 'in_progress' ? (
                            <Spin size="small" />
                          ) : (
                            taskIcon
                          )}
                        </div>
                        <div className="task-content">
                          <div className="task-name">{task.name}</div>
                          <div className="task-meta">
                            <Tag color={taskStatus.color} size="small">
                              {taskStatus.text}
                            </Tag>
                          </div>
                        </div>
                        <div className="task-actions">
                          {task.status === 'todo' && (
                            <Button
                              type="link"
                              size="small"
                              icon={<PlayCircleFilled />}
                              onClick={() => handleStartTask(task.id)}
                            >
                              开始
                            </Button>
                          )}
                          {task.status === 'in_progress' && (
                            <Button
                              type="link"
                              size="small"
                              icon={<CheckCircleFilled />}
                              onClick={() => handleCompleteTask(task.id)}
                            >
                              完成
                            </Button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Complete Phase Button */}
            {selectedPhase.status === 'active' && (
              <Button
                type="primary"
                block
                icon={<CheckCircleFilled />}
                onClick={() => handleCompletePhase(selectedPhase.id)}
                className="complete-phase-btn"
              >
                完成阶段
              </Button>
            )}
          </div>
        )}
      </Drawer>
    </>
  )
}

export default AssessmentProgress
