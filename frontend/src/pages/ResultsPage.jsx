import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Layout, Card, Table, Tag, Space, Button, Typography, Spin, Empty, Progress, Select, Popconfirm, message } from 'antd'
import { 
  ArrowLeftOutlined, 
  ScanOutlined, 
  CheckCircleOutlined, 
  CloseCircleOutlined,
  WarningOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import './ResultsPage.css'

const { Header, Content } = Layout
const { Title, Text } = Typography

function ResultsPage() {
  const navigate = useNavigate()
  const { projectId } = useParams()
  const [scanTasks, setScanTasks] = useState([])
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('completed')

  useEffect(() => {
    fetchData()
  }, [projectId])

  const fetchData = async () => {
    setLoading(true)
    try {
      // 获取项目信息
      const projectRes = await api.get(`/projects/${projectId}`)
      setProject(projectRes.data)

      // 获取扫描任务列表
      const scansRes = await api.get(`/results/projects/${projectId}/scans`)
      setScanTasks(scansRes.data)
    } catch (error) {
      console.error('Failed to fetch data:', error)
    } finally {
      setLoading(false)
    }
  }

  const getStatusTag = (status) => {
    const statusMap = {
      completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
      running: { color: 'processing', icon: <ScanOutlined spin />, text: '运行中' },
      pending: { color: 'default', icon: <ClockCircleOutlined />, text: '等待中' },
      failed: { color: 'error', icon: <CloseCircleOutlined />, text: '失败' },
    }
    const config = statusMap[status] || statusMap.pending
    return (
      <Tag color={config.color} icon={config.icon}>
        {config.text}
      </Tag>
    )
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

  const filteredTasks = statusFilter === 'all' 
    ? scanTasks 
    : scanTasks.filter(t => t.status === statusFilter)

  const handleDeleteScan = async (scanTaskId) => {
    try {
      await api.delete(`/results/scans/${scanTaskId}`)
      message.success('扫描任务已删除')
      fetchData()
    } catch (error) {
      console.error('Failed to delete scan:', error)
      message.error(error.response?.data?.detail || '删除失败')
    }
  }

  const columns = [
    {
      title: '扫描任务',
      dataIndex: 'id',
      key: 'id',
      render: (id, record) => {
        const taskTypeMap = {
          full: '全量扫描',
          incremental: '增量扫描',
          targeted: '定向扫描',
          scheduled: '定时扫描',
        }
        return (
          <div>
            <div style={{ fontWeight: 600 }}>#{id} {taskTypeMap[record.task_type] || '扫描'}</div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.findings_count > 0 ? `${record.findings_count} 项发现` : '无发现'}
            </Text>
          </div>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status) => getStatusTag(status),
    },
    {
      title: '风险发现',
      key: 'findings',
      render: (_, record) => {
        if (record.findings_count === 0) {
          return <Text type="secondary">-</Text>
        }
        return (
          <Space>
            {record.high_severity_count > 0 && (
              <Tag color="error" icon={<WarningOutlined />}>
                {record.high_severity_count} 高危
              </Tag>
            )}
            {record.medium_severity_count > 0 && (
              <Tag color="warning">
                {record.medium_severity_count} 中危
              </Tag>
            )}
            {record.low_severity_count > 0 && (
              <Tag color="default">
                {record.low_severity_count} 低危
              </Tag>
            )}
          </Space>
        )
      },
    },
    {
      title: '合规分数',
      key: 'score',
      render: (_, record) => {
        if (record.status !== 'completed') return '-'
        const score = project?.compliance_score
        if (score === null || score === undefined) return '-'
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Progress 
              type="circle" 
              percent={score} 
              size={40}
              strokeColor={score >= 90 ? '#52c41a' : score >= 75 ? '#1890ff' : score >= 60 ? '#faad14' : '#ff4d4f'}
              format={() => score}
            />
          </div>
        )
      },
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date) => new Date(date).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button 
            type="link" 
            onClick={() => navigate(`/projects/${projectId}/results/${record.id}`)}
          >
            查看详情
          </Button>
          <Popconfirm
            title="确认删除"
            description="删除后无法恢复，确定要删除这个扫描任务吗？"
            onConfirm={() => handleDeleteScan(record.id)}
            okText="确定"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  if (loading) {
    return (
      <Layout className="results-page">
        <Content className="results-content">
          <Spin size="large" />
        </Content>
      </Layout>
    )
  }

  return (
    <Layout className="results-page">
      <Header className="results-header">
        <div className="header-left">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
            className="back-btn"
          />
          <div>
            <Title level={3} style={{ margin: 0, color: '#fff' }}>
              {project?.name || '项目'} - 扫描结果
            </Title>
            <Text style={{ color: 'rgba(255,255,255,0.6)' }}>
              等保{project?.compliance_level || '三级'}合规检测
            </Text>
          </div>
        </div>
        <div className="header-right">
          {project?.compliance_score !== null && (
            <div className="compliance-score">
              <Text style={{ color: 'rgba(255,255,255,0.8)' }}>合规分数：</Text>
              <Progress 
                type="circle" 
                percent={project.compliance_score} 
                size={50}
                strokeColor={project.compliance_score >= 90 ? '#52c41a' : project.compliance_score >= 75 ? '#1890ff' : project.compliance_score >= 60 ? '#faad14' : '#ff4d4f'}
                format={() => project.compliance_score}
              />
            </div>
          )}
        </div>
      </Header>

      <Content className="results-content">
        {/* Summary Cards */}
        {scanTasks.length > 0 && (
          <div className="results-summary">
            <Card size="small" className="summary-card">
              <div className="summary-label">总扫描数</div>
              <div className="summary-value">{scanTasks.length}</div>
            </Card>
            <Card size="small" className="summary-card">
              <div className="summary-label">已完成</div>
              <div className="summary-value" style={{ color: '#52c41a' }}>{scanTasks.filter(t => t.status === 'completed').length}</div>
            </Card>
            <Card size="small" className="summary-card">
              <div className="summary-label">风险发现</div>
              <div className="summary-value" style={{ color: scanTasks.reduce((a, t) => a + t.high_severity_count, 0) > 0 ? '#ff4d4f' : '#52c41a' }}>
                {scanTasks.reduce((a, t) => a + t.findings_count, 0)}
              </div>
            </Card>
          </div>
        )}
        
        <Card
          title="扫描任务列表"
          extra={
            <Space>
              <Select
                value={statusFilter}
                onChange={setStatusFilter}
                style={{ width: 120 }}
                options={[
                  { value: 'completed', label: '已完成' },
                  { value: 'all', label: '全部' },
                  { value: 'running', label: '运行中' },
                  { value: 'failed', label: '失败' },
                ]}
              />
              <Button 
                type="primary" 
                icon={<ScanOutlined />}
                onClick={() => navigate('/')}
              >
                新建扫描
              </Button>
            </Space>
          }
        >
          {filteredTasks.length === 0 ? (
            <Empty description={statusFilter === 'completed' ? '暂无已完成的扫描任务' : '暂无扫描任务'}>
              <Button type="primary" onClick={() => navigate('/')}>
                去扫描
              </Button>
            </Empty>
          ) : (
            <Table
              columns={columns}
              dataSource={filteredTasks}
              rowKey="id"
              pagination={{
                showSizeChanger: true,
                showQuickJumper: true,
                pageSizeOptions: ['10', '20', '50'],
                defaultPageSize: 10,
                showTotal: (total) => `共 ${total} 条`,
              }}
            />
          )}
        </Card>
      </Content>
    </Layout>
  )
}

export default ResultsPage
