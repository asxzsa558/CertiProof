import { useState } from 'react'
import { Button, Progress } from 'antd'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  DownOutlined,
  LoadingOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  StopOutlined,
  UpOutlined,
} from '@ant-design/icons'

function MultiAssetProgressCard({ msg, onPause, onStop, onResume }) {
  const [expanded, setExpanded] = useState(!msg.taskCompleted)
  const assetProgress = msg.assetProgress || {}
  const totalAssets = msg.totalAssets || Object.keys(assetProgress).length
  const taskStatus = msg.taskStatus || 'running'
  const isPaused = taskStatus === 'paused'
  const isStopped = taskStatus === 'stopped'
  const isFailed = taskStatus === 'failed'
  const isCompleted = msg.taskCompleted || ['completed', 'success', 'failed', 'stopped'].includes(taskStatus)

  const completedCount = Object.values(assetProgress).filter(asset =>
    asset.status === 'completed' || asset.status === 'failed' || asset.status === 'success' || asset.status === 'cancelled'
  ).length
  const failedCount = Object.values(assetProgress).filter(asset => asset.status === 'failed').length
  const progress = totalAssets > 0 ? Math.round((completedCount / totalAssets) * 100) : 0
  const displayStatus = isStopped ? '已停止' : isFailed || failedCount ? '部分失败' : isPaused ? '已暂停' : isCompleted ? '已完成' : '执行中'
  const cardClassName = `task-progress-card multi-asset-card ${isPaused ? 'paused' : ''} ${isStopped || isFailed ? 'stopped' : ''} ${isCompleted ? 'completed' : ''}`

  return (
    <div className="scan-animation-fade-in" style={{ marginTop: 4 }}>
      <div className={cardClassName}>
        <button className="task-card-summary" type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}>
          <span className={`task-summary-icon ${isFailed || failedCount || isStopped ? 'failed' : isCompleted ? 'completed' : isPaused ? 'paused' : 'running'}`}>
            {isFailed || failedCount || isStopped ? <CloseCircleFilled /> : isCompleted ? <CheckCircleFilled /> : isPaused ? <PauseCircleOutlined /> : <LoadingOutlined spin />}
          </span>
          <span className="task-summary-copy">
            <strong>{msg.content || '多资产安全检测'}</strong>
            <small>{totalAssets || 0} 个资产 · {completedCount} 个已返回</small>
          </span>
          <span className={`task-summary-status ${isFailed || failedCount || isStopped ? 'failed' : isCompleted ? 'completed' : isPaused ? 'paused' : 'running'}`}>{displayStatus}</span>
          {expanded ? <UpOutlined /> : <DownOutlined />}
        </button>

        {expanded && <div className="task-card-details">
          {(isPaused || isStopped) && (
            <div className={`task-status-badge ${isPaused ? 'badge-paused' : 'badge-stopped'}`}>
              {isPaused ? <PauseCircleOutlined /> : <StopOutlined />}
              <span>{isPaused ? '已暂停' : '已停止'}</span>
            </div>
          )}

          <div className="progress-bar-container">
            <Progress
              percent={progress}
              strokeColor={isStopped || isFailed ? '#ef4444' : isPaused ? '#faad14' : { from: '#22d3ee', to: '#3b82f6' }}
              showInfo={false}
              size="small"
            />
            <span className="progress-text">
              {completedCount} / {totalAssets}
            </span>
          </div>

        {!isCompleted && <div className="task-controls">
          {isPaused ? (
            <>
              <Button
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => onResume(msg.taskId)}
                className="task-control-btn"
                style={{ background: 'rgba(16, 185, 129, 0.1)', borderColor: '#10b981', color: '#10b981' }}
              >
                恢复
              </Button>
              <Button
                size="small"
                danger
                icon={<StopOutlined />}
                onClick={() => onStop(msg.taskId)}
                className="task-control-btn"
              >
                停止
              </Button>
            </>
          ) : (
            <>
              <Button
                size="small"
                icon={<PauseCircleOutlined />}
                onClick={() => onPause(msg.taskId)}
                className="task-control-btn"
              >
                暂停
              </Button>
              <Button
                size="small"
                danger
                icon={<StopOutlined />}
                onClick={() => onStop(msg.taskId)}
                className="task-control-btn"
              >
                停止
              </Button>
            </>
          )}
        </div>}

        <div className="asset-progress-list">
          {Object.entries(assetProgress).map(([index, asset]) => {
            const isRunning = asset.status === 'running' || asset.status === 'pending'
            const showPaused = isPaused && isRunning

            return (
              <div key={index} className={`asset-progress-item ${showPaused ? 'paused' : asset.status}`}>
                {asset.status === 'completed' || asset.status === 'success' ? (
                  <CheckCircleFilled style={{ color: '#10b981' }} />
                ) : asset.status === 'failed' ? (
                  <CloseCircleFilled style={{ color: '#ef4444' }} />
                ) : asset.status === 'cancelled' ? (
                  <StopOutlined style={{ color: '#faad14' }} />
                ) : showPaused ? (
                  <PauseCircleOutlined style={{ color: '#faad14' }} />
                ) : (
                  <LoadingOutlined style={{ color: '#6366f1' }} spin />
                )}
                <span className="asset-name">{asset.name}</span>
                {asset.status === 'running' && !isPaused && (
                  <span className="asset-status">扫描中...</span>
                )}
                {asset.status === 'cancelled' && (
                  <span className="asset-status">已取消</span>
                )}
                {showPaused && (
                  <span className="asset-status">已暂停</span>
                )}
              </div>
            )
          })}
        </div>
        </div>}
      </div>
    </div>
  )
}

