import { useState, useEffect, useRef } from 'react'
import { Card, Progress, Tag, List, Typography, Spin, Empty } from 'antd'
import { 
  CheckCircleOutlined, 
  LoadingOutlined, 
  ClockCircleOutlined,
  CloseCircleOutlined,
  ApiOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import './AgentStatusCard.css'
import './ScanAnimation.css'

const { Text, Title } = Typography

function AgentStatusCard({ taskIds, onComplete }) {
  const [agents, setAgents] = useState([])
  const [loading, setLoading] = useState(true)
  const [polling, setPolling] = useState(true)
  const wsRefs = useRef({})  // task_id -> WebSocket
  const completedRef = useRef(false)  // 确保 onComplete 只调用一次

  useEffect(() => {
    if (!taskIds || taskIds.length === 0) {
      setLoading(false)
      return
    }

    // 重置完成标志
    completedRef.current = false

    // 初始加载
    fetchStatus()

    // 使用轮询获取状态（禁用 WebSocket）
    const interval = setInterval(() => {
      if (polling && !completedRef.current) {
        fetchStatus()
      }
    }, 2000)  // 每 2 秒轮询一次

    return () => {
      clearInterval(interval)
    }
  }, [taskIds])

  const connectWebSocket = (taskId) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/v1/ws/agents/${taskId}`
    
    try {
      const token = useAuthStore.getState().token
      if (!token) return
      const ws = new WebSocket(wsUrl, ['certiproof', `auth.${token}`])
      wsRefs.current[taskId] = ws

      ws.onopen = () => {
        // 发送心跳
        const heartbeat = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping')
          } else {
            clearInterval(heartbeat)
          }
        }, 30000)
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          handleWebSocketMessage(taskId, message)
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }

      ws.onerror = (error) => {
        console.error(`WebSocket error for task ${taskId}:`, error)
      }

      ws.onclose = () => {
        delete wsRefs.current[taskId]
      }
    } catch (error) {
      console.error(`Failed to connect WebSocket for task ${taskId}:`, error)
    }
  }

  const handleWebSocketMessage = (taskId, message) => {
    const { type, data } = message

    if (type === 'status') {
      // 更新 Agent 状态
      setAgents(prev => {
        const existing = prev.find(a => a.agent_id === taskId)
        if (existing) {
          return prev.map(a => a.agent_id === taskId ? { ...a, ...data } : a)
        } else {
          return [...prev, { ...data, agent_id: taskId }]
        }
      })
    } else if (type === 'completed') {
      // Agent 完成 - 先更新状态，然后做一次 final fetch 获取完整数据
      setAgents(prev => {
        const updated = prev.map(a => 
          a.agent_id === taskId 
            ? { ...a, status: 'completed', progress: 100, evidence_count: data.evidence_count, scan_results: data.scan_results }
            : a
        )
        
        // 检查是否所有 Agent 都完成
        const allCompleted = updated.every(a => a.status === 'completed' || a.status === 'failed')
        if (allCompleted && updated.length > 0 && !completedRef.current) {
          // 做一次 final fetch 获取完整的 scan_results
          fetchStatus(true).then(() => {
            completedRef.current = true
            setPolling(false)
            if (onComplete) {
              // 从最新的 agents 状态中获取数据
              setAgents(currentAgents => {
                onComplete(currentAgents)
                return currentAgents
              })
            }
          })
        }
        
        return updated
      })
    } else if (type === 'failed') {
      // Agent 失败
      setAgents(prev => {
        const updated = prev.map(a => 
          a.agent_id === taskId 
            ? { ...a, status: 'failed', error: data.error }
            : a
        )
        
        // 检查是否所有 Agent 都完成
        const allCompleted = updated.every(a => a.status === 'completed' || a.status === 'failed')
        if (allCompleted && updated.length > 0 && !completedRef.current) {
          completedRef.current = true
          setPolling(false)
          if (onComplete) {
            onComplete(updated)
          }
        }
        
        return updated
      })
    }
  }

  const fetchStatus = async () => {
    // 如果已经完成，不再轮询
    if (completedRef.current) {
      return
    }

    try {
      const response = await api.get('/chat/status')
      const allAgents = [
        ...response.data.running.map(a => ({
          ...a,
          isRunning: true,
        })),
        ...response.data.completed.map(t => ({
          agent_id: t.task_id,
          name: t.agent_name,
          status: 'completed',
          progress: 100,
          evidence_count: t.evidence_count || 0,
          scan_results: t.scan_results || {},
          isRunning: false,
        })),
      ]

      // 过滤出当前任务的 Agent
      const filteredAgents = allAgents.filter(a => taskIds.includes(a.agent_id))
      setAgents(filteredAgents)

      // 检查是否所有 Agent 都完成，且只调用一次 onComplete
      const allCompleted = filteredAgents.length > 0 && filteredAgents.every(a => a.status === 'completed' || a.status === 'failed')
      if (allCompleted && !completedRef.current) {
        completedRef.current = true
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

  const renderProgress = (agent) => {
    if (agent.status !== 'running') return null

    const scanProgress = agent.scan_progress || {}
    const totalPorts = scanProgress.total_ports || 0
    const scannedPorts = scanProgress.scanned_ports || 0
    const openPortsFound = scanProgress.open_ports_found || 0

    return (
      <div className="agent-progress scan-animation-fade-in">
        <div className="scan-progress-container">
          <Progress 
            percent={agent.progress || 0} 
            size="small"
            status="active"
            className="scan-progress-shine"
          />
        </div>
        {totalPorts > 0 && (
          <div className="scan-details scan-animation-slide-in">
            <ApiOutlined style={{ marginRight: 4, color: '#6366f1' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              已扫描 <span className="scan-animation-number-bounce">{scannedPorts.toLocaleString()}</span> / {totalPorts.toLocaleString()} 端口
            </Text>
            {openPortsFound > 0 && (
              <Tag 
                color="orange" 
                style={{ marginLeft: 8, fontSize: 11 }}
                className="scan-animation-port-discover"
              >
                发现 {openPortsFound} 个开放端口
              </Tag>
            )}
          </div>
        )}
        {agent.current_step && (
          <Text type="secondary" className="current-step scan-animation-slide-in">
            {agent.current_step}
          </Text>
        )}
      </div>
    )
  }

  if (loading) {
    return (
      <Card className="agent-status-card scan-animation-fade-in">
        <div style={{ 
          display: 'flex', 
          flexDirection: 'column',
          alignItems: 'center', 
          justifyContent: 'center',
          padding: '40px 0',
          gap: 12
        }}>
          <SafetyCertificateOutlined 
            className="scan-animation-shield"
            style={{ fontSize: 32, color: '#6366f1' }}
          />
          <Spin size="small" />
          <Text type="secondary" style={{ fontSize: 12 }}>
            正在初始化检测...
          </Text>
        </div>
      </Card>
    )
  }

  if (agents.length === 0) {
    return (
      <Card className="agent-status-card scan-animation-fade-in">
        <div style={{ 
          display: 'flex', 
          flexDirection: 'column',
          alignItems: 'center', 
          justifyContent: 'center',
          padding: '40px 0',
          gap: 12
        }}>
          <SafetyCertificateOutlined 
            style={{ fontSize: 32, color: '#6b7280' }}
          />
          <Text type="secondary">
            暂无检测任务
          </Text>
        </div>
      </Card>
    )
  }

  return (
    <Card 
      className="agent-status-card scan-animation-fade-in"
      title={
        <div className="card-title">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {polling ? (
              <SafetyCertificateOutlined 
                className="scan-animation-shield" 
                style={{ color: '#6366f1', fontSize: 18 }}
              />
            ) : (
              <CheckCircleOutlined 
                style={{ color: '#10b981', fontSize: 18 }}
              />
            )}
            <span>当前执行状态</span>
          </div>
          <div className={`scan-status-indicator ${
            polling ? 'scan-status-running' : 'scan-status-completed'
          }`}>
            {polling ? (
              <>
                <LoadingOutlined spin />
                <span>执行中</span>
              </>
            ) : (
              <>
                <CheckCircleOutlined />
                <span>已完成</span>
              </>
            )}
          </div>
        </div>
      }
    >
      <List
        dataSource={agents}
        renderItem={(agent, index) => (
          <List.Item 
            className="agent-item scan-animation-slide-in"
            style={{ animationDelay: `${index * 0.1}s` }}
          >
            <div className="agent-info">
              <div className="agent-header">
                <div className={`scan-animation-pulse ${
                  agent.status === 'running' ? '' : 'scan-animation-glow'
                }`}>
                  {getStatusIcon(agent.status)}
                </div>
                <Text strong className="agent-name">
                  {agent.name}
                </Text>
                <Tag color={getStatusColor(agent.status)} className="scan-animation-fade-in">
                  {agent.status === 'running' ? '运行中' : 
                   agent.status === 'completed' ? '已完成' : 
                   agent.status === 'failed' ? '失败' : '等待中'}
                </Tag>
              </div>
              
              {renderProgress(agent)}
              
              {agent.status === 'completed' && (
                <div className="scan-result-summary scan-animation-fade-in">
                  {agent.scan_results && typeof agent.scan_results === 'object' && Object.keys(agent.scan_results).length > 0 ? (
                    <>
                      <div className="result-header">
                        <SafetyCertificateOutlined style={{ marginRight: 8, color: '#10b981' }} />
                        <Text strong>检测完成</Text>
                      </div>
                      <div className="result-details">
                        {agent.scan_results.open_ports && agent.scan_results.open_ports.length > 0 && (
                          <div className="result-item">
                            <ApiOutlined style={{ marginRight: 4 }} />
                            <Text>发现 {agent.scan_results.open_ports.length} 个开放端口</Text>
                            <div className="port-list">
                              {agent.scan_results.open_ports.slice(0, 5).map((port, idx) => (
                                <Tag key={idx} color={port.risk_level === 'critical' ? 'red' : port.risk_level === 'high' ? 'orange' : 'blue'}>
                                  {port.port}/{port.protocol} {port.service}
                                </Tag>
                              ))}
                              {agent.scan_results.open_ports.length > 5 && (
                                <Text type="secondary"> 等 {agent.scan_results.open_ports.length} 个</Text>
                              )}
                            </div>
                          </div>
                        )}
                        {agent.scan_results.vulnerabilities && agent.scan_results.vulnerabilities.length > 0 && (
                          <div className="result-item">
                            <CloseCircleOutlined style={{ marginRight: 4, color: '#ef4444' }} />
                            <Text>发现 {agent.scan_results.vulnerabilities.length} 个安全漏洞</Text>
                          </div>
                        )}
                        {agent.scan_results.ssl_issues && agent.scan_results.ssl_issues.length > 0 && (
                          <div className="result-item">
                            <CloseCircleOutlined style={{ marginRight: 4, color: '#f59e0b' }} />
                            <Text>发现 {agent.scan_results.ssl_issues.length} 个 SSL 问题</Text>
                          </div>
                        )}
                        {agent.scan_results.compliance_score !== null && agent.scan_results.compliance_score !== undefined && (
                          <div className="result-item">
                            <CheckCircleOutlined style={{ marginRight: 4, color: '#10b981' }} />
                            <Text>合规评分: <Text strong style={{ color: agent.scan_results.compliance_score >= 80 ? '#10b981' : agent.scan_results.compliance_score >= 60 ? '#f59e0b' : '#ef4444' }}>{agent.scan_results.compliance_score}</Text> 分</Text>
                          </div>
                        )}
                      </div>
                    </>
                  ) : (
                    <Text type="success">
                      <CheckCircleOutlined style={{ marginRight: 4 }} />
                      检测已完成
                    </Text>
                  )}
                </div>
              )}
              
              {agent.status === 'failed' && agent.error && (
                <Text type="danger" className="error-message scan-animation-fade-in">
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
