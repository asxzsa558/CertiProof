import { Tag } from 'antd'
import {
  ApiOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  FileSearchOutlined,
  MonitorOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'

export default function DiagnosticResultCard({ data = {} }) {
  const services = data.services || {}
  const overallStatus = data.status
  
  const serviceConfig = {
    gateway: { 
      label: 'MCP Gateway', 
      icon: <ApiOutlined />, 
      gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' 
    },
    security_tools: { 
      label: 'Security Tools', 
      icon: <SafetyCertificateOutlined />, 
      gradient: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' 
    },
    ocr_server: { 
      label: 'OCR Server', 
      icon: <FileSearchOutlined />, 
      gradient: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' 
    },
  }

  const healthyCount = Object.values(services).filter(s => s.status === 'healthy').length
  const totalCount = Object.keys(services).length

  return (
    <div className="scan-animation-fade-in">
      <div className="diagnostic-card">
        {/* Header */}
        <div className="diagnostic-header">
          <div className="diagnostic-title">
            <ApiOutlined />
            <span>MCP 连通性测试</span>
          </div>
          <div className={`diagnostic-overall ${overallStatus === 'healthy' ? 'healthy' : 'unhealthy'}`}>
            {overallStatus === 'healthy' ? (
              <><CheckCircleFilled /> 全部正常</>
            ) : (
              <><CloseCircleFilled /> 部分异常</>
            )}
          </div>
        </div>

        {/* Service Cards */}
        <div className="diagnostic-services">
          {Object.entries(services).map(([key, info]) => {
            const config = serviceConfig[key] || { label: key, icon: <MonitorOutlined />, gradient: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }
            const isHealthy = info.status === 'healthy'
            const tools = info.details?.tools || info.details?.details?.tools || []
            
            return (
              <div key={key} className={`diagnostic-service-card ${isHealthy ? 'healthy' : 'unhealthy'}`}>
                <div className="service-card-header" style={{ background: config.gradient }}>
                  <div className="service-icon">{config.icon}</div>
                  <div className="service-info">
                    <div className="service-name">{config.label}</div>
                    <div className="service-status">
                      {isHealthy ? (
                        <><CheckCircleFilled /> 正常</>
                      ) : (
                        <><CloseCircleFilled /> 异常</>
                      )}
                    </div>
                  </div>
                </div>
                
                {tools.length > 0 && (
                  <div className="service-tools">
                    <div className="tools-label">可用工具</div>
                    <div className="tools-list">
                      {tools.map((tool, i) => (
                        <Tag key={i} color={isHealthy ? 'success' : 'default'} className="tool-tag">
                          {tool.replace(/_scan|_analyze|_bruteforce/, '')}
                        </Tag>
                      ))}
                    </div>
                  </div>
                )}
                
                {info.error && (
                  <div className="service-error">
                    <CloseCircleFilled /> {info.error}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Summary */}
        <div className="diagnostic-summary">
          <div className="summary-stat">
            <span className="stat-value">{healthyCount}</span>
            <span className="stat-label">正常</span>
          </div>
          <div className="summary-divider">/</div>
          <div className="summary-stat">
            <span className="stat-value">{totalCount}</span>
            <span className="stat-label">服务</span>
          </div>
        </div>
      </div>
    </div>
  )
}
