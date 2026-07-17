import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Layout, Card, Table, Tag, Space, Button, Typography, Spin, Empty, Progress, Select, Popconfirm, message } from 'antd'
import { 
  ArrowLeftOutlined, 
  ScanOutlined, 
  CheckCircleOutlined, 
  CloseCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { scanTaskConclusion, scanTaskName, scanTaskSource, scanTaskTarget } from '../components/toolCatalog'
import './ResultsPage.css'

const { Header, Content } = Layout
const { Title, Text } = Typography
const activeStatuses = new Set(['pending', 'running'])

const formatBytes = (bytes) => {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`
}

function ResultsPage() {
  const navigate = useNavigate()
  const { projectId } = useParams()
  const [scanTasks, setScanTasks] = useState([])
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('all')
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [deleting, setDeleting] = useState(false)

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

  const filteredTasks = statusFilter === 'all' 
    ? scanTasks 
    : scanTasks.filter(t => t.status === statusFilter)

  const handleDeleteScan = async (scanTaskId) => {
    try {
      await api.delete(`/results/scans/${scanTaskId}`)
      message.success('检测记录已删除')
      setScanTasks((tasks) => tasks.filter((task) => task.id !== scanTaskId))
      setSelectedRowKeys((keys) => keys.filter((id) => id !== scanTaskId))
    } catch (error) {
      console.error('Failed to delete scan:', error)
      message.error(error.response?.data?.detail || '删除失败')
    }
  }

  const handleBulkDelete = async (deleteAll = false) => {
    if (!deleteAll && selectedRowKeys.length === 0) return
    setDeleting(true)
    try {
      const { data } = await api.post(`/results/projects/${projectId}/scans/bulk-delete`, {
        scan_task_ids: deleteAll ? [] : selectedRowKeys,
        delete_all: deleteAll,
      })
      const deletedIds = new Set(data.deleted_ids || [])
      setScanTasks((tasks) => tasks.filter((task) => !deletedIds.has(task.id)))
      setSelectedRowKeys((keys) => keys.filter((id) => !deletedIds.has(id)))
      const released = formatBytes(data.released_file_bytes)
      message.success(`已删除 ${data.deleted_count} 条检测记录${released ? `，清理附件 ${released}` : ''}`)
      if (data.skipped_active_count) message.warning(`已保留 ${data.skipped_active_count} 条运行中或等待中的任务`)
    } catch (error) {
      console.error('Failed to bulk delete scans:', error)
      message.error(error.response?.data?.detail || '批量删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const columns = [
    {
      title: '检测内容',
      dataIndex: 'id',
      key: 'id',
      render: (id, record) => <div><div style={{ fontWeight: 600 }}>{scanTaskName(record)}</div><Text type="secondary" style={{ fontSize: 12 }}>记录 #{id}</Text></div>,
    },
    {
      title: '目标资产',
      key: 'target',
      render: (_, record) => scanTaskTarget(record),
    },
    {
      title: '执行来源',
      key: 'source',
      render: (_, record) => <Tag>{scanTaskSource(record)}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status) => getStatusTag(status),
    },
    {
      title: '检测结论',
      key: 'conclusion',
      render: (_, record) => {
        const conclusion = scanTaskConclusion(record)
        const colors = { failed: 'error', warning: 'warning', risk: 'error', clean: 'success', running: 'processing' }
        return <Tag color={colors[conclusion.key]}>{conclusion.label}</Tag>
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
            description="将同时删除关联发现、证据和整改记录，且无法恢复。"
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
            onClick={() => navigate(`/projects/${projectId}`)}
            className="back-btn"
          />
          <div className="results-title-block">
            <Title level={3} className="results-page-title">
              检测执行记录
            </Title>
            <span className="results-title-context">{project?.name || '当前项目'}</span>
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
              <div className="summary-label">执行记录</div>
              <div className="summary-value">{scanTasks.length}</div>
            </Card>
            <Card size="small" className="summary-card">
              <div className="summary-label">已完成</div>
              <div className="summary-value" style={{ color: '#52c41a' }}>{scanTasks.filter(t => t.status === 'completed').length}</div>
            </Card>
            <Card size="small" className="summary-card">
              <div className="summary-label">风险命中</div>
              <div className="summary-value" style={{ color: scanTasks.reduce((a, t) => a + t.high_severity_count, 0) > 0 ? '#ff4d4f' : '#52c41a' }}>
                {scanTasks.reduce((a, t) => a + t.findings_count, 0)}
              </div>
            </Card>
          </div>
        )}
        
        <Card
          title="检测执行记录"
          extra={
            <Space wrap className="results-toolbar">
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
              <Popconfirm
                title={`删除选中的 ${selectedRowKeys.length} 条记录？`}
                description="关联的检测结果、问题、证据和整改记录也会永久删除。"
                onConfirm={() => handleBulkDelete(false)}
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button danger icon={<DeleteOutlined />} disabled={!selectedRowKeys.length} loading={deleting}>
                  删除选中{selectedRowKeys.length ? ` (${selectedRowKeys.length})` : ''}
                </Button>
              </Popconfirm>
              <Popconfirm
                title="清空全部历史检测记录？"
                description="已完成、失败和已取消的记录及其关联数据将永久删除；运行中的任务会保留。"
                onConfirm={() => handleBulkDelete(true)}
                okText="清空"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button danger disabled={!scanTasks.some((task) => !activeStatuses.has(task.status))} loading={deleting}>
                  清空历史
                </Button>
              </Popconfirm>
              <Button 
                type="primary" 
                icon={<ScanOutlined />}
                onClick={() => navigate(`/projects/${projectId}`)}
              >
                执行检测
              </Button>
            </Space>
          }
        >
          {filteredTasks.length === 0 ? (
            <Empty description={statusFilter === 'completed' ? '暂无已完成的检测记录' : '暂无检测记录'}>
              <Button type="primary" onClick={() => navigate(`/projects/${projectId}`)}>
                执行检测
              </Button>
            </Empty>
          ) : (
            <Table
              columns={columns}
              dataSource={filteredTasks}
              rowKey="id"
              scroll={{ x: 980 }}
              rowSelection={{
                selectedRowKeys,
                onChange: setSelectedRowKeys,
                getCheckboxProps: (record) => ({ disabled: activeStatuses.has(record.status) }),
              }}
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
