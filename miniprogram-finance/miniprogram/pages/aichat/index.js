const { stockData } = require('../../utils/data')
const { getCodeByKeyword } = require('../../utils/helpers')

function pickStock(code) {
  const c = String(code || '').trim()
  return stockData[c] || stockData['300750']
}

Page({
  data: {
    keyword: '',
    currentCode: '300750',
    current: pickStock('300750')
  },
  onLoad(query) {
    const qCode = query?.code ? String(query.code) : ''
    const app = getApp()
    const globalCode = app?.globalData?.selectedCode || wx.getStorageSync('selectedCode') || '300750'
    const code = qCode || globalCode
    this.applyCode(code)
  },
  onKeywordInput(e) {
    this.setData({ keyword: e.detail.value })
  },
  analyzeByInput() {
    const code = getCodeByKeyword(this.data.keyword)
    if (!code || !stockData[code]) {
      wx.showToast({ title: '暂不支持该股票', icon: 'none' })
      return
    }
    this.applyCode(code)
  },
  goDialog() {
    wx.navigateTo({ url: `/pages/aidialog/index?code=${this.data.currentCode}` })
  },
  goBack() {
    const pages = getCurrentPages()
    if (pages.length > 1) {
      wx.navigateBack({ delta: 1 })
      return
    }
    wx.switchTab({ url: '/pages/research/index' })
  },
  applyCode(code) {
    const c = String(code)
    const app = getApp()
    if (app?.globalData) app.globalData.selectedCode = c
    try { wx.setStorageSync('selectedCode', c) } catch (e) {}
    this.setData({
      currentCode: c,
      current: pickStock(c),
      keyword: c
    })
  }
})

