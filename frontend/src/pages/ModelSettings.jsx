import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Card, Button, Table, Space, Tag, Modal, Form, Input, Select, Switch, message, Popconfirm, Tabs, Statistic, Row, Col } from 'antd'
import {
  ArrowLeftOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ApiOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DollarOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import './ModelSettings.css'

const { Header, Content } = Layout
const { TabPane } = Tabs

function ModelSettings() {
  const navigate = useNavigate()
  const [providers, setProviders] = useState([])
  const [models, setModels] = useState([])
  const [usage, setUsage] = useState([])
  const [loading, setLoading] = useState(false)
  const [providerModalVisible, setProviderModalVisible] = useState(false)
  const [modelModalVisible, setModelModalVisible] = useState(false)
  const [editingProvider, setEditingProvider] = useState(null)
  const [editingModel, setEditingModel] = useState(null)
  const [providerForm] = Form.useForm()
  const [modelForm] = Form.useForm()
  const lastProjectId = localStorage.getItem('lastProjectId')
  const returnToWorkspace = () => navigate(lastProjectId ? `/projects/${lastProjectId}` : '/projects')

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [providersRes, modelsRes, usageRes] = await Promise.all([
        api.get('/models/providers'),
        api.get('/models/configs'),
        api.get('/models/usage'),
      ])
      setProviders(providersRes.data)
      setModels(modelsRes.data)
      setUsage(usageRes.data)
    } catch (error) {
      message.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }

  const handleCreateProvider = () => {
    setEditingProvider(null)
    providerForm.resetFields()
    setProviderModalVisible(true)
  }

  const handleEditProvider = (provider) => {
    setEditingProvider(provider)
    providerForm.setFieldsValue(provider)
    setProviderModalVisible(true)
  }

  const handleDeleteProvider = async (id) => {
    try {
      await api.delete(`/models/providers/${id}`)
      message.success('删除成功')
      fetchData()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handleSubmitProvider = async () => {
    try {
      const values = await providerForm.validateFields()
      if (editingProvider) {
        await api.put(`/models/providers/${editingProvider.id}`, values)
        message.success('更新成功')
      } else {
        await api.post('/models/providers', values)
        message.success('创建成功')
      }
      setProviderModalVisible(false)
      fetchData()
    } catch (error) {
      message.error(error.response?.data?.detail || '操作失败')
    }
  }

  const handleCreateModel = () => {
    setEditingModel(null)
    modelForm.resetFields()
    setModelModalVisible(true)
  }

  const handleEditModel = (model) => {
    setEditingModel(model)
    modelForm.setFieldsValue(model)
    setModelModalVisible(true)
  }

  const handleDeleteModel = async (id) => {
    try {
      await api.delete(`/models/configs/${id}`)
      message.success('删除成功')
      fetchData()
    } catch (error) {
      message.error('删除失败')
    }
  }

  const handleSubmitModel = async () => {
    try {
      const values = await modelForm.validateFields()
      if (editingModel) {
        await api.put(`/models/configs/${editingModel.id}`, values)
        message.success('更新成功')
      } else {
        await api.post('/models/configs', values)
        message.success('创建成功')
      }
      setModelModalVisible(false)
      fetchData()
    } catch (error) {
      message.error(error.response?.data?.detail || '操作失败')
    }
  }

  const handleTestModel = async (id) => {
    try {
      const response = await api.post(`/models/configs/${id}/test`)
      if (response.data.success) {
        message.success('连接测试成功')
      } else {
        message.error(`连接失败: ${response.data.error || '请检查 API Key 和 API Base 配置'}`)
      }
    } catch (error) {
      message.error(error.response?.data?.error || error.response?.data?.detail || '测试请求失败')
    }
  }

  const providerColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '类型',
      dataIndex: 'provider_type',
      key: 'provider_type',
      render: (type) => <Tag color="blue">{type}</Tag>,
    },
    {
      title: 'API Base',
      dataIndex: 'api_base',
      key: 'api_base',
      render: (url) => url || '默认',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => (
        <Tag color={active ? 'success' : 'default'}>
          {active ? '已启用' : '已禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEditProvider(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此提供商？" onConfirm={() => handleDeleteProvider(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const modelColumns = [
    {
      title: '模型名称',
      dataIndex: 'display_name',
      key: 'display_name',
      render: (name, record) => (
        <div>
          <div style={{ fontWeight: 600 }}>{name}</div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>{record.model_name}</div>
        </div>
      ),
    },
    {
      title: '提供商',
      key: 'provider',
      render: (_, record) => record.provider?.name || '-',
    },
    {
      title: '能力',
      dataIndex: 'capabilities',
      key: 'capabilities',
      render: (caps) => (
        <Space>
          {caps?.map(cap => (
            <Tag key={cap} color="purple">{cap}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      key: 'is_default',
      render: (isDefault) => isDefault ? <Tag color="gold">默认</Tag> : null,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => (
        <Tag color={active ? 'success' : 'default'}>
          {active ? '已启用' : '已禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => handleTestModel(record.id)}>
            测试
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEditModel(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此模型？" onConfirm={() => handleDeleteModel(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const usageColumns = [
    {
      title: '模型',
      dataIndex: 'display_name',
      key: 'display_name',
    },
    {
      title: '调用次数',
      dataIndex: 'total_calls',
      key: 'total_calls',
    },
    {
      title: '输入 Tokens',
      dataIndex: 'total_prompt_tokens',
      key: 'total_prompt_tokens',
      render: (tokens) => tokens?.toLocaleString() || 0,
    },
    {
      title: '输出 Tokens',
      dataIndex: 'total_completion_tokens',
      key: 'total_completion_tokens',
      render: (tokens) => tokens?.toLocaleString() || 0,
    },
  ]

  return (
    <Layout className="model-settings-layout">
      <Header className="model-settings-header">
        <div className="header-left">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={returnToWorkspace}
            className="back-btn"
          >
            返回项目对话
          </Button>
          <h1>模型配置</h1>
        </div>
      </Header>

      <Content className="model-settings-content">
        <Tabs defaultActiveKey="providers" className="settings-tabs">
          <TabPane tab="模型提供商" key="providers">
            <Card
              title="模型提供商"
              extra={
                <Button type="primary" className="provider-add-button" icon={<PlusOutlined />} onClick={handleCreateProvider}>
                  添加提供商
                </Button>
              }
            >
              <Table
                columns={providerColumns}
                dataSource={providers}
                rowKey="id"
                loading={loading}
                pagination={false}
              />
            </Card>
          </TabPane>

          <TabPane tab="模型配置" key="models">
            <Card
              title="模型配置"
              extra={
                <Button type="primary" icon={<PlusOutlined />} onClick={handleCreateModel}>
                  添加模型
                </Button>
              }
            >
              <Table
                columns={modelColumns}
                dataSource={models}
                rowKey="id"
                loading={loading}
                pagination={false}
              />
            </Card>
          </TabPane>

          <TabPane tab="使用统计" key="usage">
            <Card title="使用统计">
              <Row gutter={16} style={{ marginBottom: 24 }}>
                <Col span={8}>
                  <Card>
                    <Statistic
                      title="总调用次数"
                      value={usage.reduce((sum, u) => sum + u.total_calls, 0)}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card>
                    <Statistic
                      title="总 Tokens"
                      value={usage.reduce((sum, u) => sum + u.total_prompt_tokens + u.total_completion_tokens, 0)}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card>
                    <Statistic
                      title="模型数量"
                      value={models.length}
                    />
                  </Card>
                </Col>
              </Row>

              <Table
                columns={usageColumns}
                dataSource={usage}
                rowKey="model_name"
                loading={loading}
                pagination={false}
              />
            </Card>
          </TabPane>
        </Tabs>
      </Content>

      {/* Provider Modal */}
      <Modal
        title={editingProvider ? '编辑提供商' : '添加提供商'}
        open={providerModalVisible}
        onOk={handleSubmitProvider}
        onCancel={() => setProviderModalVisible(false)}
      >
        <Form form={providerForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="例如：OpenAI" />
          </Form.Item>
          <Form.Item name="provider_type" label="类型" rules={[{ required: true }]}>
            <Select placeholder="选择类型">
              <Select.Option value="openai">OpenAI</Select.Option>
              <Select.Option value="anthropic">Anthropic</Select.Option>
              <Select.Option value="ollama">Ollama (本地)</Select.Option>
              <Select.Option value="azure">Azure OpenAI</Select.Option>
              <Select.Option value="custom">自定义</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="api_key" label="API Key">
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item name="api_base" label="API Base URL">
            <Input placeholder="https://api.openai.com/v1 (可选)" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Model Modal */}
      <Modal
        title={editingModel ? '编辑模型' : '添加模型'}
        open={modelModalVisible}
        onOk={handleSubmitModel}
        onCancel={() => setModelModalVisible(false)}
      >
        <Form form={modelForm} layout="vertical">
          <Form.Item name="provider_id" label="提供商" rules={[{ required: true }]}>
            <Select placeholder="选择提供商">
              {providers.map(p => (
                <Select.Option key={p.id} value={p.id}>{p.name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="model_name" label="模型名称" rules={[{ required: true }]}>
            <Input placeholder="例如：gpt-4-turbo-preview" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="例如：GPT-4 Turbo" />
          </Form.Item>
          <Form.Item name="capabilities" label="能力">
            <Select mode="multiple" placeholder="选择能力">
              <Select.Option value="chat">对话</Select.Option>
              <Select.Option value="vision">视觉</Select.Option>
              <Select.Option value="code">代码</Select.Option>
              <Select.Option value="embedding">文本向量</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="max_tokens" label="最大 Tokens">
            <Input type="number" placeholder="4096" />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Input type="number" placeholder="1 (数字越小优先级越高)" />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default ModelSettings
