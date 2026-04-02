const { getApiBase, DEFAULT_API_BASE } = require('./config')

function makeUrl(path) {
  const base = getApiBase()
  const p = String(path || '')
  if (!p) return base
  return p.startsWith('http') ? p : `${base}${p.startsWith('/') ? p : `/${p}`}`
}

function requestJson({ url, method = 'GET', data, timeout = 12000 }) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: makeUrl(url),
      method,
      data,
      timeout,
      success: (res) => {
        const body = res.data
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(body || {})
          return
        }
        reject(new Error(`HTTP ${res.statusCode}`))
      },
      fail: (err) => reject(err || new Error('request failed'))
    })
  })
}

function getHotTopics(limit = 10) {
  return requestJson({ url: `/api/topics/hot?limit=${encodeURIComponent(String(limit || 10))}` })
}

function getHomeNews(page = 1, num = 6) {
  return requestJson({
    url: `/api/news/home?page=${encodeURIComponent(String(page || 1))}&num=${encodeURIComponent(String(num || 6))}`
  })
}

function getQuote(symbol) {
  return requestJson({ url: `/api/stock?symbol=${encodeURIComponent(String(symbol || ''))}` })
}

/** A 股：按代码或名称子串搜索，全市场列表在后端缓存 */
function searchStocks(q, limit = 30) {
  const qs = `q=${encodeURIComponent(String(q || '').trim())}&limit=${encodeURIComponent(String(limit || 30))}`
  return requestJson({ url: `/api/stock/search?${qs}` })
}

/** A 股市场总貌：上交所 stock_sse_summary + 深交所 stock_szse_summary（需安装 akshare） */
function getMarketAOverview() {
  return requestJson({ url: '/api/market/a-overview' })
}

/** A 股日线：OHLCV + 日期，供 ECharts K 线 */
function getStockDailyBars(symbol) {
  // K 线接口可能涉及抓取较多历史数据：放宽超时避免前端请求直接 timeout
  return requestJson({
    url: `/api/stock/daily-bars?symbol=${encodeURIComponent(String(symbol || ''))}`,
    timeout: 30000
  })
}

function postStockInsight(payload) {
  return requestJson({ url: '/api/topics/stock-insight', method: 'POST', data: payload || {} })
}

function postResearchAnalyze(payload) {
  return requestJson({ url: '/api/research/analyze', method: 'POST', data: payload || {} })
}

function uploadPdf(filePath, name = 'report.pdf') {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: makeUrl('/api/upload'),
      filePath,
      name: 'file',
      formData: {},
      timeout: 30000,
      success: (res) => {
        try {
          const body = JSON.parse(res.data || '{}')
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(body)
            return
          }
          reject(new Error(body.error || `HTTP ${res.statusCode}`))
        } catch (e) {
          reject(new Error('上传响应解析失败'))
        }
      },
      fail: (err) => reject(err || new Error('upload failed'))
    })
  })
}

function startAnalyze(sessionId) {
  return requestJson({ url: '/api/analyze', method: 'POST', data: { sessionId } })
}

function getTask(taskId) {
  return requestJson({ url: `/api/tasks/${encodeURIComponent(String(taskId || ''))}` })
}

module.exports = {
  get API_BASE() {
    return getApiBase()
  },
  DEFAULT_API_BASE,
  getHotTopics,
  getHomeNews,
  getQuote,
  searchStocks,
  getMarketAOverview,
  getStockDailyBars,
  postStockInsight,
  postResearchAnalyze,
  uploadPdf,
  startAnalyze,
  getTask
}
