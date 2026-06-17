import { useState, useEffect } from 'react'
import { Select, Tooltip, Button, Space } from 'antd'
import { SettingOutlined, RobotOutlined } from '@ant-design/icons'
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

  return (
    <div className="model-selector">
      <Select
        value={selectedModel}
        onChange={handleChange}
        loading={loading}
        placeholder="选择模型"
        className="model-select"
        dropdownClassName="model-select-dropdown"
        suffixIcon={<RobotOutlined />}
      >
        {models.map(model => (
          <Option key={model.id} value={model.id}>
            <div className="model-option">
              <div className="model-option-header">
                <span className="model-name">{model.display_name}</span>
                {model.is_default && <span className="model-badge">默认</span>}
              </div>
              <div className="model-option-meta">
                <span className="model-provider">{model.provider_name}</span>
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
