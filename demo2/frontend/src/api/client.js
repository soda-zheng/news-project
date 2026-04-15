/**
 * API 根地址：
 * - 默认始终直连 http://127.0.0.1:5000（与 Flask CORS 配合），避免依赖 Vite 代理；
 *   部分环境下代理未转发 POST，会出现 /api/topics/* 的 HTTP 404。
 * - 若必须用开发代理：在 frontend/.env.local 写 VITE_API_RELATIVE=1
 * - 部署线上：构建前设置 VITE_API_BASE_URL=https://你的后端域名
 */
function apiOrigin() {
  if (import.meta.env.VITE_API_RELATIVE === '1' || import.meta.env.VITE_API_RELATIVE === 'true') {
    return ''
  }
  const raw = import.meta.env.VITE_API_BASE_URL
  if (typeof raw === 'string' && raw.trim() !== '') {
    return raw.trim().replace(/\/$/, '')
  }
  return 'http://127.0.0.1:5000'
}

export function apiUrl(path) {
  const p = path.startsWith('/') ? path : `/${path}`
  const o = apiOrigin()
  return o ? `${o}${p}` : p
}

/** B 站封面 CDN 禁止热链时，经后端 /api/video-cover 带 Referer 拉取 */
export function resolveVideoCoverUrl(cover) {
  const c = String(cover || '').trim()
  if (!c) {
    return apiUrl('/api/video-cover?src=')
  }
  const lower = c.toLowerCase()
  if (
    lower.includes('hdslb.com') ||
    lower.includes('bfs/archive') ||
    (lower.startsWith('http') && lower.includes('bilibili') && lower.includes('bfs'))
  ) {
    return apiUrl(`/api/video-cover?${new URLSearchParams({ src: c })}`)
  }
  // 部分网络直连 picsum 不稳定，统一走后端代理
  if (lower.includes('picsum.photos')) {
    return apiUrl(`/api/video-cover?${new URLSearchParams({ src: c })}`)
  }
  return c
}

async function getJson(path) {
  const resp = await fetch(apiUrl(path))
  return resp.json()
}

async function postJson(path, body, fetchOpts = {}) {
  const resp = await fetch(apiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
    signal: fetchOpts.signal,
  })
  const text = await resp.text()
  if (!text) {
    return { code: resp.ok ? 500 : resp.status, msg: '接口返回空内容', data: null }
  }
  try {
    return JSON.parse(text)
  } catch {
    return {
      code: 500,
      msg: `接口返回非 JSON（HTTP ${resp.status}）`,
      data: null,
    }
  }
}

export function getCoreQuotes() {
  return getJson('/api/core-quotes')
}

export function convertFx({ amount, from, to }) {
  const qs = new URLSearchParams({
    amount: String(amount),
    from: String(from),
    to: String(to),
  })
  return getJson(`/api/convert?${qs.toString()}`)
}

export function getFxCurrencies() {
  return getJson('/api/fx/currencies')
}

export function queryStock(symbol) {
  const qs = new URLSearchParams({ symbol: String(symbol) })
  return getJson(`/api/stock?${qs.toString()}`)
}

export function queryQuote(symbol) {
  const qs = new URLSearchParams({ symbol: String(symbol) })
  return getJson(`/api/quote?${qs.toString()}`)
}

export function getQuoteCandidates(q) {
  const qs = new URLSearchParams({ q: String(q || '') })
  return getJson(`/api/quote-candidates?${qs.toString()}`)
}

export function getHotTopics({ limit = 10 } = {}) {
  const qs = new URLSearchParams({ limit: String(limit) })
  return getJson(`/api/topics/hot?${qs.toString()}`)
}

/** 大模型个股解读（无 LLM 配置时后端回退模板文案） */
export function postTopicsStockInsight(payload, fetchOpts) {
  return postJson('/api/topics/stock-insight', payload, fetchOpts)
}

/** 盘面综述要点（基于当前榜单样本，后端可选用语言模型） */
export function postTopicsBoardInsight(payload, fetchOpts) {
  return postJson('/api/topics/board-insight', payload, fetchOpts)
}

/** 智能投研分析：基于行情快照与热点样本生成结构化研判 */
export function postResearchAnalyze(payload, fetchOpts) {
  return postJson('/api/research/analyze', payload, fetchOpts)
}

export function getResearchTask(taskId) {
  return getJson(`/api/research/tasks/${encodeURIComponent(String(taskId || ''))}`)
}

export function createResearchTaskStream() {
  return new EventSource(apiUrl('/api/research/tasks/stream'))
}

export function getResearchChatSessions({ limit = 50 } = {}) {
  const qs = new URLSearchParams({ limit: String(limit) })
  return getJson(`/api/research/chat/sessions?${qs.toString()}`)
}

export function getResearchChatSessionMessages(sessionId) {
  return getJson(`/api/research/chat/sessions/${encodeURIComponent(String(sessionId || ''))}`)
}

export async function deleteResearchChatSession(sessionId) {
  const resp = await fetch(apiUrl(`/api/research/chat/sessions/${encodeURIComponent(String(sessionId || ''))}`), {
    method: 'DELETE',
  })
  return await resp.json()
}

export function getHomeNews({ page = 1, num = 20 } = {}) {
  const qs = new URLSearchParams({ page: String(page), num: String(num) })
  return getJson(`/api/news/home?${qs.toString()}`)
}

export function getVideos() {
  return getJson('/api/videos')
}

/**
 * 财报分析（迁移自 analystgpt-demo）
 * 这组接口返回结构化 JSON（不使用 {code,msg,data} 包装），因此这里单独实现 jsonFetch：
 * - POST /api/upload
 * - POST /api/analyze
 * - GET  /api/tasks/:taskId
 * - POST /api/regen
 */
async function jsonFetch(path, init) {
  const resp = await fetch(apiUrl(path), init)
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`HTTP ${resp.status} ${resp.statusText}${text ? `: ${text}` : ''}`)
  }
  return await resp.json()
}

export async function uploadPdf(file) {
  const form = new FormData()
  form.append('file', file)
  return await jsonFetch('/api/upload', { method: 'POST', body: form })
}

export async function startAnalyze(sessionId) {
  return await jsonFetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId }),
  })
}

export async function getTask(taskId) {
  return await jsonFetch(`/api/tasks/${encodeURIComponent(taskId)}`)
}

export async function regenPage(args) {
  return await jsonFetch('/api/regen', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  })
}
