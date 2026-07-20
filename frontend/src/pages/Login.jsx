import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Form, Input, Button, Checkbox, message } from 'antd'
import { LockOutlined, MailOutlined } from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import './Auth.css'

function Login() {
  const [loading, setLoading] = useState(false)
  const [registrationEnabled, setRegistrationEnabled] = useState(false)
  const navigate = useNavigate()
  const setAuth = useAuthStore((state) => state.setAuth)

  useEffect(() => {
    api.get('/auth/registration-status')
      .then(response => setRegistrationEnabled(Boolean(response.data?.enabled)))
      .catch(() => setRegistrationEnabled(false))
  }, [])

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
              <span className="logo-text">CertiProof</span>
            </div>
            <div className="brand-badge">Intelligence · Compliance · Assurance</div>
          </div>
          
          <div className="brand-content">
            <h1 className="brand-title">智能合规验证平台</h1>
            <p className="brand-description">
              面向等保测评、资产检测与整改闭环的 AI 指挥中心。
            </p>
            
            <div className="brand-signal-grid">
              <div><span>01</span><strong>等保测评推进</strong></div>
              <div><span>02</span><strong>多资产安全检测</strong></div>
              <div><span>03</span><strong>整改证据闭环</strong></div>
            </div>
          </div>

          <div className="brand-footer">
            <div className="trust-badges">
              <span>本地部署</span>
              <span>工具链可观测</span>
              <span>多资产检测</span>
            </div>
          </div>
        </div>

        <div className="auth-form-section">
          <div className="form-wrapper">
            <div className="form-header">
              <h2>欢迎回来</h2>
              <p>登录组织安全合规工作台</p>
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

              <div className="login-options">
                <Form.Item name="remember" valuePropName="checked" noStyle>
                  <Checkbox>记住我</Checkbox>
                </Form.Item>
                <a>忘记密码</a>
              </div>

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

            {registrationEnabled && (
              <div className="form-footer">
                <span>还没有账户？</span>
                <Link to="/register" className="auth-link">
                  立即注册
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default Login
