const { profileMenus } = require('../../utils/data')
const { getQuote, searchStocks, getStockDailyBars } = require('../../utils/api')
const { getCodeByKeyword } = require('../../utils/helpers')

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

function buildChatReply(userText, stock) {
  const s = stock
  const t = String(userText || '')
  const p = s.percentile
  if (/分位|位置|操作/.test(t)) {
    return `【${s.name}】近一年价格分位约 ${p}%（演示数据）。分位偏高时追涨容错低，偏低时更需结合基本面是否恶化；当前趋势「${s.trend}」，波动「${s.volatility}」。${s.insight[0]}`
  }
  if (/风险|情景|警惕|不及预期/.test(t)) {
    return `【${s.name}】可重点关注：① ${s.volatility}波动下仓位节奏；② 行业政策与景气边际；③ ${s.suggestion[0] || '注意业绩与估值匹配。'}（演示回复，接入模型后可细化。）`
  }
  if (/同业|对比|优势/.test(t)) {
    return `【${s.name}】与同业对比（演示）：优势常体现在${s.insight[0]}；风险在于行业竞争与成本。建议用一致口径比较 PE、增速与 ROE。`
  }
  if (/大盘|指数|联动|急跌/.test(t)) {
    return `【${s.name}】与大盘联动为统计意义上的经验描述（演示）。当前分位 ${p}%，若指数急跌，高估值/高波动标的往往回撤更大，需结合您的持仓周期。`
  }
  return `【${s.name}】现价约 ¥${s.price}，分位 ${p}%，趋势「${s.trend}」。${s.insight[0]} ${s.insight[1] || ''}`
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
  },
  '600096': {
    name: '云天化',
    code: '600096.SH',
    price: 22.5,
    change: 1.8,
    high: 26,
    low: 18,
    percentile: 61,
    trend: '震荡上行',
    volatility: '中',
    insight: ['磷化工一体化优势。', '化肥景气与成本管控。'],
    suggestion: ['关注产品价格与出口政策。', '周期波动下注意仓位。']
  },
  '600598': {
    name: '北大荒',
    code: '600598.SH',
    price: 14.2,
    change: -0.21,
    high: 15.6,
    low: 13.1,
    percentile: 44,
    trend: '区间震荡',
    volatility: '中',
    insight: ['粮价与种植链情绪相关。', '关注农产品价格与政策补贴。'],
    suggestion: ['波段思路，注意商品波动。']
  },
  '601952': {
    name: '苏垦农发',
    code: '601952.SH',
    price: 9.85,
    change: 0.05,
    high: 10.4,
    low: 9.2,
    percentile: 51,
    trend: '区间震荡',
    volatility: '中',
    insight: ['区域种植与加工一体化。', '成本与粮价双重驱动。'],
    suggestion: ['适合作为农业主题配置观察。']
  }
}

const WATCHLIST_STORAGE_KEY = 'portal_watchlist_codes'
const WATCHLIST_DEFAULT = ['600519', '600028', '02097', '01364']
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

function isAshare6digit(code) {
  return /^\d{6}$/.test(String(code || '').trim())
}

function resolveStockKey(raw) {
  const orig = String(raw || '').trim()
  if (!orig) return null
  if (stockData[orig]) return orig
  const sul = orig.toUpperCase()
  const stripped = orig.replace(/\.(SH|SZ|HK)$/i, '')
  if (stockData[stripped]) return stripped
  for (const k of Object.keys(stockData)) {
    const c = String(stockData[k].code).toUpperCase()
    if (c === sul || c.replace(/\./g, '') === stripped.replace(/\./g, '').toUpperCase()) return k
  }

  const alias = getCodeByKeyword(orig)
  if (alias) {
    if (stockData[alias]) return alias
    if (isAshare6digit(alias)) return alias
  }

  const compact = orig.replace(/\s+/g, '')
  for (const k of Object.keys(stockData)) {
    const nm = String(stockData[k].name || '').replace(/\s+/g, '')
    if (nm && nm === compact) return k
  }
  if (orig.length >= 2) {
    for (const k of Object.keys(stockData)) {
      const nm = stockData[k].name || ''
      if (nm && nm.includes(orig)) return k
    }
  }
  return null
}

/** 无内置演示数据时，仍允许输入 6 位 A 股拉后端行情 */
function stockBaseForKey(key) {
  if (stockData[key]) {
    return { ...stockData[key] }
  }
  if (isAshare6digit(key)) {
    return {
      name: key,
      code: key,
      price: 0,
      change: 0,
      high: 0,
      low: 0,
      percentile: 50,
      trend: '—',
      volatility: '—',
      insight: ['已连接后端时将显示实时价量；以下为占位说明。'],
      suggestion: ['若长期无牌价，请检查网络与后端 /api/stock。']
    }
  }
  return { ...stockData['600519'] }
}

