const { profileMenus } = require('../../utils/data')

const topicDataMap = {
  mixue: {
    title: '蜜雪冰城全球门店6万，海外业务净增长',
    drive:
      '驱动事件：蜜雪冰城全球门店近60000家，2026年预期门店增速接近15%；海外业务进入净增长阶段；幸运咖单店效益持续改善。据新浪财经报道，公司供应链优势持续强化，海外市场拓展加速。',
    logic:
      '投资逻辑：通过全球门店高速扩张、海外市场优化及幸运咖单店效益提升，驱动业绩稳健增长。供应链和数字化能力支撑效率提升，多品牌矩阵拓展产品线，为长期高质量增长提供坚实基础。',
    stocks: [
      { name: '古茗', code: '01364.HK', change: '+1.39%', positive: true },
      { name: '蜜雪集团', code: '02097.HK', change: '+0.56%', positive: true }
    ],
    originalNews:
      '蜜雪冰城全球门店近60000家，2026年预期门店增速接近15%；海外业务进入净增长阶段；幸运咖单店效益持续改善。供应链和数字化能力支撑效率，多品牌矩阵拓展产品线，为长期高质量增长提供坚实基础。来源：百度财经 2026-04-01'
  },
  oil: {
    title: '原油期货异常交易引监管关注',
    drive:
      '驱动事件：美国商品期货交易委员会（CFTC）于2026年3月30日宣布正密切关注原油期货市场异常交易，此前3月23日特朗普发帖前15分钟出现5.8亿美元空单引发内幕交易质疑。来源：新浪财经。',
    logic:
      '投资逻辑：能源板块短期波动加剧，监管趋严或影响投机情绪，但供需基本面仍偏紧。关注油气龙头低吸机会，同时警惕政策风险对油价的短期扰动。',
    stocks: [
      { name: '中国石化', code: '600028.SH', change: '+0.32%', positive: true },
      { name: '中国石油', code: '601857.SH', change: '+0.15%', positive: true }
    ],
    originalNews:
      '美国商品期货交易委员会（CFTC）于2026年3月30日宣布正密切关注原油期货市场异常交易，此前3月23日特朗普发帖前15分钟出现5.8亿美元空单引发内幕交易质疑。监管机构表示将彻查此事，原油市场波动加剧。来源：新浪财经 2026-03-30'
  },
  soy: {
    title: '巴西大豆出口预期微调，全球供应稳定',
    drive:
      '驱动事件：巴西全国谷物出口商协会（ANEC）于03月31日将3月大豆出口量预期从1587万吨微调至1586万吨。来源：百度财经。',
    logic:
      '投资逻辑：南美丰产预期下，大豆价格维持区间震荡，国内压榨企业成本可控。北大荒等种植企业受益于粮价高位，关注农产品加工链成本改善机会。',
    stocks: [
      { name: '北大荒', code: '600598.SH', change: '-0.21%', positive: false },
      { name: '苏垦农发', code: '601952.SH', change: '+0.05%', positive: true }
    ],
    originalNews:
      '巴西全国谷物出口商协会（ANEC）于03月31日将3月大豆出口量预期从1587万吨微调至1586万吨，调整幅度仅0.06%。南美丰产预期下，全球大豆供应保持宽松格局。来源：百度财经 2026-03-31'
  },
  fertilizer: {
    title: '中东冲突推高全球化肥及能源价格',
    drive:
      '驱动事件：中东冲突导致霍尔木兹海峡航运受阻，全球化肥与能源价格攀升，推高农业生产成本。来源：新浪财经。',
    logic:
      '投资逻辑：化肥价格上行利好国内拥有磷矿、钾肥资源的龙头企业，同时农产品景气度提升。关注盐湖股份、云天化等资源型企业的业绩弹性。',
    stocks: [
      { name: '盐湖股份', code: '000792.SZ', change: '+2.1%', positive: true },
      { name: '云天化', code: '600096.SH', change: '+1.8%', positive: true }
    ],
    originalNews:
      '中东地缘冲突升级，霍尔木兹海峡航运受阻，引发市场对能源和化肥供应担忧。全球化肥价格应声上涨，欧洲和北非农业生产成本预计上升。来源：新浪财经 2026-03-31'
  }
}

