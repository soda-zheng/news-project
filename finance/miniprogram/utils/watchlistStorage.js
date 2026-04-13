/**
 * 自选列表存储：与登录 meta 中的 localUserId 绑定；未登录为 guest。
 * 兼容旧 key portal_watchlist_codes。
 */
const { getLoginMeta } = require('./auth')

const LEGACY_WATCHLIST_KEY = 'portal_watchlist_codes'

function getWatchlistScope() {
  const m = getLoginMeta() || {}
  if (m.localUserId) return m.localUserId
  return 'guest'
}

function getWatchlistStorageKey() {
  return `portal_wl_${getWatchlistScope()}`
}

function readWatchlistCodesRaw() {
  const key = getWatchlistStorageKey()
  try {
    const cur = wx.getStorageSync(key)
    if (Array.isArray(cur) && cur.length) return cur.map((c) => String(c).trim()).filter(Boolean)
  } catch (e) {}
  try {
    const old = wx.getStorageSync(LEGACY_WATCHLIST_KEY)
    if (Array.isArray(old) && old.length) {
      const codes = old.map((c) => String(c).trim()).filter(Boolean)
      try {
        wx.setStorageSync(key, codes)
      } catch (e2) {}
      return codes
    }
  } catch (e3) {}
  return []
}

function saveWatchlistCodes(codes) {
  const arr = Array.isArray(codes) ? codes.map((c) => String(c).trim()).filter(Boolean) : []
  try {
    wx.setStorageSync(getWatchlistStorageKey(), arr)
  } catch (e) {}
}

/** 首次微信授权登录后：游客自选合并进当前账号空间 */
function mergeGuestWatchlistIntoUser(userLocalId) {
  if (!userLocalId) return
  let guest = []
  try {
    const g = wx.getStorageSync('portal_wl_guest')
    guest = Array.isArray(g) ? g.map((c) => String(c).trim()).filter(Boolean) : []
  } catch (e) {}
  if (!guest.length) return
  const userKey = `portal_wl_${userLocalId}`
  let user = []
  try {
    const u = wx.getStorageSync(userKey)
    user = Array.isArray(u) ? u.map((c) => String(c).trim()).filter(Boolean) : []
  } catch (e2) {}
  const seen = new Set(user)
  guest.forEach((c) => {
    if (c && !seen.has(c)) {
      seen.add(c)
      user.push(c)
    }
  })
  try {
    wx.setStorageSync(userKey, user)
  } catch (e3) {}
}

module.exports = {
  LEGACY_WATCHLIST_KEY,
  getWatchlistStorageKey,
  readWatchlistCodesRaw,
  saveWatchlistCodes,
  mergeGuestWatchlistIntoUser,
}
