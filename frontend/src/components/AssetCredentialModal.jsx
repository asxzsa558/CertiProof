import { useState, useEffect } from 'react'
import { Modal, Input, Radio, Checkbox, Tag, Button } from 'antd'
import {
  UserOutlined,
  LockOutlined,
  FileOutlined,
  WarningOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import './AssetCredentialModal.css'

function AssetCredentialModal({
  visible,
  assets,
  onConfirm,
  onCancel,
  title = '配置 SSH 凭据',
  description = '仅用于安全基线检查',
  defaultCredential = { username: 'root', password: '', key_file: '', port: 22 },
}) {
  const [defaultCred, setDefaultCred] = useState(defaultCredential)
  const [assetConfigs, setAssetConfigs] = useState({})
  const [selectedAssetIds, setSelectedAssetIds] = useState([])

  // 初始化资产配置
  useEffect(() => {
    if (visible && assets.length > 0) {
      const configs = {}
      const ids = []
      assets.forEach(asset => {
        configs[asset.id] = { mode: 'default' }
        ids.push(asset.id)
      })
      setAssetConfigs(configs)
      setSelectedAssetIds(ids)
    }
  }, [visible, assets])

  const handleModeChange = (assetId, mode) => {
    setAssetConfigs(prev => ({
      ...prev,
      [assetId]: { ...prev[assetId], mode },
    }))
  }

  const handleOverrideChange = (assetId, field, value) => {
    setAssetConfigs(prev => ({
      ...prev,
      [assetId]: { ...prev[assetId], [field]: value },
    }))
  }

  const handleToggleAsset = (assetId) => {
    setSelectedAssetIds(prev =>
      prev.includes(assetId)
        ? prev.filter(id => id !== assetId)
        : [...prev, assetId]
    )
  }

  const handleConfirm = () => {
    const result = assets
      .filter(asset => selectedAssetIds.includes(asset.id))
      .map(asset => {
        const config = assetConfigs[asset.id] || { mode: 'default' }
        let ssh_credential = null

        if (config.mode === 'default') {
          ssh_credential = {
            username: defaultCred.username,
            password: defaultCred.password,
            key_file: defaultCred.key_file,
            port: defaultCred.port,
          }
        } else if (config.mode === 'override') {
          ssh_credential = {
            username: config.username || defaultCred.username,
            password: config.password || '',
            key_file: config.key_file || '',
            port: config.port || defaultCred.port,
          }
        }
        // mode === 'skip' → ssh_credential = null

        return {
          id: asset.id,
          value: asset.value,
          type: asset.asset_type,
          name: asset.name,
          ssh_credential,
        }
      })

    onConfirm(result)
  }

  const getAssetTypeLabel = (type) => {
    const labels = { ip: 'IP', domain: '域名', cloud_resource: '云资源' }
    return labels[type] || type
  }

  return (
    <Modal
      title={
        <div className="credential-modal-title">
          <LockOutlined style={{ marginRight: 8, color: '#6366f1' }} />
          {title}
        </div>
      }
      open={visible}
      onCancel={onCancel}
      onOk={handleConfirm}
      okText="开始测评"
      cancelText="取消"
      width={680}
      className="asset-credential-modal"
      destroyOnClose
    >
      <div className="credential-modal-body">
        {/* 说明文字 */}
        <div className="credential-description">
          <span>{description}</span>
          <Tag color="blue" style={{ marginLeft: 8 }}>
            10 项检查中仅 1 项需要 SSH 凭据
          </Tag>
        </div>

        {/* 默认凭据 */}
        <div className="credential-section default-credential">
          <div className="credential-section-title">
            默认凭据
            <span className="credential-section-subtitle">
              （所有未单独配置的资产将使用此凭据）
            </span>
          </div>
          <div className="credential-inputs">
            <div className="credential-input-row">
              <div className="credential-input-group">
                <label>用户名</label>
                <Input
                  prefix={<UserOutlined />}
                  value={defaultCred.username}
                  onChange={(e) => setDefaultCred({ ...defaultCred, username: e.target.value })}
                  placeholder="root"
                />
              </div>
              <div className="credential-input-group">
                <label>密码</label>
                <Input.Password
                  prefix={<LockOutlined />}
                  value={defaultCred.password}
                  onChange={(e) => setDefaultCred({ ...defaultCred, password: e.target.value })}
                  placeholder="输入密码"
                />
              </div>
              <div className="credential-input-group small">
                <label>端口</label>
                <Input
                  type="number"
                  value={defaultCred.port}
                  onChange={(e) => setDefaultCred({ ...defaultCred, port: parseInt(e.target.value) || 22 })}
                  placeholder="22"
                />
              </div>
            </div>
            <div className="credential-input-row">
              <div className="credential-input-group full">
                <label>密钥文件路径（与密码二选一）</label>
                <Input
                  prefix={<FileOutlined />}
                  value={defaultCred.key_file}
                  onChange={(e) => setDefaultCred({ ...defaultCred, key_file: e.target.value })}
                  placeholder="/path/to/private_key"
                />
              </div>
            </div>
          </div>
        </div>

        {/* 资产列表 */}
        <div className="credential-section asset-list">
          <div className="credential-section-title">
            资产列表
            <span className="credential-section-subtitle">
              （已选择 {selectedAssetIds.length} / {assets.length}）
            </span>
          </div>

          <div className="asset-items">
            {assets.map(asset => {
              const config = assetConfigs[asset.id] || { mode: 'default' }
              const isSelected = selectedAssetIds.includes(asset.id)

              return (
                <div
                  key={asset.id}
                  className={`asset-item ${isSelected ? '' : 'disabled'}`}
                >
                  {/* 资产头部 */}
                  <div className="asset-header">
                    <Checkbox
                      checked={isSelected}
                      onChange={() => handleToggleAsset(asset.id)}
                    />
                    <div className="asset-info">
                      <span className="asset-value">{asset.value}</span>
                      <Tag size="small" style={{ marginLeft: 8 }}>
                        {getAssetTypeLabel(asset.asset_type)}
                      </Tag>
                      {asset.name && (
                        <span className="asset-name">{asset.name}</span>
                      )}
                    </div>
                  </div>

                  {/* 凭据模式选择 */}
                  {isSelected && (
                    <div className="asset-credential-config">
                      <Radio.Group
                        value={config.mode}
                        onChange={(e) => handleModeChange(asset.id, e.target.value)}
                        size="small"
                      >
                        <Radio.Button value="default">
                          <CheckCircleOutlined style={{ marginRight: 4 }} />
                          使用默认
                        </Radio.Button>
                        <Radio.Button value="override">单独配置</Radio.Button>
                        <Radio.Button value="skip">跳过基线检查</Radio.Button>
                      </Radio.Group>

                      {/* 单独配置输入框 */}
                      {config.mode === 'override' && (
                        <div className="override-inputs">
                          <div className="credential-input-row">
                            <div className="credential-input-group">
                              <label>用户名</label>
                              <Input
                                size="small"
                                value={config.username || ''}
                                onChange={(e) => handleOverrideChange(asset.id, 'username', e.target.value)}
                                placeholder={defaultCred.username || 'root'}
                              />
                            </div>
                            <div className="credential-input-group">
                              <label>密码</label>
                              <Input.Password
                                size="small"
                                value={config.password || ''}
                                onChange={(e) => handleOverrideChange(asset.id, 'password', e.target.value)}
                                placeholder="输入密码"
                              />
                            </div>
                            <div className="credential-input-group small">
                              <label>端口</label>
                              <Input
                                size="small"
                                type="number"
                                value={config.port || ''}
                                onChange={(e) => handleOverrideChange(asset.id, 'port', parseInt(e.target.value) || 22)}
                                placeholder={defaultCred.port || 22}
                              />
                            </div>
                          </div>
                          <div className="credential-input-row">
                            <div className="credential-input-group full">
                              <label>密钥文件路径</label>
                              <Input
                                size="small"
                                value={config.key_file || ''}
                                onChange={(e) => handleOverrideChange(asset.id, 'key_file', e.target.value)}
                                placeholder="/path/to/private_key"
                              />
                            </div>
                          </div>
                        </div>
                      )}

                      {/* 跳过提示 */}
                      {config.mode === 'skip' && (
                        <div className="skip-warning">
                          <WarningOutlined style={{ color: '#f59e0b', marginRight: 6 }} />
                          <span>将跳过安全基线检查，其他 9 项检查正常执行</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </Modal>
  )
}

export default AssetCredentialModal
