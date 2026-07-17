import { Tag, Table } from 'antd'
import {
  SafetyCertificateOutlined,
  MonitorOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  ExclamationCircleFilled,
  InfoCircleFilled,
  DatabaseOutlined,
  KeyOutlined,
  ClusterOutlined,
  GlobalOutlined,
  BugOutlined,
  LockOutlined,
  FolderOpenOutlined,
  WifiOutlined,
  SearchOutlined,
  RadarChartOutlined,
} from '@ant-design/icons'
import { hexToRgba, readableFindingText, severityLabel } from './resultRendererUtils'
import { createPortColumns } from './resultColumns'

const portColumns = createPortColumns()

// Helper: Build summary for a single asset
const buildAssetSummary = (assetData, capability) => {
  const result = assetData.result || {}
  const openPorts = assetData.result?.open_ports || []
  const filteredPorts = assetData.result?.filtered_ports || []
  const vulnerabilities = assetData.result?.vulnerabilities || []
  const findings = assetData.result?.findings || []
  const issues = assetData.result?.issues || []
  const weakPasswords = assetData.result?.weak_passwords || []
  const rawWeakPasswords = assetData.result?.found || []
  const weakPasswordIncomplete = capability === 'scan_weak_passwords' && (
    assetData.result?.scan_completed === false ||
    assetData.result?.reachable === false ||
    assetData.display_status === 'warning'
  )
  const weakPasswordStats = assetData.result?.weak_password_stats || {}
  const webVulnerabilities = assetData.result?.web_vulnerabilities || []
  const webDiscoveries = assetData.result?.web_discoveries || []
  const sslIssues = assetData.result?.ssl_issues || []
  const compositeResults = assetData.result?.composite_results || (assetData.result?.sub_results ? [{
    target: assetData.result?.target,
    summary: assetData.result?.summary,
    sub_results: assetData.result?.sub_results,
  }] : [])
  const discoveredAssets = assetData.result?.discovered_assets || {}
  
  const items = []
  if (openPorts.length > 0) items.push({ label: '明确开放端口', value: `${openPorts.length} 个`, color: '#3b82f6', icon: <MonitorOutlined /> })
  if (filteredPorts.length > 0) items.push({ label: '被过滤端口', value: `${filteredPorts.length} 个`, color: '#f59e0b', icon: <ExclamationCircleFilled /> })
  if (vulnerabilities.length > 0) items.push({ label: '漏洞', value: `${vulnerabilities.length} 个`, color: '#ef4444', icon: <CloseCircleFilled /> })
  if (findings.length > 0) items.push({ label: capability === 'nikto_scan' ? 'Web 问题' : '发现项', value: `${findings.length} 个`, color: '#ef4444', icon: <BugOutlined /> })
  if (weakPasswords.length > 0) items.push({ label: '弱口令', value: `${weakPasswords.length} 个`, color: '#ef4444', icon: <KeyOutlined /> })
  if (rawWeakPasswords.length > 0) items.push({ label: '弱口令', value: `${rawWeakPasswords.length} 个`, color: '#ef4444', icon: <KeyOutlined /> })
  if (sslIssues.length > 0) items.push({ label: 'SSL 问题', value: `${sslIssues.length} 个`, color: '#f59e0b', icon: <SafetyCertificateOutlined /> })
  if (issues.length > 0) items.push({ label: '问题', value: `${issues.length} 个`, color: '#f59e0b', icon: <SafetyCertificateOutlined /> })
  if (webVulnerabilities.length > 0) items.push({ label: 'Web 漏洞', value: `${webVulnerabilities.length} 个`, color: '#a855f7', icon: <GlobalOutlined /> })
  if (webDiscoveries.length > 0) items.push({ label: 'Web 发现', value: `${webDiscoveries.length} 个`, color: '#0ea5e9', icon: <FolderOpenOutlined /> })
  if (compositeResults.length > 0) {
    const summary = compositeResults[0]?.summary || {}
    items.push({ label: '子项结果', value: `${summary.success || 0}/${summary.total || compositeResults[0]?.sub_results?.length || 0}`, color: '#6366f1', icon: <RadarChartOutlined /> })
  }
  if (Object.keys(discoveredAssets).length > 0) items.push({ label: '已发现资产', value: `${Object.keys(discoveredAssets).length} 个`, color: '#10b981', icon: <RadarChartOutlined /> })
  if (capability === 'nikto_scan' && findings.length === 0) items.push({ label: 'Web 问题', value: '0 个', color: '#10b981', icon: <GlobalOutlined /> })
  if (capability === 'sqlmap_scan' && !result.vulnerable) items.push({ label: 'SQL 注入', value: '未发现', color: '#10b981', icon: <SearchOutlined /> })
  if (['redis_check', 'mongodb_check', 'memcached_check'].includes(capability)) {
    items.push({ label: '未授权访问', value: result.unauthorized ? '存在' : '未发现', color: result.unauthorized ? '#ef4444' : '#10b981', icon: <DatabaseOutlined /> })
  }
  if (capability === 'mysql_check') {
    items.push({ label: '空口令', value: result.empty_password ? '存在' : '未发现', color: result.empty_password ? '#ef4444' : '#10b981', icon: <DatabaseOutlined /> })
  }
  if (capability === 'oracle_check') {
    const hasVersion = result.version_info && Object.keys(result.version_info).length > 0
    items.push({ label: '版本信息泄露', value: hasVersion ? '存在' : '未发现', color: hasVersion ? '#f59e0b' : '#10b981', icon: <DatabaseOutlined /> })
  }
  if (capability === 'scan_weak_passwords' && rawWeakPasswords.length === 0) {
    items.push({
      label: '弱口令',
      value: weakPasswordIncomplete ? '无法判定' : '未发现',
      color: weakPasswordIncomplete ? '#f59e0b' : '#10b981',
      icon: <KeyOutlined />,
    })
  }
  if (capability === 'scan_vulnerabilities' && findings.length === 0) items.push({ label: '漏洞', value: '0 个', color: '#10b981', icon: <BugOutlined /> })
  if (capability === 'scan_ssl') {
    const sslDone = result.scan_completed !== false && result.reachable !== false
    items.push({ label: 'SSL 状态', value: sslDone ? '已完成' : '未完成', color: sslDone ? '#10b981' : '#f59e0b', icon: <SafetyCertificateOutlined /> })
    if (result.tls_version) items.push({ label: 'TLS 版本', value: result.tls_version, color: '#3b82f6', icon: <LockOutlined /> })
    if (result.certificate) items.push({ label: '证书', value: '已获取', color: '#10b981', icon: <SafetyCertificateOutlined /> })
  }
  if (capability === 'fping_scan') items.push({ label: '存活主机', value: `${result.alive_count || 0}/${result.total_scanned || 0}`, color: '#10b981', icon: <WifiOutlined /> })
  if (capability === 'snmp_walk') items.push({ label: 'SNMP 返回', value: `${result.total_results || 0} 条`, color: result.success ? '#10b981' : '#f59e0b', icon: <ClusterOutlined /> })
  if (['baseline_check', 'linux_baseline'].includes(capability)) {
    const summary = result.summary || {}
    items.push({ label: '操作系统', value: result.os_type || '未知', color: '#3b82f6', icon: <MonitorOutlined /> })
    if (result.skipped) {
      items.push({ label: '核查状态', value: result.connection_error ? '无法连接' : '已跳过', color: '#f59e0b', icon: <ExclamationCircleFilled /> })
    } else {
      items.push({ label: '未通过', value: `${summary.non_compliant || 0} 项`, color: summary.non_compliant ? '#ef4444' : '#10b981', icon: <SafetyCertificateOutlined /> })
    }
  }
  
  if (items.length === 0) {
    return (
      <div className="result-summary">
        <div className="summary-item">
          <div className="summary-icon" style={{ background: 'rgba(16, 185, 129, 0.2)' }}>
            <CheckCircleFilled style={{ color: '#10b981' }} />
          </div>
          <div className="summary-content">
            <div className="summary-title">执行状态</div>
            <div className="summary-value">完成</div>
          </div>
        </div>
      </div>
    )
  }
  
  return (
    <div className="result-summary">
      {items.map((item, idx) => (
        <div key={idx} className="summary-item">
          <div className="summary-icon" style={{ background: hexToRgba(item.color, 0.2) }}>
            <span style={{ color: item.color }}>{item.icon}</span>
          </div>
          <div className="summary-content">
            <div className="summary-title">{item.label}</div>
            <div className="summary-value" style={{ color: item.color }}>{item.value}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// Helper: Build details for a single asset
const buildAssetDetails = (assetData, capability) => {
  const result = assetData.result || {}
  const openPorts = assetData.result?.open_ports || []
  const filteredPorts = assetData.result?.filtered_ports || []
  const vulnerabilities = assetData.result?.vulnerabilities || []
  const findings = assetData.result?.findings || []
  const issues = assetData.result?.issues || []
  const weakPasswords = assetData.result?.weak_passwords || []
  const rawWeakPasswords = assetData.result?.found || []
  const weakPasswordStats = assetData.result?.weak_password_stats || {}
  const weakPasswordIncomplete = capability === 'scan_weak_passwords' && (
    assetData.result?.scan_completed === false ||
    assetData.result?.reachable === false ||
    assetData.display_status === 'warning'
  )
  const webVulnerabilities = assetData.result?.web_vulnerabilities || []
  const webDiscoveries = assetData.result?.web_discoveries || []
  const compositeResults = assetData.result?.composite_results || (assetData.result?.sub_results ? [{
    target: assetData.result?.target,
    summary: assetData.result?.summary,
    sub_results: assetData.result?.sub_results,
  }] : [])
  const errorMsg = assetData.error
  const errorDetail = assetData.error_detail || result.error_detail
  
  const sections = []
  
  // Error section
  if (errorMsg) {
    sections.push(
      <div key="error" className="result-details-section error-section">
        <div className="section-title danger">
          <ExclamationCircleFilled style={{ marginRight: 8 }} />
          错误信息
        </div>
        {errorDetail ? (
          <>
            <div className="baseline-target-item">
              <span>错误类型</span>
              <Tag color="red">{errorDetail.error_type || 'tool_execution_failed'}</Tag>
            </div>
            <div className="baseline-target-item">
              <span>具体原因</span>
              <span className="text-muted">{errorDetail.error_reason || errorMsg}</span>
            </div>
            <div className="baseline-target-item">
              <span>处理建议</span>
              <span className="text-muted">{errorDetail.remediation || '检查目标、网络和工具诊断后重试'}</span>
            </div>
            <div className="error-message">{errorDetail.raw_error || errorMsg}</div>
          </>
        ) : (
          <div className="error-message">{errorMsg}</div>
        )}
      </div>
    )
  }
  
  // Weak passwords
  if (weakPasswords.length > 0) {
    sections.push(
      <div key="weak-passwords" className="result-details-section weak-password-section">
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
    )
  }

  if (capability === 'scan_weak_passwords') {
    const weakPasswordError = result.tool_error || assetData.error || '目标服务不可达或检测未完成'
    sections.push(
      <div key="raw-weak-passwords" className={`result-details-section ${rawWeakPasswords.length ? 'weak-password-section' : weakPasswordIncomplete ? 'warning-section' : 'success-section'}`}>
        <div className={`section-title ${rawWeakPasswords.length ? 'danger' : weakPasswordIncomplete ? 'warning' : 'success'}`}>
          弱口令检测：{rawWeakPasswords.length ? `发现 ${rawWeakPasswords.length} 个弱口令` : weakPasswordIncomplete ? '未完成，无法判定' : '未发现弱口令'}
        </div>
        {weakPasswordIncomplete && (
          <div className="baseline-target-item">
            <span>原因</span>
            <span className="text-muted">{weakPasswordError}</span>
          </div>
        )}
        <div className="baseline-target-item">
          <span>服务</span>
          <span className="text-muted">{result.service || 'ssh'}:{result.port || 22}</span>
        </div>
        <div className="baseline-target-item">
          <span>组合数</span>
          <span className="text-muted">{result.tested_users || 0} 用户 x {result.tested_passwords || 0} 密码 = {result.total_combinations || 0}</span>
        </div>
        {rawWeakPasswords.map((fp, idx) => (
          <div key={idx} className="password-item danger">
            <Tag color="red">{fp.username || '?'}</Tag>
            <span className="password-text">{fp.password || '?'}</span>
          </div>
        ))}
      </div>
    )
  }
  
  // Web vulnerabilities
  if (webVulnerabilities.length > 0) {
    sections.push(
      <div key="web-vulns" className="result-details-section">
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
    )
  }

  if (capability === 'nikto_scan') {
    const niktoDone = result.scan_completed !== false
    sections.push(
      <div key="nikto-summary" className={`result-details-section ${!niktoDone ? 'warning-section' : findings.length ? '' : 'success-section'}`}>
        <div className={`section-title ${!niktoDone ? 'warning' : findings.length ? '' : 'success'}`}>
          Nikto Web 扫描：{!niktoDone ? '未完成，无法判断是否存在漏洞' : findings.length ? `发现 ${findings.length} 个问题` : '扫描完成，未发现 Web 问题'}
        </div>
        <div className="baseline-target-item">
          <span>扫描目标</span>
          <span className="text-muted">{result.target || '-'}</span>
        </div>
        {findings.map((finding, idx) => (
          <div key={idx} className="vulnerability-item">
            <Tag color="orange">{finding.severity ? severityLabel(finding.severity) : finding.osvdb || '发现'}</Tag>
            <span>{readableFindingText(finding, 'Web 问题')}</span>
          </div>
        ))}
      </div>
    )
  }

  if (capability === 'sqlmap_scan') {
    const injectionPoints = result.injection_points || []
    sections.push(
      <div key="sqlmap-summary" className={`result-details-section ${result.vulnerable ? 'weak-password-section' : 'success-section'}`}>
        <div className={`section-title ${result.vulnerable ? 'danger' : 'success'}`}>
          SQL 注入检测：{result.vulnerable ? `发现 ${injectionPoints.length || 1} 个注入点` : '未发现注入点'}
        </div>
        <div className="baseline-target-item">
          <span>扫描 URL</span>
          <span className="text-muted">{result.url || result.target || '-'}</span>
        </div>
      </div>
    )
  }

  if (capability === 'scan_vulnerabilities') {
    const durationMs = result.metadata?.duration_ms
    const vulnDone = result.scan_completed !== false
    sections.push(
      <div key="nuclei-summary" className={`result-details-section ${!vulnDone || findings.length ? 'weak-password-section' : 'success-section'}`}>
        <div className={`section-title ${!vulnDone || findings.length ? 'danger' : 'success'}`}>
          漏洞扫描：{!vulnDone ? '未完成' : findings.length ? `发现 ${findings.length} 个漏洞/发现项` : '未发现漏洞'}
        </div>
        <div className="baseline-target-item">
          <span>扫描目标</span>
          <span className="text-muted">{result.target || '-'}</span>
        </div>
        <div className="baseline-target-item">
          <span>扫描引擎</span>
          <span className="text-muted">nuclei</span>
        </div>
        <div className="baseline-target-item">
          <span>模板/级别</span>
          <span className="text-muted">{result.templates || '默认模板'} / {result.severity_filter || '全部级别'}</span>
        </div>
        {durationMs !== undefined && (
          <div className="baseline-target-item">
            <span>耗时</span>
            <span className="text-muted">{Math.round(durationMs / 1000)} 秒</span>
          </div>
        )}
        {result.tool_error && (
          <div className="baseline-target-item">
            <span>工具提示</span>
            <span className="text-muted">{result.tool_error}</span>
          </div>
        )}
        {findings.map((finding, idx) => (
          <div key={idx} className="vulnerability-item">
            <Tag color={finding.severity === 'critical' || finding.severity === 'high' ? 'red' : finding.severity === 'medium' ? 'orange' : 'blue'}>
              {severityLabel(finding.severity)}
            </Tag>
            <span className="vuln-target">[{finding.host || finding.matched_at || result.target}]</span>
            <span>{readableFindingText(finding, '漏洞发现项')}</span>
            {finding.template_id && <Tag color="purple" style={{ marginLeft: 4 }}>{finding.template_id}</Tag>}
          </div>
        ))}
      </div>
    )
  }

  if (['redis_check', 'mysql_check', 'mongodb_check', 'memcached_check', 'oracle_check'].includes(capability)) {
    const dbLabels = {
      redis_check: 'Redis 未授权访问',
      mysql_check: 'MySQL 空口令',
      mongodb_check: 'MongoDB 未授权访问',
      memcached_check: 'Memcached 未授权访问',
      oracle_check: 'Oracle TNS 版本信息',
    }
    const risky = result.unauthorized || result.empty_password || (result.version_info && Object.keys(result.version_info).length > 0)
    sections.push(
      <div key="database-summary" className={`result-details-section ${risky ? 'weak-password-section' : 'success-section'}`}>
        <div className={`section-title ${risky ? 'danger' : 'success'}`}>
          {dbLabels[capability]}：{risky ? '发现需关注项' : '未发现明显风险'}
        </div>
        <div className="baseline-target-item">
          <span>目标端口</span>
          <span className="text-muted">{result.target || '-'}:{result.port || '-'}</span>
        </div>
        {'reachable' in result && (
          <div className="baseline-target-item">
            <span>连接状态</span>
            <Tag color={result.reachable === false ? 'gold' : 'green'}>{result.reachable === false ? '不可达/无响应' : '可连接'}</Tag>
          </div>
        )}
        {result.tool_error && (
          <div className="baseline-target-item">
            <span>工具提示</span>
            <span className="text-muted">{result.tool_error}</span>
          </div>
        )}
      </div>
    )
  }

  if (capability === 'scan_ssl') {
    const cert = result.certificate || {}
    const sslDone = result.scan_completed !== false && result.reachable !== false
    sections.push(
      <div key="ssl-summary" className={`result-details-section ${sslDone ? (issues.length || vulnerabilities.length ? 'warning-section' : 'success-section') : 'warning-section'}`}>
        <div className={`section-title ${sslDone && !issues.length && !vulnerabilities.length ? 'success' : 'warning'}`}>
          SSL/TLS 检测：{sslDone ? `问题 ${issues.length || 0} 个，漏洞 ${vulnerabilities.length || 0} 个` : '未完成'}
        </div>
        <div className="baseline-target-item">
          <span>检测目标</span>
          <span className="text-muted">{result.target || '-'}:{result.port || 443}</span>
        </div>
        <div className="baseline-target-item">
          <span>连接状态</span>
          <Tag color={sslDone ? 'green' : 'gold'}>{sslDone ? '已完成 TLS 检测' : '未获取 TLS 信息'}</Tag>
        </div>
        <div className="baseline-target-item">
          <span>TLS 版本</span>
          <span className="text-muted">{result.tls_version || '未获取'}</span>
        </div>
        <div className="baseline-target-item">
          <span>证书主体</span>
          <span className="text-muted">{cert.subject || '未获取'}</span>
        </div>
        <div className="baseline-target-item">
          <span>证书签发者</span>
          <span className="text-muted">{cert.issuer || '未获取'}</span>
        </div>
        {result.tool_error && (
          <div className="baseline-target-item">
            <span>工具提示</span>
            <span className="text-muted">{result.tool_error}</span>
          </div>
        )}
        {issues.map((issue, idx) => (
          <div key={idx} className="ssl-issue-item">
            <Tag color="orange">警告</Tag>
            <span>{issue}</span>
          </div>
        ))}
      </div>
    )
  }

  if (capability === 'fping_scan') {
    sections.push(
      <div key="fping-summary" className="result-details-section">
        <div className="section-title">批量存活检测</div>
        <div className="baseline-target-item">
          <span>扫描数量</span>
          <span className="text-muted">{result.total_scanned || 0}</span>
        </div>
        <div className="baseline-target-item">
          <span>存活主机</span>
          <span className="text-muted">{(result.alive_hosts || []).join(', ') || '无'}</span>
        </div>
      </div>
    )
  }

  if (capability === 'snmp_walk') {
    sections.push(
      <div key="snmp-summary" className="result-details-section">
        <div className="section-title">SNMP 检测结果</div>
        <div className="baseline-target-item">
          <span>返回结果</span>
          <span className="text-muted">{result.total_results || 0} 条</span>
        </div>
        {result.tool_error && (
          <div className="baseline-target-item">
            <span>工具提示</span>
            <span className="text-muted">{result.tool_error}</span>
          </div>
        )}
      </div>
    )
  }

  if (['baseline_check', 'linux_baseline'].includes(capability)) {
    const summary = result.summary || {}
    const baselineReason = result.error_detail?.error_reason || result.skip_reason || result.tool_error
    const baselineRemediation = result.error_detail?.remediation
    sections.push(
      <div key="baseline-summary" className={`result-details-section ${result.skipped ? 'warning-section' : 'success-section'}`}>
        <div className={`section-title ${result.skipped ? 'warning' : 'success'}`}>
          安全基线核查：{result.skipped ? (result.connection_error ? '无法连接目标' : '已跳过') : `未通过 ${summary.non_compliant || 0} 项`}
        </div>
        <div className="baseline-target-item">
          <span>目标</span>
          <span className="text-muted">{result.target || '-'}</span>
        </div>
        <div className="baseline-target-item">
          <span>操作系统</span>
          <span className="text-muted">{result.os_type || '未知'}</span>
        </div>
        {baselineReason && (
          <div className="baseline-target-item">
            <span>原因</span>
            <span className="text-muted">{baselineReason}</span>
          </div>
        )}
        {baselineRemediation && (
          <div className="baseline-target-item">
            <span>建议</span>
            <span className="text-muted">{baselineRemediation}</span>
          </div>
        )}
      </div>
    )
  }

  if (webDiscoveries.length > 0) {
    sections.push(
      <div key="web-discoveries" className="result-details-section">
        <div className="section-title">Web 路径/端点发现</div>
        {webDiscoveries.slice(0, 30).map((item, idx) => (
          <div key={idx} className="vulnerability-item">
            <Tag color="blue">{item.status || item.status_code || '发现'}</Tag>
            <span>{item.url || item.path || item.input || '未知端点'}</span>
          </div>
        ))}
      </div>
    )
  }

  if (compositeResults.length > 0) {
    const describeSubResult = (sub) => {
      const data = sub.data || {}
      if (data.scan_completed === false || data.success === false) {
        return `未完成/无响应${data.tool_error ? `：${data.tool_error}` : ''}`
      }
      if (['redis_check', 'mongodb_check', 'memcached_check'].includes(sub.capability)) {
        return data.unauthorized ? '存在未授权访问' : data.reachable === false ? '不可达/无响应，未发现未授权访问' : '未发现未授权访问'
      }
      if (sub.capability === 'mysql_check') {
        return data.empty_password ? '存在空口令' : data.reachable === false ? '不可达/无响应，未发现空口令' : '未发现空口令'
      }
      if (sub.capability === 'oracle_check') {
        const hasVersion = data.version_info && Object.keys(data.version_info).length > 0
        return hasVersion ? '存在版本信息泄露' : data.reachable === false ? '不可达/无响应，未发现版本信息泄露' : '未发现版本信息泄露'
      }
      if (sub.capability === 'nikto_scan') return `Web 问题 ${data.total_findings ?? data.findings?.length ?? 0} 个`
      if (sub.capability === 'scan_ports') return `明确开放 ${data.open_ports?.length || 0} 个，被过滤/未确认 ${data.filtered_count || data.filtered_ports?.length || 0} 个`
      if (sub.capability === 'scan_ssl') return `SSL 问题 ${data.issues?.length || 0} 个`
      if (sub.capability === 'scan_vulnerabilities') return `漏洞 ${data.total_findings ?? data.findings?.length ?? 0} 个`
      if (sub.capability === 'scan_weak_passwords') return `弱口令 ${data.found?.length || 0} 个`
      if (sub.capability === 'snmp_walk') return `SNMP 返回 ${data.total_results || 0} 条`
      return sub.error || '已完成'
    }
    sections.push(
      <div key="composite-results" className="result-details-section">
        <div className="section-title">组合扫描子任务</div>
        {compositeResults.map((group, groupIdx) => (
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
        ))}
      </div>
    )
  }
  
  // Port table
  if (openPorts.length > 0) {
    sections.push(
      <div key="ports" className="result-details-table">
        <div className="table-header"><span>明确开放端口详情</span></div>
        <Table
          dataSource={openPorts.map((port, idx) => ({ ...port, key: idx }))}
          columns={portColumns}
          pagination={openPorts.length > 10 ? { defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] } : false}
          size="small"
          className="port-table-compact"
        />
      </div>
    )
  }

  if (filteredPorts.length > 0) {
    sections.push(
      <div key="filtered-ports" className="result-details-table">
        <div className="table-header"><span>被过滤端口详情（未确认开放）</span></div>
        <div className="info-box warning" style={{ marginBottom: 12 }}>
          <InfoCircleFilled style={{ color: '#f59e0b', marginRight: 8 }} />
          <span>filtered/no-response 表示被过滤或无响应，不能当作开放端口。</span>
        </div>
        <Table
          dataSource={filteredPorts.map((port, idx) => ({ ...port, key: idx }))}
          columns={portColumns}
          pagination={filteredPorts.length > 10 ? { defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] } : false}
          size="small"
          className="port-table-compact"
        />
      </div>
    )
  }
  
  // Vulnerabilities
  if (vulnerabilities.length > 0) {
    sections.push(
      <div key="vulns" className="result-details-section">
        <div className="section-title">漏洞列表</div>
        {vulnerabilities.map((vuln, idx) => (
          <div key={idx} className="vulnerability-item">
            <Tag color={vuln.severity === 'critical' ? 'red' : vuln.severity === 'high' ? 'red' : 'orange'}>{severityLabel(vuln.severity, '未知')}</Tag>
            <span>{readableFindingText(vuln, '漏洞')}</span>
          </div>
        ))}
      </div>
    )
  }
  
  return <>{sections}</>
}


export { buildAssetSummary, buildAssetDetails }
