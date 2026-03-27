const { profileMenus } = require('../../utils/data')

Page({
  data: {
    profileMenus
  },
  tapMenu(e) {
    const name = e.currentTarget.dataset.name || ''
    wx.showToast({ title: String(name), icon: 'none' })
  }
})

