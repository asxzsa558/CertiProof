const safeJson = (value) => {
  if (value === undefined || value === null) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const hexToRgba = (hex, alpha = 0.2) => {
  const value = String(hex || '').replace('#', '')
  if (!/^[0-9a-f]{6}$/i.test(value)) return `rgba(255, 255, 255, ${alpha})`
  const channels = value.match(/.{2}/g).map(part => parseInt(part, 16))
  return `rgba(${channels.join(', ')}, ${alpha})`
}

const RESULT_STATES = {
  success: { key: 'success', label: '检测完成', color: 'success', risk: 'low' },
  risk: { key: 'risk', label: '发现问题', color: 'error', risk: 'high' },
  warning: { key: 'warning', label: '检测不完整', color: 'warning', risk: 'medium' },
  not_applicable: { key: 'not_applicable', label: '不适用', color: 'default', risk: 'low' },
  failed: { key: 'failed', label: '执行失败', color: 'error', risk: 'high' },
}

const SEVERITY_LABELS = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '提示',
}

const severityLabel = (value, fallback = '提示') => SEVERITY_LABELS[String(value || '').toLowerCase()] || value || fallback

const hasItems = (value) => Array.isArray(value)
  ? value.length > 0
  : Boolean(value && typeof value === 'object' && Object.keys(value).length)

const hasSecurityIssues = (result = {}) => {
  if (!result || typeof result !== 'object') return false
  if (result.compliant === false || result.vulnerable === true || result.unauthorized === true || result.empty_password === true) return true
  if (['fail', 'partial', 'vulnerable', 'non_compliant'].includes(String(result.judgment || '').toLowerCase())) return true
  if (['total_findings', 'total_issues', 'non_compliant'].some(key => Number(result[key] || result.summary?.[key]) > 0)) return true
  if (['findings', 'vulnerabilities', 'issues', 'found', 'credentials', 'found_credentials', 'injection_points', 'failed_checks', 'weak_passwords']
    .some(key => hasItems(result[key]))) return true
  const nested = Array.isArray(result.sub_results)
    ? result.sub_results
    : Object.values(result.sub_results || {})
  return nested.some(item => hasSecurityIssues(item?.result || item?.data || item))
}

const inferResultState = (assetData = {}) => {
  const result = assetData.result || assetData.data || assetData
  const capability = assetData.capability || result.capability
  const explicit = String(assetData.display_status || assetData.status || result.status || '').toLowerCase()
  if (['failed', 'failure', 'error'].includes(explicit)) return RESULT_STATES.failed
  if (explicit === 'not_applicable' || result.outcome === 'not_applicable' || result.applicable === false) return RESULT_STATES.not_applicable
  if (hasSecurityIssues(result)) return RESULT_STATES.risk
  if (['skipped', 'cancelled', 'canceled'].includes(explicit) || result.skipped) return RESULT_STATES.warning
  if (
    ['warning', 'partial', 'incomplete', 'timeout', 'unreachable'].includes(explicit) ||
    result.scan_completed === false ||
    result.reachable === false ||
    result.success === false
  ) {
    return RESULT_STATES.warning
  }
  if (assetData.error || result.error_detail) return RESULT_STATES.failed
  if (
    capability === 'scan_vulnerabilities' &&
    result.reachable !== true &&
    !(result.findings || []).length
  ) {
    return RESULT_STATES.warning
  }
  return RESULT_STATES.success
}

const readableFindingText = (finding, fallback = '安全发现项') => {
  if (typeof finding === 'string') return finding
  if (!finding || typeof finding !== 'object') return fallback
  return finding.description || finding.finding || finding.message || finding.name || finding.info?.name || finding.id || finding.template_id || fallback
}

export { safeJson, hexToRgba, RESULT_STATES, SEVERITY_LABELS, severityLabel, hasSecurityIssues, inferResultState, readableFindingText }
