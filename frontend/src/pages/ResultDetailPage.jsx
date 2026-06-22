import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Layout, Card, Table, Tag, Space, Button, Typography, Spin, Empty, Descriptions, Collapse, List } from 'antd'
import { 
  ArrowLeftOutlined, 
  CheckCircleOutlined, 
  CloseCircleOutlined,
  WarningOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import './ResultDetailPage.css'

const { Header, Content } = Layout
const { Title, Text, Paragraph } = Typography
const { Panel } = Collapse

function ResultDetailPage() {
  const navigate = useNavigate()
  const { projectId, scanTaskId } = useParams()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchSummary()
  }, [scanTaskId])

  const fetchSummary = async () => {
    setLoading(true)
    try {
      const response = await api.get(`/results/scans/${scanTaskId}/summary`)
      setSummary(response.data)
    } catch (error) {
      console.error('Failed to fetch summary:', error)
    } finally {
      setLoading(false)
    }
  }

  const getSeverityColor = (severity) => {
    const colorMap = {
      critical: '#ff4d4f',
      high: '#ff7a45',
      medium: '#ffa940',
      low: '#ffc53d',
      info: '#1890ff',
    }
    return colorMap[severity] || '#d9d9d9'
  }

  const getJudgmentTag = (judgment) => {
    const judgmentMap = {
      pass: { color: 'success', icon: <CheckCircleOutlined />, text: '通过' },
      fail: { color: 'error', icon: <CloseCircleOutlined />, text: '不通过' },
      partial: { color: 'warning', icon: <WarningOutlined />, text: '部分通过' },
      not_tested: { color: 'default', text: '未测试' },
    }
    const config = judgmentMap[judgment] || judgmentMap.not_tested
    return (
      <Tag color={config.color} icon={config.icon}>
        {config.text}
      </Tag>
    )
  }

  const findingColumns = [
    {
      title: '条款',
      dataIndex: 'clause_id',
      key: 'clause_id',
      render: (id, record) => (
        <div>
          <div style={{ fontWeight: 600 }}>{id}</div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.clause_name}
          </Text>
        </div>
      ),
    },
    {
      title: '严重性',
      dataIndex: 'severity',
      key: 'severity',
      render: (severity) => (
        <Tag color={getSeverityColor(severity)}>
          {severity.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: '判定',
      dataIndex: 'judgment',
      key: 'judgment',
      render: (judgment) => getJudgmentTag(judgment),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      render: (desc) => desc || '-',
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Button 
          type="link" 
          icon={<FileTextOutlined />}
          onClick={() => navigate(`/projects/${projectId}/findings/${record.id}`)}
        >
          查看证据
        </Button>
      ),
    },
  ]

  if (loading) {
    return (
      <Layout className="result-detail-page">
        <Content className="result-detail-content">
          <Spin size="large" />
        </Content>
      </Layout>
    )
  }

  if (!summary) {
    return (
      <Layout className="result-detail-page">
        <Content className="result-detail-content">
          <Empty description="未找到扫描结果" />
        </Content>
      </Layout>
    )
  }

  return (
    <Layout className="result-detail-page">
      <Header className="result-detail-header">
        <div className="header-left">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate(`/projects/${projectId}/results`)}
            className="back-btn"
          />
          <div>
            <Title level={3} style={{ margin: 0, color: '#fff' }}>
              扫描任务 #{summary.scan_task.id}
            </Title>
            <Text style={{ color: 'rgba(255,255,255,0.6)' }}>
              {summary.scan_task.parameters?.target || '未知目标'}
            </Text>
          </div>
        </div>
      </Header>

      <Content className="result-detail-content">
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          {/* 扫描任务信息 */}
          <Card title="扫描任务信息">
            <Descriptions column={2}>
              <Descriptions.Item label="任务类型">
                {summary.scan_task.task_type === 'full' ? '全量扫描' : '定向扫描'}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={summary.scan_task.status === 'completed' ? 'success' : 'processing'}>
                  {summary.scan_task.status === 'completed' ? '已完成' : '运行中'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="扫描目标">
                {summary.scan_task.parameters?.target || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="扫描类型">
                {summary.scan_task.parameters?.scan_type || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {new Date(summary.scan_task.created_at).toLocaleString('zh-CN')}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间">
                {summary.scan_task.completed_at 
                  ? new Date(summary.scan_task.completed_at).toLocaleString('zh-CN')
                  : '-'}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 统计信息 */}
          <Card title="检测结果统计">
            <div className="stats-grid">
              <div className="stat-item">
                <div className="stat-value">{summary.total_findings}</div>
                <div className="stat-label">总发现</div>
              </div>
              <div className="stat-item pass">
                <div className="stat-value">{summary.passed}</div>
                <div className="stat-label">通过</div>
              </div>
              <div className="stat-item fail">
                <div className="stat-value">{summary.failed}</div>
                <div className="stat-label">不通过</div>
              </div>
              <div className="stat-item partial">
                <div className="stat-value">{summary.partial}</div>
                <div className="stat-label">部分通过</div>
              </div>
              <div className="stat-item score">
                <div className="stat-value">{summary.compliance_score || 0}</div>
                <div className="stat-label">合规分数</div>
              </div>
            </div>
          </Card>

          {/* 发现列表 */}
          <Card title="发现详情">
            {summary.findings.length === 0 ? (
              <Empty description="未发现任何问题" />
            ) : (
              <Table
                columns={findingColumns}
                dataSource={summary.findings}
                rowKey="id"
                pagination={false}
              />
            )}
          </Card>
        </Space>
      </Content>
    </Layout>
  )
}

export default ResultDetailPage
