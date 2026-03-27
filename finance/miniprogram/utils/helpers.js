function normalizeKeyword(s) {
  return String(s || '').trim()
}

function getCodeByKeyword(keyword) {
  const text = normalizeKeyword(keyword)
  if (!text) return ''
  if (/^\d{6}$/.test(text)) return text
  const map = {
    '宁德时代': '300750',
    '茅台': '600519',
    '贵州茅台': '600519',
    '比亚迪': '002594'
  }
  return map[text] || ''
}

function formatSigned(n, digits = 2) {
  const v = Number(n)
  if (!Number.isFinite(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}`
}

module.exports = {
  normalizeKeyword,
  getCodeByKeyword,
  formatSigned
}

