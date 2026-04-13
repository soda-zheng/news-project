const { profileMenus } = require('../../utils/data')
const {
  getQuote,
  searchStocks,
  getStockDailyBars,
  postStockLLMInsight,
  postResearchAnalyze,
  getHomeNewsEnhanced,
  postNewsAiAnalyze,
  uploadPdf,
  startAnalyze,
  getTask,
  regenPage,
  formatApiError,
  explainBackendConnectionError
} = require('../../utils/api')
const { getCodeByKeyword } = require('../../utils/helpers')

let parsePageToBlocks = () => []
try {
  // eslint-disable-next-line global-require
  parsePageToBlocks = require('../../utils/earningsMarkdown').parsePageToBlocks || (() => [])
} catch (e) {
  parsePageToBlocks = () => []
}

const DEFAULT_PERCENTILE_HINT =
  '分位说明：近约250个交易日最低价—最高价区间内，按最新「收盘价」相对位置（百分比）；不是市盈率分位。'

const DEFAULT_STOCK_QUICK_QUESTIONS = [
  '结合当前分位与10/20日动量，下一步走势更偏哪边？',
  '52周回撤下，最该盯的支撑/压力信号是什么？',
  '若继续偏弱，未持仓者如何控风险与等信号？'
]

/** 与后端 daily-bars / LLM 输入统一：保留两位小数展示，游标用未截断数值 */
function percentileUiFromNumber(p) {
  const x = Number(p)
  if (!Number.isFinite(x)) return null
  const cap = Math.min(100, Math.max(0, x))
  const r2 = Math.round(cap * 100) / 100
  const label = `${r2.toFixed(2)}%`
  const sub = r2 > 50 ? '中位偏上' : r2 < 50 ? '中位偏下' : '接近中位'
  return { label, marker: cap, barWidth: r2, sub }
}

const topicDataMap = {
  mixue: {
    title: '蜜雪冰城全球门店6万，海外业务净增长',
    heatPercentile: 72,
    drive:
      '驱动事件：蜜雪冰城全球门店近60000家，2026年预期门店增速接近15%；海外业务进入净增长阶段；幸运咖单店效益持续改善。据新浪财经报道，公司供应链优势持续强化，海外市场拓展加速。',
    logic:
      '投资逻辑：通过全球门店高速扩张、海外市场优化及幸运咖单店效益提升，驱动业绩稳健增长。供应链和数字化能力支撑效率提升，多品牌矩阵拓展产品线，为长期高质量增长提供坚实基础。',
    causalChain: [
      { label: '事件', text: '门店数近6万、海外净增长、幸运咖效益改善，供应链与数字化强化。' },
      { label: '影响路径', text: '规模效应 → 单店模型与采购成本优化 → 利润与增速预期上修。' },
      { label: '可能受益', text: '供应链龙头、同赛道可比公司、港股新茶饮板块情绪。' },
      { label: '可能承压', text: '同店增速不及预期、加盟管控与食安舆情、海外汇率与合规成本。' }
    ],
    counterRisk: {
      title: '若情况相反会怎样',
      points: [
        '同店销售或门店增速低于指引，估值可能从高增长叙事回落。',
        '海外拓展与关税、合规成本超预期，压制利润率。',
        '行业价格战加剧，单店模型恶化。'
      ]
    },
    timeline: [
      { date: '2026-04-01', title: '门店与增速指引相关报道', tag: '资讯' },
      { date: '2026-06-30', title: '中期财报（演示：可设财报前提醒）', tag: '财报' },
      { date: '2026-12-31', title: '年度经营数据盘点', tag: '数据' }
    ],
    stocks: [
      { name: '古茗', code: '01364.HK', change: '+1.39%', positive: true },
      { name: '蜜雪集团', code: '02097.HK', change: '+0.56%', positive: true }
    ],
    originalNews:
      '蜜雪冰城全球门店近60000家，2026年预期门店增速接近15%；海外业务进入净增长阶段；幸运咖单店效益持续改善。供应链和数字化能力支撑效率，多品牌矩阵拓展产品线，为长期高质量增长提供坚实基础。来源：百度财经 2026-04-01',
    riskIfWrong:
      '若消费走弱或同店下滑超预期，开店增速与单店模型无法同步改善，则当前叙事中的「高质量增长」需下调预期，股价可能先行反应在估值压缩上。'
  },
  oil: {
    title: '原油期货异常交易引监管关注',
    heatPercentile: 86,
    drive:
      '驱动事件：美国商品期货交易委员会（CFTC）于2026年3月30日宣布正密切关注原油期货市场异常交易，此前3月23日特朗普发帖前15分钟出现5.8亿美元空单引发内幕交易质疑。来源：新浪财经。',
    logic:
      '投资逻辑：能源板块短期波动加剧，监管趋严或影响投机情绪，但供需基本面仍偏紧。关注油气龙头低吸机会，同时警惕政策风险对油价的短期扰动。',
    causalChain: [
      { label: '事件', text: 'CFTC 表态关注异常交易；巨额空单时点引发监管与舆情。' },
      { label: '影响路径', text: '监管介入 → 短期投机资金收敛 → 波动率变化 → 油气链情绪重定价。' },
      { label: '可能受益', text: '高壁垒一体化炼化、高分红油气龙头（波动中防御属性）。' },
      { label: '可能承压', text: '高杠杆贸易商、纯投机策略；若调查扩大或引发流动性担忧。' }
    ],
    counterRisk: {
      title: '若情况相反会怎样',
      points: [
        '调查落地快、市场解读为「利空出尽」，油价波动反而收窄。',
        '地缘与供需数据盖过监管叙事，油气股与期货脱敏。',
        '监管未找到实质违规，事件热度快速消退。'
      ]
    },
    timeline: [
      { date: '2026-03-23', title: '异常空单时点（媒体报道）', tag: '事件' },
      { date: '2026-03-30', title: 'CFTC 公开表态', tag: '政策' },
      { date: '2026-04-15', title: 'EIA 库存与产量（演示）', tag: '宏观' }
    ],
    stocks: [
      { name: '中国石化', code: '600028.SH', change: '+0.32%', positive: true },
      { name: '中国石油', code: '601857.SH', change: '+0.15%', positive: true }
    ],
    originalNews:
      '美国商品期货交易委员会（CFTC）于2026年3月30日宣布正密切关注原油期货市场异常交易，此前3月23日特朗普发帖前15分钟出现5.8亿美元空单引发内幕交易质疑。监管机构表示将彻查此事，原油市场波动加剧。来源：新浪财经 2026-03-30',
    riskIfWrong:
      '若调查结论淡化、且地缘与供需未恶化，油价快速回落，则事件驱动逻辑减弱，板块可能重回基本面定价，需防追高回撤。'
  },
  soy: {
    title: '巴西大豆出口预期微调，全球供应稳定',
    heatPercentile: 44,
    drive:
      '驱动事件：巴西全国谷物出口商协会（ANEC）于03月31日将3月大豆出口量预期从1587万吨微调至1586万吨。来源：百度财经。',
    logic:
      '投资逻辑：南美丰产预期下，大豆价格维持区间震荡，国内压榨企业成本可控。北大荒等种植企业受益于粮价高位，关注农产品加工链成本改善机会。',
    causalChain: [
      { label: '事件', text: '巴西出口预期微调，幅度极小，全球供应仍偏宽松。' },
      { label: '影响路径', text: '供应预期稳定 → 国内压榨利润区间波动 → 种植与加工链分化。' },
      { label: '可能受益', text: '成本可控的龙头压榨、种植端龙头（粮价韧性）。' },
      { label: '可能承压', text: '若南美产量上修或需求走弱，豆价下行拖累种植情绪。' }
    ],
    counterRisk: {
      title: '若情况相反会怎样',
      points: [
        '后续月度出口连续下调，可能重新引发紧平衡预期。',
        '国内饲料需求超预期复苏，豆类价格弹性放大。',
        '天气与物流扰动导致南美发运节奏变化。'
      ]
    },
    timeline: [
      { date: '2026-03-31', title: 'ANEC 出口预期更新', tag: '数据' },
      { date: '2026-04-10', title: 'USDA 月报（演示）', tag: '宏观' },
      { date: '2026-05-01', title: '国内港口到港与库存', tag: '行业' }
    ],
    stocks: [
      { name: '北大荒', code: '600598.SH', change: '-0.21%', positive: false },
      { name: '苏垦农发', code: '601952.SH', change: '+0.05%', positive: true }
    ],
    originalNews:
      '巴西全国谷物出口商协会（ANEC）于03月31日将3月大豆出口量预期从1587万吨微调至1586万吨，调整幅度仅0.06%。南美丰产预期下，全球大豆供应保持宽松格局。来源：百度财经 2026-03-31',
    riskIfWrong:
      '若南美天气或物流再现扰动、或国内需求骤升，宽松叙事可能逆转，豆类价格上行将挤压下游利润，原逻辑需修正。'
  },
  fertilizer: {
    title: '中东冲突推高全球化肥及能源价格',
    heatPercentile: 79,
    drive:
      '驱动事件：中东冲突导致霍尔木兹海峡航运受阻，全球化肥与能源价格攀升，推高农业生产成本。来源：新浪财经。',
    logic:
      '投资逻辑：化肥价格上行利好国内拥有磷矿、钾肥资源的龙头企业，同时农产品景气度提升。关注盐湖股份、云天化等资源型企业的业绩弹性。',
    causalChain: [
      { label: '事件', text: '地缘冲突 → 航运受阻 → 能源与化肥报价上行。' },
      { label: '影响路径', text: '全球化肥成本曲线抬升 → 国内资源型企业议价与价差改善。' },
      { label: '可能受益', text: '钾/磷资源自给率高、一体化化工龙头。' },
      { label: '可能承压', text: '下游农业利润率受压；若冲突缓和，价格快速回吐。' }
    ],
    counterRisk: {
      title: '若情况相反会怎样',
      points: [
        '冲突未升级或航线快速恢复，运价与化肥价回落。',
        '国内保供政策压制出厂价，业绩弹性低于预期。',
        '全球农产品需求走弱，化肥需求同步下修。'
      ]
    },
    timeline: [
      { date: '2026-03-28', title: '霍尔木兹相关报道发酵', tag: '事件' },
      { date: '2026-03-31', title: '全球化肥现货报价（演示）', tag: '数据' },
      { date: '2026-04-20', title: '一季报窗口（演示）', tag: '财报' }
    ],
    stocks: [
      { name: '盐湖股份', code: '000792.SZ', change: '+2.1%', positive: true },
      { name: '云天化', code: '600096.SH', change: '+1.8%', positive: true }
    ],
    originalNews:
      '中东地缘冲突升级，霍尔木兹海峡航运受阻，引发市场对能源和化肥供应担忧。全球化肥价格应声上涨，欧洲和北非农业生产成本预计上升。来源：新浪财经 2026-03-31',
    riskIfWrong:
      '若冲突缓和、运力恢复或主要出口国增产，化肥价格回落，则涨价叙事收敛，需重新按供需均衡定价。'
  }
}

