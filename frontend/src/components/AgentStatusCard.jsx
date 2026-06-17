import { useState, useEffect } from 'react'
import { Card, Progress, Tag, List, Typography, Spin, Empty } from 'antd'
import { 
  CheckCircleOutlined, 
  LoadingOutlined, 
  ClockCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import './AgentStatusCard.css'

const { Text, Title } = Typography

function AgentStatusCard({ taskIds, onComplete }) {
  const [agents, setAgents] = useState([])
  const [loading, setLoading] = useState(true)
  const [polling, setPolling] = useState(true)

  useEffect(() => {
    if (!taskIds || taskIds.length === 0) {
      setLoading(false)
      return
    }

    // 初始加载
    fetchStatus()

    // 轮询状态
    const interval = setInterval(() => {
      if (polling) {
        fetchStatus()
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [taskIds, polling])

  const fetchStatus = async () => {
    try {
      const response = await api.get('/chat/status')
      const allAgents = [
        ...response.data.running,
        ...response.data.completed.map(t => ({
          agent_id: t.task_id,
          name: t.agent_name,
          status: 'completed',
          progress: 100,
        })),
      ]

      // 过滤出当前任务的 Agent
      const filteredAgents = allAgents.filter(a => taskIds.includes(a.agent_id))
      setAgents(filteredAgents)

      // 检查是否所有 Agent 都完成
      const allCompleted = filteredAgents.every(a => a.status === 'completed')
      if (allCompleted && filteredAgents.length > 0) {
        setPolling(false)
        if (onComplete) {
          onComplete(filteredAgents)
        }
      }
    } catch (error) {
      console.error('Failed to fetch agent status:', error)
    } finally {
      setLoading(false)
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'running':
        return <LoadingOutlined style={{ color: '#1890ff' }} spin />
      case 'completed':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />
      case 'failed':
        return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
      default:
        return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />
    }
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'running':
        return 'processing'
      case 'completed':
        return 'success'
      case 'failed':
        return 'error'
      default:
        return 'default'
    }
  }

  if (loading) {
    return (
      <Card className="agent-status-card">
        <Spin tip="加载中..." />
      </Card>
    )
  }

  if (agents.length === 0) {
    return (
      <Card className="agent-status-card">
        <Empty description="暂无 Agent 运行" />
      </Card>
    )
  }

  return (
    <Card 
      className="agent-status-card"
      title={
        <div className="card-title">
          <span>当前执行状态</span>
          <Tag color={polling ? 'processing' : 'default'}>
            {polling ? '执行中' : '已完成'}
          </Tag>
        </div>
      }
    >
      <List
        dataSource={agents}
        renderItem={(agent) => (
          <List.Item className="agent-item">
            <div className="agent-info">
              <div className="agent-header">
                {getStatusIcon(agent.status)}
                <Text strong className="agent-name">
                  {agent.name}
                </Text>
                <Tag color={getStatusColor(agent.status)}>
                  {agent.status === 'running' ? '运行中' : 
                   agent.status === 'completed' ? '已完成' : 
                   agent.status === 'failed' ? '失败' : '等待中'}
                </Tag>
              </div>
              
              {agent.status === 'running' && (
                <div className="agent-progress">
                  <Progress 
                    percent={agent.progress || 0} 
                    size="small"
                    status="active"
                  />
                  {agent.current_step && (
                    <Text type="secondary" className="current-step">
                      {agent.current_step}
                    </Text>
                  )}
                </div>
              )}
              
              {agent.status === 'completed' && agent.evidence_count > 0 && (
                <Text type="success" className="evidence-count">
                  收集了 {agent.evidence_count} 条证据
                </Text>
              )}
              
              {agent.status === 'failed' && agent.error && (
                <Text type="danger" className="error-message">
                  {agent.error}
                </Text>
              )}
            </div>
          </List.Item>
        )}
      />
    </Card>
  )
}

export default AgentStatusCard
