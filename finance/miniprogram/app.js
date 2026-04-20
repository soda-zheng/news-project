const { getSelectedCode } = require('./utils/state')
const { getStoredUser, getLoginMeta, ensureLocalUserId, ensureBackendUserId } = require('./utils/auth')

App({
  globalData: {
    selectedCode: '300750',
    userInfo: null,
    loginMeta: null
  },
  onLaunch() {
    this.globalData.selectedCode = getSelectedCode()
    this.globalData.userInfo = getStoredUser()
    this.globalData.loginMeta = getLoginMeta()
    ensureLocalUserId()
    // 尽早完成 code->openid 绑定，便于后续自选云同步
    ensureBackendUserId()
  }
})

