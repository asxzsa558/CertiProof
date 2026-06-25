import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Form, Input, Button, message } from 'antd'
import { LockOutlined, MailOutlined } from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import './Auth.css'

function Login() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const setAuth = useAuthStore((state) => state.setAuth)

  const onFinish = async (values) => {
    setLoading(true)
    try {
      const response = await api.post('/auth/login', {
        email: values.email,
        password: values.password,
      })

      const { access_token, refresh_token, user, organizations } = response.data
      setAuth(access_token, refresh_token, user, organizations)
      message.success('登录成功')
      navigate('/dashboard')
    } catch (error) {
      message.error(error.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-container">
        <div className="auth-brand">
          <div className="brand-header">
            <div className="logo">
              <VeriSureLogo size={72} />
              <span className="logo-text">VeriSure</span>
            </div>
            <div className="brand-badge">Intelligence · Compliance · Assurance</div>
          </div>
          
          <div className="brand-content">
            <h1 className="brand-title">
              智能合规<br/>
              <span className="brand-accent">精准验证</span>
            </h1>
            <p className="brand-description">
              以 AI 驱动的智能验证引擎，为企业构建全链路合规保障体系
            </p>
            
            <div className="brand-metrics">
              <div className="metric">
                <div className="metric-value">99.9%</div>
                <div className="metric-label">检测准确率</div>
              </div>
              <div className="metric-divider"></div>
              <div className="metric">
                <div className="metric-value">10x</div>
                <div className="metric-label">效率提升</div>
              </div>
              <div className="metric-divider"></div>
              <div className="metric">
                <div className="metric-value">24/7</div>
                <div className="metric-label">持续监控</div>
              </div>
            </div>
          </div>

          <div className="brand-footer">
            <div className="trust-badges">
              <span>🔒 企业级安全</span>
              <span>⚡ 实时检测</span>
              <span>📊 智能分析</span>
            </div>
          </div>
        </div>

        <div className="auth-form-section">
          <div className="form-wrapper">
            <div className="form-header">
              <h2>欢迎回来</h2>
              <p>登录您的账户以继续</p>
            </div>

            <Form
              name="login"
              onFinish={onFinish}
              autoComplete="off"
              layout="vertical"
              className="auth-form"
            >
              <Form.Item
                label="邮箱"
                name="email"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '请输入有效的邮箱' }
                ]}
              >
                <Input
                  prefix={<MailOutlined className="input-icon" />}
                  placeholder="your@email.com"
                  size="large"
                />
              </Form.Item>

              <Form.Item
                label="密码"
                name="password"
                rules={[{ required: true, message: '请输入密码' }]}
              >
                <Input.Password
                  prefix={<LockOutlined className="input-icon" />}
                  placeholder="输入密码"
                  size="large"
                />
              </Form.Item>

              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={loading}
                  block
                  size="large"
                  className="submit-btn"
                >
                  登录
                </Button>
              </Form.Item>
            </Form>

            <div className="form-footer">
              <span>还没有账户？</span>
              <Link to="/register" className="auth-link">
                立即注册
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Login
