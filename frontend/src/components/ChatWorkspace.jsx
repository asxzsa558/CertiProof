import { useState, useRef, useEffect } from 'react'
import { Input, Button, Avatar, Spin, Empty } from 'antd'
import {
  SendOutlined,
  UserOutlined,
  RobotOutlined,
  ThunderboltOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
  MonitorOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import ToolCardComponent from './ToolCard'
import AgentStatusCard from './AgentStatusCard'
import api from '../services/api'
import './ChatWorkspace.css'

const { TextArea } = Input

const SUGGESTIONS = [
  { icon: <PlusOutlined />, title: '创建项目', text: '创建项目 我的电商网站', color: '#6366f1' },
  { icon: <ThunderboltOutlined />, title: '开始扫描', text: '扫描', color: '#10b981' },
  { icon: <FileSearchOutlined />, title: '查看问题', text: '查看问题', color: '#ef4444' },
  { icon: <SafetyCertificateOutlined />, title: '合规评分', text: '查看分数', color: '#f59e0b' },
]

function ChatWorkspace({ projectId, projectName, modelId }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: '你好！我是 CertiProof 等保合规 Agent。我可以帮你创建项目、扫描资产、检测安全风险、管理合规整改。试试下面的快捷操作，或直接告诉我你的需求。',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [currentProjectId, setCurrentProjectId] = useState(projectId || null)
  const [currentModelId, setCurrentModelId] = useState(modelId || null)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  useEffect(() => {
    if (projectId) {
      setCurrentProjectId(projectId)
    }
  }, [projectId])

  useEffect(() => {
    if (modelId) {
      setCurrentModelId(modelId)
    }
  }, [modelId])

  const handleSend = async (text = null) => {
    const messageText = text || input.trim()
    if (!messageText || loading) return

    const userMessage = { role: 'user', content: messageText }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      const response = await api.post('/chat/', {
        message: messageText,
        project_id: currentProjectId,
        model_id: currentModelId,
      })

      const assistantMessage = {
        role: 'assistant',
        content: response.data.response,
        tool_cards: response.data.tool_cards || [],
        actions: response.data.actions || [],
        context: response.data.context,
        model_used: response.data.model_used,
        task_ids: response.data.task_ids || [],  // 保存 task_ids
      }
      setMessages((prev) => [...prev, assistantMessage])

      // Update project context if returned
      if (response.data.context?.project_id) {
        setCurrentProjectId(response.data.context.project_id)
      }
    } catch (error) {
      const errorMessage = {
        role: 'assistant',
        content: `抱歉，处理请求时出错：${error.response?.data?.detail || error.message || '未知错误'}`,
        isError: true,
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleToolCardAction = (action) => {
    // Map tool card actions to chat commands
    const actionMap = {
      view_findings: '查看问题',
      download_report: '下载报告',
      view_remediation: '查看整改',
    }
    const command = actionMap[action]
    if (command) {
      handleSend(command)
    }
  }

  return (
    <div className="chat-workspace">
      {/* Header */}
      <div className="workspace-header">
        <div className="workspace-title">
          <div className="workspace-logo">
            <RobotOutlined />
          </div>
          <div>
            <div className="workspace-name">CertiProof Agent</div>
            <div className="workspace-subtitle">
              {projectName ? `项目：${projectName}` : '等保合规智能对话'}
            </div>
          </div>
        </div>
        <div className="workspace-status">
          <div className="status-indicator">
            <div className="status-dot"></div>
            <span>在线</span>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="workspace-messages">
        {messages.map((msg, index) => (
          <div key={index} className={`workspace-message ${msg.role}`}>
            <div className="message-avatar">
              {msg.role === 'user' ? (
                <Avatar size={32} style={{ background: 'rgba(255,255,255,0.1)' }} icon={<UserOutlined />} />
              ) : (
                <Avatar
                  size={32}
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
                  icon={<RobotOutlined />}
                />
              )}
            </div>
            <div className="message-body">
              <div className={`message-bubble ${msg.role} ${msg.isError ? 'error' : ''}`}>
                {msg.content}
                {msg.model_used && msg.role === 'assistant' && (
                  <div className="message-model-tag">
                    使用模型: {msg.model_used}
                  </div>
                )}
              </div>
              {msg.tool_cards && msg.tool_cards.length > 0 && (
                <div className="message-tool-cards">
                  {msg.tool_cards.map((card, i) => (
                    <ToolCardComponent
                      key={card.id || i}
                      card={card}
                      onAction={handleToolCardAction}
                    />
                  ))}
                </div>
              )}
              {/* 显示 Agent 执行状态 */}
              {msg.task_ids && msg.task_ids.length > 0 && (
                <AgentStatusCard 
                  taskIds={msg.task_ids}
                  onComplete={(results) => {
                    const totalEvidence = results.reduce((sum, r) => sum + (r.evidence_count || 0), 0)
                    const summaryMessage = {
                      role: 'assistant',
                      content: `✅ 所有检测任务已完成！共收集 ${totalEvidence} 条证据。`,
                    }
                    setMessages(prev => [...prev, summaryMessage])
                  }}
                />
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="workspace-message assistant">
            <div className="message-avatar">
              <Avatar
                size={32}
                style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
                icon={<RobotOutlined />}
              />
            </div>
            <div className="message-body">
              <div className="message-bubble assistant loading">
                <Spin size="small" />
                <span style={{ marginLeft: 8, color: 'rgba(255,255,255,0.6)' }}>思考中...</span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Suggestions (only show when no messages yet) */}
      {messages.length <= 1 && (
        <div className="workspace-suggestions">
          <div className="suggestions-label">快捷操作：</div>
          <div className="suggestions-row">
            {SUGGESTIONS.map((s, i) => (
              <button
                key={i}
                className="suggestion-btn"
                onClick={() => handleSend(s.text)}
                style={{ '--accent': s.color }}
              >
                <span className="suggestion-icon">{s.icon}</span>
                <span className="suggestion-text">{s.title}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="workspace-input-area">
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyPress}
          placeholder={projectName ? `向 Agent 询问"${projectName}"的合规状态...` : '向 Agent 询问合规相关问题...'}
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={loading}
          className="workspace-input"
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={() => handleSend()}
          loading={loading}
          disabled={!input.trim()}
          className="workspace-send-btn"
        >
          发送
        </Button>
      </div>
    </div>
  )
}

export default ChatWorkspace
