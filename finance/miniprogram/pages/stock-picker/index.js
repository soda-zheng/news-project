const { searchStocks, getHotTopics } = require('../../utils/api')
const HISTORY_KEY = 'stock_picker_history'
const HOT_CACHE_KEY = 'stock_picker_hot_sina_cache'
const HOT_CACHE_TTL_LIVE_MS = 10 * 60 * 1000
const HOT_CACHE_TTL_CLOSE_MS = 24 * 60 * 60 * 1000

function normalizeA6(raw) {
  const s = String(raw || '').trim()
  if (/^\d{6}$/.test(s)) return s
  const x = s.replace(/\.(SH|SZ|BJ)$/i, '').replace(/^(sh|sz|bj)/i, '')
  return /^\d{6}$/.test(x) ? x : ''
}

Page({
  data: {
    query: '',
    selectedCode: '',
    selectedName: '',
    hotList: [],
    hotQuoteHint: '',
    hotLoading: false,
    suggestList: [],
    suggestLoading: false,
    historyList: []
  },

  onLoad(query) {
    const q = query && query.q ? String(query.q) : ''
    this.setData({ query: q, historyList: this.loadHistory() })
    this.loadHot()
    if (q) this.fetchSuggest(q)
  },

  onBack() {
    wx.navigateBack()
  },

  loadHistory() {
    try {
      const saved = wx.getStorageSync(HISTORY_KEY)
      if (!Array.isArray(saved)) return []
      return saved.slice(0, 8)
    } catch (e) {
      return []
    }
  },

  saveHistory(code, name) {
    if (!code) return
    const row = { code, name: name || code }
    const cur = this.loadHistory().filter((x) => x.code !== code)
    const next = [row].concat(cur).slice(0, 8)
    try {
      wx.setStorageSync(HISTORY_KEY, next)
    } catch (e) {}
    this.setData({ historyList: next })
  },

  loadHot() {
    const cached = this.loadHotCache()
    if (cached.items && cached.items.length) {
      this.setData({
        hotList: cached.items,
        hotQuoteHint: cached.hint || '',
        hotLoading: false
      })
      return
    }
    this.setData({ hotLoading: true })
    getHotTopics(10, 'sina', false)
      .then((res) => {
        const d = res && res.data ? res.data : {}
        const rows = res && res.code === 200 && Array.isArray(d.items) ? d.items : []
        const quoteMode = String(d.quote_mode || 'live')
        const boardSource = String(d.board_source || '')
        let hotQuoteHint = ''
        if (quoteMode === 'last_close') {
          hotQuoteHint = '以下为上一交易日收盘快照，交易时段将自动更新'
        } else if (boardSource === 'sina_merged') {
          hotQuoteHint = '沪深A股涨幅榜（新浪 sh_a+sz_a 合并，与 demo2 一致）'
        } else if (boardSource === 'sina_merged_sync') {
          hotQuoteHint = '当前为新浪A股同步兜底（定时缓存未就绪）'
        }
        const hotList = rows
          .map((r) => {
            const code = normalizeA6(r.leader || r.code || r.symbol)
            if (!code) return null
            const pct = Number(r.pct_chg)
            const pctText = Number.isFinite(pct) ? (pct >= 0 ? `+${pct.toFixed(2)}%` : `${pct.toFixed(2)}%`) : '--'
            return {
              code,
              name: String(r.name || code),
              pct: Number.isFinite(pct) ? pct : 0,
              pctText
            }
          })
          .filter(Boolean)
          .slice(0, 10)
        this.setData({ hotList, hotQuoteHint, hotLoading: false })
        this.saveHotCache(hotList, hotQuoteHint, quoteMode)
        if (!hotList.length) {
          wx.showToast({ title: 'A股涨幅榜暂不可用', icon: 'none' })
        }
      })
      .catch(() => {
        this.setData({ hotLoading: false })
        wx.showToast({ title: '涨幅榜请求失败', icon: 'none' })
      })
  },

  loadHotCache() {
    try {
      const x = wx.getStorageSync(HOT_CACHE_KEY)
      if (!x || typeof x !== 'object') return { items: [], hint: '' }
      const ts = Number(x.ts || 0)
      const items = Array.isArray(x.items) ? x.items : []
      const hint = String(x.hint || '')
      const quoteMode = String(x.quoteMode || 'live')
      if (!items.length) return { items: [], hint: '' }
      const ttl = quoteMode === 'last_close' ? HOT_CACHE_TTL_CLOSE_MS : HOT_CACHE_TTL_LIVE_MS
      if (!ts || Date.now() - ts > ttl) return { items: [], hint: '' }
      return { items, hint }
    } catch (e) {
      return { items: [], hint: '' }
    }
  },

  saveHotCache(items, hint, quoteMode) {
    try {
      wx.setStorageSync(HOT_CACHE_KEY, {
        ts: Date.now(),
        items: Array.isArray(items) ? items : [],
        hint: String(hint || ''),
        quoteMode: String(quoteMode || 'live')
      })
    } catch (e) {}
  },

  onInput(e) {
    const q = String((e && e.detail && e.detail.value) || '')
    this.setData({ query: q })
    if (!q.trim()) {
      this.setData({ suggestList: [], suggestLoading: false })
      return
    }
    this.fetchSuggest(q)
  },

  fetchSuggest(q) {
    this.setData({ suggestLoading: true })
    searchStocks(q, 25)
      .then((res) => {
        const items = res && res.code === 200 && res.data && Array.isArray(res.data.items) ? res.data.items : []
        this.setData({ suggestList: items, suggestLoading: false })
      })
      .catch(() => this.setData({ suggestLoading: false }))
  },

  onPickRow(e) {
    const code = String(e.currentTarget.dataset.code || '').trim()
    const name = String(e.currentTarget.dataset.name || '').trim()
    if (!code) return
    this.setData({ selectedCode: code, selectedName: name, query: code })
  },

  onAnalyzeTap() {
    const q = String(this.data.query || '').trim()
    let code = normalizeA6(q) || String(this.data.selectedCode || '').trim()
    let name = String(this.data.selectedName || '').trim()
    if (!code) {
      const one = (this.data.suggestList || []).length === 1 ? this.data.suggestList[0] : null
      if (one && one.code) {
        code = String(one.code).trim()
        name = String(one.name || '').trim()
      }
    }
    if (!code) {
      wx.showToast({ title: '请选择一只股票', icon: 'none' })
      return
    }
    this.saveHistory(code, name)
    const eventChannel = this.getOpenerEventChannel && this.getOpenerEventChannel()
    if (eventChannel && eventChannel.emit) {
      eventChannel.emit('pickStock', { code, name })
    }
    wx.navigateBack()
  },

  onPickHistory(e) {
    const code = String(e.currentTarget.dataset.code || '').trim()
    const name = String(e.currentTarget.dataset.name || '').trim()
    if (!code) return
    this.setData({ selectedCode: code, selectedName: name, query: code })
    this.onAnalyzeTap()
  }
})
