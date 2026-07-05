import { Tag, Table } from 'antd'
import {
  SafetyCertificateOutlined,
  MonitorOutlined,
  CloseCircleFilled,
  ExclamationCircleFilled,
  InfoCircleFilled,
  DatabaseOutlined,
  KeyOutlined,
  ClusterOutlined,
  CloudServerOutlined,
  GlobalOutlined,
  FolderOpenOutlined,
  RadarChartOutlined,
} from '@ant-design/icons'
import ToolResultCard from './ToolResultCard'
import { CAPABILITY_NAMES } from './toolCatalog'
import { safeJson, inferResultState } from './resultRendererUtils'
import { createPortColumns } from './resultColumns'

const portColumns = createPortColumns()

const renderResultMessage = (msg, options = {}) => {
  const scanResults = msg.scanResults || {}
  const openPorts = scanResults.open_ports || []
  const filteredPorts = scanResults.filtered_ports || []
  const vulnerabilities = scanResults.vulnerabilities || []
  const sslIssues = scanResults.ssl_issues || []
  const weakPasswords = scanResults.weak_passwords || []
  const weakPasswordStats = scanResults.weak_password_stats || {}
  const weakPasswordIncompleteTargets = Object.entries(weakPasswordStats)
    .filter(([, stats]) => stats.scan_completed === false)
  const webVulnerabilities = scanResults.web_vulnerabilities || []
  const webDiscoveries = scanResults.web_discoveries || []
  const databaseIssues = scanResults.database_issues || []
  const databaseResults = scanResults.database_results || {}
  const snmpResults = scanResults.snmp_results || {}
  const windowsResults = scanResults.windows_results || {}
  const compositeResults = scanResults.composite_results || []
  const baselineResults = scanResults.baseline_results || {}
  const discoveredAssets = scanResults.discovered_assets || {}
  const quality = scanResults.quality || {}

  // 从 asset_results 提取工具类型和状态
  const assetResults = scanResults.asset_results || {}
  const firstAsset = Object.values(assetResults)[0]
  const tool = firstAsset?.capability || 'scan_ports'
  const status = inferResultState(firstAsset || scanResults).key
  const error = firstAsset?.error
  const resultTarget = Object.keys(assetResults)[0] || firstAsset?.result?.target || scanResults.target || scanResults.asset || ''
  const copyText = [
    msg.content,
    resultTarget ? `资产/IP: ${resultTarget}` : '',
    `检测工具: ${CAPABILITY_NAMES[tool] || tool}`,
    error ? `错误信息: ${error}` : '',
    scanResults ? `结构化结果:\n${safeJson(scanResults)}` : '',
  ].filter(Boolean).join('\n\n')

  // 构建摘要内容
  const summary = (
    <div className="result-summary">
      {openPorts.length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(59, 130, 246, 0.2)' }}>
            <MonitorOutlined style={{ color: '#3b82f6' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">明确开放端口</div>
            <div className="summary-value">{openPorts.length} 个</div>
          </div>
        </div>
      )}
      {filteredPorts.length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(245, 158, 11, 0.2)' }}>
            <ExclamationCircleFilled style={{ color: '#f59e0b' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">被过滤端口</div>
            <div className="summary-value">{filteredPorts.length} 个</div>
          </div>
        </div>
      )}
      {vulnerabilities.length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.2)' }}>
            <CloseCircleFilled style={{ color: '#ef4444' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">漏洞</div>
            <div className="summary-value">{vulnerabilities.length} 个</div>
          </div>
        </div>
      )}
      {weakPasswords.length > 0 && (
        <div className="summary-item critical">
          <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.3)' }}>
            <KeyOutlined style={{ color: '#ef4444' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">弱口令</div>
            <div className="summary-value" style={{ color: '#ef4444' }}>{weakPasswords.length} 个</div>
          </div>
        </div>
      )}
      {sslIssues.length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(245, 158, 11, 0.2)' }}>
            <SafetyCertificateOutlined style={{ color: '#f59e0b' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">SSL 问题</div>
            <div className="summary-value">{sslIssues.length} 个</div>
          </div>
        </div>
      )}
      {webVulnerabilities.length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(168, 85, 247, 0.2)' }}>
            <GlobalOutlined style={{ color: '#a855f7' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">Web 漏洞</div>
            <div className="summary-value">{webVulnerabilities.length} 个</div>
          </div>
        </div>
      )}
      {webDiscoveries.length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(14, 165, 233, 0.2)' }}>
            <FolderOpenOutlined style={{ color: '#0ea5e9' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">Web 发现</div>
            <div className="summary-value">{webDiscoveries.length} 个</div>
          </div>
        </div>
      )}
      {databaseIssues.length > 0 && (
        <div className="summary-item critical">
          <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.2)' }}>
            <DatabaseOutlined style={{ color: '#ef4444' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">数据库风险</div>
            <div className="summary-value">{databaseIssues.length} 项</div>
          </div>
        </div>
      )}
      {Object.keys(snmpResults).length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(217, 70, 239, 0.2)' }}>
            <ClusterOutlined style={{ color: '#d946ef' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">SNMP</div>
            <div className="summary-value">{Object.keys(snmpResults).length} 个目标</div>
          </div>
        </div>
      )}
      {Object.keys(windowsResults).length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(100, 116, 139, 0.2)' }}>
            <CloudServerOutlined style={{ color: '#64748b' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">Windows/SMB</div>
            <div className="summary-value">{Object.keys(windowsResults).length} 个目标</div>
          </div>
        </div>
      )}
      {compositeResults.length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(99, 102, 241, 0.2)' }}>
            <RadarChartOutlined style={{ color: '#6366f1' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">组合扫描</div>
            <div className="summary-value">{compositeResults.length} 组</div>
          </div>
        </div>
      )}
      {Object.keys(discoveredAssets).length > 0 && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(16, 185, 129, 0.2)' }}>
            <RadarChartOutlined style={{ color: '#10b981' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">已发现资产</div>
            <div className="summary-value">{Object.keys(discoveredAssets).length} 个</div>
          </div>
        </div>
      )}
    </div>
  )

  // 构建详情内容
  const details = (
    <>
      {(resultTarget || tool) && (
        <div className="result-details-section result-identity-section">
          {resultTarget && (
            <div className="baseline-target-item">
              <span>资产/IP</span>
              <span className="text-muted">{resultTarget}</span>
            </div>
          )}
          <div className="baseline-target-item">
            <span>检测工具</span>
            <span className="text-muted">{CAPABILITY_NAMES[tool] || tool}</span>
          </div>
        </div>
      )}

      {quality.verdict && (
        <div className={`result-details-section quality-section ${quality.verdict}`}>
          <div className={`section-title ${quality.verdict === 'complete' ? 'success' : quality.verdict === 'partial' ? 'danger' : 'warning'}`}>
            结果可信度：{quality.verdict === 'complete' ? '完整' : quality.verdict === 'partial' ? '部分失败' : '有条件可信'}
          </div>
          <div className="baseline-target-item">
            <span>资产状态</span>
            <span className="text-muted">
              成功 {quality.success || 0}，警告/不可判定 {quality.warning || 0}，失败 {quality.failed || 0}
            </span>
          </div>
          <div className="baseline-target-item">
            <span>说明</span>
            <span className="text-muted">{quality.note}</span>
          </div>
          {(quality.incomplete_targets || []).length > 0 && (
            <div className="baseline-target-item">
              <span>需复核资产</span>
              <span className="text-muted">{quality.incomplete_targets.join('、')}</span>
            </div>
          )}
        </div>
      )}

      {/* 错误信息 */}
      {error && (
        <div className="result-details-section error-section">
          <div className="section-title danger">
            <ExclamationCircleFilled style={{ marginRight: 8 }} />
            错误信息
          </div>
          <div className="error-message">{error}</div>
        </div>
      )}

      {/* 弱口令详情 - 高亮显示 */}
      {weakPasswords.length > 0 && (
        <div className="result-details-section weak-password-section">
          <div className="section-title danger">
            ⚠ 发现 {weakPasswords.length} 个弱口令！
          </div>
          {Object.entries(weakPasswordStats).map(([target, stats]) => {
            const targetPasswords = weakPasswords.filter(p => p.target === target)
            return (
              <div key={target} className="weak-password-target">
                <div className="target-header">
                  <span className="target-name">{target}</span>
                  <span className="target-stats">
                    测试 {stats.tested_users} 用户 × {stats.tested_passwords} 密码 = {stats.total_combinations} 组合
                    {targetPasswords.length > 0 && (
                      <Tag color="red" style={{ marginLeft: 8 }}>
                        ⚠ {targetPasswords.length} 个弱口令
                      </Tag>
                    )}
                  </span>
                </div>
                {targetPasswords.length > 0 && (
                  <div className="password-list">
                    {targetPasswords.map((fp, idx) => (
                      <div key={idx} className="password-item danger">
                        <Tag color="red">{fp.username || '?'}</Tag>
                        <span className="password-text">{fp.password || '?'}</span>
                      </div>
                    ))}
                  </div>
                )}
                {targetPasswords.length === 0 && (
                  <div className={`password-list ${stats.scan_completed === false ? 'warning' : 'success'}`}>
                    <Tag color={stats.scan_completed === false ? 'orange' : 'green'}>{stats.scan_completed === false ? '未完成' : '✓ 安全'}</Tag>
                    <span>{stats.scan_completed === false ? (stats.tool_error || '无法判定是否存在弱口令') : '未发现弱口令'}</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* 弱口令全部安全的提示 */}
      {weakPasswords.length === 0 && Object.keys(weakPasswordStats).length > 0 && (
        <div className={`result-details-section ${weakPasswordIncompleteTargets.length ? 'warning-section' : 'success-section'}`}>
          <div className={`section-title ${weakPasswordIncompleteTargets.length ? 'warning' : 'success'}`}>
            {weakPasswordIncompleteTargets.length ? '⚠ 弱口令检测未完成，无法判定' : '✓ 弱口令检测完成，未发现弱口令'}
          </div>
          {Object.entries(weakPasswordStats).map(([target, stats]) => (
            <div key={target} className="baseline-target-item">
              <span>{target}</span>
              <span className="text-muted">
                {stats.scan_completed === false
                  ? (stats.tool_error || '目标服务不可达或检测未完成')
                  : `测试 ${stats.tested_users} 用户 × ${stats.tested_passwords} 密码 = ${stats.total_combinations} 组合`}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Web 漏洞详情 */}
      {webVulnerabilities.length > 0 && (
        <div className="result-details-section">
          <div className="section-title">Web 漏洞列表</div>
          {webVulnerabilities.map((vuln, idx) => (
            <div key={idx} className="vulnerability-item">
              <Tag color="red">{vuln.severity || '未知'}</Tag>
              <span className="vuln-target">[{vuln.target}]</span>
              <span>{vuln.name || vuln.id || 'Web 漏洞'}</span>
              {vuln.tool && <Tag color="purple" style={{ marginLeft: 4 }}>{vuln.tool}</Tag>}
            </div>
          ))}
        </div>
      )}

      {webDiscoveries.length > 0 && (
        <div className="result-details-section">
          <div className="section-title">Web 路径/端点发现</div>
          {webDiscoveries.slice(0, 50).map((item, idx) => (
            <div key={idx} className="vulnerability-item">
              <Tag color="blue">{item.status || item.status_code || '发现'}</Tag>
              <span className="vuln-target">[{item.target}]</span>
              <span>{item.url || item.path || item.input || '未知端点'}</span>
              {item.tool && <Tag color="purple" style={{ marginLeft: 4 }}>{item.tool}</Tag>}
            </div>
          ))}
          {webDiscoveries.length > 50 && <div className="text-muted">还有 {webDiscoveries.length - 50} 条未展开</div>}
        </div>
      )}

      {databaseIssues.length > 0 && (
        <div className="result-details-section">
          <div className="section-title danger">数据库风险项</div>
          {databaseIssues.map((issue, idx) => (
            <div key={idx} className="vulnerability-item">
              <Tag color="red">{issue.tool}</Tag>
              <span className="vuln-target">[{issue.target}]</span>
              <span>
                {issue.unauthorized ? '存在未授权访问' : issue.empty_password ? '存在空口令风险' : issue.version_info ? `暴露版本信息：${issue.version_info}` : '需关注'}
              </span>
            </div>
          ))}
        </div>
      )}

      {Object.keys(databaseResults).length > 0 && databaseIssues.length === 0 && (
        <div className="result-details-section success-section">
          <div className="section-title success">数据库检测完成，未发现明显风险</div>
          {Object.entries(databaseResults).map(([target, tools]) => (
            <div key={target} className="baseline-target-item">
              <span>{target}</span>
              <span className="text-muted">{Object.keys(tools).join(', ')}</span>
            </div>
          ))}
        </div>
      )}

      {Object.keys(snmpResults).length > 0 && (
        <div className="result-details-section">
          <div className="section-title">SNMP 检测结果</div>
          {Object.entries(snmpResults).map(([target, tools]) => (
            <div key={target} className="baseline-target-item">
              <span>{target}</span>
              <span className="text-muted">{Object.keys(tools).join(', ')}</span>
            </div>
          ))}
        </div>
      )}

      {Object.keys(windowsResults).length > 0 && (
        <div className="result-details-section">
          <div className="section-title">Windows/SMB 检测结果</div>
          {Object.entries(windowsResults).map(([target, tools]) => (
            <div key={target} className="baseline-target-item">
              <span>{target}</span>
              <span className="text-muted">{Object.keys(tools).join(', ')}</span>
            </div>
          ))}
        </div>
      )}

      {compositeResults.length > 0 && (
        <div className="result-details-section">
          <div className="section-title">组合扫描子任务</div>
          {(() => {
            const describeSubResult = (sub) => {
              const data = sub.data || {}
              if (data.scan_completed === false || data.success === false) {
                return `未完成/无响应${data.tool_error ? `：${data.tool_error}` : ''}`
              }
              if (['redis_check', 'mongodb_check', 'memcached_check'].includes(sub.capability)) {
                return data.unauthorized ? '存在未授权访问' : data.reachable === false ? `不可达/无响应，端口 ${data.port || '-'}` : `未发现未授权访问，端口 ${data.port || '-'}`
              }
              if (sub.capability === 'mysql_check') {
                return data.empty_password ? '存在空口令' : data.reachable === false ? `不可达/无响应，端口 ${data.port || '-'}` : `未发现空口令，端口 ${data.port || '-'}`
              }
              if (sub.capability === 'oracle_check') {
                const hasVersion = data.version_info && Object.keys(data.version_info).length > 0
                return hasVersion ? `存在版本信息，端口 ${data.port || '-'}` : data.reachable === false ? `不可达/无响应，端口 ${data.port || '-'}` : `未发现版本信息泄露，端口 ${data.port || '-'}`
              }
              if (sub.capability === 'nikto_scan') return `Web 问题 ${data.total_findings ?? data.findings?.length ?? 0} 个`
              if (sub.capability === 'scan_ports') return `明确开放 ${data.open_ports?.length || 0} 个，被过滤/未确认 ${data.filtered_count || data.filtered_ports?.length || 0} 个`
              if (sub.capability === 'scan_ssl') return `SSL 问题 ${data.issues?.length || 0} 个`
              if (sub.capability === 'scan_vulnerabilities') return `漏洞 ${data.total_findings ?? data.findings?.length ?? 0} 个`
              if (sub.capability === 'scan_weak_passwords') return `弱口令 ${data.found?.length || 0} 个`
              if (sub.capability === 'snmp_walk') return `SNMP 返回 ${data.total_results || 0} 条`
              return sub.error || '已完成'
            }
            return compositeResults.map((group, groupIdx) => (
              <div key={groupIdx} className="weak-password-target">
                <div className="target-header">
                  <span className="target-name">{group.target}</span>
                  <span className="target-stats">
                    成功 {group.summary?.success || 0}，失败 {group.summary?.failed || 0}，跳过 {group.summary?.skipped || 0}
                  </span>
                </div>
                {(group.sub_results || []).map((sub, idx) => (
                  <div key={idx} className="baseline-target-item">
                    <span>{sub.label || sub.capability}</span>
                    <Tag color={sub.status === 'success' ? 'green' : sub.status === 'skipped' ? 'gold' : 'red'}>{sub.status}</Tag>
                    <span className="text-muted">{describeSubResult(sub)}</span>
                  </div>
                ))}
              </div>
            ))
          })()}
        </div>
      )}

      {/* 端口详情表格 */}
      {openPorts.length > 0 && (
        <div className="result-details-table">
          <div className="table-header">
            <span>明确开放端口详情</span>
          </div>
          <Table
            dataSource={openPorts.map((port, idx) => ({ ...port, key: idx }))}
            columns={portColumns}
            pagination={openPorts.length > 10 ? { defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] } : false}
            size="small"
            className="port-table"
          />
        </div>
      )}

      {filteredPorts.length > 0 && (
        <div className="result-details-table">
          <div className="table-header">
            <span>被过滤端口详情（未确认开放）</span>
          </div>
          <div className="info-box warning" style={{ marginBottom: 12 }}>
            <InfoCircleFilled style={{ color: '#f59e0b', marginRight: 8 }} />
            <span>这些端口状态是 filtered/no-response，不能作为 SSH 登录、弱口令或基线检查的开放依据。</span>
          </div>
          <Table
            dataSource={filteredPorts.map((port, idx) => ({ ...port, key: idx }))}
            columns={portColumns}
            pagination={filteredPorts.length > 10 ? { defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] } : false}
            size="small"
            className="port-table"
          />
        </div>
      )}

      {/* 漏洞详情 */}
      {vulnerabilities.length > 0 && (
        <div className="result-details-section">
          <div className="section-title">漏洞列表</div>
          {vulnerabilities.map((vuln, idx) => (
            <div key={idx} className="vulnerability-item">
              <Tag color="red">{vuln.severity || '未知'}</Tag>
              <span>{vuln.name || vuln.id}</span>
            </div>
          ))}
        </div>
      )}

      {/* SSL 问题 */}
      {sslIssues.length > 0 && (
        <div className="result-details-section">
          <div className="section-title">SSL/TLS 问题</div>
          {sslIssues.map((issue, idx) => (
            <div key={idx} className="ssl-issue-item">
              <Tag color="orange">警告</Tag>
              <span>{issue}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )

  return (
    <div className="scan-animation-fade-in">
      <div className="message-bubble assistant" style={{ whiteSpace: 'pre-wrap' }}>
        {msg.content}
      </div>

      <ToolResultCard
        tool={tool}
        status={status}
        summary={summary}
        details={details}
        copyText={copyText}
        defaultExpanded={!options.compact}
      />
    </div>
  )
}

export default function SingleResultMessage({ msg, compact = false }) {
  return renderResultMessage(msg, { compact })
}