function mergeQuoteIntoStock(base, apiRes) {
  if (!base || !apiRes || apiRes.code !== 200 || !apiRes.data) return base
  const d = apiRes.data
  const pct = Number(d.pct_chg)
  const change = Number.isFinite(pct) ? pct : base.change
  const price = d.price != null ? Number(d.price) : base.price
  const open = d.open != null ? Number(d.open) : undefined
  const high = d.high != null ? Number(d.high) : base.high
  const low = d.low != null ? Number(d.low) : base.low
  return {
    ...base,
    name: d.name || base.name,
    code: d.symbol || d.code || base.code,
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

/** ECharts：A股红涨绿跌 + 成交量 + 内置缩放 */
function buildStockKlineOption(d) {
  const dates = d.dates || []
  const candle = d.candle || []
  const vol = d.volume || []
  const n = dates.length
  const startPct = n > 80 ? Math.max(0, 100 - (80 / n) * 100) : 0
  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' }
    },
    axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
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
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: startPct,
        end: 100,
        filterMode: 'filter'
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        start: startPct,
        end: 100,
        height: 22,
        bottom: 4,
        borderColor: '#e2e8f0',
        fillerColor: 'rgba(15,47,115,0.12)',
        handleStyle: { color: '#0f2f73' }
      }
    ],
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
    stockSearchInput: '600519',
    currentStock: stockData['600519'],
    ecKline: { lazyLoad: true },
    klineShowEcharts: false,
    klinePlaceholderText: '加载K线…',
    chatInput: '',
    chatMessages: [
      {
        role: 'ai',
        text: '您好！我是财懂了AI助手。可先点下方场景问题，也可直接输入。我会结合您当前查看的个股与价格分位来答（演示版为模板回复）。'
      }
    ],
    chatQuickChips: CHAT_QUICK_CHIPS,
    earningsVisible: false,
    earningsHtml: '',
    earningsFileName: '',
    chatMsgAreaPx: 520,
    chatInputFocus: false,
    watchlistItems: [],
    watchlistAddVisible: false,
    watchlistAddInput: '',
    watchlistHeaderMarginTopPx: 0,
    homeNewsList: buildHomeNewsList(),
    stockSuggestList: [],
    stockSuggestLoading: false,
    percentileBarWidth: 62,
    percentileMarkerLeft: 62,
    percentileLabel: '62%',
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

  onReady() {
    this._pageViewReady = true
  },

  onLoad() {
    this._stockKlineChart = null
    this._klineOption = null
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
    this.updateStockUI(stockData['600519'])
    this.refreshLiveQuote('600519')
    this._loadWatchlist()
  },

  onShow() {
    if (this.data.activePage === 'chat') {
      this._layoutChatArea()
    }
  },

  switchPage(pageId) {
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
      this.setData({ chatInputFocus: false })
      this._layoutChatArea()
    }
    if (pageId === 'stock') {
      const k = resolveStockKey(this.data.stockSearchInput) || '600519'
      this.updateStockUI(this.data.currentStock)
      if (isAshare6digit(k)) this.refreshLiveQuote(k)
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
    const notes = readTopicNotes()
    const n = notes[id]
    this.setData({
      topicDetail: { ...topic, topicId: id },
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
    if (!codes.length) codes = [...WATCHLIST_DEFAULT]
    const seen = new Set(codes)
    let added = 0
    topic.stocks.forEach((s) => {
      const key = resolveStockKey(s.code)
      if (!key || seen.has(key)) return
      seen.add(key)
      codes.push(key)
      added++
    })
    if (!added) {
      wx.showToast({ title: '标的已在清单中', icon: 'none' })
      return
    }
    try {
      wx.setStorageSync(WATCHLIST_STORAGE_KEY, codes)
    } catch (e2) {}
    this.setData({ watchlistItems: buildWatchlistRows(codes) })
    wx.showToast({ title: `已加入 ${added} 只`, icon: 'success' })
  },

  onAiChatEntry() {
    this.switchPage('chat')
  },

  onBackChat() {
    this.switchPage('home')
  },

  refreshLiveQuote(key) {
    if (!isAshare6digit(key)) return
    getQuote(key)
      .then((res) => {
        if (res.code !== 200 || !res.data) {
          wx.showToast({ title: String(res.msg || '行情失败').slice(0, 18), icon: 'none' })
          const cur = resolveStockKey(this.data.stockSearchInput) || '600519'
          if (cur === key) this._loadKlineForSymbol(key)
          return
        }
        const cur = resolveStockKey(this.data.stockSearchInput) || '600519'
        if (cur !== key) return
        const merged = mergeQuoteIntoStock(stockBaseForKey(key), res)
        this.updateStockUI(merged)
        this._loadKlineForSymbol(key)
      })
      .catch(() => {
        wx.showToast({
          title: '连不上后端：真机请改局域网IP',
          icon: 'none',
          duration: 2800
        })
        const cur = resolveStockKey(this.data.stockSearchInput) || '600519'
        if (cur === key) this._loadKlineForSymbol(key)
      })
  },

  onStockQuickAsk(e) {
    const q = e.currentTarget.dataset.q
    if (!q) return
    this.switchPage('chat')
    this.setData({ chatInput: q, chatInputFocus: true })
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
    const msgs = this.data.chatMessages.concat([{ role: 'user', text }])
    const reply = buildChatReply(text, cur)
    this.setData({ chatMessages: msgs, chatInput: '' })
    setTimeout(() => {
      this.setData({ chatMessages: msgs.concat([{ role: 'ai', text: reply }]) })
    }, 320)
  },

  onStockSearchInput(e) {
    const v = e.detail.value
    this.setData({ stockSearchInput: v })
    this._scheduleStockSuggest(v)
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
    if (!key) return
    const s = stockBaseForKey(key)
    this.setData({ stockSearchInput: key, stockSuggestList: [], stockSuggestLoading: false })
    this.updateStockUI(s)
    if (isAshare6digit(key)) this.refreshLiveQuote(key)
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
        this._stockKlineChart.dispose()
      } catch (e) {}
      this._stockKlineChart = null
    }
  },

  onResetKline() {
    if (!this._stockKlineChart || !this._klineOption) return
    const dz = this._klineOption.dataZoom
    const first = Array.isArray(dz) ? dz[0] : dz
    const start = first && first.start != null ? first.start : 0
    const end = first && first.end != null ? first.end : 100
    try {
      this._stockKlineChart.dispatchAction({ type: 'dataZoom', start, end })
    } catch (e) {}
  },

  _loadKlineForSymbol(code6) {
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
    this.setData({ klinePlaceholderText: '加载K线…' })
    getStockDailyBars(c)
      .then((res) => {
        if (res.code !== 200 || !res.data) {
          this._disposeKlineChartIfAny()
          this.setData({
            klineShowEcharts: false,
            klinePlaceholderText: String(res.msg || 'K线失败').slice(0, 24)
          })
          return
        }
        const d = res.data
        if (!d.dates || !d.candle || !d.dates.length) {
          this._disposeKlineChartIfAny()
          this.setData({ klineShowEcharts: false, klinePlaceholderText: '无K线数据' })
          return
        }
        this._klineOption = buildStockKlineOption(d)
        const cur = this.data.currentStock || {}
        const merged = {
          ...cur,
          high: d.high_52w,
          low: d.low_52w,
          percentile: Math.round(d.percentile)
        }
        const p = Math.round(d.percentile)
        this.setData({
          klineShowEcharts: true,
          klinePlaceholderText: '',
          currentStock: merged,
          high52w: `¥${d.high_52w}`,
          low52w: `¥${d.low_52w}`,
          percentileText: `${p}%`,
          percentileBarWidth: p,
          percentileMarkerLeft: Math.min(100, Math.max(0, p)),
          percentileLabel: `${p}%`,
          percentileSub: p > 50 ? '中位偏上' : '中位偏下'
        })
        const run = () => this._ensureKlineChart()
        if (typeof wx.nextTick === 'function') wx.nextTick(run)
        else setTimeout(run, 50)
      })
      .catch(() => {
        this._disposeKlineChartIfAny()
        this.setData({
          klineShowEcharts: false,
          klinePlaceholderText: '网络错误，无法加载K线'
        })
      })
  },

  _ensureKlineChart() {
    if (!this._klineOption) return
    const com = this.selectComponent('#stock-kline-ec')
    if (!com) return
    const echartsLib = require('../../components/ec-canvas/echarts.min.js')
    if (this._stockKlineChart) {
      try {
        this._stockKlineChart.setOption(this._klineOption, true)
      } catch (e) {}
      return
    }
    com.init((canvas, width, height, dpr) => {
      const chart = echartsLib.init(canvas, null, { width, height, devicePixelRatio: dpr })
      chart.setOption(this._klineOption)
      this._stockKlineChart = chart
      return chart
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
    const code = String(e.currentTarget.dataset.code || '')
    const s = stockData[code]
    if (!s) return
    this.setData({ stockSearchInput: code })
    this.updateStockUI(s)
    if (isAshare6digit(code)) this.refreshLiveQuote(code)
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
      wx.showToast({ title: '未找到（请用代码或内置名称）', icon: 'none' })
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
          earningsFileName: name,
          earningsHtml:
            '🤖 综合解读（示例）：收入与利润增速匹配度较好；毛利率处于需同业对照区间；若接入真实解析，将在上表逐项自动勾选并引用报表附注位置。'
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
    let detail
    if (stock.open != null && stock.high != null && stock.low != null) {
      detail = `今开${stock.open} 最高${stock.high} 最低${stock.low}`
    } else {
      const openPrice = (stock.price * (1 - stock.change / 100)).toFixed(2)
      detail = `今开${openPrice} 最高${(stock.price * 1.02).toFixed(2)} 最低${(stock.price * 0.98).toFixed(2)}`
    }
    const pctLabel = stock.change >= 0 ? `+${stock.change}%` : `${stock.change}%`
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
      percentileBarWidth: stock.percentile,
      percentileMarkerLeft: Math.min(100, Math.max(0, stock.percentile)),
      percentileLabel: `${stock.percentile}%`,
      percentileSub: stock.percentile > 50 ? '中位偏上' : '中位偏下',
      trendText: stock.trend,
      volText: stock.volatility,
      aiInsightList: stock.insight,
      suggestionList: stock.suggestion
    })
  }
})
