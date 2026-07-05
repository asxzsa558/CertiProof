import { Button, Progress } from 'antd'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from '@ant-design/icons'

function MultiAssetProgressCard({ msg, onPause, onStop, onResume }) {
  const assetProgress = msg.assetProgress || {}
  const totalAssets = msg.totalAssets || Object.keys(assetProgress).length
  const taskStatus = msg.taskStatus || 'running'
  const isPaused = taskStatus === 'paused'
  const isStopped = taskStatus === 'stopped'

  const completedCount = Object.values(assetProgress).filter(asset =>
    asset.status === 'completed' || asset.status === 'failed' || asset.status === 'success' || asset.status === 'cancelled'
  ).length
  const progress = totalAssets > 0 ? Math.round((completedCount / totalAssets) * 100) : 0
  const cardClassName = `task-progress-card multi-asset-card ${isPaused ? 'paused' : ''} ${isStopped ? 'stopped' : ''}`

  return (
    <div className="scan-animation-fade-in" style={{ marginTop: 4 }}>
      <div className={cardClassName}>
        {(isPaused || isStopped) && (
          <div className={`task-status-badge ${isPaused ? 'badge-paused' : 'badge-stopped'}`}>
            {isPaused ? <PauseCircleOutlined /> : <StopOutlined />}
            <span>{isPaused ? '已暂停' : '已停止'}</span>
          </div>
        )}

        <div className="progress-bar-container">
          <Progress
            percent={progress}
            strokeColor={isStopped ? '#ef4444' : isPaused ? '#faad14' : { from: '#6366f1', to: '#8b5cf6' }}
            showInfo={false}
            size="small"
          />
          <span className="progress-text">
            {completedCount} / {totalAssets}
          </span>
        </div>

        <div className="task-controls">
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
          ) : isStopped ? (
            <span className="task-stopped-text">任务已终止</span>
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
        </div>

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
      </div>
    </div>
  )
}

export default function TaskStatusCard({ msg, onPause, onStop, onResume }) {
  if (!msg.taskId || msg.taskCompleted) return null

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

  return (
    <div className="scan-animation-fade-in" style={{ marginTop: 4 }}>
      <div className={`task-progress-card ${isPaused ? 'paused' : ''}`}>
        {isPaused && (
          <div className="task-status-badge badge-paused">
            <PauseCircleOutlined />
            <span>已暂停</span>
          </div>
        )}

        {stepProgress && stepProgress.total_steps > 0 && (
          <div className="progress-bar-container">
            <Progress
              percent={Math.round(((stepProgress.step_index + 1) / stepProgress.total_steps) * 100)}
              strokeColor={isPaused ? '#faad14' : { from: '#6366f1', to: '#8b5cf6' }}
              showInfo={false}
              size="small"
            />
            <span className="progress-text">
              {stepProgress.step_index + 1} / {stepProgress.total_steps}
            </span>
          </div>
        )}

        <div className="current-step">
          {isPaused ? (
            <PauseCircleOutlined style={{ color: '#faad14' }} />
          ) : (
            <LoadingOutlined style={{ color: '#6366f1' }} spin />
          )}
          <span className="step-text">{isPaused ? '任务已暂停' : (currentStep || '任务执行中...')}</span>
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
      </div>
    </div>
  )
}