const stockData = {
  '600519': {
    name: '贵州茅台',
    code: '600519',
    price: 1720,
    change: 1.45,
    high: 1920,
    low: 1600,
    percentile: 62,
    trend: '稳步上行',
    volatility: '低',
    insight: ['白酒板块稳健，当前位置中位偏上。', '消费复苏延续时，关注1800元上方。', '若大盘转弱，震荡整理概率增加。'],
    suggestion: ['1700下方可分批关注。', '长期配置价值较高。', '短期波动较小，适合稳健型。']
  },
  '600028': {
    name: '中国石化',
    code: '600028',
    price: 6.28,
    change: 0.32,
    high: 6.8,
    low: 5.9,
    percentile: 55,
    trend: '区间震荡',
    volatility: '中',
    insight: ['油价高位震荡，一体化炼化龙头受益。', '股息率具备吸引力，防御属性强。', '关注原油价格走势及政策变化。'],
    suggestion: ['6.0附近可考虑配置。', '适合稳健型投资者长期持有。']
  },
  '02097': {
    name: '蜜雪集团',
    code: '02097.HK',
    price: 188.6,
    change: 0.56,
    high: 210,
    low: 165,
    percentile: 68,
    trend: '稳步上行',
    volatility: '低',
    insight: ['门店突破6万家，海外业务净增长。', '供应链优势持续强化。', '2026年预期增速15%，业绩确定性高。'],
    suggestion: ['180附近可分批关注。', '长期配置价值较高。']
  },
  '01364': {
    name: '古茗',
    code: '01364.HK',
    price: 15.8,
    change: 1.39,
    high: 17.5,
    low: 14.2,
    percentile: 72,
    trend: '震荡上行',
    volatility: '中',
    insight: ['新茶饮同店复苏，区域优势稳固。', '单店模型优化，下沉市场渗透率提升。'],
    suggestion: ['15附近可关注。', '短期波动较大，注意风险。']
  },
  '601857': {
    name: '中国石油',
    code: '601857.SH',
    price: 9.85,
    change: 0.15,
    high: 10.6,
    low: 8.9,
    percentile: 48,
    trend: '区间震荡',
    volatility: '中',
    insight: ['油气板块受益于油价高位。', '一体化炼化龙头，股息稳定。'],
    suggestion: ['9.5附近可关注。', '适合稳健配置。']
  },
  '000792': {
    name: '盐湖股份',
    code: '000792.SZ',
    price: 18.6,
    change: 2.1,
    high: 22,
    low: 16,
    percentile: 58,
    trend: '震荡上行',
    volatility: '中高',
    insight: ['钾肥资源稀缺性支撑。', '锂盐业务贡献增量。'],
    suggestion: ['回调后分批关注。', '注意周期波动。']
  }
}

const WATCHLIST_STORAGE_KEY = 'portal_watchlist_codes'
const WATCHLIST_DEFAULT = ['600519', '600028', '02097', '01364']

function resolveStockKey(raw) {
  const s = String(raw || '').trim().toUpperCase()
  if (!s) return null
  if (stockData[s]) return s
  const stripped = s.replace(/\.(SH|SZ|HK)$/i, '')
  if (stockData[stripped]) return stripped
  for (const k of Object.keys(stockData)) {
    const c = String(stockData[k].code).toUpperCase()
    if (c === s || c.replace(/\./g, '') === stripped.replace(/\./g, '')) return k
  }
  return null
}

function buildWatchlistRows(codes) {
  const seen = new Set()
  const rows = []
  for (const c of codes) {
    const key = resolveStockKey(c) || (stockData[c] ? c : null)
    if (!key || seen.has(key)) continue
    seen.add(key)
    const st = stockData[key]
    if (!st) continue
    const pct = st.change >= 0 ? `+${st.change}%` : `${st.change}%`
    rows.push({
      code: key,
      name: st.name,
      labelCode: st.code,
      changeStr: pct,
      positive: st.change >= 0
    })
  }
  return rows
}

const klineSeed = [1680, 1695, 1702, 1698, 1710, 1705, 1715, 1720, 1718, 1725]

function buildKlineBars(arr) {
  if (!arr || !arr.length) return []
  const maxVal = Math.max(...arr)
  const minVal = Math.min(...arr)
  const range = maxVal - minVal || 1
  return arr.map((v, i) => ({
    hRpx: Math.max(16, Math.round(((v - minVal) / range) * 280)),
    up: v >= (arr[i - 1] !== undefined ? arr[i - 1] : v)
  }))
}

