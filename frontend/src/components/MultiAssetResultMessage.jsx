import { useState } from 'react'
import { Tag, Collapse } from 'antd'
import {
  MonitorOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  ExclamationCircleFilled,
} from '@ant-design/icons'
import ToolResultCard from './ToolResultCard'
import { CAPABILITY_NAMES, TOOL_CATALOG } from './toolCatalog'
import { safeJson, RESULT_STATES, inferResultState } from './resultRendererUtils'
import { buildAssetSummary, buildAssetDetails } from './AssetResultSections'

export default function MultiAssetResultMessage({ msg, compact = false }) {
  const [assetResultFilters, setAssetResultFilters] = useState({})
  const resultKey = msg.id || msg.taskId || `${msg.content || 'result'}-multi`

  const renderMultiAssetResult = (msg, options = {}) => {
    const scanResults = msg.scanResults || {}
    const assetResults = scanResults.asset_results || {}
    const quality = scanResults.quality || {}
    
    const totalAssets = Object.keys(assetResults).length
    const getDisplayStatus = (assetData) => inferResultState(assetData).key
    const successCount = Object.values(assetResults).filter(r => getDisplayStatus(r) === 'success').length
    const riskCount = Object.values(assetResults).filter(r => getDisplayStatus(r) === 'risk').length
    const warningCount = Object.values(assetResults).filter(r => getDisplayStatus(r) === 'warning').length
    const notApplicableCount = Object.values(assetResults).filter(r => getDisplayStatus(r) === 'not_applicable').length
    const failedCount = Object.values(assetResults).filter(r => getDisplayStatus(r) === 'failed').length
    const effectiveQualityVerdict = failedCount === totalAssets && totalAssets > 0
      ? 'failed'
      : failedCount > 0
        ? 'partial'
        : warningCount > 0
          ? 'conditional'
          : quality.verdict
    const capabilitySet = Array.from(new Set(Object.values(assetResults).map(r => r.capability).filter(Boolean)))
    const mainCapability = capabilitySet.length === 1 ? capabilitySet[0] : 'full_compliance_scan'
    const mainTool = mainCapability
    const overallStatus = failedCount === totalAssets && totalAssets > 0
      ? 'failed'
      : failedCount > 0 || warningCount > 0
        ? 'warning'
        : riskCount > 0 ? 'risk' : notApplicableCount === totalAssets && totalAssets > 0 ? 'not_applicable' : 'success'
    const statusTextMap = Object.fromEntries(Object.entries(RESULT_STATES).map(([key, value]) => [key, value.label]))
    const assetResultFilter = assetResultFilters[resultKey] || 'all'
    const setAssetResultFilter = (value) => setAssetResultFilters(prev => ({ ...prev, [resultKey]: value }))

    const assetStatusConfig = {
      success: { color: 'success', text: '检测完成', icon: <CheckCircleFilled /> },
      risk: { color: 'error', text: '发现问题', icon: <CloseCircleFilled /> },
      warning: { color: 'warning', text: '检测不完整', icon: <ExclamationCircleFilled /> },
      not_applicable: { color: 'default', text: '不适用', icon: <ExclamationCircleFilled /> },
      failed: { color: 'error', text: '执行失败', icon: <CloseCircleFilled /> },
    }
    const assetEntries = Object.entries(assetResults)
    const filteredAssetEntries = assetResultFilter === 'all'
      ? assetEntries
      : assetEntries.filter(([, assetData]) => getDisplayStatus(assetData) === assetResultFilter)
    const auditFilters = [
      { key: 'all', label: '全部', count: totalAssets },
      { key: 'success', label: '检测完成', count: successCount },
      { key: 'risk', label: '发现问题', count: riskCount },
      { key: 'warning', label: '检测不完整', count: warningCount },
      { key: 'not_applicable', label: '不适用', count: notApplicableCount },
      { key: 'failed', label: '执行失败', count: failedCount },
    ]

    const riskLevel = (assetData) => {
      const result = assetData.result || {}
      const findings = result.findings || []
      const weakPasswords = result.found || result.weak_passwords || []
      const state = inferResultState(assetData)
      if (state.key === 'failed') return { label: '高', className: 'high' }
      if (weakPasswords.length || findings.some(item => ['critical', 'high'].includes(item.severity))) return { label: '高', className: 'high' }
      if (state.key === 'risk') return { label: '高', className: 'high' }
      if (state.key === 'warning') return { label: '中', className: 'medium' }
      if (state.key === 'not_applicable') return { label: '无', className: 'low' }
      if ((result.open_ports || []).length || (result.filtered_ports || []).length || findings.length) return { label: '中', className: 'medium' }
      return { label: '低', className: 'low' }
    }

    const metricText = (assetData) => {
      const result = assetData.result || {}
      const capability = assetData.capability
      if (capability === 'scan_ports' || capability === 'masscan_scan') {
        return `明确开放 ${result.open_ports?.length || 0}，被过滤/未确认 ${result.filtered_count || result.filtered_ports?.length || 0}`
      }
      if (capability === 'scan_ssl') {
        if (result.outcome === 'not_applicable') return '目标未提供 TLS 服务，本项不适用'
        return result.scan_completed === false || result.reachable === false
          ? 'SSL/TLS 未完成'
          : `SSL 问题 ${result.issues?.length || 0}，漏洞 ${result.vulnerabilities?.length || 0}`
      }
      if (capability === 'scan_vulnerabilities') {
        if (result.coverage_limited) return result.tool_error || '受防护限制，漏洞检测不完整'
        if (result.scan_completed === false || (result.reachable !== true && !(result.findings || []).length)) {
          return '目标不可达或未验证，无法判断漏洞'
        }
        return `漏洞 ${result.total_findings ?? result.findings?.length ?? 0}`
      }
      if (capability === 'scan_weak_passwords') return `弱口令 ${result.found?.length || 0}`
      if (capability === 'database_security_scan') {
        const summary = result.summary || {}
        return `子项成功 ${summary.success || 0}/${summary.total || result.sub_results?.length || 0}`
      }
      if (result.sub_results) {
        const summary = result.summary || {}
        return `子项成功 ${summary.success || 0}，失败 ${summary.failed || 0}，跳过 ${summary.skipped || 0}`
      }
      if (capability === 'baseline_check' || capability === 'linux_baseline') {
        return result.skipped ? (result.connection_error ? '无法连接' : '已跳过') : `未通过 ${result.summary?.non_compliant || 0} 项`
      }
      if (['nikto_scan', 'gobuster_scan', 'ffuf_scan'].includes(capability) && result.scan_completed === false) {
        return result.tool_error || 'Web 检测未完整执行'
      }
      if (capability === 'nikto_scan') return `Web 问题 ${result.total_findings ?? result.findings?.length ?? 0}`
      return assetData.error || '已完成'
    }

    const buildMultiAssetCopyText = () => {
      const lines = []
      if (msg.content) lines.push(msg.content)
      lines.push(`总资产数: ${totalAssets}`)
      lines.push(`检测完成: ${successCount}`)
      lines.push(`发现问题: ${riskCount}`)
      lines.push(`检测不完整: ${warningCount}`)
      lines.push(`不适用: ${notApplicableCount}`)
      lines.push(`执行失败: ${failedCount}`)
      if (effectiveQualityVerdict) lines.push(`结果可信度: ${effectiveQualityVerdict} - ${quality.note || ''}`)
      lines.push(`检测工具: ${capabilitySet.map(c => CAPABILITY_NAMES[c] || c).join('、') || '安全检测'}`)
      lines.push('')

      Object.entries(assetResults).forEach(([target, assetData], index) => {
        const displayStatus = getDisplayStatus(assetData)
        const capability = assetData.capability
        lines.push(`资产 ${index + 1}: ${target}`)
        lines.push(`状态: ${statusTextMap[displayStatus] || displayStatus}`)
        lines.push(`工具: ${CAPABILITY_NAMES[capability] || capability}`)
        lines.push(`摘要: ${metricText(assetData)}`)
        if (assetData.error) lines.push(`错误: ${assetData.error}`)
        if (assetData.error_detail) lines.push(`错误详情: ${safeJson(assetData.error_detail)}`)
        if (assetData.result) lines.push(`结果:\n${safeJson(assetData.result)}`)
        lines.push('')
      })

      return lines.join('\n').trim()
    }

    // Map capability to ToolResultCard tool name
    const capabilityToTool = {
      ...Object.fromEntries(TOOL_CATALOG.map(tool => [tool.capability, tool.capability])),
      ping_asset: 'ping_host',
      linux_baseline: 'baseline_check',
      testssl_scan: 'scan_ssl',
      nuclei_scan: 'scan_vulnerabilities',
      hydra_bruteforce: 'scan_weak_passwords',
    }

    return (
      <div className="scan-animation-fade-in">
        {/* 统计摘要 */}
        <div className="result-summary multi-asset-summary">
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(99, 102, 241, 0.2)' }}>
              <MonitorOutlined style={{ color: '#6366f1' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">总资产数</div>
              <div className="summary-value">{totalAssets}</div>
            </div>
          </div>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(16, 185, 129, 0.2)' }}>
              <CheckCircleFilled style={{ color: '#10b981' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">检测完成</div>
              <div className="summary-value">{successCount}</div>
            </div>
          </div>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.2)' }}>
              <CloseCircleFilled style={{ color: '#ef4444' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">发现问题</div>
              <div className="summary-value">{riskCount}</div>
            </div>
          </div>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(245, 158, 11, 0.2)' }}>
              <ExclamationCircleFilled style={{ color: '#f59e0b' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">检测不完整</div>
              <div className="summary-value">{warningCount}</div>
            </div>
          </div>
          <div className="summary-item">
            <div className="summary-icon" style={{ background: 'rgba(239, 68, 68, 0.2)' }}>
              <CloseCircleFilled style={{ color: '#ef4444' }} />
            </div>
            <div className="summary-content">
              <div className="summary-title">执行失败</div>
              <div className="summary-value">{failedCount}</div>
            </div>
          </div>
        </div>
        
        <ToolResultCard
          tool={mainTool}
          status={overallStatus}
          summary={
            <div className="asset-unified-summary">
              <div className="baseline-target-item">
                <span>检测工具</span>
                <span className="text-muted">{capabilitySet.map(c => CAPABILITY_NAMES[c] || c).join('、') || '安全检测'}</span>
              </div>
              <div className="baseline-target-item">
                <span>资产范围</span>
                <span className="text-muted">{Object.keys(assetResults).join('、')}</span>
              </div>
            </div>
          }
          details={
            <div className="asset-audit-panel">
              <div className="asset-audit-toolbar">
                <div>
                  <strong>多资产审计矩阵</strong>
                  <span>{filteredAssetEntries.length}/{totalAssets} 个资产</span>
                </div>
                <div className="asset-audit-filters">
                  {auditFilters.map(filter => (
                    <button
                      type="button"
                      key={filter.key}
                      className={assetResultFilter === filter.key ? 'active' : ''}
                      onClick={() => setAssetResultFilter(filter.key)}
                    >
                      {filter.label}<span>{filter.count}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="asset-audit-matrix">
                <div className="asset-audit-row head">
                  <span>资产/IP</span>
                  <span>状态</span>
                  <span>风险</span>
                  <span>工具</span>
                  <span>摘要</span>
                </div>
                {filteredAssetEntries.length ? filteredAssetEntries.map(([target, assetData]) => {
                  const displayStatus = getDisplayStatus(assetData)
                  const capability = assetData.capability
                  const currentStatus = assetStatusConfig[displayStatus] || assetStatusConfig.success
                  const risk = riskLevel(assetData)
                  return (
                    <div key={target} className={`asset-audit-row ${displayStatus}`}>
                      <strong>{target}</strong>
                      <Tag color={currentStatus.color} icon={currentStatus.icon}>{currentStatus.text}</Tag>
                      <span className={`risk-pill ${risk.className}`}>{risk.label}</span>
                      <span>{CAPABILITY_NAMES[capability] || capability}</span>
                      <em>{metricText(assetData)}</em>
                    </div>
                  )
                }) : (
                  <div className="asset-audit-empty">当前筛选条件下暂无资产结果</div>
                )}
              </div>

              <Collapse
                className="asset-result-collapse"
                bordered={false}
                defaultActiveKey={filteredAssetEntries.length <= 2 ? filteredAssetEntries.map(([target]) => target) : []}
                items={filteredAssetEntries.map(([target, assetData]) => {
                  const displayStatus = getDisplayStatus(assetData)
                  const capability = assetData.capability
                  const currentStatus = assetStatusConfig[displayStatus] || assetStatusConfig.success
                  const risk = riskLevel(assetData)
                  return {
                    key: target,
                    label: (
                      <div className="asset-collapse-label">
                        <span className="asset-collapse-target">{target}</span>
                        <Tag color={currentStatus.color} icon={currentStatus.icon}>{currentStatus.text}</Tag>
                        <span className={`risk-pill ${risk.className}`}>{risk.label}风险</span>
                        <span className="asset-collapse-metric">{metricText(assetData)}</span>
                      </div>
                    ),
                    children: (
                      <div className="asset-collapse-body">
                        <div className="asset-result-identity">
                          <div className="baseline-target-item">
                            <span>资产/IP</span>
                            <span className="text-muted">{target}</span>
                          </div>
                          <div className="baseline-target-item">
                            <span>检测工具</span>
                            <span className="text-muted">{CAPABILITY_NAMES[capability] || capability}</span>
                          </div>
                        </div>
                        {buildAssetSummary(assetData, capability)}
                        {buildAssetDetails(assetData, capability)}
                      </div>
                    ),
                  }
                })}
              />
            </div>
          }
          copyText={buildMultiAssetCopyText()}
          defaultExpanded={!options.compact}
        />
      </div>
    )
  }

  return renderMultiAssetResult(msg, { compact })
}