export default function TaskStatusCard({ msg, onPause, onStop, onResume }) {
  const [expanded, setExpanded] = useState(!msg.taskCompleted)
  if (!msg.taskId) return null

  if (msg.isMultiAsset && msg.assetProgress) {
    return (
      <MultiAssetProgressCard
        msg={msg}
        onPause={onPause}
        onStop={onStop}
        onResume={onResume}
      />
    )
  }

  const stepProgress = msg.stepProgress
  const currentStep = msg.currentStep
  const isPaused = msg.taskStatus === 'paused'
  const isStopped = msg.taskStatus === 'stopped'
  const isFailed = msg.taskStatus === 'failed'
  const isCompleted = msg.taskCompleted || ['completed', 'success', 'failed', 'stopped'].includes(msg.taskStatus)
  const displayStatus = isStopped ? '已停止' : isFailed ? '失败' : isPaused ? '已暂停' : isCompleted ? '已完成' : '执行中'
  const progress = stepProgress?.total_steps > 0
    ? Math.round(((stepProgress.step_index + 1) / stepProgress.total_steps) * 100)
    : isCompleted ? 100 : 0

  return (
    <div className="scan-animation-fade-in" style={{ marginTop: 4 }}>
      <div className={`task-progress-card ${isPaused ? 'paused' : ''} ${isFailed || isStopped ? 'stopped' : ''} ${isCompleted ? 'completed' : ''}`}>
        <button className="task-card-summary" type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}>
          <span className={`task-summary-icon ${isFailed || isStopped ? 'failed' : isCompleted ? 'completed' : isPaused ? 'paused' : 'running'}`}>
            {isFailed || isStopped ? <CloseCircleFilled /> : isCompleted ? <CheckCircleFilled /> : isPaused ? <PauseCircleOutlined /> : <LoadingOutlined spin />}
          </span>
          <span className="task-summary-copy">
            <strong>{msg.content || '安全检测任务'}</strong>
            <small>{currentStep || (isCompleted ? '执行结果已返回' : '等待执行进度')}</small>
          </span>
          <span className={`task-summary-status ${isFailed || isStopped ? 'failed' : isCompleted ? 'completed' : isPaused ? 'paused' : 'running'}`}>{displayStatus}</span>
          {expanded ? <UpOutlined /> : <DownOutlined />}
        </button>

        {expanded && <div className="task-card-details">
        {isPaused && (
          <div className="task-status-badge badge-paused">
            <PauseCircleOutlined />
            <span>已暂停</span>
          </div>
        )}

        {stepProgress && stepProgress.total_steps > 0 && (
          <div className="progress-bar-container">
            <Progress
              percent={progress}
              strokeColor={isFailed || isStopped ? '#ef4444' : isPaused ? '#faad14' : { from: '#22d3ee', to: '#3b82f6' }}
              showInfo={false}
              size="small"
            />
            <span className="progress-text">
              {stepProgress.step_index + 1} / {stepProgress.total_steps}
            </span>
          </div>
        )}

        <div className="current-step">
          {isFailed || isStopped ? (
            <CloseCircleFilled style={{ color: '#ef4444' }} />
          ) : isCompleted ? (
            <CheckCircleFilled style={{ color: '#10b981' }} />
          ) : isPaused ? (
            <PauseCircleOutlined style={{ color: '#faad14' }} />
          ) : (
            <LoadingOutlined style={{ color: '#6366f1' }} spin />
          )}
          <span className="step-text">{isFailed ? (currentStep || '任务执行失败') : isStopped ? '任务已停止' : isPaused ? '任务已暂停' : isCompleted ? (currentStep || '任务执行完成') : (currentStep || '任务执行中...')}</span>
        </div>

        {stepProgress && stepProgress.steps && stepProgress.steps.length > 0 && (
          <div className="steps-list">
            {stepProgress.steps.map((step, idx) => (
              <div key={idx} className={`step-item step-${step.status}`}>
                {step.status === 'completed' ? (
                  <CheckCircleFilled style={{ color: '#10b981' }} />
                ) : step.status === 'failed' ? (
                  <CloseCircleFilled style={{ color: '#ef4444' }} />
                ) : (
                  <LoadingOutlined style={{ color: '#6366f1' }} spin />
                )}
                <span>{step.display_name}</span>
              </div>
            ))}
          </div>
        )}
        {!isCompleted && <div className="task-controls">
          {isPaused ? (
            <Button size="small" icon={<PlayCircleOutlined />} onClick={() => onResume(msg.taskId)} className="task-control-btn">继续</Button>
          ) : (
            <Button size="small" icon={<PauseCircleOutlined />} onClick={() => onPause(msg.taskId)} className="task-control-btn">暂停</Button>
          )}
          <Button size="small" danger icon={<StopOutlined />} onClick={() => onStop(msg.taskId)} className="task-control-btn">停止</Button>
        </div>}
        </div>}
      </div>
    </div>
  )
}