const NARRATIVE_PERCENT_MAP = { oil: 72, soy: 58, fertilizer: 81, mixue: 65 }

const HOME_NEWS_SEED = [
  {
    id: 'oil',
    title: '美国CFTC密切关注原油期货异常交易，特朗普帖前15分钟现5.8亿空单引发质疑',
    summary:
      '🤖 AI摘要：美国商品期货交易委员会(CFTC)于3月30日宣布正密切关注原油期货市场异常交易。此前3月23日，特朗普在社交媒体发帖前15分钟，市场出现5.8亿美元原油空单，引发内幕交易质疑。监管机构表示将彻查此事，原油市场波动加剧。',
    metaTime: '2026-03-30 08:57',
    metaSource: '来源：新浪财经',
    chips: ['中国石化 600028.SH', '中国石油 601857.SH']
  },
  {
    id: 'soy',
    title: '巴西ANEC：3月大豆出口预期微调至1586万吨，全球供应格局稳定',
    summary:
      '🤖 AI摘要：巴西全国谷物出口商协会(ANEC)于3月31日发布数据显示，将3月大豆出口量预期从1587万吨微调至1586万吨，调整幅度仅0.06%。南美丰产预期下，全球大豆供应保持宽松格局，国内压榨企业成本可控，农产品价格预计维持区间震荡。',
    metaTime: '2026-03-31 01:24',
    metaSource: '来源：百度财经',
    chips: ['北大荒 600598.SH', '苏垦农发 601952.SH']
  },
  {
    id: 'fertilizer',
    title: '中东冲突导致霍尔木兹海峡航运受阻，全球化肥与能源价格攀升',
    summary:
      '🤖 AI摘要：中东地缘冲突升级，霍尔木兹海峡航运受阻，引发市场对能源和化肥供应担忧。全球化肥价格应声上涨，欧洲和北非农业生产成本预计上升。分析认为，拥有磷矿、钾肥资源的国内龙头企业有望受益于价格上涨周期。',
    metaTime: '2026-03-31 20:21',
    metaSource: '来源：新浪财经',
    chips: ['盐湖股份 000792.SZ', '云天化 600096.SH']
  },
  {
    id: 'mixue',
    title: '蜜雪冰城全球门店近60000家，海外业务净增长，幸运咖单店效益持续改善',
    summary:
      '🤖 AI摘要：蜜雪冰城全球门店突破60000家，2026年预期门店增速接近15%，海外业务进入净增长阶段。旗下咖啡品牌幸运咖单店效益持续改善，供应链和数字化能力支撑效率提升。机构认为，多品牌矩阵拓展为长期高质量增长提供坚实基础。',
    metaTime: '2026-04-01 09:00',
    metaSource: '来源：百度财经',
    chips: ['蜜雪集团 02097.HK', '古茗 01364.HK']
  }
]

function buildHomeNewsList() {
  return HOME_NEWS_SEED.map((row) => {
    const t = topicDataMap[row.id]
    const heat = t && typeof t.heatPercentile === 'number' ? t.heatPercentile : 0
    const narrativePct = NARRATIVE_PERCENT_MAP[row.id] != null ? NARRATIVE_PERCENT_MAP[row.id] : heat
    return { ...row, heatPercentile: heat, narrativePercent: narrativePct }
  })
}

const CHAT_QUICK_CHIPS = [
  { label: '分位与操作', q: '用三点说明：当前股价与近一年分位的关系，对操作意味着什么？' },
  { label: '风险与机会', q: '列出与该股相关的两条主要风险与一条机会。' },
  { label: '与大盘联动', q: '若大盘指数下周急跌，该股历史上通常如何反应？' }
]

function toChatChipsFromFollowUps(items) {
  const arr = Array.isArray(items) ? items : []
  const out = []
  for (let i = 0; i < arr.length; i++) {
    const q = String(arr[i] || '').trim()
    if (!q) continue
    const label = q.length > 12 ? `${q.slice(0, 12)}…` : q
    out.push({ label, q })
    if (out.length >= 3) break
  }
  return out
}

const WATCHLIST_STORAGE_KEY = 'portal_watchlist_codes'
/** 上次在个股页选中的 A 股代码（仅本机） */
const PORTAL_LAST_STOCK_KEY = 'portal_last_stock_code'
const TOPIC_NOTES_KEY = 'portal_topic_notes'

function readTopicNotes() {
  try {
    const x = wx.getStorageSync(TOPIC_NOTES_KEY)
    return x && typeof x === 'object' ? x : {}
  } catch (e) {
    return {}
  }
}

function formatTopicNoteTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => (n < 10 ? '0' + n : '' + n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatCtime(ctime) {
  if (!ctime || ctime <= 0) return ''
  const d = new Date(ctime * 1000)
  const now = new Date()
  const diff = now - d
  const mins = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (mins < 60) return `${mins}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 7) return `${days}天前`
  const pad = (n) => (n < 10 ? '0' + n : '' + n)
  return `${d.getMonth() + 1}/${pad(d.getDate())}`
}

function isAshare6digit(code) {
  return /^\d{6}$/.test(String(code || '').trim())
}

/** 从「600519」「sh600519」「600519.SH」等提取 6 位 A 股代码 */
function normalizeToAshare6(raw) {
  const s = String(raw || '').trim()
  if (!s) return ''
  if (/^\d{6}$/.test(s)) return s
  const stripped = s.replace(/\.(SH|SZ|BJ)$/i, '').replace(/^(sh|sz|bj)/i, '')
  if (/^\d{6}$/.test(stripped)) return stripped
  return ''
}

function resolveStockKey(raw) {
  const n = normalizeToAshare6(raw)
  if (n) return n
  const alias = getCodeByKeyword(String(raw || '').trim())
  if (alias && isAshare6digit(String(alias).trim())) return String(alias).trim()
  return null
}

/** 仅沪深京 A 股：行情与 K 线均由后端拉取，无本地假数据 */
function stockBaseForKey(key) {
  const k = String(key || '').trim()
  if (!isAshare6digit(k)) return null
  return {
    name: k,
    code: k,
    price: 0,
    change: 0,
    high: 0,
    low: 0,
    open: undefined,
    percentile: null,
    trend: '—',
    volatility: '—',
    insight: [],
    suggestion: []
  }
}

/** 由日线蜡烛序列估算趋势/波动（近 20 日收益与日内收益波动） */
function computeTrendVolFromCandles(candle) {
  const c = Array.isArray(candle) ? candle : []
  const closes = []
  for (let i = 0; i < c.length; i++) {
    const row = c[i]
    if (!Array.isArray(row) || row.length < 2) continue
    const cl = Number(row[1])
    if (Number.isFinite(cl)) closes.push(cl)
  }
  const n = closes.length
  if (n < 5) return { trend: '—', volatility: '—' }
  const last = closes[n - 1]
  const prev20 = n >= 21 ? closes[n - 21] : closes[0]
  const ret20 = prev20 ? ((last - prev20) / prev20) * 100 : 0
  let trend = '区间震荡'
  if (ret20 > 5) trend = '偏强'
  else if (ret20 < -5) trend = '偏弱'
  const win = Math.min(20, n - 1)
  const rets = []
  for (let i = n - win; i < n; i++) {
    if (i > 0 && closes[i - 1]) rets.push(((closes[i] - closes[i - 1]) / closes[i - 1]) * 100)
  }
  if (!rets.length) return { trend, volatility: '—' }
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length
  const variance = rets.reduce((s, x) => s + (x - mean) * (x - mean), 0) / rets.length
  const std = Math.sqrt(Math.max(0, variance))
  let volatility = '中'
  if (std < 1.2) volatility = '低'
  else if (std > 2.8) volatility = '高'
  return { trend, volatility }
}

function mergeQuoteIntoStock(base, apiRes) {
  if (!apiRes || apiRes.code !== 200 || !apiRes.data) return base
  const b =
    base ||
    stockBaseForKey(String(apiRes.data.symbol || apiRes.data.code || '').trim()) || {
      name: '',
      code: '',
      price: 0,
      change: 0,
      high: 0,
      low: 0,
      percentile: null,
      trend: '—',
      volatility: '—',
      insight: [],
      suggestion: []
    }
  if (!b) return base
  const d = apiRes.data
  const pct = Number(d.pct_chg)
  const change = Number.isFinite(pct) ? pct : b.change
  const price = d.price != null ? Number(d.price) : b.price
  const open = d.open != null ? Number(d.open) : undefined
  const high = d.high != null ? Number(d.high) : b.high
  const low = d.low != null ? Number(d.low) : b.low
  return {
    ...b,
    name: d.name || b.name,
    code: d.symbol || d.code || b.code,
    price,
    change,
    open,
    high,
    low,
    liveSource: d.source || ''
  }
}

function buildWatchlistRows(codes) {
  const seen = new Set()
  const rows = []
  for (const c of codes) {
    const key = normalizeToAshare6(c) || resolveStockKey(c)
    if (!key || !isAshare6digit(key) || seen.has(key)) continue
    seen.add(key)
    rows.push({
      code: key,
      name: key,
      labelCode: key,
      changeStr: '--',
      positive: true
    })
  }
  return rows
}

/** ECharts：A股红涨绿跌 + 成交量 + 内置缩放 */
function buildStockKlineOption(d) {
  const dates = d.dates || []
  const candle = d.candle || []
  const vol = d.volume || []
  const n = dates.length
  const startPct = n > 80 ? Math.max(0, 100 - (80 / n) * 100) : 0
  return {
    animation: false,
    // 不启用 tooltip / axisPointer，避免指针移动时产生“图跟随鼠标”的错觉
    tooltip: { show: false },
    grid: [
      { left: 48, right: 16, top: 28, height: '48%' },
      { left: 48, right: 16, top: '62%', height: '18%' }
    ],
    xAxis: [
      {
        type: 'category',
        gridIndex: 0,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: '#94a3b8' } },
        axisLabel: { fontSize: 9, color: '#64748b' }
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        boundaryGap: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false }
      }
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        scale: true,
        splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } },
        axisLabel: { fontSize: 9, color: '#64748b' }
      },
      {
        type: 'value',
        gridIndex: 1,
        scale: true,
        splitNumber: 2,
        axisLabel: { show: false },
        splitLine: { show: false }
      }
    ],
    // 不启用 dataZoom，确保 K 线不会被交互拖拽/重排
    dataZoom: [],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        gridIndex: 0,
        data: candle,
        itemStyle: {
          color: '#ef4444',
          color0: '#22c55e',
          borderColor: '#ef4444',
          borderColor0: '#22c55e'
        }
      },
      {
        name: '成交量',
        type: 'bar',
        gridIndex: 1,
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: vol.map((v, i) => {
          const row = candle[i]
          const up = row && row[1] >= row[0]
          return {
            value: v,
            itemStyle: { color: up ? '#ef4444' : '#22c55e' }
          }
        })
      }
    ]
  }
}

Page({
  data: {
    statusBarHeight: 44,
    activePage: 'home',
    tabSelected: 'home',
    topicDetail: null,
    profileMenus,
    stockSearchInput: '',
    currentStock: {
      name: '',
      code: '',
      price: 0,
      change: 0,
      high: 0,
      low: 0,
      percentile: null,
      trend: '—',
      volatility: '—',
      insight: [],
      suggestion: []
    },
    stockName: '请选择 A 股',
    stockCode: '',
    stockPrice: '¥--',
    stockChange: '--',
    stockChangePositive: true,
    stockDetail: '—',
    high52w: '¥--',
    low52w: '¥--',
    percentileText: '--',
    percentileBarWidth: 0,
    percentileMarkerLeft: 0,
    percentileLabel: '--',
    percentileSub: '',
    percentileDefHint: DEFAULT_PERCENTILE_HINT,
    trendText: '—',
    volText: '—',
    stockQuickQuestions: DEFAULT_STOCK_QUICK_QUESTIONS.slice(),
    aiInsightList: [],
    suggestionList: [],
    stockNewsList: [],
    ecKline: { lazyLoad: true },
    klineShowEcharts: false,
    klinePlaceholderText: '加载K线…',
    klineDomCandles: [],
    klineDomCandleWidthPct: 1,
    klineDomPriceMarks: [],
    klineDomDateLabels: [],
    klineViewBaseMaxCandles: 90,
    klineViewMaxCandles: 90,
    klineViewMinCandles: 18,
    klineViewMaxCandlesLimit: 220,
    chatInput: '',
    chatScrollToId: '',
    chatMessages: [
      {
        role: 'ai',
        text: '您好！我是财懂了AI助手。你可以直接提问做“通用全面分析”；若先在「个股分析」选择一只 A 股，我也能给更聚焦的个股解读。'
      }
    ],
    chatQuickChips: CHAT_QUICK_CHIPS,
    earningsVisible: false,
    earningsHtml: '',
    earningsFileName: '',
    earningsSessionId: '',
    earningsTaskId: '',
    earningsTaskStatus: '',
    earningsStage: '',
    earningsLoading: false,
    earningsPages: [],
    earningsPageIndex: 0,
    earningsPageBlocks: [],
    earningsFacts: [],
    earningsFactChoices: [],
    earningsEditChoiceIndex: 0,
    earningsEditVisible: false,
    earningsEditQuestion: '',
    earningsEditBusy: false,
    chatMsgAreaPx: 520,
    chatInputFocus: false,
    watchlistItems: [],
    watchlistAddVisible: false,
    watchlistAddInput: '',
    watchlistHeaderMarginTopPx: 0,
    homeNewsList: [],
    _newsAnalysisCache: {},
    _homeNewsLoading: false,
    stockSuggestList: [],
    stockSuggestLoading: false,
    currentTopicId: '',
    topicNoteBody: '',
    topicNoteSaved: ''
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
      const inputBarPx = Math.ceil(rpx(420)) + safeBottom
      const msgH = Math.floor(winH - headerPx - inputBarPx)
      this.setData({ chatMsgAreaPx: Math.max(280, msgH) })
    } catch (e) {
      this.setData({ chatMsgAreaPx: 520 })
    }
  },

  _loadWatchlist() {
    let codes = []
    try {
      const saved = wx.getStorageSync(WATCHLIST_STORAGE_KEY)
      if (Array.isArray(saved) && saved.length) {
        codes = saved.map((c) => String(c).trim()).filter(Boolean)
      }
    } catch (e) {}
    const rows = buildWatchlistRows(codes)
    try {
      wx.setStorageSync(WATCHLIST_STORAGE_KEY, rows.map((r) => r.code))
    } catch (e3) {}
    this.setData({ watchlistItems: rows })
    this._refreshWatchlistQuotes(rows.map((r) => r.code))
  },

  _refreshWatchlistQuotes(codeList) {
    const codes = Array.isArray(codeList) ? codeList : []
    codes.forEach((code) => {
      if (!isAshare6digit(code)) return
      getQuote(code)
        .then((res) => {
          if (res.code !== 200 || !res.data) return
          const d = res.data
          const pct = Number(d.pct_chg)
          const items = (this.data.watchlistItems || []).map((row) => {
            if (row.code !== code) return row
            const pos = Number.isFinite(pct) ? pct >= 0 : true
            const ch = Number.isFinite(pct) ? (pct >= 0 ? `+${pct.toFixed(2)}%` : `${pct.toFixed(2)}%`) : '--'
            return {
              code,
              name: d.name || code,
              labelCode: d.symbol || code,
              changeStr: ch,
              positive: pos
            }
          })
          this.setData({ watchlistItems: items })
        })
        .catch(() => {})
    })
  },

  onReady() {
    this._pageViewReady = true
  },

  onLoad() {
    this._stockKlineChart = null
    this._klineOption = null
    this._klineSource = null
    this._klineInitRetryCount = 0
    this._stockSuggestTimer = null
    this._stockSuggestSeq = 0
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
    let last = ''
    try {
      last = String(wx.getStorageSync(PORTAL_LAST_STOCK_KEY) || '').trim()
    } catch (e) {}
    last = normalizeToAshare6(last) || (isAshare6digit(last) ? last : '')
    if (last) {
      this.setData({ stockSearchInput: last })
      const s = stockBaseForKey(last)
      if (s) this.updateStockUI(s)
      this.refreshLiveQuote(last)
    }
    this._loadWatchlist()
    this._loadHomeNewsEnhanced()
  },

  onShow() {
    if (this.data.activePage === 'chat') this._layoutChatArea()
  },

  switchPage(pageId) {
    const fromPage = this.data.activePage
    // 仅当从个股进入 chat 后，返回个股时才跳过 AI 重新生成；切到其它页面则清除标记
    if (pageId !== 'stock' && pageId !== 'chat' && this._chatReturnSkipAiRegen) {
      this._chatReturnSkipAiRegen = false
    }
    if (pageId !== 'stock') {
      if (this._stockSuggestTimer) {
        clearTimeout(this._stockSuggestTimer)
        this._stockSuggestTimer = null
      }
      this._stockSuggestSeq += 1
      if (this.data.stockSuggestList.length || this.data.stockSuggestLoading) {
        this.setData({ stockSuggestList: [], stockSuggestLoading: false })
      }
    }
    const main = ['home', 'stock', 'watchlist', 'earnings', 'mine']
    const patch = { activePage: pageId }
    if (main.includes(pageId)) patch.tabSelected = pageId
    this.setData(patch)
    if (pageId === 'chat') {
      // 记录进入 chat 之前的页面，返回时回到原页面而不是固定首页
      if (fromPage && fromPage !== 'chat') this._chatReturnPage = fromPage
      this.setData({ chatInputFocus: false })
      // 打开聊天页时自动定位到最后一条消息
      const lastIdx = (this.data.chatMessages || []).length - 1
      if (lastIdx >= 0) this.setData({ chatScrollToId: `msg-${lastIdx}` })
      this._layoutChatArea()
      // 从个股页进入聊天：返回时先跳过 LLM 重新生成
      if (fromPage === 'stock') this._chatReturnSkipAiRegen = true
    }
    if (pageId === 'stock') {
      const k = resolveStockKey(this.data.stockSearchInput) || normalizeToAshare6(this.data.stockSearchInput) || ''
      if (isAshare6digit(k)) {
        const skipKlineAi = this._chatReturnSkipAiRegen === true
        if (skipKlineAi) {
          // 从 chat 返回 stock：保持原屏内容，不做任何刷新，避免触发“重新生成分析”的观感
          this._chatReturnSkipAiRegen = false
          return
        } else {
          // 从 chat 返回时跳过，避免重复生成；其它场景仍保证 UI 正确刷新
          const hasAi =
            Array.isArray(this.data.aiInsightList) &&
            this.data.aiInsightList.length > 0 &&
            Array.isArray(this.data.suggestionList) &&
            this.data.suggestionList.length > 0
          if (!hasAi) this.updateStockUI(this.data.currentStock)
        }
        this.refreshLiveQuote(k, { skipKlineAi: false })
      }
    }
  },

  stopBubble() {},

  onTabTap(e) {
    const page = e.currentTarget.dataset.page
    if (page) this.switchPage(page)
  },

  _loadHomeNewsEnhanced() {
    this.setData({ _homeNewsLoading: true })
    getHomeNewsEnhanced(6)
      .then((res) => {
        console.log('📰 首页新闻 API 响应:', res)
        if (res.code === 200 && res.data && Array.isArray(res.data.items)) {
          const items = res.data.items.map((item, idx) => {
            // 原文直链由后端尽量提供；前端不再把“搜索页”伪装成原文
            const url = item.url || ''
            return {
              id: item.id || `news_${idx}`,
              title: item.title || '',
              summary: item.summary || '',
              metaTime: item.metaTime || '',
              metaSource: item.metaSource || '',
              chips: item.chips || [],
              heatPercentile: item.heatPercentile || 60,
              narrativePercent: item.narrativePercent || 60,
              url: url,
              _raw: item._analysis || null,
            }
          })
          console.log('✅ 处理后的新闻列表:', items.length, '条')
          this.setData({ homeNewsList: items, _homeNewsLoading: false })
          items.forEach((item) => {
            if (item._raw && item.id) {
              this.data._newsAnalysisCache[item.id] = item._raw
            }
          })
        } else {
          console.error('❌ 首页新闻 API 返回格式异常:', res)
          this.setData({ _homeNewsLoading: false })
        }
      })
      .catch((err) => {
        console.error('❌ 首页新闻 API 请求失败:', err)
        this.setData({ _homeNewsLoading: false })
      })
  },

  onNewsTap(e) {
    const id = e.currentTarget.dataset.newsid
    console.log('📰 点击新闻:', id)
    if (!id) return

    const cached = this.data._newsAnalysisCache[id]
    console.log('📰 缓存分析结果:', cached)
    if (cached) {
      console.log('📰 使用缓存分析结果')
      this._showTopicDetail(id, cached)
      return
    }

    const newsItem = (this.data.homeNewsList || []).find((n) => n.id === id)
    console.log('📰 新闻项:', newsItem)
    if (!newsItem) return

    wx.showLoading({ title: 'AI分析中...', mask: true })

    console.log('📰 调用AI分析')
    postNewsAiAnalyze({
      title: newsItem.title,
      summary: newsItem.summary.replace(/🤖 AI摘要[：:]\s*/, ''),
      url: newsItem._raw ? (newsItem._raw.url || '') : newsItem.url || '',
      source: newsItem._raw ? (newsItem._raw.source || '') : newsItem.metaSource.replace('来源：', ''),
      publishTime: newsItem.metaTime || '',
      ctime: newsItem._raw ? (newsItem._raw.ctime || 0) : 0,
    })
      .then((res) => {
        console.log('📰 AI分析响应:', res)
        wx.hideLoading()
        if (res.code === 200 && res.data) {
          console.log('📰 AI分析成功，显示详情')
          this.data._newsAnalysisCache[id] = res.data
          this._showTopicDetail(id, res.data)

          const updatedList = (this.data.homeNewsList || []).map((n) => {
            if (n.id !== id) return n
            const d = res.data
            return {
              ...n,
              chips: d.chips || n.chips,
              heatPercentile: d.heat_percentile || n.heatPercentile,
              narrativePercent: d.narrativePercent || n.narrativePercent,
              summary: d.ai_summary || n.summary,
              _raw: d,
            }
          })
          this.setData({ homeNewsList: updatedList })
        } else {
          console.log('📰 AI分析失败:', res)
          wx.showToast({ title: '分析失败，请重试', icon: 'none' })
        }
      })
      .catch((err) => {
        console.log('📰 AI分析网络错误:', err)
        wx.hideLoading()
        wx.showToast({ title: '网络错误', icon: 'none' })
      })
  },

  _showTopicDetail(id, detail) {
    const notes = readTopicNotes()
    const n = notes[id]
    // 原文直链：不再用“搜索页”兜底冒充原文
    const url = (detail && detail.url) ? detail.url : ''
    this.setData({
      topicDetail: { ...detail, topicId: id, url: url },
      currentTopicId: id,
      topicNoteBody: (n && n.noteText) || '',
      topicNoteSaved: n && n.savedAt ? formatTopicNoteTime(n.savedAt) : '',
      activePage: 'topic'
    })
  },

  onBackTopic() {
    this.setData({
      activePage: 'home',
      topicDetail: null,
      currentTopicId: '',
      topicNoteBody: '',
      topicNoteSaved: ''
    })
  },

  onTopicNoteBodyInput(e) {
    this.setData({ topicNoteBody: e.detail.value })
  },

  saveTopicTextNote() {
    const id = this.data.currentTopicId
    if (!id) return
    const stock = this.data.currentStock
    const rec = {
      noteText: this.data.topicNoteBody || '',
      savedAt: Date.now(),
      priceSnapshot: stock ? `${stock.name} ¥${stock.price}` : ''
    }
    const all = readTopicNotes()
    all[id] = { ...all[id], ...rec }
    try {
      wx.setStorageSync(TOPIC_NOTES_KEY, all)
    } catch (err) {}
    this.setData({ topicNoteSaved: formatTopicNoteTime(rec.savedAt) })
    wx.showToast({ title: '笔记已保存', icon: 'success' })
  },

  addTopicToWatchlist() {
    const id = this.data.currentTopicId
    const topic = id ? topicDataMap[id] : null
    if (!topic || !topic.stocks || !topic.stocks.length) return
    let codes = []
    try {
      const saved = wx.getStorageSync(WATCHLIST_STORAGE_KEY)
      if (Array.isArray(saved) && saved.length) codes = saved.map((c) => String(c).trim()).filter(Boolean)
    } catch (e) {}
    const seen = new Set(codes)
    let added = 0
    topic.stocks.forEach((s) => {
      const key = normalizeToAshare6(s.code) || resolveStockKey(s.code)
      if (!key || !isAshare6digit(key) || seen.has(key)) return
      seen.add(key)
      codes.push(key)
      added++
    })
    if (!added) {
      wx.showToast({ title: '未加入（仅支持沪深京 A 股或已在清单中）', icon: 'none' })
      return
    }
    try {
      wx.setStorageSync(WATCHLIST_STORAGE_KEY, codes)
    } catch (e2) {}
    const rows = buildWatchlistRows(codes)
    this.setData({ watchlistItems: rows })
    this._refreshWatchlistQuotes(rows.map((r) => r.code))
    wx.showToast({ title: `已加入 ${added} 只`, icon: 'success' })
  },

  onAiChatEntry() {
    this.switchPage('chat')
  },

  onBackChat() {
    const backTo = this._chatReturnPage || 'home'
    this.switchPage(backTo)
  },

  refreshLiveQuote(key, opts) {
    const skipKlineAi = opts && opts.skipKlineAi === true
    if (!isAshare6digit(key)) return
    getQuote(key)
      .then((res) => {
        if (res.code !== 200 || !res.data) {
          wx.showToast({ title: String(res.msg || '行情失败').slice(0, 18), icon: 'none' })
          const cur = resolveStockKey(this.data.stockSearchInput) || normalizeToAshare6(this.data.stockSearchInput) || ''
          if (cur === key && !skipKlineAi) this._loadKlineForSymbol(key)
          return
        }
        const cur = resolveStockKey(this.data.stockSearchInput) || normalizeToAshare6(this.data.stockSearchInput) || ''
        if (cur !== key) return
        const merged = mergeQuoteIntoStock(stockBaseForKey(key), res)
        let prevAi = null
        let prevSug = null
        if (skipKlineAi) {
          prevAi = this.data.aiInsightList
          prevSug = this.data.suggestionList
        }
        this.updateStockUI(merged)
        if (skipKlineAi && prevAi && prevSug) {
          this.setData({ aiInsightList: prevAi, suggestionList: prevSug })
        }
        if (!skipKlineAi) this._loadKlineForSymbol(key)
      })
      .catch(() => {
        wx.showToast({
          title: '连不上后端：真机请改局域网IP',
          icon: 'none',
          duration: 2800
        })
        const cur = resolveStockKey(this.data.stockSearchInput) || normalizeToAshare6(this.data.stockSearchInput) || ''
        if (cur === key && !skipKlineAi) this._loadKlineForSymbol(key)
      })
  },

  onStockQuickAsk(e) {
    const q0 = e.currentTarget.dataset.q
    if (!q0) return

    this.switchPage('chat')
    this.setData({ chatInput: String(q0), chatInputFocus: true })
  },

  onOpenStockNews(e) {
    const url = e.currentTarget.dataset.url
    if (!url) {
      wx.showToast({ title: '该条暂无原文链接', icon: 'none' })
      return
    }
    const u = String(url)
    if (/search\.sina\.com\.cn\/\?q=/.test(u) || /so\.eastmoney\.com\/news\/s\?/.test(u)) {
      wx.showToast({ title: '当前为搜索页，可能不是原文', icon: 'none', duration: 1800 })
    }
    wx.navigateTo({
      url: `/pages/webview/index?url=${encodeURIComponent(url)}`
    })
  },

  onChatChipTap(e) {
    const q = e.currentTarget.dataset.q
    if (!q) return
    this._sendChatWithText(q)
  },

  _sendChatWithText(raw) {
    const text = String(raw || '').trim()
    if (!text) return
    const cur = this.data.currentStock
    const code = cur && String(cur.code || '').trim()
    const msgs = this.data.chatMessages.concat([{ role: 'user', text }])
    this.setData({
      chatMessages: msgs,
      chatInput: '',
      chatScrollToId: `msg-${msgs.length - 1}`
    })
    const payload = { question: text }
    if (isAshare6digit(code)) payload.symbol = code
    payload.chatHistory = msgs.slice(-8).map((m) => ({
      role: m.role === 'ai' ? 'assistant' : m.role,
      text: String(m.text || '')
    }))
    postResearchAnalyze(payload)
      .then((res) => {
        const summary = res && res.code === 200 && res.data ? res.data.summary : ''
        const followUps = res && res.code === 200 && res.data ? res.data.followUps : []
        const reply = summary || '暂无法生成回答，请检查后端与 LLM 配置。'
        const nextMsgs = msgs.concat([{ role: 'ai', text: reply }])
        const chips = toChatChipsFromFollowUps(followUps)
        this.setData({
          chatMessages: nextMsgs,
          chatScrollToId: `msg-${nextMsgs.length - 1}`,
          chatQuickChips: chips.length ? chips : CHAT_QUICK_CHIPS
        })
      })
      .catch(() => {
        const nextMsgs = msgs.concat([{ role: 'ai', text: '请求失败，请检查网络与后端。' }])
        this.setData({
          chatMessages: nextMsgs,
          chatScrollToId: `msg-${nextMsgs.length - 1}`,
          chatQuickChips: CHAT_QUICK_CHIPS
        })
      })
  },

  onStockSearchInput(e) {
    const v = e.detail.value
    this.setData({ stockSearchInput: v })
    this._scheduleStockSuggest(v)
  },

  openStockPicker() {
    const q = String(this.data.stockSearchInput || '').trim()
    wx.navigateTo({
      url: `/pages/stock-picker/index?q=${encodeURIComponent(q)}`,
      events: {
        pickStock: (payload) => {
          const code = String(payload && payload.code ? payload.code : '').trim()
          if (!code) return
          this._commitStockKey(code)
        }
      }
    })
  },

  _scheduleStockSuggest(raw) {
    if (this._stockSuggestTimer) {
      clearTimeout(this._stockSuggestTimer)
      this._stockSuggestTimer = null
    }
    const q = String(raw || '').trim()
    if (!q) {
      this._stockSuggestSeq += 1
      this.setData({ stockSuggestList: [], stockSuggestLoading: false })
      return
    }
    this._stockSuggestTimer = setTimeout(() => {
      this._stockSuggestTimer = null
      this._fetchStockSuggest(q)
    }, 380)
  },

  _fetchStockSuggest(q) {
    const seq = ++this._stockSuggestSeq
    this.setData({ stockSuggestLoading: true })
    searchStocks(q, 35)
      .then((res) => {
        if (seq !== this._stockSuggestSeq) return
        if (res.code !== 200 || !res.data) {
          this.setData({ stockSuggestList: [], stockSuggestLoading: false })
          return
        }
        const items = Array.isArray(res.data.items) ? res.data.items : []
        this.setData({ stockSuggestList: items, stockSuggestLoading: false })
      })
      .catch(() => {
        if (seq !== this._stockSuggestSeq) return
        this.setData({ stockSuggestList: [], stockSuggestLoading: false })
      })
  },

  _commitStockKey(useKey) {
    const key = String(useKey || '').trim()
    if (!isAshare6digit(key)) {
      wx.showToast({ title: '请选择沪深京 A 股（6 位代码）', icon: 'none' })
      return
    }
    const s = stockBaseForKey(key)
    if (!s) return
    this.setData({ stockSearchInput: key, stockSuggestList: [], stockSuggestLoading: false })
    try {
      wx.setStorageSync(PORTAL_LAST_STOCK_KEY, key)
    } catch (e) {}
    this.updateStockUI(s)
    this.refreshLiveQuote(key)
  },

  onPickStockSuggest(e) {
    const code = String(e.currentTarget.dataset.code || '').trim()
    if (!code) return
    this._stockSuggestSeq += 1
    if (this._stockSuggestTimer) {
      clearTimeout(this._stockSuggestTimer)
      this._stockSuggestTimer = null
    }
    this._commitStockKey(code)
  },

  /** 用后端搜索结果：1 条直接选中，多条写入列表并提示点选，0 条提示未找到 */
  _applyRemoteSuggestItems(items, emptyMsg) {
    const list = Array.isArray(items) ? items : []
    this.setData({ stockSuggestList: list, stockSuggestLoading: false })
    if (!list.length) {
      wx.showToast({ title: emptyMsg || '未找到匹配 A 股', icon: 'none' })
      return
    }
    if (list.length === 1) {
      this._commitStockKey(String(list[0].code || '').trim())
      return
    }
    wx.showToast({ title: '请从下方列表选择一只股票', icon: 'none' })
  },

  onSearchStock() {
    const raw = String(this.data.stockSearchInput || '').trim()
    if (!raw) {
      wx.showToast({ title: '请输入代码或名称', icon: 'none' })
      return
    }
    let key = resolveStockKey(raw)
    if (!key && isAshare6digit(raw)) key = raw
    if (key) {
      this._commitStockKey(key)
      return
    }
    const sug = this.data.stockSuggestList
    if (sug && sug.length === 1) {
      this._commitStockKey(String(sug[0].code || '').trim())
      return
    }
    if (sug && sug.length > 1) {
      wx.showToast({ title: '请从下方列表选择一只股票', icon: 'none' })
      return
    }
    /* 列表往往还空：防抖未完成 / 请求未返回 / 刚切到个股 —— 点「分析」时补一次即时搜索 */
    if (this._stockSuggestTimer) {
      clearTimeout(this._stockSuggestTimer)
      this._stockSuggestTimer = null
    }
    this._stockSuggestSeq += 1
    wx.showLoading({ title: '查找中', mask: true })
    searchStocks(raw, 35)
      .then((res) => {
        wx.hideLoading()
        if (res.code !== 200 || !res.data) {
          const tip = res.code === 503 ? '股票列表暂不可用（检查后端与 akshare）' : String(res.msg || '接口异常').slice(0, 18)
          wx.showToast({ title: tip, icon: 'none', duration: 2800 })
          return
        }
        this._applyRemoteSuggestItems(res.data.items, '未找到匹配 A 股，可换关键词')
      })
      .catch(() => {
        wx.hideLoading()
        wx.showToast({
          title: '连不上后端：真机请配局域网 IP 并启动服务',
          icon: 'none',
          duration: 2800
        })
      })
  },

  _disposeKlineChartIfAny() {
    if (this._stockKlineChart) {
      try {
        // 清理画布与引用，避免上一次绘制“残影”影响当前布局
        this._stockKlineChart.clear()
        this._stockKlineChart.dispose()
      } catch (e) {}
      this._stockKlineChart = null
    }
  },

  onResetKline() {
    try {
      if (!this._klineSource) return
      this.setData({ klineViewMaxCandles: this.data.klineViewBaseMaxCandles || 90 }, () => {
        this._ensureKlineChart()
      })
    } catch (e) {}
  },

  onKlineTouchStart(e) {
    try {
      const t = e && e.touches && e.touches[0]
      this._klineTouchLastX = t && typeof t.clientX === 'number' ? t.clientX : 0
      this._klineTouchLastY = t && typeof t.clientY === 'number' ? t.clientY : 0
      this._klineTouchAcc = 0
    } catch (err) {}
  },

  onKlineTouchMove(e) {
    try {
      if (!this._klineSource) return
      const t = e && e.touches && e.touches[0]
      if (!t || typeof t.clientX !== 'number' || typeof t.clientY !== 'number') return

      const lastX = typeof this._klineTouchLastX === 'number' ? this._klineTouchLastX : t.clientX
      const lastY = typeof this._klineTouchLastY === 'number' ? this._klineTouchLastY : t.clientY
      const dx = t.clientX - lastX
      const dy = t.clientY - lastY

      this._klineTouchLastX = t.clientX
      this._klineTouchLastY = t.clientY

      // 主导方向：横向(dx)优先于纵向(dy)
      const useDx = Math.abs(dx) >= Math.abs(dy)

      this._klineTouchAcc = (this._klineTouchAcc || 0) + (useDx ? dx : dy)
      if (Math.abs(this._klineTouchAcc) < 2) return

      let maxCandles = Number(this.data.klineViewMaxCandles) || 90
      const minCandles = Number(this.data.klineViewMinCandles) || 30
      const maxLimit = Number(this.data.klineViewMaxCandlesLimit) || 140

      // dx < 0：向左 -> 更多日期（放大日期范围/缩小到更远？这里按“更多日期=更多K线”处理）=> visible 增大
      // dx > 0：向右 -> 更少日期 => visible 减小
      // dy < 0：上划 -> 更近（显示更少K线）=> visible 减小
      // dy > 0：下滑 -> 更远（显示更多K线）=> visible 增大
      if (useDx) {
        if (this._klineTouchAcc < 0) maxCandles = Math.min(maxLimit, Math.ceil(maxCandles * 1.6))
        else maxCandles = Math.max(minCandles, Math.floor(maxCandles * 0.6))
      } else {
        if (this._klineTouchAcc < 0) maxCandles = Math.max(minCandles, Math.floor(maxCandles * 0.6))
        else maxCandles = Math.min(maxLimit, Math.ceil(maxCandles * 1.6))
      }

      this._klineTouchAcc = 0
      this.setData({ klineViewMaxCandles: maxCandles }, () => this._ensureKlineChart())
    } catch (err) {}
  },

  _loadKlineForSymbol(code6) {
    const seq = (this._klineReqSeq = (this._klineReqSeq || 0) + 1)
    const c = String(code6 || '')
      .trim()
      .replace(/\D/g, '')
      .slice(-6)
    if (!isAshare6digit(c)) {
      this._disposeKlineChartIfAny()
      this.setData({
        klineShowEcharts: false,
        klinePlaceholderText: '非沪深京 A 股暂无日线 K 线'
      })
      return
    }
    // 重新加载 K 线前，先清理旧图表，避免旧 canvas 尺寸/绘制残留
    this._disposeKlineChartIfAny()
    this.setData({
      klinePlaceholderText: '加载K线…',
      aiInsightList: ['正在生成 AI 分析…'],
      suggestionList: ['请稍候…']
    })
    getStockDailyBars(c)
      .then((res) => {
        // 旧请求返回了就丢弃，避免并发导致“多层/错位”
        if (seq !== this._klineReqSeq) return
        if (res.code !== 200 || !res.data) {
          this._disposeKlineChartIfAny()
          this.setData({
            klineShowEcharts: false,
            // 不要过度截断错误信息：用于定位后端/AKShare 的失败原因
            klinePlaceholderText: String(res.msg || 'K线失败').slice(0, 180)
          })
          this._refreshLLMInsightIfPossible(this.data.currentStock)
          return
        }
        const d = res.data
        if (!d.dates || !d.candle || !d.dates.length) {
          this._disposeKlineChartIfAny()
          this.setData({ klineShowEcharts: false, klinePlaceholderText: '无K线数据' })
          this._refreshLLMInsightIfPossible(this.data.currentStock)
          return
        }
        const cur = this.data.currentStock || {}
        const tv = computeTrendVolFromCandles(d.candle || [])
        const rawPct = Number(d.percentile)
        const pctUi = percentileUiFromNumber(rawPct)
        const merged = {
          ...cur,
          high: d.high_52w,
          low: d.low_52w,
          percentile: rawPct,
          trend: tv.trend,
          volatility: tv.volatility
        }
        this.setData(
          {
            klineShowEcharts: true,
            klinePlaceholderText: '',
            // 切换标的时恢复默认缩放，避免上一轮的放大/缩小影响观感
            klineViewMaxCandles: this.data.klineViewBaseMaxCandles || 90,
            currentStock: merged,
            high52w: `¥${d.high_52w}`,
            low52w: `¥${d.low_52w}`,
            percentileText: pctUi ? pctUi.label : '--',
            percentileBarWidth: pctUi ? pctUi.barWidth : 0,
            percentileMarkerLeft: pctUi ? Math.min(100, Math.max(0, pctUi.marker)) : 0,
            percentileLabel: pctUi ? pctUi.label : '--',
            percentileSub: pctUi ? pctUi.sub : '',
            trendText: tv.trend,
            volText: tv.volatility
          },
          () => {
            // K 线与「历史位置」已对齐同一套 daily-bars 数据后再拉 LLM，避免分位与文案不一致
            this._refreshLLMInsightIfPossible(merged)
          }
        )
        this._klineInitRetryCount = 0
        // 用自绘 K 线 canvas 替代 ECharts
        this._klineSource = d
        const run = () => this._ensureKlineChart()
        if (typeof wx.nextTick === 'function') wx.nextTick(run)
        else setTimeout(run, 50)
      })
      .catch(() => {
        if (seq !== this._klineReqSeq) return
        this._disposeKlineChartIfAny()
        this.setData({
          klineShowEcharts: false,
          klinePlaceholderText: '网络错误，无法加载K线'
        })
        this._refreshLLMInsightIfPossible(this.data.currentStock)
      })
  },

  _ensureKlineChart() {
    // DOM 方式绘制 K 线（替代 canvas/ECharts）
    if (!this._klineSource) return
    const src = this._klineSource

    const candleRaw = Array.isArray(src.candle) ? src.candle : []
    const dateRaw = Array.isArray(src.dates) ? src.dates : []

    const maxCandles = Number(this.data.klineViewMaxCandles) || 90
    const start = Math.max(0, candleRaw.length - maxCandles)

    const candles = []
    const dates = []
    for (let i = start; i < candleRaw.length; i++) {
      const r = candleRaw[i]
      if (!Array.isArray(r) || r.length < 4) continue
      const o = Number(r[0])
      const c = Number(r[1])
      const lo = Number(r[2])
      const hi = Number(r[3])
      if (![o, c, lo, hi].every((x) => Number.isFinite(x))) continue
      candles.push([o, c, lo, hi])
      const ds = dateRaw[i]
      const s = ds == null ? '' : String(ds)
      // 统一成“MM-DD”，视觉更紧凑
      const short = s.includes('-') ? s.slice(5) : s
      dates.push(short)
    }

    if (!candles.length) {
      this.setData({ klineShowEcharts: false, klinePlaceholderText: '无K线数据' })
      this.setData({
        klineDomCandles: [],
        klineDomCandleWidthPct: 1,
        klineDomDateLabels: [],
        klineDomPriceMarks: []
      })
      return
    }

    const lows = candles.map((r) => r[2])
    const highs = candles.map((r) => r[3])
    const minLow = Math.min(...lows)
    let maxHigh = Math.max(...highs)
    if (!Number.isFinite(minLow) || !Number.isFinite(maxHigh)) {
      this.setData({ klineShowEcharts: false, klinePlaceholderText: 'K线数据异常' })
      return
    }
    if (minLow === maxHigh) maxHigh = minLow + 1
    const range = maxHigh - minLow
    // 视觉留白：给蜡烛映射的价格范围做一点扩展，避免触顶触底
    const pad = range * 0.08
    const renderMinLow = minLow - pad
    const renderMaxHigh = maxHigh + pad
    const renderRange = renderMaxHigh - renderMinLow

    const candleCount = candles.length

    // 以百分比控制宽度，保证缩放后蜡烛不会太窄
    const candleWidthPct = Math.min(8, 100 / candleCount)

    const midPrice = (renderMinLow + renderMaxHigh) / 2
    const klineDomPriceMarks = [
      { text: `¥${renderMaxHigh.toFixed(2)}`, topPct: 10 },
      { text: `¥${midPrice.toFixed(2)}`, topPct: 50 },
      { text: `¥${renderMinLow.toFixed(2)}`, topPct: 90 }
    ]

    const wickMinPct = 0.45
    const bodyMinPct = 0.55

    // 蜡烛内部宽度：用“蜡烛宽度的百分比”随缩放一起变化
    // wick 要细，body 要略宽，避免“看起来粗糙/不清晰”
    const wickWidthPct = 22
    const bodyWidthPct = 58

    const domCandles = candles.map((row, idx) => {
      const o = row[0]
      const c = row[1]
      const lo = row[2]
      const hi = row[3]
      // 颜色口径：红=上涨（收盘>=开盘），绿=下跌（收盘<开盘）
      const up = c >= o
      const color = up ? '#ef4444' : '#22c55e'

      const wickTopPct = ((renderMaxHigh - hi) / renderRange) * 100
      const wickBottomPct = ((renderMaxHigh - lo) / renderRange) * 100
      const wickHeightPct = Math.max(wickMinPct, wickBottomPct - wickTopPct)

      const topPrice = Math.min(o, c)
      const bottomPrice = Math.max(o, c)
      const bodyTopPct = ((renderMaxHigh - topPrice) / renderRange) * 100
      const bodyBottomPct = ((renderMaxHigh - bottomPrice) / renderRange) * 100
      const bodyHeightPct = Math.max(bodyMinPct, bodyBottomPct - bodyTopPct)

      return {
        idx,
        color,
        wickTopPct,
        wickHeightPct,
        bodyTopPct,
        bodyHeightPct,
        wickWidthPct,
        bodyWidthPct
      }
    })

    // 生成横轴日期：根据当前可见“时间跨度”取点
    const dateLen = dates.length
    let dateLabels = []

    if (dateLen > 0) {
      // 近看 -> 标签略多；远看 -> 标签略少（类似主流 K 线的观感）
      let labelCount = 5
      if (candleCount <= 30) labelCount = 7
      else if (candleCount <= 60) labelCount = 6
      else labelCount = 5
      labelCount = Math.min(labelCount, dateLen)

      const parseYMDtoMs = (s) => {
        try {
          // s: YYYY-MM-DD
          if (!s || typeof s !== 'string' || !s.includes('-')) return NaN
          const parts = s.slice(0, 10).split('-')
          if (parts.length !== 3) return NaN
          const y = Number(parts[0])
          const m = Number(parts[1]) - 1
          const d = Number(parts[2])
          const t = Date.UTC(y, m, d)
          return Number.isFinite(t) ? t : NaN
        } catch (e) {
          return NaN
        }
      }

      const firstT = parseYMDtoMs(dates[0])
      const lastT = parseYMDtoMs(dates[dateLen - 1])

      // 如果解析失败，退回到“按索引均匀取点”
      if (!Number.isFinite(firstT) || !Number.isFinite(lastT) || firstT === lastT) {
        for (let j = 0; j < labelCount; j++) {
          const pickIdx = Math.round((j * (dateLen - 1)) / (labelCount - 1))
          dateLabels.push(dates[pickIdx] || '')
        }
      } else {
        for (let j = 0; j < labelCount; j++) {
          const targetT = firstT + ((lastT - firstT) * j) / (labelCount - 1)
          // 找到最接近 target 的日期点（第一个 >= target 的交易日）
          let pick = 0
          for (let i = 0; i < dateLen; i++) {
            const ti = parseYMDtoMs(dates[i])
            if (!Number.isFinite(ti)) continue
            if (ti >= targetT) {
              pick = i
              break
            }
            pick = i
          }
          dateLabels.push(dates[pick] || '')
        }
      }

      // 去掉相邻重复，保证不会出现一坨相同日期
      const dedup = []
      for (let i = 0; i < dateLabels.length; i++) {
        if (i === 0 || dateLabels[i] !== dateLabels[i - 1]) dedup.push(dateLabels[i])
      }
      dateLabels = dedup
      if (dateLabels.length) dateLabels[0] = dates[0]
      if (dateLabels.length) dateLabels[dateLabels.length - 1] = dates[dateLen - 1]
    }

    this.setData({
      klineDomCandles: domCandles,
      klineDomCandleWidthPct: candleWidthPct,
      klineDomDateLabels: dateLabels,
      klineDomPriceMarks
    })
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
    this._sendChatWithText(this.data.chatInput)
  },

  onWatchItemTap(e) {
    const code = String(e.currentTarget.dataset.code || '').trim()
    if (!isAshare6digit(code)) return
    const s = stockBaseForKey(code)
    if (!s) return
    this.setData({ stockSearchInput: code })
    try {
      wx.setStorageSync(PORTAL_LAST_STOCK_KEY, code)
    } catch (err) {}
    this.updateStockUI(s)
    this.refreshLiveQuote(code)
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
    const raw = String(this.data.watchlistAddInput || '').trim()
    const key = normalizeToAshare6(raw) || resolveStockKey(raw)
    if (!key || !isAshare6digit(key)) {
      wx.showToast({ title: '请输入沪深京 A 股 6 位代码', icon: 'none' })
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
    const rows = buildWatchlistRows(next)
    this.setData({
      watchlistItems: rows,
      watchlistAddVisible: false,
      watchlistAddInput: ''
    })
    this._refreshWatchlistQuotes(rows.map((r) => r.code))
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
          earningsFileName: name,
          earningsHtml: '',
          earningsSessionId: '',
          earningsTaskId: '',
          earningsTaskStatus: 'uploading',
          earningsStage: '上传中...',
          earningsLoading: true,
          earningsPages: [],
          earningsPageIndex: 0,
          earningsPageBlocks: []
        })
        this._startEarningsFromFile(f.path, name)
      },
      fail: () => {
        wx.showToast({ title: '请选择 PDF 文件', icon: 'none' })
      }
    })
  },

  async _startEarningsFromFile(filePath, name) {
    try {
      const up = await uploadPdf(filePath, name)
      const sid = String(up && up.sessionId ? up.sessionId : '').trim()
      if (!sid) throw new Error('sessionId missing')
      this.setData({ earningsSessionId: sid, earningsTaskStatus: 'queued', earningsStage: '任务已创建' })
      const st = await startAnalyze(sid)
      const tid = String(st && st.taskId ? st.taskId : '').trim()
      if (!tid) throw new Error('taskId missing')
      this.setData({ earningsTaskId: tid, earningsTaskStatus: 'running', earningsStage: '分析中...' })
      this._pollEarningsTask(tid)
    } catch (e) {
      this.setData({
        earningsLoading: false,
        earningsTaskStatus: 'failed',
        earningsStage: '启动失败',
        earningsHtml: explainBackendConnectionError(formatApiError(e, '启动失败'))
      })
    }
  },

  _pollEarningsTask(taskId) {
    const run = async () => {
      try {
        const out = await getTask(taskId)
        const status = String(out && out.status ? out.status : '')
        const stage = String(out && out.stage ? out.stage : '')
        this.setData({ earningsTaskStatus: status, earningsStage: stage })
        if (status === 'succeeded') {
          const result = (out && out.result) || {}
          const summary = String(result.summary || result.answer || '分析完成')
          const pages = Array.isArray(result.pages) ? result.pages.map((x) => String(x || '')) : []
          const facts = Array.isArray(result.facts) ? result.facts : []
          const factChoices = this._buildEarningsFactChoices(facts)
          const firstMd = pages[0] || ''
          this.setData({
            earningsLoading: false,
            earningsHtml: summary,
            earningsPages: pages,
            earningsPageIndex: 0,
            earningsPageBlocks: firstMd ? parsePageToBlocks(firstMd) : [],
            earningsFacts: facts,
            earningsFactChoices: factChoices,
            earningsEditChoiceIndex: 0
          })
          return
        }
        if (status === 'failed') {
          this.setData({
            earningsLoading: false,
            earningsHtml: String(out && out.error ? out.error : '分析失败'),
            earningsPages: [],
            earningsPageIndex: 0,
            earningsPageBlocks: []
          })
          return
        }
      } catch (e) {
        this.setData({
          earningsLoading: false,
          earningsTaskStatus: 'failed',
          earningsStage: '轮询失败',
          earningsHtml: '任务轮询失败，请稍后重试。',
          earningsPages: [],
          earningsPageIndex: 0,
          earningsPageBlocks: []
        })
        return
      }
      this._earningsPollTimer = setTimeout(run, 1600)
    }
    run()
  },

  _syncEarningsPageBlocks(index) {
    const pages = this.data.earningsPages || []
    if (!pages.length) {
      this.setData({ earningsPageIndex: 0, earningsPageBlocks: [] })
      return
    }
    const i = Math.max(0, Math.min(Number(index) || 0, pages.length - 1))
    const raw = String(pages[i] || '')
    this.setData({
      earningsPageIndex: i,
      earningsPageBlocks: raw ? parsePageToBlocks(raw) : []
    })
  },

  onEarningsPagePrev() {
    const i = (this.data.earningsPageIndex || 0) - 1
    if (i < 0) return
    this._syncEarningsPageBlocks(i)
  },

  onEarningsPageNext() {
    const pages = this.data.earningsPages || []
    const i = (this.data.earningsPageIndex || 0) + 1
    if (i >= pages.length) return
    this._syncEarningsPageBlocks(i)
  },

  openEarningsEdit() {
    this.setData({ earningsEditVisible: true, earningsEditQuestion: '', earningsEditChoiceIndex: 0 })
  },

  closeEarningsEdit() {
    this.setData({ earningsEditVisible: false })
  },

  onEarningsEditQuestionInput(e) {
    this.setData({ earningsEditQuestion: e.detail.value })
  },

  onEarningsEditChoiceChange(e) {
    const idx = Number(e.detail.value || 0)
    this.setData({ earningsEditChoiceIndex: Number.isFinite(idx) ? idx : 0 })
  },

  _buildEarningsFactChoices(facts) {
    const out = []
    const seen = new Set()
    for (const f of facts || []) {
      if (!f || typeof f !== 'object') continue
      const ind = String(f.indicator || '').trim()
      if (!ind) continue
      const parts = [ind]
      if (f.value) parts.push(String(f.value).trim())
      if (f.page) parts.push(String(f.page).trim())
      const s = parts.join('｜')
      if (!s || seen.has(s)) continue
      seen.add(s)
      out.push(s)
      if (out.length >= 240) break
    }
    return out
  },

  async saveEarningsEdit() {
    if (this.data.earningsEditBusy) return
    const sessionId = String(this.data.earningsSessionId || '').trim()
    if (!sessionId) return
    const idx = Number(this.data.earningsPageIndex || 0)
    const customQuestion = String(this.data.earningsEditQuestion || '').trim()
    const choices = this.data.earningsFactChoices || []
    const choice = choices.length ? String(choices[this.data.earningsEditChoiceIndex || 0] || '').trim() : ''
    this.setData({ earningsEditBusy: true })
    try {
      const resp = await regenPage({
        sessionId,
        pageIndex: idx,
        customQuestion: customQuestion || undefined,
        choice: choice || undefined
      })
      const pages = Array.isArray(resp.pages) ? resp.pages.map((x) => String(x || '')) : (this.data.earningsPages || [])
      const nextIdx = resp.pageIndex != null ? Number(resp.pageIndex) : idx
      this.setData({ earningsPages: pages, earningsEditVisible: false })
      this._syncEarningsPageBlocks(nextIdx)
      wx.showToast({ title: '已重新生成', icon: 'success' })
    } catch (e) {
      wx.showToast({ title: '重算失败', icon: 'none' })
    } finally {
      this.setData({ earningsEditBusy: false })
    }
  },

  tapMenu(e) {
    const name = e.currentTarget.dataset.name || ''
    wx.showToast({ title: String(name), icon: 'none' })
  },

  _applyEmptyStockUI() {
    this._disposeKlineChartIfAny()
    this._klineSource = null
    this.setData({
      currentStock: {
        name: '',
        code: '',
        price: 0,
        change: 0,
        high: 0,
        low: 0,
        percentile: null,
        trend: '—',
        volatility: '—',
        insight: [],
        suggestion: []
      },
      stockName: '请选择 A 股',
      stockCode: '',
      stockPrice: '¥--',
      stockChange: '--',
      stockChangePositive: true,
      stockDetail: '—',
      high52w: '¥--',
      low52w: '¥--',
      percentileText: '--',
      percentileBarWidth: 0,
      percentileMarkerLeft: 0,
      percentileLabel: '--',
      percentileSub: '',
      percentileDefHint: DEFAULT_PERCENTILE_HINT,
      trendText: '—',
      volText: '—',
      stockQuickQuestions: DEFAULT_STOCK_QUICK_QUESTIONS.slice(),
      aiInsightList: [],
      suggestionList: [],
      klineShowEcharts: false,
      klinePlaceholderText: '请先搜索并选择沪深京 A 股',
      klineDomCandles: [],
      klineDomCandleWidthPct: 1,
      klineDomDateLabels: [],
      klineDomPriceMarks: []
    })
  },

  updateStockUI(stock) {
    if (!stock) {
      this._applyEmptyStockUI()
      return
    }
    const code = String(stock.code || '').trim()
    if (!isAshare6digit(code)) {
      this._applyEmptyStockUI()
      return
    }

    const hasPrice = Number(stock.price) > 0
    let detail
    if (stock.open != null && stock.high != null && stock.low != null) {
      detail = `今开${stock.open} 最高${stock.high} 最低${stock.low}`
    } else if (hasPrice) {
      const openPrice = (stock.price * (1 - stock.change / 100)).toFixed(2)
      detail = `今开${openPrice} 最高${(stock.price * 1.02).toFixed(2)} 最低${(stock.price * 0.98).toFixed(2)}`
    } else {
      detail = '加载行情中…'
    }

    const pctLabel =
      hasPrice || (Number.isFinite(stock.change) && stock.change !== 0)
        ? stock.change >= 0
          ? `+${stock.change}%`
          : `${stock.change}%`
        : '--'
    const priceStr = hasPrice ? `¥${stock.price}` : '¥--'
    const hasPct = stock.percentile != null && stock.percentile !== '' && Number.isFinite(Number(stock.percentile))
    const pctUi = hasPct ? percentileUiFromNumber(stock.percentile) : null

    this.setData({
      currentStock: stock,
      stockName: stock.name || code,
      stockCode: stock.code,
      stockPrice: priceStr,
      stockChange: pctLabel,
      stockChangePositive: !hasPrice ? true : stock.change >= 0,
      stockDetail: detail,
      high52w: stock.high ? `¥${stock.high}` : '¥--',
      low52w: stock.low ? `¥${stock.low}` : '¥--',
      percentileText: pctUi ? pctUi.label : '--',
      percentileBarWidth: pctUi ? pctUi.barWidth : 0,
      percentileMarkerLeft: pctUi ? Math.min(100, Math.max(0, pctUi.marker)) : 0,
      percentileLabel: pctUi ? pctUi.label : '--',
      percentileSub: pctUi ? pctUi.sub : '',
      trendText: stock.trend || '—',
      volText: stock.volatility || '—',
      // 切换股票时先重置为默认追问，避免短暂显示上一只股票的追问
      stockQuickQuestions: DEFAULT_STOCK_QUICK_QUESTIONS.slice(),
      aiInsightList: [],
      suggestionList: []
    })
    // AI 研判在 K 线 daily-bars 成功并写入分位后再请求，避免与「历史位置」口径不一致；见 _loadKlineForSymbol
  },

  _refreshLLMInsightIfPossible(stock) {
    try {
      const code = String(stock && stock.code ? stock.code : '').trim()
      if (!isAshare6digit(code)) return
      const seq = (this._aiInsightReqSeq = (this._aiInsightReqSeq || 0) + 1)
      this.setData({
        aiInsightList: ['正在生成 AI 分析…'],
        suggestionList: ['请稍候…']
      })

      postStockLLMInsight({ symbol: code })
        .then((res) => {
          if (seq !== this._aiInsightReqSeq) return
          const curCode = String((this.data.currentStock && this.data.currentStock.code) || '').trim()
          // 切股后旧请求返回：直接丢弃，避免把上一只股票的问题写回当前页面
          if (curCode !== code) return
          const payload = res && res.data
          let aiInsightList = payload && Array.isArray(payload.aiInsightList) ? payload.aiInsightList : []
          let suggestionList = payload && Array.isArray(payload.suggestionList) ? payload.suggestionList : []
          let quickQuestionList = payload && Array.isArray(payload.quickQuestionList) ? payload.quickQuestionList : []
          let stockNewsList = payload && Array.isArray(payload.stockNews) ? payload.stockNews : []
          const meta = payload && payload.meta && typeof payload.meta === 'object' ? payload.meta : {}
          const pdef =
            meta.percentileDefinition != null && String(meta.percentileDefinition).trim()
              ? String(meta.percentileDefinition).slice(0, 360)
              : DEFAULT_PERCENTILE_HINT
          
          // 格式化新闻时间并确保每个新闻都有url
          const formattedNews = stockNewsList.map((n) => {
            const ctime = n.ctime || 0
            const ctimeStr = ctime > 0 ? formatCtime(ctime) : ''
            // 个股新闻原文链接尽量由后端提供；前端不再造搜索页假装原文
            const url = n.url || ''
            return { ...n, ctime: Number(ctime) || 0, ctimeStr, url }
          }).sort((a, b) => {
            // 相关新闻按发布时间倒序：最新在前
            return (b.ctime || 0) - (a.ctime || 0)
          })
          
          // 后端在 LLM 失败时可能仍返回 code=500 但附带模板化 aiInsightList/suggestionList，前端应展示
          if (aiInsightList.length || suggestionList.length) {
            this.setData({
              aiInsightList,
              suggestionList,
              percentileDefHint: pdef,
              stockQuickQuestions:
                quickQuestionList.length > 0 ? quickQuestionList : this.data.stockQuickQuestions,
              stockNewsList: formattedNews
            })
            return
          }
          const tip = res && res.msg ? String(res.msg).slice(0, 160) : '分析暂不可用（请检查网络、后端与 LLM 环境变量）'
          this.setData({
            aiInsightList: [tip],
            suggestionList: ['—'],
            stockQuickQuestions:
              quickQuestionList.length > 0 ? quickQuestionList : this.data.stockQuickQuestions,
            percentileDefHint: pdef,
            stockNewsList: formattedNews
          })
        })
        .catch(() => {
          if (seq !== this._aiInsightReqSeq) return
          const curCode = String((this.data.currentStock && this.data.currentStock.code) || '').trim()
          if (curCode !== code) return
          this.setData({
            aiInsightList: ['分析请求失败，请检查网络与后端'],
            suggestionList: ['—']
          })
        })
    } catch (e) {}
  }
})
