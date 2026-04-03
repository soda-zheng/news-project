function normalizeCode(code) {
  const raw = String(code || '').trim().toLowerCase()
  if (!raw) return ''
  const m = raw.match(/^(?:sh|sz|bj)?(\d{6})$/)
  return m ? m[1] : raw
}

function getSelectedCode() {
  const app = getApp()
  const globalCode = app && app.globalData ? app.globalData.selectedCode : ''
  const stored = wx.getStorageSync('selectedCode')
  return normalizeCode(globalCode || stored || '') || ''
}

function setSelectedCode(code) {
  const normalized = normalizeCode(code)
  if (!normalized) return ''
  const app = getApp()
  if (app && app.globalData) app.globalData.selectedCode = normalized
  try {
    wx.setStorageSync('selectedCode', normalized)
  } catch (e) {}
  return normalized
}

module.exports = {
  normalizeCode,
  getSelectedCode,
  setSelectedCode
}
