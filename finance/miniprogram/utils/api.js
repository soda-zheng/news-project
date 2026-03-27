const API_BASE = 'http://127.0.0.1:5000'

function makeUrl(path) {
  const p = String(path || '')
  if (!p) return API_BASE
  return p.startsWith('http') ? p : `${API_BASE}${p.startsWith('/') ? p : `/${p}`}`
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
  API_BASE,
  getHotTopics,
  getHomeNews,
  getQuote,
  postStockInsight,
  postResearchAnalyze,
  uploadPdf,
  startAnalyze,
  getTask
}
