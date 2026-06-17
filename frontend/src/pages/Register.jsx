import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Form, Input, Button, message, Steps, Progress } from 'antd'
import { UserOutlined, LockOutlined, MailOutlined, CheckOutlined } from '@ant-design/icons'
import api from '../services/api'
import './Auth.css'

function Register() {
  const [loading, setLoading] = useState(false)
  const [currentStep, setCurrentStep] = useState(0)
  const [formData, setFormData] = useState({})
  const navigate = useNavigate()
  const [form] = Form.useForm()

  const calculatePasswordStrength = (password) => {
    let strength = 0
    if (password.length >= 12) strength += 25
    if (/[a-z]/.test(password)) strength += 15
    if (/[A-Z]/.test(password)) strength += 15
    if (/[0-9]/.test(password)) strength += 15
    if (/[!@#$%^&*(),.?":{}|<>]/.test(password)) strength += 20
    return Math.min(strength, 100)
  }

  const getStrengthColor = (s) => s < 40 ? '#ef4444' : s < 70 ? '#f59e0b' : '#10b981'
  const getStrengthText = (s) => s < 40 ? '弱' : s < 70 ? '中' : '强'

  const onNext = async () => {
    try {
      const values = await form.validateFields()
      setFormData({ ...formData, ...values })
      setCurrentStep(currentStep + 1)
    } catch (error) {}
  }

  const onFinish = async () => {
    setLoading(true)
    try {
      await api.post('/auth/register', {
        email: formData.email,
        username: formData.username,
        password: formData.password,
        full_name: formData.fullName,
      })
      message.success('注册成功，请登录')
      navigate('/login')
    } catch (error) {
      const msg = error.response?.data?.detail
      message.error(Array.isArray(msg) ? msg.join('; ') : msg || '注册失败')
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
              <div className="logo-mark"></div>
              <span className="logo-text">CertiProof</span>
            </div>
            <div className="brand-badge">Enterprise Security</div>
          </div>
          
          <div className="brand-content">
            <h1 className="brand-title">
              开启您的<br/>
              <span className="brand-accent">合规之旅</span>
            </h1>
            <p className="brand-description">
              注册账户，体验 AI 驱动的等保合规自检平台。快速、智能、专业。
            </p>
            
            <div className="brand-metrics">
              <div className="metric">
                <div className="metric-value">3min</div>
                <div className="metric-label">首次检测</div>
              </div>
              <div className="metric-divider"></div>
              <div className="metric">
                <div className="metric-value">60+</div>
                <div className="metric-label">检查条款</div>
              </div>
              <div className="metric-divider"></div>
              <div className="metric">
                <div className="metric-value">0</div>
                <div className="metric-label">人工干预</div>
              </div>
            </div>
          </div>

          <div className="brand-footer">
            <div className="trust-badges">
              <span>🔒 数据安全</span>
              <span>⚡ 即时反馈</span>
              <span>🎯 精准定位</span>
            </div>
          </div>
        </div>

        <div className="auth-form-section">
          <div className="form-wrapper">
            <div className="form-header">
              <h2>创建账户</h2>
              <p>填写以下信息开始使用</p>
            </div>

            <Steps
              current={currentStep}
              size="small"
              items={[{ title: '账户' }, { title: '安全' }, { title: '完成' }]}
              style={{ marginBottom: '2rem' }}
            />

            <Form form={form} layout="vertical" className="auth-form">
              {currentStep === 0 && (
                <>
                  <Form.Item label="邮箱" name="email" rules={[
                    { required: true, message: '请输入邮箱' },
                    { type: 'email', message: '请输入有效的邮箱' }
                  ]}>
                    <Input prefix={<MailOutlined className="input-icon" />} placeholder="your@email.com" size="large" />
                  </Form.Item>
                  <Form.Item label="用户名" name="username" rules={[
                    { required: true, message: '请输入用户名' },
                    { min: 3, message: '用户名至少3个字符' }
                  ]}>
                    <Input prefix={<UserOutlined className="input-icon" />} placeholder="用户名" size="large" />
                  </Form.Item>
                  <Form.Item label="姓名（可选）" name="fullName">
                    <Input prefix={<UserOutlined className="input-icon" />} placeholder="姓名" size="large" />
                  </Form.Item>
                  <Form.Item>
                    <Button type="primary" onClick={onNext} block size="large" className="submit-btn">下一步</Button>
                  </Form.Item>
                </>
              )}

              {currentStep === 1 && (
                <>
                  <Form.Item label="密码" name="password" rules={[
                    { required: true, message: '请输入密码' },
                    { min: 12, message: '密码至少 12 个字符' },
                    { pattern: /[A-Z]/, message: '需包含大写字母' },
                    { pattern: /[a-z]/, message: '需包含小写字母' },
                    { pattern: /[0-9]/, message: '需包含数字' },
                    { pattern: /[!@#$%^&*(),.?":{}|<>]/, message: '需包含特殊字符' },
                  ]}>
                    <Input.Password prefix={<LockOutlined className="input-icon" />} placeholder="密码" size="large" />
                  </Form.Item>

                  <Form.Item noStyle dependencies={['password']}>
                    {({ getFieldValue }) => {
                      const pwd = getFieldValue('password') || ''
                      const s = calculatePasswordStrength(pwd)
                      return pwd ? (
                        <div style={{ marginBottom: '1rem' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                            <span style={{ fontSize: '0.875rem', color: 'rgba(255,255,255,0.5)' }}>密码强度</span>
                            <span style={{ fontSize: '0.875rem', fontWeight: 600, color: getStrengthColor(s) }}>
                              {getStrengthText(s)}
                            </span>
                          </div>
                          <Progress percent={s} showInfo={false} strokeColor={getStrengthColor(s)} trailColor="rgba(255,255,255,0.1)" />
                        </div>
                      ) : null
                    }}
                  </Form.Item>

                  <div style={{
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: 10,
                    padding: '1rem',
                    marginBottom: '1.5rem',
                    border: '1px solid rgba(255,255,255,0.08)',
                  }}>
                    <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'rgba(255,255,255,0.7)', marginBottom: '0.75rem' }}>
                      密码要求
                    </div>
                    <Form.Item noStyle dependencies={['password']}>
                      {({ getFieldValue }) => {
                        const pwd = getFieldValue('password') || ''
                        return [
                          { text: '至少 12 个字符', ok: pwd.length >= 12 },
                          { text: '包含大写字母', ok: /[A-Z]/.test(pwd) },
                          { text: '包含小写字母', ok: /[a-z]/.test(pwd) },
                          { text: '包含数字', ok: /[0-9]/.test(pwd) },
                          { text: '包含特殊字符', ok: /[!@#$%^&*(),.?":{}|<>]/.test(pwd) },
                        ].map((r, i) => (
                          <div key={i} style={{
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                            fontSize: '0.8125rem', color: r.ok ? '#10b981' : 'rgba(255,255,255,0.4)',
                            marginBottom: '0.375rem',
                          }}>
                            <CheckOutlined style={{ fontSize: '0.75rem' }} />
                            {r.text}
                          </div>
                        ))
                      }}
                    </Form.Item>
                  </div>

                  <Form.Item label="确认密码" name="confirmPassword" dependencies={['password']} rules={[
                    { required: true, message: '请确认密码' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (!value || getFieldValue('password') === value) return Promise.resolve()
                        return Promise.reject(new Error('两次输入的密码不一致'))
                      },
                    }),
                  ]}>
                    <Input.Password prefix={<LockOutlined className="input-icon" />} placeholder="确认密码" size="large" />
                  </Form.Item>

                  <div style={{ display: 'flex', gap: '1rem' }}>
                    <Button onClick={() => setCurrentStep(0)} size="large" style={{ flex: 1, height: 48, borderRadius: 10, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#fff' }}>
                      上一步
                    </Button>
                    <Button type="primary" onClick={onNext} loading={loading} size="large" className="submit-btn" style={{ flex: 1 }}>
                      下一步
                    </Button>
                  </div>
                </>
              )}

              {currentStep === 2 && (
                <div style={{ textAlign: 'center' }}>
                  <div style={{
                    width: 80, height: 80, margin: '0 auto 2rem',
                    background: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
                    borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '2rem', color: 'white',
                  }}>
                    <CheckOutlined />
                  </div>
                  <h3 style={{ fontSize: '1.5rem', fontWeight: 600, color: '#fff', marginBottom: '1rem' }}>信息确认</h3>
                  <div style={{
                    background: 'rgba(255,255,255,0.03)', borderRadius: 12, padding: '1.5rem',
                    marginBottom: '2rem', textAlign: 'left', border: '1px solid rgba(255,255,255,0.08)',
                  }}>
                    <div style={{ marginBottom: '0.75rem' }}>
                      <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.875rem' }}>邮箱：</span>
                      <span style={{ color: '#fff', fontWeight: 500, marginLeft: '0.5rem' }}>{formData.email}</span>
                    </div>
                    <div>
                      <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.875rem' }}>用户名：</span>
                      <span style={{ color: '#fff', fontWeight: 500, marginLeft: '0.5rem' }}>{formData.username}</span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '1rem' }}>
                    <Button onClick={() => setCurrentStep(1)} size="large" style={{ flex: 1, height: 48, borderRadius: 10, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#fff' }}>
                      上一步
                    </Button>
                    <Button type="primary" onClick={onFinish} loading={loading} size="large" className="submit-btn" style={{ flex: 1, background: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)' }}>
                      完成注册
                    </Button>
                  </div>
                </div>
              )}
            </Form>

            <div className="form-footer">
              <span>已有账户？</span>
              <Link to="/login" className="auth-link">立即登录</Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Register
