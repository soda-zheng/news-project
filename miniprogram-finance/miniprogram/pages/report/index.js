const { reportTips } = require('../../utils/data')

Page({
  data: {
    reportTips
  },
  showTip() {
    wx.showToast({ title: '目前是静态演示版', icon: 'none' })
  }
})

