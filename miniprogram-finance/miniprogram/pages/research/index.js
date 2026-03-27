const { stockData, hotTags, hotTopicsTop10, featuredNews } = require('../../utils/data')
const { formatSigned } = require('../../utils/helpers')

function pickStock(code) {
  const c = String(code || '').trim()
  return stockData[c] || stockData['300750']
}

Page({
  data: {
    hotTags,
    hotTopicsTop10,
    featuredNews,
    heroStock: pickStock('300750')
  },
  onShow() {
    const app = getApp()
    const code = app?.globalData?.selectedCode || wx.getStorageSync('selectedCode') || '300750'
    this.setData({ heroStock: pickStock(code) })
  },
  goAiChat() {
    wx.navigateTo({ url: '/pages/aichat/index' })
  },
  pickTopic(e) {
    const leader = e.currentTarget.dataset.leader
    if (leader && stockData[String(leader)]) {
      const code = String(leader)
      const app = getApp()
      if (app?.globalData) app.globalData.selectedCode = code
      try { wx.setStorageSync('selectedCode', code) } catch (err) {}
      wx.navigateTo({ url: `/pages/aichat/index?code=${code}` })
    } else {
      wx.showToast({ title: '该条目暂无个股演示数据', icon: 'none' })
    }
  },
  formatSigned
})

