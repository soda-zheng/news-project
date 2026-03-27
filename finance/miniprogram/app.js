const { getSelectedCode } = require('./utils/state')
const { getStoredUser, getLoginMeta } = require('./utils/auth')

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
  }
})

