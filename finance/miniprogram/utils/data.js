/** 无本地演示行情：仅占位，名称与价格以服务端 / getQuote 为准 */
function stockShell(code) {
  const raw = String(code || '').trim()
  const m = raw.match(/(\d{6})/)
  const c = m ? m[1] : ''
  return {
    code: c || '',
    name: c ? c : '未选择',
    fullName: c ? `${c}` : '未选择股票',
    price: '¥--',
    info: '连接后端后显示',
    high: '',
    low: '',
    level: '—',
    trend: '—',
    vol: '—',
    ai: [],
    news: [],
    suggest: []
  }
}

const stockData = {}

// demo2 数据结构参考：热点榜 items: { name, leader, pct_chg }
const hotTopicsTop10 = [
  { name: '动力电池', leader: '300750', pct_chg: 9.8 },
  { name: '汽车零部件', leader: '002594', pct_chg: 8.91 },
  { name: '白酒龙头', leader: '600519', pct_chg: 6.42 },
  { name: 'AI算力', leader: '300308', pct_chg: 5.88 },
  { name: '机器人', leader: '300024', pct_chg: 5.41 },
  { name: '半导体', leader: '688981', pct_chg: 4.99 },
  { name: '储能', leader: '300274', pct_chg: 4.72 },
  { name: '消费电子', leader: '300136', pct_chg: 4.37 },
  { name: '高端制造', leader: '600031', pct_chg: 4.06 },
  { name: '中特估', leader: '601668', pct_chg: 3.84 }
]

// demo2 首页新闻结构参考（做成简约列表）
const featuredNews = [
  { id: 'n1', title: '新能源产业链景气延续，机构关注盈利修复', category: '市场快讯', ctime: 0, summary: '关注上游原材料波动与下游需求弹性。' },
  { id: 'n2', title: '白酒板块出现修复，龙头成交额提升', category: '财联观察', ctime: 0, summary: '旺季预期与估值修复共同驱动。' },
  { id: 'n3', title: '政策端再提科技创新，硬科技方向活跃', category: '投研日报', ctime: 0, summary: '聚焦业绩与订单兑现，避免纯概念。' }
]

const hotTags = ['新能源', '白酒消费', '新能源车', '政策利好', '高股息']

const watchList = [
  { code: '300750', tip: '偏低位置 · 震荡回升' },
  { code: '600519', tip: '中位偏上 · 稳步上行' },
  { code: '002594', tip: '中位偏低 · 区间震荡' }
]

const reportTips = [
  '支持上传 PDF 财报做结构化解读（后续可接入后端）。',
  '输出建议包含：盈利质量、现金流、风险项、估值观察。',
  '当前版本为本地静态演示，先把交互与UI跑通。'
]

const profileMenus = ['账户与安全', '提醒设置', '主题外观', '关于应用']

module.exports = {
  stockData,
  stockShell,
  hotTopicsTop10,
  featuredNews,
  hotTags,
  watchList,
  reportTips,
  profileMenus
}

