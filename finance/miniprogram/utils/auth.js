const AUTH_USER_KEY = 'authUser'
const AUTH_LOGIN_META_KEY = 'authLoginMeta'

function getStoredUser() {
  const app = getApp()
  const globalUser = app && app.globalData ? app.globalData.userInfo : null
  if (globalUser) return globalUser
  const user = wx.getStorageSync(AUTH_USER_KEY)
  return user || null
}

function setStoredUser(user) {
  if (!user) return
  const app = getApp()
  if (app && app.globalData) app.globalData.userInfo = user
  try {
    wx.setStorageSync(AUTH_USER_KEY, user)
  } catch (e) {}
}

function setLoginMeta(meta) {
  if (!meta) return
  const app = getApp()
  if (app && app.globalData) app.globalData.loginMeta = meta
  try {
    wx.setStorageSync(AUTH_LOGIN_META_KEY, meta)
  } catch (e) {}
}

function getLoginMeta() {
  const app = getApp()
  const globalMeta = app && app.globalData ? app.globalData.loginMeta : null
  if (globalMeta) return globalMeta
  const meta = wx.getStorageSync(AUTH_LOGIN_META_KEY)
  return meta || null
}

function generateLocalUserId() {
  const hex = '0123456789abcdef'
  let s = ''
  for (let i = 0; i < 32; i++) s += hex[Math.floor(Math.random() * 16)]
  return s
}

/** 保证本地账号 id（与自选存储绑定，登出后仍保留以便自选不丢） */
function ensureLocalUserId() {
  let m = getLoginMeta() || {}
  if (!m.localUserId) {
    m = { ...m, localUserId: generateLocalUserId() }
    setLoginMeta(m)
  }
  return m.localUserId
}

/** 微信 getUserProfile 成功后调用：写入用户信息并合并游客自选 */
function applyWeChatUserProfile(userInfo) {
  if (!userInfo) return
  setStoredUser(userInfo)
  const id = ensureLocalUserId()
  const prev = getLoginMeta() || {}
  setLoginMeta({
    ...prev,
    localUserId: id,
    lastLoginAt: Date.now(),
    loginVia: 'wechat_profile',
  })
  try {
    const { mergeGuestWatchlistIntoUser } = require('./watchlistStorage')
    mergeGuestWatchlistIntoUser(id)
  } catch (e) {}
}

/** 仅清除微信展示信息；保留 localUserId，自选仍挂在同一本地账号上 */
function clearWeChatUserProfile() {
  const app = getApp()
  if (app && app.globalData) app.globalData.userInfo = null
  try {
    wx.removeStorageSync(AUTH_USER_KEY)
  } catch (e) {}
}

module.exports = {
  getStoredUser,
  setStoredUser,
  setLoginMeta,
  getLoginMeta,
  generateLocalUserId,
  ensureLocalUserId,
  applyWeChatUserProfile,
  clearWeChatUserProfile,
}
