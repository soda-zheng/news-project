const { stockData, watchList } = require('../../utils/data')

function buildList() {
  return watchList.map((x) => {
    const s = stockData[x.code] || {}
    return {
      code: x.code,
      name: s.name || x.code,
      price: s.price || '—',
      tip: x.tip
    }
  })
}

Page({
  data: {
    list: buildList()
  },
  addTip() {
    wx.showToast({ title: '演示版：暂未开放添加', icon: 'none' })
  },
  pick(e) {
    const code = String(e.currentTarget.dataset.code || '')
    const app = getApp()
    if (app && app.globalData) app.globalData.selectedCode = code
    try { wx.setStorageSync('selectedCode', code) } catch (err) {}
    wx.switchTab({ url: '/pages/research/index' })
  }
})

