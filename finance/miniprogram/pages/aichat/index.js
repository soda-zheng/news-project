const { stockData } = require('../../utils/data')
const { getCodeByKeyword } = require('../../utils/helpers')
const { getQuote, postStockInsight, getHotTopics } = require('../../utils/api')
const { getSelectedCode, setSelectedCode, normalizeCode } = require('../../utils/state')

function pickStock(code) {
  const c = String(code || '').trim()
  return stockData[c] || stockData['300750']
}

Page({
  data: {
    keyword: '',
    currentCode: '300750',
    current: pickStock('300750'),
    loading: false
  },
  onLoad(query) {
    const qCode = query && query.code ? String(query.code) : ''
    const code = normalizeCode(qCode) || getSelectedCode()
    this.applyCode(code)
    this.refreshCurrentAnalysis(code)
  },
  onKeywordInput(e) {
    this.setData({ keyword: e.detail.value })
  },
  async analyzeByInput() {
    const input = String(this.data.keyword || '').trim()
    if (!input) return
    const code = normalizeCode(getCodeByKeyword(input) || input)
    this.applyCode(code)
    await this.refreshCurrentAnalysis(code)
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
    wx.reLaunch({ url: '/pages/portal/index' })
  },
  async refreshCurrentAnalysis(code) {
    const c = normalizeCode(code) || this.data.currentCode
    const fallback = pickStock(c)
    this.setData({ loading: true })
    try {
      const [quoteRes, boardRes] = await Promise.all([getQuote(c), getHotTopics(10)])
      const quote = quoteRes && quoteRes.code === 200 ? quoteRes.data : null
      const boardTop = boardRes && boardRes.code === 200 ? (boardRes.data?.items || []).slice(0, 10) : []
      const insightRes = await postStockInsight({
        name: quote?.name || fallback.name,
        leader: quote?.symbol || c,
        code: c,
        pct_chg: quote?.pct_chg || 0,
        rank: 1,
        avg_pct: 0,
        board_top: boardTop
      })
      const lines = insightRes?.data?.lines || []
      const merged = {
        ...fallback,
        fullName: `${quote?.name || fallback.name || c} ${c}`,
        price: quote ? `¥${quote.price}` : fallback.price,
        info: quote
          ? `${quote.pct_chg >= 0 ? '+' : ''}${quote.pct_chg}% | 今开${quote.open} 最高${quote.high} 最低${quote.low}`
          : fallback.info,
        ai: lines.length ? lines : fallback.ai
      }
      this.setData({ current: merged })
    } catch (e) {
      wx.showToast({ title: '接口异常，已展示本地数据', icon: 'none' })
      this.setData({ current: fallback })
    } finally {
      this.setData({ loading: false })
    }
  },
  applyCode(code) {
    const c = normalizeCode(code) || '300750'
    setSelectedCode(c)
    this.setData({
      currentCode: c,
      current: pickStock(c),
      keyword: c
    })
  }
})

