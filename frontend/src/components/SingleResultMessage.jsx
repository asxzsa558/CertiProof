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
import { safeJson, inferResultState, readableFindingText, severityLabel } from './resultRendererUtils'
import { createPortColumns } from './resultColumns'

const portColumns = createPortColumns()
const assetTypeLabels = { ip: 'IP', domain: '域名', cloud_resource: '云资源' }
const verificationLabels = { verified: '已验证', pending: '待验证', failed: '验证失败' }
const assetColumns = [
  {
    title: '资产名称',
    dataIndex: 'name',
    key: 'name',
    render: value => value || '未命名资产',
  },
  {
    title: '类型',
    dataIndex: 'type',
    key: 'type',
    width: 90,
    render: value => assetTypeLabels[value] || value || '资产',
  },
  {
    title: '地址',
    dataIndex: 'value',
    key: 'value',
  },
  {
    title: '验证状态',
    dataIndex: 'verification_status',
    key: 'verification_status',
    width: 100,
    render: value => verificationLabels[value] || value || '状态未知',
  },
]

const renderResultMessage = (msg, options = {}) => {
  const scanResults = msg.scanResults || {}
  const queryResult = scanResults.query_result || null
  const listedAssets = queryResult?.capability === 'list_assets' ? (queryResult.assets || []) : []
  const projectStatus = ['view_project_status', 'view_compliance_score'].includes(queryResult?.capability)
    ? (queryResult.data || {})
    : null
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
  const tool = queryResult?.capability || firstAsset?.capability || 'scan_ports'
  const status = inferResultState(queryResult || firstAsset || scanResults).key
  const error = queryResult?.error || firstAsset?.error
  const firstResult = firstAsset?.result || {}
  const isVulnerabilityScan = ['nikto_scan', 'scan_vulnerabilities'].includes(tool)
  const vulnerabilityScanIncomplete = firstResult.scan_completed === false || (
    tool === 'scan_vulnerabilities' &&
    firstResult.reachable !== true &&
    !(firstResult.findings || []).length
  )
  const resultTarget = Object.keys(assetResults)[0] || firstAsset?.result?.target || scanResults.target || scanResults.asset || ''
  const displayQuality = queryResult
    ? {}
    : vulnerabilityScanIncomplete
    ? {
        ...quality,
        verdict: 'conditional',
        success: 0,
        warning: Math.max(Number(quality.warning) || 0, 1),
        incomplete_targets: Array.from(new Set([...(quality.incomplete_targets || []), resultTarget].filter(Boolean))),
        note: error || firstResult.error || '漏洞扫描未完整执行，当前结果不可用于判断目标是否存在漏洞。',
      }
    : quality
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
      {queryResult?.capability === 'list_assets' && (
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(14, 165, 233, 0.2)' }}>
            <DatabaseOutlined style={{ color: '#38bdf8' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">项目资产</div>
            <div className="summary-value">{listedAssets.length} 个</div>
          </div>
        </div>
      )}
      {projectStatus && (
        <>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(14, 165, 233, 0.2)' }}>
              <MonitorOutlined style={{ color: '#38bdf8' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">测评进度</div>
              <div className="summary-value">{Number(projectStatus.workflow_progress || 0).toFixed(1)}%</div>
            </div>
          </div>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(16, 185, 129, 0.18)' }}>
              <SafetyCertificateOutlined style={{ color: '#34d399' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">合规评分</div>
              <div className="summary-value">
                {projectStatus.compliance_score == null ? '未形成' : `${Number(projectStatus.compliance_score).toFixed(1)} 分`}
              </div>
            </div>
          </div>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(245, 158, 11, 0.18)' }}>
              <ExclamationCircleFilled style={{ color: '#f59e0b' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">待处理问题</div>
              <div className="summary-value">{projectStatus.findings?.open || 0} 项</div>
            </div>
          </div>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(99, 102, 241, 0.18)' }}>
              <InfoCircleFilled style={{ color: '#818cf8' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">有效覆盖率</div>
              <div className="summary-value">{Number(projectStatus.coverage || 0).toFixed(1)}%</div>
            </div>
          </div>
        </>
      )}
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
      {queryResult?.capability === 'list_assets' && (
        <div className="result-details-table">
          <div className="table-header">
            <span>项目资产清单</span>
          </div>
          <Table
            dataSource={listedAssets.map(asset => ({ ...asset, key: asset.id || asset.value }))}
            columns={assetColumns}
            pagination={listedAssets.length > 10 ? { defaultPageSize: 10, showSizeChanger: true } : false}
            locale={{ emptyText: '当前项目暂无资产' }}
            size="small"
            className="port-table"
          />
        </div>
      )}

      {projectStatus && (
        <div className="result-details-section project-status-detail">
          <div className="section-title">当前项目状态</div>
          <div className="baseline-target-item">
            <span>项目</span>
            <span className="text-muted">{projectStatus.project_name || '当前项目'} · {projectStatus.compliance_level || '未设置等级'}</span>
          </div>
          <div className="baseline-target-item">
            <span>当前阶段</span>
            <span className="text-muted">{projectStatus.current_phase?.name || '尚未开始'}</span>
          </div>
          <div className="baseline-target-item">
            <span>问题分布</span>
            <span className="text-muted">
              全部 {projectStatus.findings?.total || 0} · 待处理 {projectStatus.findings?.open || 0} · 已修复 {projectStatus.findings?.fixed || 0} · 无法验证 {projectStatus.findings?.unable || 0}
            </span>
          </div>
          <div className="baseline-target-item">
            <span>报告</span>
            <span className="text-muted">
              {projectStatus.report?.available ? `已生成 v${projectStatus.report.version}` : '尚未生成有效报告'}
            </span>
          </div>
          {(projectStatus.phases || []).map(phase => (
            <div className="baseline-target-item" key={phase.id || phase.phase_id}>
              <span>{phase.name}</span>
              <span className="text-muted">{Number(phase.progress || 0).toFixed(1)}% · {phase.status}</span>
            </div>
          ))}
        </div>
      )}

      {(resultTarget || (tool && !queryResult)) && (
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

      {displayQuality.verdict && (
        <div className={`result-details-section quality-section ${displayQuality.verdict}`}>
          <div className={`section-title ${displayQuality.verdict === 'complete' ? 'success' : displayQuality.verdict === 'partial' ? 'danger' : 'warning'}`}>
            结果可信度：{displayQuality.verdict === 'complete' ? '完整' : displayQuality.verdict === 'partial' ? '部分失败' : '有条件可信'}
          </div>
          <div className="baseline-target-item">
            <span>资产状态</span>
            <span className="text-muted">
              成功 {displayQuality.success || 0}，无法判定 {displayQuality.warning || 0}，失败 {displayQuality.failed || 0}
            </span>
          </div>
          <div className="baseline-target-item">
            <span>说明</span>
            <span className="text-muted">{displayQuality.note}</span>
          </div>
          {(displayQuality.incomplete_targets || []).length > 0 && (
            <div className="baseline-target-item">
              <span>需复核资产</span>
              <span className="text-muted">{displayQuality.incomplete_targets.join('、')}</span>
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
      {isVulnerabilityScan && webVulnerabilities.length === 0 && vulnerabilities.length === 0 && (
        <div className={`result-details-section ${vulnerabilityScanIncomplete ? 'warning-section' : 'success-section'}`}>
          <div className={`section-title ${vulnerabilityScanIncomplete ? 'warning' : 'success'}`}>
            {vulnerabilityScanIncomplete ? '漏洞扫描未完成，无法判断是否存在漏洞' : '漏洞扫描完成，本次未发现漏洞'}
          </div>
          {vulnerabilityScanIncomplete && <div className="error-message">{firstResult.tool_error || error || '工具未返回完整结果'}</div>}
        </div>
      )}
      {webVulnerabilities.length > 0 && (
        <div className="result-details-section">
          <div className="section-title">Web 漏洞列表</div>
          {webVulnerabilities.map((vuln, idx) => (
            <div key={idx} className="vulnerability-item">
              <Tag color="red">{severityLabel(vuln.severity, '未知')}</Tag>
              <span className="vuln-target">[{vuln.target}]</span>
              <span>{readableFindingText(vuln, 'Web 漏洞')}</span>
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
              <Tag color="red">{severityLabel(vuln.severity, '未知')}</Tag>
              <span>{readableFindingText(vuln, '漏洞发现项')}</span>
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
        {vulnerabilityScanIncomplete
          ? `漏洞扫描未能验证目标 ${resultTarget || ''} 是否可达，本次不能得出“未发现漏洞”的结论。`
          : msg.content}
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
