const { watchList } = require('../../utils/data')
const { normalizeCode, setSelectedCode } = require('../../utils/state')

const STORAGE_KEY = 'watchlistCodes'

function getDefaultCodes() {
  return watchList.map((x) => x.code)
}

function buildList(codes) {
  return (codes || []).map((code) => ({
    code,
    name: code,
    price: '¥--',
    tip: '自选'
  }))
}

Page({
  data: {
    list: []
  },
  onShow() {
    const codes = this.getCodes()
    this.setData({ list: buildList(codes) })
  },
  getCodes() {
    try {
      const raw = wx.getStorageSync(STORAGE_KEY)
      if (Array.isArray(raw) && raw.length) return raw.map((x) => normalizeCode(x)).filter(Boolean)
    } catch (e) {}
    return getDefaultCodes()
  },
  saveCodes(codes) {
    try { wx.setStorageSync(STORAGE_KEY, codes) } catch (e) {}
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
        const prev = this.getCodes()
        if (prev.includes(code)) {
          wx.showToast({ title: '已在自选中', icon: 'none' })
          return
        }
        const next = [code, ...prev].slice(0, 30)
        this.saveCodes(next)
        this.setData({ list: buildList(next) })
      }
    })
  },
  pick(e) {
    const code = normalizeCode(String(e.currentTarget.dataset.code || ''))
    setSelectedCode(code)
    wx.navigateTo({ url: `/pages/aichat/index?code=${code}` })
  }
})

