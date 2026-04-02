function normalizeKeyword(s) {
  return String(s || '').trim()
}

function getCodeByKeyword(keyword) {
  const text = normalizeKeyword(keyword)
  if (!text) return ''
  if (/^\d{6}$/.test(text)) return text
  const map = {
    宁德时代: '300750',
    茅台: '600519',
    贵州茅台: '600519',
    比亚迪: '002594',
    中国石化: '600028',
    中石油: '601857',
    中国石油: '601857',
    蜜雪集团: '02097',
    蜜雪: '02097',
    古茗: '01364',
    盐湖股份: '000792',
    云天化: '600096',
    北大荒: '600598',
    苏垦农发: '601952'
  }
  const direct = map[text]
  if (direct) return direct
  const compact = text.replace(/\s+/g, '')
  for (const [k, v] of Object.entries(map)) {
    if (k.replace(/\s+/g, '') === compact) return v
  }
  return ''
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

