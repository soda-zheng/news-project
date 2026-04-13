const { normalizeCode, setSelectedCode } = require('../../utils/state')
const { readWatchlistCodesRaw, saveWatchlistCodes } = require('../../utils/watchlistStorage')

function buildList(codes) {
  return (codes || []).map((code) => ({
    code,
    name: code,
    price: '¥--',
    tip: '自选',
  }))
}

Page({
  data: {
    list: [],
  },
  onShow() {
    const codes = readWatchlistCodesRaw()
    this.setData({ list: buildList(codes) })
  },
  saveCodes(codes) {
    saveWatchlistCodes(codes)
  },
  addTip() {
    wx.showModal({
      title: '添加自选',
      editable: true,
      placeholderText: '输入股票代码，如 600519',
      success: (res) => {
        if (!res.confirm) return
        const code = normalizeCode(res.content || '')
        if (!code || !/^\d{6}$/.test(code)) {
          wx.showToast({ title: '请输入6位代码', icon: 'none' })
          return
        }
        const prev = readWatchlistCodesRaw()
        if (prev.includes(code)) {
          wx.showToast({ title: '已在自选中', icon: 'none' })
          return
        }
        const next = [code, ...prev].slice(0, 30)
        this.saveCodes(next)
        this.setData({ list: buildList(next) })
      },
    })
  },
  pick(e) {
    const code = normalizeCode(String(e.currentTarget.dataset.code || ''))
    setSelectedCode(code)
    wx.navigateTo({ url: `/pages/aichat/index?code=${code}` })
  },
})
