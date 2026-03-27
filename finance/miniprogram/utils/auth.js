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

module.exports = {
  getStoredUser,
  setStoredUser,
  setLoginMeta,
  getLoginMeta
}
