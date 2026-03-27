const { profileMenus } = require('../../utils/data')
const { getStoredUser } = require('../../utils/auth')

Page({
  data: {
    profileMenus,
    userInfo: null
  },
  onShow() {
    this.setData({
      userInfo: getStoredUser()
    })
  },
  tapMenu(e) {
    const name = e.currentTarget.dataset.name || ''
    wx.showToast({ title: String(name), icon: 'none' })
  }
})

