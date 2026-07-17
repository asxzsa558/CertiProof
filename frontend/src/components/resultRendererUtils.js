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
  success: { key: 'success', label: '成功', color: 'success', risk: 'low' },
  warning: { key: 'warning', label: '未完成/无法判定', color: 'warning', risk: 'medium' },
  failed: { key: 'failed', label: '失败', color: 'error', risk: 'high' },
  skipped: { key: 'skipped', label: '已跳过', color: 'default', risk: 'medium' },
}

const SEVERITY_LABELS = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '提示',
}

const severityLabel = (value, fallback = '提示') => SEVERITY_LABELS[String(value || '').toLowerCase()] || value || fallback

const inferResultState = (assetData = {}) => {
  const result = assetData.result || assetData.data || assetData
  const explicit = String(assetData.display_status || assetData.status || result.status || '').toLowerCase()
  if (['failed', 'failure', 'error'].includes(explicit)) return RESULT_STATES.failed
  if (['skipped', 'cancelled', 'canceled'].includes(explicit) || result.skipped) return RESULT_STATES.skipped
  if (
    ['warning', 'partial', 'incomplete', 'timeout', 'unreachable'].includes(explicit) ||
    result.scan_completed === false ||
    result.reachable === false ||
    result.success === false
  ) {
    return RESULT_STATES.warning
  }
  if (assetData.error || result.error_detail) return RESULT_STATES.failed
  return RESULT_STATES.success
}

const readableFindingText = (finding, fallback = '安全发现项') => {
  if (typeof finding === 'string') return finding
  if (!finding || typeof finding !== 'object') return fallback
  return finding.description || finding.finding || finding.message || finding.name || finding.info?.name || finding.id || finding.template_id || fallback
}

export { safeJson, hexToRgba, RESULT_STATES, SEVERITY_LABELS, severityLabel, inferResultState, readableFindingText }
