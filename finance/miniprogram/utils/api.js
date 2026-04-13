const { getApiBase, DEFAULT_API_BASE } = require('./config')

function makeUrl(path) {
  const base = getApiBase()
  const p = String(path || '')
  if (!p) return base
  return p.startsWith('http') ? p : `${base}${p.startsWith('/') ? p : `/${p}`}`
}

/** 微信 fail 回调多为 { errMsg }，无 message；避免界面出现 [object Object] */
function formatApiError(e, fallback = '请求失败') {
  if (e == null || e === false) return fallback
  if (typeof e === 'string') return e
  if (e instanceof Error && e.message) return e.message
  if (typeof e.errMsg === 'string' && e.errMsg) return e.errMsg
  if (typeof e.message === 'string' && e.message) return e.message
  if (typeof e.error === 'string') return e.error
  try {
    const s = JSON.stringify(e)
    if (s && s !== '{}') return s
  } catch (_) {}
  return fallback
}

/**
 * 针对「连不上 Flask」的常见报错补充可操作说明（ECONNREFUSED / 127.0.0.1）。
 */
function explainBackendConnectionError(message) {
  const s = String(message || '').trim()
  if (!s) return s
  const refuse = /ECONNREFUSED|connection refused|连接被拒绝/i.test(s)
  const local = /127\.0\.0\.1|localhost/i.test(s)
  if (refuse && local) {
    return (
      `${s}\n\n` +
      '【处理办法】\n' +
      '1）开发者工具模拟器：先在电脑启动后端（finance/backend 目录执行启动命令，监听 5000 端口）。\n' +
      '2）真机预览 / 手机：127.0.0.1 是手机本机，不是你的电脑。请把电脑连同一 WiFi，查电脑局域网 IP（如 192.168.x.x），' +
      '在开发者工具控制台执行：wx.setStorageSync("finance_api_base","http://192.168.x.x:5000") 后再预览；并确认 Windows 防火墙允许 5000 端口入站。\n' +
      '3）仍失败：检查小程序后台「开发」里是否勾选不校验合法域名（仅调试），以及后端是否为 host=0.0.0.0。'
    )
  }
  if (refuse) {
    return `${s}\n\n【处理办法】请确认 API 地址（getApiBase）与后端 IP、端口一致，且后端进程已启动。`
  }
  return s
}

function requestJson({ url, method = 'GET', data, timeout = 12000 }) {
  return new Promise((resolve, reject) => {
    const m = String(method || 'GET').toUpperCase()
    const req = {
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
        let msg = `HTTP ${res.statusCode}`
        if (body && typeof body === 'object' && body.error != null) {
          msg =
            typeof body.error === 'string'
              ? body.error
              : formatApiError(body.error, msg)
        } else if (typeof body === 'string' && body.trim()) {
          msg = body.trim().slice(0, 240)
        }
        reject(new Error(msg))
      },
      fail: (err) => reject(new Error(formatApiError(err, '网络请求失败')))
    }
    if (m === 'POST' || m === 'PUT' || m === 'PATCH') {
      req.header = { 'Content-Type': 'application/json' }
    }
    wx.request(req)
  })
}

function getHotTopics(limit = 10, source = 'auto', strict = false) {
  return requestJson({
    url: `/api/topics/hot?limit=${encodeURIComponent(String(limit || 10))}&source=${encodeURIComponent(String(source || 'auto'))}&strict=${strict ? '1' : '0'}`,
    timeout: 150000
  })
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

function postStockLLMInsight(payload) {
  return requestJson({ url: '/api/research/stock-llm-insight', method: 'POST', data: payload || {}, timeout: 90000 })
}

function postResearchAnalyze(payload) {
  return requestJson({ url: '/api/research/analyze', method: 'POST', data: payload || {}, timeout: 90000 })
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
          reject(
            new Error(
              body && typeof body.error === 'string'
                ? body.error
                : formatApiError(body && body.error, `HTTP ${res.statusCode}`)
            )
          )
        } catch (e) {
          reject(new Error('上传响应解析失败'))
        }
      },
      fail: (err) => reject(new Error(formatApiError(err, '上传失败')))
    })
  })
}

function startAnalyze(sessionId) {
  return requestJson({ url: '/api/analyze', method: 'POST', data: { sessionId }, timeout: 30000 })
}

function getTask(taskId) {
  return requestJson({ url: `/api/tasks/${encodeURIComponent(String(taskId || ''))}` })
}

function regenPage(payload) {
  return requestJson({ url: '/api/regen', method: 'POST', data: payload || {}, timeout: 30000 })
}

function getBaiduStockRssNews(limit = 20) {
  return requestJson({ url: `/api/news/baidu-rss?limit=${encodeURIComponent(String(limit || 20))}` })
}

function getAggregateNews(limit = 30, category = '') {
  let url = `/api/news/aggregate?limit=${encodeURIComponent(String(limit || 30))}`
  if (category) url += `&category=${encodeURIComponent(String(category))}`
  return requestJson({ url })
}

function getStockNews(symbol, limit = 10) {
  return requestJson({
    url: `/api/news/stock?symbol=${encodeURIComponent(String(symbol || ''))}&limit=${encodeURIComponent(String(limit || 10))}`
  })
}

function getHomeNewsEnhanced(limit = 10, region = 'all') {
  let url = `/api/news/home-enhanced?limit=${encodeURIComponent(String(limit || 10))}`
  const r = String(region || 'all').trim()
  if (r && r !== 'all') url += `&region=${encodeURIComponent(r)}`
  return requestJson({
    url,
    timeout: 300000
  })
}

function postNewsAiAnalyze(payload) {
  return requestJson({
    url: '/api/news/ai-analyze',
    method: 'POST',
    data: payload || {},
    timeout: 300000
  })
}

module.exports = {
  get API_BASE() {
    return getApiBase()
  },
  DEFAULT_API_BASE,
  formatApiError,
  explainBackendConnectionError,
  getHotTopics,
  getHomeNews,
  getQuote,
  searchStocks,
  getMarketAOverview,
  getStockDailyBars,
  postStockInsight,
  postStockLLMInsight,
  postResearchAnalyze,
  uploadPdf,
  startAnalyze,
  getTask,
  regenPage,
  getBaiduStockRssNews,
  getAggregateNews,
  getStockNews,
  getHomeNewsEnhanced,
  postNewsAiAnalyze
}
