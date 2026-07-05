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
  warning: { key: 'warning', label: '警告/未完成', color: 'warning', risk: 'medium' },
  failed: { key: 'failed', label: '失败', color: 'error', risk: 'high' },
  skipped: { key: 'skipped', label: '已跳过', color: 'default', risk: 'medium' },
}

const inferResultState = (assetData = {}) => {
  const result = assetData.result || assetData.data || assetData
  const explicit = String(assetData.display_status || assetData.status || result.status || '').toLowerCase()
  if (['failed', 'failure', 'error'].includes(explicit) || assetData.error || result.error_detail) return RESULT_STATES.failed
  if (['skipped', 'cancelled', 'canceled'].includes(explicit) || result.skipped) return RESULT_STATES.skipped
  if (
    ['warning', 'partial', 'incomplete', 'timeout', 'unreachable'].includes(explicit) ||
    result.scan_completed === false ||
    result.reachable === false ||
    result.success === false
  ) {
    return RESULT_STATES.warning
  }
  return RESULT_STATES.success
}

export { safeJson, hexToRgba, RESULT_STATES, inferResultState }
