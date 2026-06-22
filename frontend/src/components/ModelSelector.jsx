import { useState, useEffect } from 'react'
import { Select, Tooltip, Button, Space, Tag } from 'antd'
import { SettingOutlined, RobotOutlined, CheckOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import './ModelSelector.css'

const { Option } = Select

function ModelSelector({ value, onChange }) {
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedModel, setSelectedModel] = useState(value)
  const navigate = useNavigate()

  useEffect(() => {
    fetchAvailableModels()
  }, [])

  useEffect(() => {
    if (value !== undefined) {
      setSelectedModel(value)
    }
  }, [value])

  const fetchAvailableModels = async () => {
    setLoading(true)
    try {
      const response = await api.get('/models/available')
      setModels(response.data)
      
      // If no model selected, select the default one
      if (!selectedModel && response.data.length > 0) {
        const defaultModel = response.data.find(m => m.is_default) || response.data[0]
        setSelectedModel(defaultModel.id)
        if (onChange) {
          onChange(defaultModel.id)
        }
      }
    } catch (error) {
      console.error('Failed to fetch models:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleChange = (modelId) => {
    setSelectedModel(modelId)
    if (onChange) {
      onChange(modelId)
    }
  }

  const handleSettingsClick = () => {
    navigate('/settings/models')
  }

  const currentModel = models.find(m => m.id === selectedModel)

  // 自定义选中项显示
  const renderSelectedModel = () => {
    if (!currentModel) return <span style={{ color: 'rgba(255,255,255,0.5)' }}>选择模型</span>
    return (
      <div className="model-selected-display">
        <RobotOutlined style={{ marginRight: 6, color: '#6366f1' }} />
        <span className="model-selected-name">{currentModel.display_name}</span>
        {currentModel.is_default && (
          <Tag color="purple" style={{ marginLeft: 6, fontSize: 10, padding: '0 4px', lineHeight: '16px', height: 18 }}>默认</Tag>
        )}
      </div>
    )
  }

  return (
    <div className="model-selector">
      <Select
        value={selectedModel}
        onChange={handleChange}
        loading={loading}
        placeholder="选择模型"
        className="model-select"
        popupClassName="model-select-dropdown"
        suffixIcon={<SettingOutlined style={{ color: 'rgba(255,255,255,0.5)' }} />}
        optionLabelProp="label"
      >
        {models.map(model => (
          <Option key={model.id} value={model.id} label={model.display_name}>
            <div className="model-option">
              <div className="model-option-header">
                <RobotOutlined style={{ color: '#6366f1', marginRight: 8 }} />
                <span className="model-name">{model.display_name}</span>
                {model.is_default && <Tag color="purple" style={{ marginLeft: 8, fontSize: 10, padding: '0 4px', lineHeight: '16px', height: 18 }}>默认</Tag>}
              </div>
              <div className="model-option-meta">
                <span className="model-provider">{model.provider_name}</span>
                {model.capabilities && model.capabilities.length > 0 && (
                  <span className="model-capabilities">
                    {model.capabilities.slice(0, 2).map(cap => (
                      <Tag key={cap} style={{ fontSize: 10, padding: '0 4px', lineHeight: '16px', height: 18, marginRight: 4 }}>
                        {cap}
                      </Tag>
                    ))}
                  </span>
                )}
              </div>
            </div>
          </Option>
        ))}
      </Select>
      
      <Tooltip title="模型设置">
        <Button
          type="text"
          icon={<SettingOutlined />}
          onClick={handleSettingsClick}
          className="model-settings-btn"
        />
      </Tooltip>
    </div>
  )
}

export default ModelSelector
