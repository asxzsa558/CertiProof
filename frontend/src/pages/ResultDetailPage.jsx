import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Layout, Card, Table, Tag, Space, Button, Typography, Spin, Empty, Descriptions, Collapse, List, Modal, message } from 'antd'
import { 
  ArrowLeftOutlined, 
  CheckCircleOutlined, 
  CloseCircleOutlined,
  WarningOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { scanTaskConclusion, scanTaskName, scanTaskSource, scanTaskTarget } from '../components/toolCatalog'
import { severityLabel } from '../components/resultRendererUtils'
import './ResultDetailPage.css'

const { Header, Content } = Layout
const { Title, Text, Paragraph } = Typography
const { Panel } = Collapse

function ResultDetailPage() {
  const navigate = useNavigate()
  const { projectId, scanTaskId } = useParams()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [findingDetail, setFindingDetail] = useState(null)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [evidenceLoading, setEvidenceLoading] = useState(false)

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

  const showFindingEvidence = async (finding) => {
    setFindingDetail(finding)
    setEvidenceOpen(true)
    setEvidenceLoading(true)
    try {
      const response = await api.get(`/results/findings/${finding.id}`)
      setFindingDetail(response.data)
    } catch (error) {
      message.error(error.response?.data?.detail || '加载问题证据失败')
    } finally {
      setEvidenceLoading(false)
    }
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
          {severityLabel(severity)}
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
          onClick={() => showFindingEvidence(record)}
        >
          问题与证据
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

  const conclusion = scanTaskConclusion(summary.scan_task)
  const executionIssues = [
    ...(summary.scan_task.result_summary?.warnings || []),
    ...(summary.scan_task.result_summary?.failed || []),
  ]

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
          <div className="result-detail-title-block">
            <Title level={3} className="result-detail-title">检测结果详情</Title>
            <span className="result-detail-context">
              {scanTaskName(summary.scan_task)} · 记录 #{summary.scan_task.id}
            </span>
          </div>
        </div>
      </Header>

      <Content className="result-detail-content">
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Card title="检测执行信息">
            <Descriptions column={{ xs: 1, md: 2 }}>
              <Descriptions.Item label="检测内容">
                {scanTaskName(summary.scan_task)}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={summary.scan_task.status === 'completed' ? 'success' : 'processing'}>
                  {summary.scan_task.status === 'completed' ? '已完成' : '运行中'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="目标资产">
                {scanTaskTarget(summary.scan_task)}
              </Descriptions.Item>
              <Descriptions.Item label="执行来源">
                {scanTaskSource(summary.scan_task)}
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
              <div className={`stat-item ${conclusion.key}`}>
                <div className="stat-value">{executionIssues.length}</div>
                <div className="stat-label">未完成项</div>
              </div>
            </div>
          </Card>

          {executionIssues.length ? (
            <Card title="未完成检测说明">
              <List
                dataSource={executionIssues}
                renderItem={(item) => <List.Item><strong>{item.capability || '检测工具'}</strong><span>{item.error || item.message || '未返回具体原因'}</span></List.Item>}
              />
            </Card>
          ) : null}

          {/* 发现列表 */}
          <Card title="发现详情">
            {summary.findings.length === 0 ? (
              <Empty description={conclusion.key === 'warning' ? '本次未形成风险发现，但存在未完成检测，请查看上方说明' : conclusion.key === 'skipped' ? '目标未启用该类服务，本项不适用' : '本次未发现安全问题'} />
            ) : (
              <Table
                columns={findingColumns}
                dataSource={summary.findings}
                rowKey="id"
                pagination={false}
                scroll={{ x: 860 }}
              />
            )}
          </Card>
        </Space>
      </Content>
      <Modal
        title={findingDetail?.clause_name || '问题与证据'}
        open={evidenceOpen}
        onCancel={() => setEvidenceOpen(false)}
        footer={<Button onClick={() => setEvidenceOpen(false)}>关闭</Button>}
        width={760}
      >
        <Spin spinning={evidenceLoading}>
          {findingDetail ? (
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="问题描述">{findingDetail.description || '-'}</Descriptions.Item>
                <Descriptions.Item label="整改建议">{findingDetail.remediation_suggestion || '暂无整改建议'}</Descriptions.Item>
              </Descriptions>
              {(findingDetail.evidences?.length || findingDetail.document_evidences?.length) ? (
                <Collapse>
                  {findingDetail.evidences.map((evidence) => (
                    <Panel header={evidence.file_name || evidence.source || `证据 #${evidence.id}`} key={evidence.id}>
                      <Paragraph className="evidence-meta">来源：{evidence.source || '-'} · 类型：{evidence.evidence_type} · SHA-256：{evidence.hash_sha256 || '-'}</Paragraph>
                      <pre className="evidence-content">{evidence.raw_output || (evidence.content ? JSON.stringify(evidence.content, null, 2) : evidence.description || '该证据没有可预览的文本内容')}</pre>
                    </Panel>
                  ))}
                  {(findingDetail.document_evidences || []).map((evidence) => (
                    <Panel
                      header={`${evidence.file_name || '文档证据'}${evidence.page ? ` · 第 ${evidence.page} 页` : ''}`}
                      key={`block-${evidence.block_id}`}
                    >
                      <Paragraph className="evidence-meta">
                        来源：{evidence.source || '-'} · 类型：{evidence.type || '-'}
                        {evidence.section?.length ? ` · 章节：${evidence.section.join(' / ')}` : ''}
                        {' '}· 置信度：{Math.round((evidence.confidence || 0) * 100)}%
                      </Paragraph>
                      <pre className="evidence-content">{evidence.text || '该内容块没有可预览文本'}</pre>
                    </Panel>
                  ))}
                </Collapse>
              ) : (
                <Empty description="暂无独立证据文件；该问题依据本次工具输出生成" />
              )}
            </Space>
          ) : null}
        </Spin>
      </Modal>
    </Layout>
  )
}

export default ResultDetailPage
