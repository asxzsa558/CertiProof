import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Layout, Menu, Card, Button, Tag, Avatar, Dropdown, Space, Spin, Descriptions, Collapse, Empty } from 'antd'
import { 
  ProjectOutlined, LogoutOutlined, UserOutlined, SettingOutlined,
  BellOutlined, SafetyCertificateOutlined, ArrowLeftOutlined,
  CheckCircleOutlined, CloseCircleOutlined, WarningOutlined,
  CodeOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import api from '../services/api'
import './ScanResults.css'

const { Header, Content, Sider } = Layout
const { Panel } = Collapse

function ScanResults() {
  const { projectId, scanId } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [scanTask, setScanTask] = useState(null)
  const [findings, setFindings] = useState([])
  const [loading, setLoading] = useState(true)
  const logout = useAuthStore((state) => state.logout)

  useEffect(() => {
    fetchProject()
    fetchScanTask()
    fetchFindings()
  }, [projectId, scanId])

  const fetchProject = async () => {
    try {
      const response = await api.get(`/projects/${projectId}`)
      setProject(response.data)
    } catch (error) {
      console.error('Failed to fetch project:', error)
    }
  }

  const fetchScanTask = async () => {
    try {
      const response = await api.get(`/projects/${projectId}/scans/${scanId}`)
      setScanTask(response.data)
    } catch (error) {
      console.error('Failed to fetch scan task:', error)
    }
  }

  const fetchFindings = async () => {
    setLoading(true)
    try {
      const response = await api.get(`/projects/${projectId}/scans/${scanId}/findings`)
      setFindings(response.data)
    } catch (error) {
      console.error('Failed to fetch findings:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleLogout = () => { logout(); navigate('/login') }

  const getSeverityColor = (severity) => {
    const colors = {
      critical: '#dc2626',
      high: '#ef4444',
      medium: '#f59e0b',
      low: '#3b82f6',
      info: '#64748b',
    }
    return colors[severity] || '#64748b'
  }

  const getSeverityText = (severity) => {
    const texts = {
      critical: '严重',
      high: '高危',
      medium: '中危',
      low: '低危',
      info: '信息',
    }
    return texts[severity] || severity
  }

  const getJudgmentIcon = (judgment) => {
    if (judgment === 'pass') return <CheckCircleOutlined style={{ color: '#10b981' }} />
    if (judgment === 'fail') return <CloseCircleOutlined style={{ color: '#ef4444' }} />
    if (judgment === 'partial') return <WarningOutlined style={{ color: '#f59e0b' }} />
    return <WarningOutlined style={{ color: '#64748b' }} />
  }

  const menuItems = [
    { key: 'dashboard', icon: <ProjectOutlined />, label: '仪表盘' },
    { key: 'projects', icon: <ProjectOutlined />, label: '项目管理' },
  ]

  const userMenuItems = [
    { key: 'profile', icon: <UserOutlined />, label: '个人资料' },
    { key: 'settings', icon: <SettingOutlined />, label: '设置' },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ]

  if (!project || !scanTask) {
    return (
      <Layout className="scan-results-loading">
        <Spin size="large" />
      </Layout>
    )
  }

  return (
    <Layout className="scan-results-layout">
      <Sider width={260} className="scan-results-sider">
        <div className="sider-logo">
          <div className="logo-mark"></div>
          <span className="logo-text">CertiProof</span>
        </div>
        <Menu
          mode="inline"
          defaultSelectedKeys={['projects']}
          items={menuItems}
          onClick={({ key }) => {
            if (key === 'dashboard') navigate('/')
            if (key === 'projects') navigate('/projects')
          }}
          className="sider-menu"
        />
      </Sider>

      <Layout className="scan-results-main">
        <Header className="scan-results-header">
          <div className="header-left">
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/projects/${projectId}`)} className="back-btn">
              返回
            </Button>
            <div className="header-info">
              <h1 className="page-title">扫描结果详情</h1>
              <p className="page-subtitle">{project.name} - 扫描任务 #{scanId}</p>
            </div>
          </div>
          <Space size="large" className="header-right">
            <Button icon={<BellOutlined />} type="text" className="header-icon-btn" />
            <Dropdown menu={{ items: userMenuItems, onClick: ({ key }) => key === 'logout' && handleLogout() }} placement="bottomRight">
              <Space className="user-menu-trigger">
                <Avatar style={{ background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' }} icon={<UserOutlined />} />
              </Space>
            </Dropdown>
          </Space>
        </Header>

        <Content className="scan-results-content">
          {/* Scan Summary */}
          <Card className="summary-card">
            <div className="summary-header">
              <h3>扫描概要</h3>
              <Tag color={scanTask.status === 'completed' ? 'green' : 'orange'}>
                {scanTask.status === 'completed' ? '已完成' : scanTask.status}
              </Tag>
            </div>
            <Descriptions column={2} className="summary-descriptions">
              <Descriptions.Item label="扫描时间">
                {scanTask.started_at ? new Date(scanTask.started_at).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间">
                {scanTask.completed_at ? new Date(scanTask.completed_at).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="发现问题">
                <span style={{ color: '#ef4444', fontWeight: 600 }}>{scanTask.findings_count}</span>
              </Descriptions.Item>
              <Descriptions.Item label="高危问题">
                <span style={{ color: '#ef4444', fontWeight: 600 }}>
                  {scanTask.high_severity_count}
                </span>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {/* Findings List */}
          <Card className="findings-card" title={`问题详情 (${findings.length})`}>
            {findings.length === 0 ? (
              <Empty description="暂无发现问题" />
            ) : (
              <Collapse className="findings-collapse" accordion>
                {findings.map((finding, index) => (
                  <Panel
                    key={finding.id}
                    header={
                      <div className="finding-header">
                        <div className="finding-title">
                          {getJudgmentIcon(finding.judgment)}
                          <span className="finding-clause">{finding.clause_id}</span>
                          <span className="finding-name">{finding.clause_name}</span>
                        </div>
                        <Tag style={{ 
                          background: getSeverityColor(finding.severity),
                          border: 'none',
                          color: '#fff',
                          fontWeight: 600,
                        }}>
                          {getSeverityText(finding.severity)}
                        </Tag>
                      </div>
                    }
                  >
                    <div className="finding-content">
                      <div className="finding-section">
                        <h4><FileTextOutlined /> 问题描述</h4>
                        <p>{finding.description || '无描述'}</p>
                      </div>
                      
                      <div className="finding-section">
                        <h4><SafetyCertificateOutlined /> 整改建议</h4>
                        <p>{finding.remediation_suggestion || '无建议'}</p>
                      </div>

                      {finding.evidence_ids && finding.evidence_ids.length > 0 && (
                        <div className="finding-section">
                          <h4><CodeOutlined /> 证据信息</h4>
                          <div className="evidence-list">
                            {finding.evidence_ids.map((evidenceId, idx) => (
                              <Card key={evidenceId} className="evidence-card" size="small">
                                <pre className="evidence-content">
                                  {JSON.stringify({ evidence_id: evidenceId }, null, 2)}
                                </pre>
                              </Card>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="finding-meta">
                        <span>判定引擎: {finding.judgment_engine}</span>
                        {finding.confidence && <span>置信度: {(finding.confidence * 100).toFixed(0)}%</span>}
                        <span>发现时间: {new Date(finding.created_at).toLocaleString()}</span>
                      </div>
                    </div>
                  </Panel>
                ))}
              </Collapse>
            )}
          </Card>
        </Content>
      </Layout>
    </Layout>
  )
}

export default ScanResults
