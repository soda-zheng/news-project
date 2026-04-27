const { postResearchAnalyze, formatApiError, explainBackendConnectionError } = require('../../utils/api')

const REPORT_POOL = [
  {
    id: 'moutai-2025-annual',
    symbol: '600519',
    name: '贵州茅台',
    period: '2025 年报',
    type: 'annual',
    publishDate: '2026-03-28',
    revenueYoY: 15.2,
    profitYoY: 13.7,
    grossMargin: 91.3,
    cfoYoY: 10.4,
    highlights: ['高端产品结构稳定', '渠道库存健康', '经营现金流持续为正'],
    risks: ['消费修复不及预期', '渠道改革节奏波动']
  },
  {
    id: 'catl-2026-q1',
    symbol: '300750',
    name: '宁德时代',
    period: '2026 Q1',
    type: 'q1',
    publishDate: '2026-04-19',
    revenueYoY: 8.9,
    profitYoY: 12.4,
    grossMargin: 24.8,
    cfoYoY: 6.1,
    highlights: ['海外出货占比提升', '储能业务增速较快', '费用率维持可控'],
    risks: ['原材料价格回升', '海外政策不确定性']
  },
  {
    id: 'midea-2025-annual',
    symbol: '000333',
    name: '美的集团',
    period: '2025 年报',
    type: 'annual',
    publishDate: '2026-03-30',
    revenueYoY: 9.6,
    profitYoY: 11.2,
    grossMargin: 27.5,
    cfoYoY: 9.9,
    highlights: ['ToB 业务占比提升', '海外市场稳健增长', '现金流质量较高'],
    risks: ['海外需求走弱', '汇率波动影响利润']
  },
  {
    id: 'pingan-2025-annual',
    symbol: '601318',
    name: '中国平安',
    period: '2025 年报',
    type: 'annual',
    publishDate: '2026-03-22',
    revenueYoY: 5.3,
    profitYoY: 7.1,
    grossMargin: 0,
    cfoYoY: 4.2,
    highlights: ['寿险新业务价值修复', '综合金融协同增强', '资产端波动可控'],
    risks: ['权益市场波动', '利率下行压力']
  }
]

const TYPE_TABS = [
  { key: 'all', label: '全部' },
  { key: 'annual', label: '年报' },
  { key: 'q1', label: '一季报' },
  { key: 'half', label: '中报' },
  { key: 'q3', label: '三季报' }
]

Page({
  data: {
    typeTabs: TYPE_TABS,
    activeType: 'all',
    keyword: '',
    reportList: REPORT_POOL,
    selectedId: REPORT_POOL[0].id,
    selectedReport: REPORT_POOL[0],
    aiSummary: '',
    loading: false
  },

  onLoad() {
    this._applyFilter()
  },

  onKeywordInput(e) {
    this.setData({ keyword: String(e.detail.value || '') }, () => this._applyFilter())
  },

  onTypeTap(e) {
    const key = String(e.currentTarget.dataset.key || 'all')
    this.setData({ activeType: key }, () => this._applyFilter())
  },

  onPickReport(e) {
    const id = String(e.currentTarget.dataset.id || '')
    const hit = (this.data.reportList || []).find((x) => x.id === id)
    if (!hit) return
    this.setData({ selectedId: id, selectedReport: hit, aiSummary: '' })
  },

  _applyFilter() {
    const kw = String(this.data.keyword || '').trim().toLowerCase()
    const t = String(this.data.activeType || 'all')
    const list = REPORT_POOL.filter((x) => {
      if (t !== 'all' && x.type !== t) return false
      if (!kw) return true
      return (
        String(x.name || '').toLowerCase().includes(kw) ||
        String(x.symbol || '').toLowerCase().includes(kw) ||
        String(x.period || '').toLowerCase().includes(kw)
      )
    })
    const prevSelected = String(this.data.selectedId || '')
    const keep = list.find((x) => x.id === prevSelected)
    const nextSel = keep || list[0] || null
    this.setData({
      reportList: list,
      selectedId: nextSel ? nextSel.id : '',
      selectedReport: nextSel,
      aiSummary: ''
    })
  },

  async runAnalyze() {
    const r = this.data.selectedReport
    if (!r) {
      wx.showToast({ title: '请先选择一份财报', icon: 'none' })
      return
    }
    const question =
      `请基于以下财报信息给出结构化解读：公司${r.name}(${r.symbol})，期别${r.period}，` +
      `营收同比${r.revenueYoY}%，利润同比${r.profitYoY}%，毛利率${r.grossMargin}%，经营现金流同比${r.cfoYoY}%。` +
      `请输出：1) 一句话结论 2) 三条业绩驱动 3) 两条主要风险 4) 下季度跟踪点。`
    this.setData({ loading: true, aiSummary: '' })
    try {
      const res = await postResearchAnalyze({ symbol: r.symbol, question })
      const summary = res && res.code === 200 && res.data ? String(res.data.summary || '').trim() : ''
      this.setData({
        loading: false,
        aiSummary: summary || this._fallbackSummary(r)
      })
    } catch (e) {
      const msg = explainBackendConnectionError(formatApiError(e, '分析失败，请稍后重试'))
      this.setData({
        loading: false,
        aiSummary: `${this._fallbackSummary(r)}\n\n（AI 接口异常：${msg}）`
      })
    }
  },

  _fallbackSummary(r) {
    const revGood = Number(r.revenueYoY) >= 0
    const profitGood = Number(r.profitYoY) >= 0
    const cashGood = Number(r.cfoYoY) >= 0
    const headline = revGood && profitGood ? '收入和利润保持增长，经营韧性较好。' : '收入或利润出现压力，需关注修复节奏。'
    const cashLine = cashGood ? '现金流同比改善，利润兑现质量相对可控。' : '现金流同比承压，需警惕利润与现金错配。'
    return [
      `【结论】${headline}`,
      `【驱动】营收同比 ${r.revenueYoY}% 、利润同比 ${r.profitYoY}% 、毛利率 ${r.grossMargin}% 。`,
      `【质量】${cashLine}`,
      `【风险】${(r.risks || []).join('；') || '需求与成本波动'}。`,
      '【跟踪】关注下一季收入增速、毛利率变化和经营现金流。'
    ].join('\n')
  }
})

