import { useState, useEffect } from 'react'
import {
  Drawer, Tabs, Select, Button, Tooltip, Space, Tag, Input, Switch,
  Slider, Form, Divider, message, Spin
} from 'antd'
import {
  SettingOutlined, RobotOutlined, ThunderboltOutlined,
  FileProtectOutlined, ExperimentOutlined, SaveOutlined,
  ReloadOutlined, BulbOutlined, GlobalOutlined, FileTextOutlined
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import './SystemConfig.css'

const { Option } = Select
const { TabPane } = Tabs

function SystemConfig({ trigger, value, onChange }) {
  const [open, setOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('ai')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  // AI 模型
  const [models, setModels] = useState([])
  const [selectedModel, setSelectedModel] = useState(value)

  // 系统配置
  const [configs, setConfigs] = useState({})
  const [meta, setMeta] = useState({})
  const [pendingChanges, setPendingChanges] = useState({})

  const navigate = useNavigate()

  useEffect(() => {
    if (open) {
      fetchAll()
    }
  }, [open])

  useEffect(() => {
    if (value !== undefined) {
      setSelectedModel(value)
    }
  }, [value])

  const fetchAll = async () => {
    setLoading(true)
    try {
      const [modelsRes, configRes, metaRes] = await Promise.all([
        api.get('/models/available'),
        api.get('/config/'),
        api.get('/config/meta'),
      ])
      setModels(modelsRes.data)
      setConfigs(configRes.data)
      setMeta(metaRes.data)
      setPendingChanges({})
    } catch (error) {
      console.error('Failed to load config:', error)
      message.error('加载配置失败')
    } finally {
      setLoading(false)
    }
  }

  const handleModelChange = (modelId) => {
    setSelectedModel(modelId)
    if (onChange) onChange(modelId)
  }

  const handleConfigChange = (key, value) => {
    setPendingChanges(prev => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    if (Object.keys(pendingChanges).length === 0) {
      message.info('没有修改')
      return
    }
    setSaving(true)
    try {
      await api.put('/config/', { updates: pendingChanges })
      message.success(`已保存 ${Object.keys(pendingChanges).length} 项配置`)
      setPendingChanges({})
      const configRes = await api.get('/config/')
      setConfigs(configRes.data)
    } catch (error) {
      console.error('Failed to save config:', error)
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    setPendingChanges({})
  }

  const getCurrentValue = (key) => {
    if (key in pendingChanges) return pendingChanges[key]
    for (const category of Object.values(configs)) {
      if (key in category) return category[key]
    }
    return meta[key]?.value
  }

  // Section 标题组件 - 图标徽章 + 标题 + 副标题
  const SectionTitle = ({ icon, title, subtitle }) => (
    <div className="section-title">
      <div className="section-icon-badge">{icon}</div>
      <div className="section-title-text">
        <span className="title">{title}</span>
        {subtitle && <span className="subtitle">{subtitle}</span>}
      </div>
    </div>
  )

  // --- Tab 1: AI 模型 ---
  const renderModelTab = () => {
    const currentModel = models.find(m => m.id === selectedModel)
    return (
      <div className="config-tab-content">
        <div className="config-section">
          <SectionTitle
            icon={<RobotOutlined />}
            title="当前模型"
            subtitle="选择 AI 提供商和具体模型"
          />
          <Select
            value={selectedModel}
            onChange={handleModelChange}
            loading={loading}
            placeholder="选择模型"
            className="full-width-select"
            optionLabelProp="label"
          >
            {models.map(model => (
              <Option key={model.id} value={model.id} label={model.display_name}>
                <div className="model-option">
                  <div className="model-option-header">
                    <RobotOutlined style={{ color: '#C5A55A', marginRight: 8 }} />
                    <span className="model-name">{model.display_name}</span>
                    {model.is_default && <Tag color="gold" style={{ marginLeft: 8, fontSize: 10 }}>默认</Tag>}
                  </div>
                  <div className="model-option-meta">
                    <span className="model-provider">{model.provider_name}</span>
                  </div>
                </div>
              </Option>
            ))}
          </Select>
          {currentModel && (
            <div className="model-info-card">
              <div className="info-row">
                <span className="info-label">Provider</span>
                <span>{currentModel.provider_name}</span>
              </div>
              {currentModel.capabilities && (
                <div className="info-row">
                  <span className="info-label">能力</span>
                  <Space size={[4, 4]} wrap>
                    {currentModel.capabilities.slice(0, 5).map(cap => (
                      <Tag key={cap} style={{ fontSize: 10 }}>{cap}</Tag>
                    ))}
                  </Space>
                </div>
              )}
            </div>
          )}
          <Button
            type="link"
            icon={<SettingOutlined />}
            onClick={() => {
              setOpen(false)
              navigate('/settings/models')
            }}
            style={{ marginTop: 10, padding: 0, color: '#C5A55A' }}
          >
            管理模型配置 →
          </Button>
        </div>
      </div>
    )
  }

  // --- Tab 2: AI 行为 ---
  const renderAIBehaviorTab = () => {
    return (
      <div className="config-tab-content">
        <div className="config-section">
          <SectionTitle
            icon={<BulbOutlined />}
            title="对话记忆"
            subtitle="控制 AI 上下文的深度和广度"
          />
          <Form layout="vertical">
            <Form.Item
              label="历史对话轮次"
              help="每次 LLM 调用时携带的最近对话轮数（1-20）。越多越智能，但 token 也越多。"
            >
              <div className="slider-row">
                <Slider
                  min={1}
                  max={20}
                  value={getCurrentValue('ai.history_turns') || 5}
                  onChange={(v) => handleConfigChange('ai.history_turns', v)}
                  marks={{ 1: '1', 5: '5', 10: '10', 20: '20' }}
                />
                <span className="slider-value">{getCurrentValue('ai.history_turns') || 5}</span>
              </div>
            </Form.Item>
          </Form>
        </div>

        <div className="config-section">
          <SectionTitle
            icon={<ExperimentOutlined />}
            title="性能优化"
            subtitle="Prompt cache 和上下文注入"
          />
          <Form layout="vertical">
            <Form.Item
              label="启用 Prompt Cache"
              help="Anthropic 节省 90% 成本，OpenAI 自动 cache 无需配置。"
            >
              <Switch
                checked={getCurrentValue('ai.enable_cache') !== false}
                onChange={(v) => handleConfigChange('ai.enable_cache', v)}
              />
            </Form.Item>

            <Form.Item
              label="注入测评状态"
              help="在 prompt 中加入当前测评阶段和任务信息，让 AI 给出更精准建议。"
            >
              <Switch
                checked={getCurrentValue('ai.enable_assessment_context') !== false}
                onChange={(v) => handleConfigChange('ai.enable_assessment_context', v)}
              />
            </Form.Item>
          </Form>
        </div>
      </div>
    )
  }

  // --- Tab 3: 测评流程 ---
  const renderAssessmentTab = () => {
    return (
      <div className="config-tab-content">
        <div className="config-section">
          <SectionTitle
            icon={<FileProtectOutlined />}
            title="自动化行为"
            subtitle="创建测评后的默认动作"
          />
          <Form layout="vertical">
            <Form.Item
              label="创建后自动开始"
              help="测评创建后是否自动启动第一阶段。"
            >
              <Switch
                checked={getCurrentValue('assessment.auto_start') === true}
                onChange={(v) => handleConfigChange('assessment.auto_start', v)}
              />
            </Form.Item>

            <Form.Item
              label="自动执行扫描任务"
              help="是否自动执行 asset_discovery / vuln_scan 等扫描类任务。"
            >
              <Switch
                checked={getCurrentValue('assessment.auto_execute_tasks') !== false}
                onChange={(v) => handleConfigChange('assessment.auto_execute_tasks', v)}
              />
            </Form.Item>
          </Form>
        </div>

        <div className="config-section">
          <SectionTitle
            icon={<GlobalOutlined />}
            title="并发控制"
            subtitle="多资产同时扫描的性能参数"
          />
          <Form layout="vertical">
            <Form.Item
              label="最大并发数"
              help="多资产同时扫描时的最大并发数（1-10）。"
            >
              <div className="slider-row">
                <Slider
                  min={1}
                  max={10}
                  value={getCurrentValue('assessment.max_concurrent') || 5}
                  onChange={(v) => handleConfigChange('assessment.max_concurrent', v)}
                  marks={{ 1: '1', 5: '5', 10: '10' }}
                />
                <span className="slider-value">{getCurrentValue('assessment.max_concurrent') || 5}</span>
              </div>
            </Form.Item>
          </Form>
        </div>
      </div>
    )
  }

  // --- Tab 4: 报告 ---
  const renderReportTab = () => {
    return (
      <div className="config-tab-content">
        <div className="config-section">
          <SectionTitle
            icon={<FileTextOutlined />}
            title="报告格式"
            subtitle="默认导出的报告类型"
          />
          <Form layout="vertical">
            <Form.Item label="默认格式">
              <Select
                value={getCurrentValue('report.default_format') || 'pdf'}
                onChange={(v) => handleConfigChange('report.default_format', v)}
                className="full-width-select"
              >
                <Option value="pdf">PDF</Option>
                <Option value="json">JSON</Option>
              </Select>
            </Form.Item>
          </Form>
        </div>

        <div className="config-section">
          <SectionTitle
            icon={<FileTextOutlined />}
            title="报告内容"
            subtitle="控制报告详尽程度"
          />
          <Form layout="vertical">
            <Form.Item
              label="包含原始扫描数据"
              help="报告 PDF/JSON 中是否包含完整的扫描原始数据（端口列表、SSL 详情等）。"
            >
              <Switch
                checked={getCurrentValue('report.include_raw_scans') === true}
                onChange={(v) => handleConfigChange('report.include_raw_scans', v)}
              />
            </Form.Item>
          </Form>
        </div>
      </div>
    )
  }

  const unsavedCount = Object.keys(pendingChanges).length

  return (
    <>
      {trigger ? (
        <span onClick={() => setOpen(true)} style={{ display: 'inline-block' }}>
          {trigger}
        </span>
      ) : (
        <Tooltip title="系统配置">
          <Button
            type="text"
            icon={<SettingOutlined />}
            onClick={() => setOpen(true)}
            className="system-config-btn"
          />
        </Tooltip>
      )}

      <Drawer
        title={
          <div className="drawer-title">
            <SettingOutlined style={{ color: '#D4AF37', marginRight: 8 }} />
            <span>系统配置</span>
          </div>
        }
        placement="right"
        width={520}
        open={open}
        onClose={() => setOpen(false)}
        className="system-config-drawer"
        extra={
          unsavedCount > 0 && (
            <div className="unsaved-indicator">
              <div className="unsaved-dot" />
              <span>{unsavedCount} 项未保存</span>
            </div>
          )
        }
        footer={
          <div className="drawer-footer">
            <Button
              icon={<ReloadOutlined />}
              onClick={fetchAll}
              disabled={loading || saving}
            >
              刷新
            </Button>
            <Button
              onClick={handleReset}
              disabled={unsavedCount === 0 || saving}
            >
              撤销
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSave}
              loading={saving}
              disabled={unsavedCount === 0}
            >
              保存
            </Button>
          </div>
        }
      >
        {loading ? (
          <div className="config-loading">
            <Spin />
          </div>
        ) : (
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            tabPosition="top"
            className="config-tabs"
          >
            <TabPane tab={<span><RobotOutlined /> AI 模型</span>} key="ai">
              {renderModelTab()}
            </TabPane>
            <TabPane tab={<span><BulbOutlined /> AI 行为</span>} key="ai-behavior">
              {renderAIBehaviorTab()}
            </TabPane>
            <TabPane tab={<span><FileProtectOutlined /> 测评流程</span>} key="assessment">
              {renderAssessmentTab()}
            </TabPane>
            <TabPane tab={<span><FileTextOutlined /> 报告</span>} key="report">
              {renderReportTab()}
            </TabPane>
          </Tabs>
        )}
      </Drawer>
    </>
  )
}

export default SystemConfig
