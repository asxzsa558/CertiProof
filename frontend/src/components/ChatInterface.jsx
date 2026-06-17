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
} from '@ant-design/icons'
import api from '../services/api'
import './ChatInterface.css'

const { TextArea } = Input

const SUGGESTIONS = [
  {
    icon: <ThunderboltOutlined />,
    title: '开始扫描',
    text: '帮我扫描当前项目',
    color: '#6366f1',
  },
  {
    icon: <FileSearchOutlined />,
    title: '查看问题',
    text: '显示所有发现的安全问题',
    color: '#ef4444',
  },
  {
    icon: <SafetyCertificateOutlined />,
    title: '合规评分',
    text: '当前项目的合规分数是多少？',
    color: '#10b981',
  },
  {
    icon: <MonitorOutlined />,
    title: '持续监控',
    text: '帮我设置每日定时扫描',
    color: '#f59e0b',
  },
]

function ChatInterface({ projectId, projectName }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: projectId
        ? `你好！我是 CertiProof 安全助手。我可以帮你管理项目"${projectName}"的合规检测。你可以让我扫描资产、查看问题、生成报告等。试试下面的快捷操作或直接输入你的需求。`
        : '你好！我是 CertiProof 安全助手。我可以帮你扫描资产、检测安全风险、管理合规项目。试试下面的快捷操作或直接输入你的需求。',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = async (text = null) => {
    const messageText = text || input.trim()
    if (!messageText || loading) return

    const userMessage = {
      role: 'user',
      content: messageText,
    }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      const response = await api.post('/chat/', {
        message: messageText,
        project_id: projectId,
      })

      const assistantMessage = {
        role: 'assistant',
        content: response.data.response,
        actions: response.data.actions || [],
      }
      setMessages((prev) => [...prev, assistantMessage])
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

  return (
    <div className="chat-interface">
      <div className="chat-header">
        <div className="chat-title">
          <RobotOutlined style={{ color: '#6366f1' }} />
          <span>AI 安全助手</span>
        </div>
        <div className="chat-status">
          <div className="status-dot"></div>
          <span>在线</span>
        </div>
      </div>

      <div className="chat-messages">
        {messages.map((msg, index) => (
          <div key={index} className={`chat-message ${msg.role}`}>
            <div className="message-avatar">
              {msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
            </div>
            <div className={`message-bubble ${msg.role} ${msg.isError ? 'error' : ''}`}>
              <div className="message-content">{msg.content}</div>
              {msg.actions && msg.actions.length > 0 && (
                <div className="message-actions">
                  {msg.actions.map((action, i) => (
                    <div key={i} className="action-chip">
                      {action.type === 'scan_started' && '🔍 扫描已启动'}
                      {action.type === 'scan_completed' && '✅ 扫描完成'}
                      {action.type === 'report_generated' && '📄 报告已生成'}
                      {action.data && action.data.scan_id && (
                        <span> (ID: {action.data.scan_id})</span>
                      )}
                      {action.data && action.data.findings_count !== undefined && (
                        <span> - 发现 {action.data.findings_count} 个问题</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="chat-message assistant">
            <div className="message-avatar">
              <RobotOutlined />
            </div>
            <div className="message-bubble assistant loading">
              <Spin size="small" />
              <span style={{ marginLeft: 8, color: 'rgba(255,255,255,0.6)' }}>思考中...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {messages.length <= 1 && (
        <div className="chat-suggestions">
          <div className="suggestions-title">试试这些操作：</div>
          <div className="suggestions-grid">
            {SUGGESTIONS.map((s, i) => (
              <button
                key={i}
                className="suggestion-card"
                onClick={() => handleSend(s.text)}
                style={{ '--accent': s.color }}
              >
                <div className="suggestion-icon">{s.icon}</div>
                <div className="suggestion-title">{s.title}</div>
                <div className="suggestion-text">{s.text}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-input-area">
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyPress}
          placeholder={projectId ? `向 AI 助手询问"${projectName}"的合规状态...` : '向 AI 助手询问合规相关问题...'}
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={loading}
          className="chat-input"
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={() => handleSend()}
          loading={loading}
          disabled={!input.trim()}
          className="chat-send-btn"
        >
          发送
        </Button>
      </div>
    </div>
  )
}

export default ChatInterface