Page({
  data: {
    statusBarHeight: 44,
    activePage: 'home',
    tabSelected: 'home',
    topicDetail: null,
    profileMenus,
    stockSearchInput: '600519',
    currentStock: stockData['600519'],
    klineData: klineSeed,
    klineBars: buildKlineBars(klineSeed),
    chatInput: '',
    chatMessages: [
      { role: 'ai', text: '您好！我是财懂了AI助手，可以针对当前关注的股票进行深度分析。请问有什么可以帮您？' }
    ],
    earningsVisible: false,
    earningsHtml: '',
    chatMsgAreaPx: 520,
    chatInputFocus: false,
    watchlistItems: [],
    watchlistAddVisible: false,
    watchlistAddInput: '',
    watchlistHeaderMarginTopPx: 0
  },

  _layoutChatArea() {
    try {
      const sys = wx.getSystemInfoSync()
      const winH = sys.windowHeight || 667
      const winW = sys.windowWidth || 375
      let safeBottom = 0
      if (sys.safeArea && typeof sys.screenHeight === 'number') {
        safeBottom = Math.max(0, sys.screenHeight - sys.safeArea.bottom)
      }
      const rpx = (n) => (n * winW) / 750
      const headerPx = Math.ceil(rpx(120))
      /* 白底输入区：顶边线 + 内边距 + 胶囊输入/按钮高度 + 安全区（与 wxss 一致） */
      const inputBarPx = Math.ceil(rpx(220)) + safeBottom
      const msgH = Math.floor(winH - headerPx - inputBarPx)
      this.setData({ chatMsgAreaPx: Math.max(280, msgH) })
    } catch (e) {
      this.setData({ chatMsgAreaPx: 520 })
    }
  },

  _loadWatchlist() {
    let codes = [...WATCHLIST_DEFAULT]
    try {
      const saved = wx.getStorageSync(WATCHLIST_STORAGE_KEY)
      if (Array.isArray(saved) && saved.length) {
        codes = saved.map((c) => String(c).trim()).filter(Boolean)
      }
    } catch (e) {}
    const rows = buildWatchlistRows(codes)
    if (!rows.length) {
      codes = [...WATCHLIST_DEFAULT]
      try {
        wx.setStorageSync(WATCHLIST_STORAGE_KEY, codes)
      } catch (e2) {}
      this.setData({ watchlistItems: buildWatchlistRows(codes) })
      return
    }
    try {
      wx.setStorageSync(WATCHLIST_STORAGE_KEY, rows.map((r) => r.code))
    } catch (e3) {}
    this.setData({ watchlistItems: rows })
  },

  onLoad() {
    let h = 44
    let watchlistHeaderMarginTopPx = 16
    try {
      const sys = typeof wx.getWindowInfo === 'function' ? wx.getWindowInfo() : wx.getSystemInfoSync()
      h = sys.statusBarHeight || 44
      const winW = sys.windowWidth || 375
      const pageTopPadPx = (24 * winW) / 750
      const rect = wx.getMenuButtonBoundingClientRect()
      if (rect && typeof rect.bottom === 'number') {
        const need = Math.ceil(rect.bottom + 12 - h - pageTopPadPx)
        watchlistHeaderMarginTopPx = Math.max(16, need)
      }
    } catch (e) {}
    this.setData({ statusBarHeight: h, watchlistHeaderMarginTopPx })
    this.updateStockUI(stockData['600519'])
    this._loadWatchlist()
  },

  onShow() {
    if (this.data.activePage === 'chat') {
      this._layoutChatArea()
    }
  },

  switchPage(pageId) {
    const main = ['home', 'stock', 'watchlist', 'earnings', 'mine']
    const patch = { activePage: pageId }
    if (main.includes(pageId)) patch.tabSelected = pageId
    this.setData(patch)
    if (pageId === 'chat') {
      this.setData({ chatInputFocus: false })
      this._layoutChatArea()
    }
    if (pageId === 'stock') {
      this.updateStockUI(this.data.currentStock)
    }
  },

  stopBubble() {},

  onTabTap(e) {
    const page = e.currentTarget.dataset.page
    if (page) this.switchPage(page)
  },

  onNewsTap(e) {
    const id = e.currentTarget.dataset.newsid
    const topic = topicDataMap[id]
    if (!topic) return
    this.setData({ topicDetail: topic, activePage: 'topic' })
  },

  onBackTopic() {
    this.setData({ activePage: 'home', topicDetail: null })
  },

  onAiChatEntry() {
    this.switchPage('chat')
  },

  onBackChat() {
    this.switchPage('home')
  },

  onStockSearchInput(e) {
    this.setData({ stockSearchInput: e.detail.value })
  },

  onSearchStock() {
    const code = String(this.data.stockSearchInput || '').trim()
    const s = stockData[code] || stockData['600519']
    this.updateStockUI(s)
  },

  onResetKline() {
    this.setData({ klineBars: buildKlineBars(this.data.klineData) })
  },

  onChatInputTap() {
    this.setData({ chatInputFocus: true })
  },

  onChatInputFocus() {
    this.setData({ chatInputFocus: true })
  },

  onChatInputBlur() {
    this.setData({ chatInputFocus: false })
  },

  onChatInput(e) {
    this.setData({ chatInput: e.detail.value })
  },

  onSendChat() {
    const text = String(this.data.chatInput || '').trim()
    if (!text) return
    const cur = this.data.currentStock
    const msgs = this.data.chatMessages.concat([{ role: 'user', text }])
    const reply = `关于${cur.name}：当前股价¥${cur.price}，${cur.trend}，价格分位${cur.percentile}%。${cur.insight[0]}`
    this.setData({ chatMessages: msgs, chatInput: '' })
    setTimeout(() => {
      this.setData({ chatMessages: msgs.concat([{ role: 'ai', text: reply }]) })
    }, 300)
  },

  onWatchItemTap(e) {
    const code = String(e.currentTarget.dataset.code || '')
    const s = stockData[code]
    if (!s) return
    this.setData({ stockSearchInput: code })
    this.updateStockUI(s)
    this.switchPage('stock')
  },

  openWatchlistAdd() {
    this.setData({ watchlistAddVisible: true, watchlistAddInput: '' })
  },

  closeWatchlistAdd() {
    this.setData({ watchlistAddVisible: false })
  },

  onWatchlistAddInput(e) {
    this.setData({ watchlistAddInput: e.detail.value })
  },

  confirmWatchlistAdd() {
    const key = resolveStockKey(this.data.watchlistAddInput)
    if (!key || !stockData[key]) {
      wx.showToast({ title: '未找到该股票代码', icon: 'none' })
      return
    }
    const cur = this.data.watchlistItems.map((r) => r.code)
    if (cur.includes(key)) {
      wx.showToast({ title: '已在自选股中', icon: 'none' })
      return
    }
    const next = cur.concat([key])
    try {
      wx.setStorageSync(WATCHLIST_STORAGE_KEY, next)
    } catch (e) {}
    this.setData({
      watchlistItems: buildWatchlistRows(next),
      watchlistAddVisible: false,
      watchlistAddInput: ''
    })
    wx.showToast({ title: '已添加', icon: 'success' })
  },

  onUploadAreaTap() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf'],
      success: (res) => {
        const f = res.tempFiles[0]
        const name = f.name || '财报文件'
        this.setData({
          earningsVisible: true,
          earningsHtml: `📄 分析：${name}\n🤖 AI分析：营业收入+15.8%，净利润+22.3%，毛利率34.2%，综合评级增持。（演示）`
        })
      },
      fail: () => {
        wx.showToast({ title: '请选择 PDF 文件', icon: 'none' })
      }
    })
  },

  tapMenu(e) {
    const name = e.currentTarget.dataset.name || ''
    wx.showToast({ title: String(name), icon: 'none' })
  },

  updateStockUI(stock) {
    if (!stock) return
    const openPrice = (stock.price * (1 - stock.change / 100)).toFixed(2)
    const detail = `今开${openPrice} 最高${(stock.price * 1.02).toFixed(2)} 最低${(stock.price * 0.98).toFixed(2)}`
    const pctLabel = stock.change >= 0 ? `+${stock.change}%` : `${stock.change}%`
    const klineData = this.data.klineData
    this.setData({
      currentStock: stock,
      stockName: stock.name,
      stockCode: stock.code,
      stockPrice: `¥${stock.price}`,
      stockChange: pctLabel,
      stockChangePositive: stock.change >= 0,
      stockDetail: detail,
      high52w: `¥${stock.high}`,
      low52w: `¥${stock.low}`,
      percentileText: `${stock.percentile}%`,
      percentileSub: stock.percentile > 50 ? '中位偏上' : '中位偏下',
      trendText: stock.trend,
      volText: stock.volatility,
      aiInsightList: stock.insight,
      suggestionList: stock.suggestion,
      klineBars: buildKlineBars(klineData)
    })
  }
})
