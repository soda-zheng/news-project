const { stockData } = require('../../utils/data')
const { getCodeByKeyword } = require('../../utils/helpers')
const { getQuote, postResearchAnalyze } = require('../../utils/api')
const { getSelectedCode, setSelectedCode, normalizeCode } = require('../../utils/state')

function pickStock(code) {
  const c = String(code || '').trim()
  return stockData[c] || stockData['300750']
}

function buildId() {
  return `${Date.now()}-${Math.floor(Math.random() * 10000)}`
}

function buildAnswer(stock, question) {
  const q = String(question || '').toLowerCase()
  if (q.includes('风险')) {
    return `关于 ${stock.name} 的主要风险：1）行业竞争加剧；2）政策与需求波动；3）若价格跌破关键位，短期波动会放大。当前建议结合仓位做分批决策。`
  }
  if (q.includes('估值') || q.includes('贵') || q.includes('便宜')) {
    return `${stock.name} 当前在 ${stock.level} 区域，趋势为“${stock.trend}”。估值判断建议结合PE/PB与业绩增速一起看，单看价格高低不够准确。`
  }
  if (q.includes('支撑') || q.includes('压力') || q.includes('技术')) {
    const first = stock.suggest && stock.suggest[0] ? stock.suggest[0] : '关注关键价位'
    return `技术面看，${stock.name} 目前为“${stock.trend}”，波动率“${stock.vol}”。${first}，并观察是否放量确认。`
  }
  if (q.includes('新闻') || q.includes('政策')) {
    const topNews = (stock.news || []).slice(0, 2).join('；')
    return `近期影响 ${stock.name} 的新闻/政策要点：${topNews}。建议你重点关注后续政策持续性和资金是否跟随。`
  }
  return `基于当前数据，${stock.name} 价格 ${stock.price}，处于 ${stock.level}，趋势为 ${stock.trend}。如果你告诉我持仓成本和风险偏好，我可以给你更细的分场景建议。`
}

Page({
  data: {
    keyword: '',
    currentCode: '300750',
    current: pickStock('300750'),
    question: '',
    messages: [],
    toViewId: '',
    quickQuestions: ['这只股票短期怎么看？', '它的主要风险是什么？', '现在估值贵不贵？', '支撑位和压力位怎么看？'],
    sending: false
  },
  onLoad(query) {
    const qCode = query && query.code ? String(query.code) : ''
    const code = normalizeCode(qCode) || getSelectedCode()
    this.applyCode(code)
    this.bootstrapChat(pickStock(code))
  },
  onKeywordInput(e) {
    this.setData({ keyword: e.detail.value })
  },
  onQuestionInput(e) {
    this.setData({ question: e.detail.value })
  },
  async analyzeByInput() {
    const input = String(this.data.keyword || '').trim()
    if (!input) return
    const code = normalizeCode(getCodeByKeyword(input) || input)
    this.applyCode(code)
    const next = await this.enrichCurrentStock(code)
    this.bootstrapChat(next)
  },
  useQuickQuestion(e) {
    const q = e.currentTarget.dataset.q || ''
    this.setData({ question: q })
    this.sendQuestion()
  },
  appendMessage(role, content) {
    const msg = { id: buildId(), role, content }
    const messages = [...this.data.messages, msg]
    this.setData({
      messages,
      toViewId: `msg-${msg.id}`
    })
  },
  bootstrapChat(stock) {
    const openText = `你好，我是你的投研AI助手。当前已切换到 ${stock.fullName}。你可以问我：趋势、风险、新闻影响、仓位节奏。`
    this.setData({ messages: [] })
    this.appendMessage('assistant', openText)
  },
  async sendQuestion() {
    const q = String(this.data.question || '').trim()
    if (!q) {
      wx.showToast({ title: '先输入问题', icon: 'none' })
      return
    }
    if (this.data.sending) return
    const current = this.data.current
    this.appendMessage('user', q)
    this.setData({ question: '', sending: true })
    try {
      const resp = await postResearchAnalyze({
        async_mode: false,
        question: q,
        symbol: this.data.currentCode
      })
      const summary = resp && resp.code === 200 ? (resp.data?.summary || '') : ''
      const reply = summary || buildAnswer(current, q)
      this.appendMessage('assistant', reply)
    } catch (e) {
      this.appendMessage('assistant', buildAnswer(current, q))
    } finally {
      this.setData({ sending: false })
    }
  },
  goBack() {
    const pages = getCurrentPages()
    if (pages.length > 1) {
      wx.navigateBack({ delta: 1 })
      return
    }
    wx.reLaunch({ url: '/pages/portal/index' })
  },
  applyCode(code) {
    const c = normalizeCode(code) || '300750'
    setSelectedCode(c)
    this.setData({
      currentCode: c,
      current: pickStock(c),
      keyword: c
    })
    void this.enrichCurrentStock(c)
  },
  async enrichCurrentStock(code) {
    const c = normalizeCode(code) || this.data.currentCode
    const fallback = pickStock(c)
    try {
      const res = await getQuote(c)
      if (res && res.code === 200 && res.data) {
        const q = res.data
        const merged = {
          ...fallback,
          fullName: `${q.name || fallback.name} ${c}`,
          price: `¥${q.price}`,
          info: `${q.pct_chg >= 0 ? '+' : ''}${q.pct_chg}% | 今开${q.open} 最高${q.high} 最低${q.low}`
        }
        this.setData({ current: merged })
        return merged
      }
    } catch (e) {}
    return fallback
  }
})

