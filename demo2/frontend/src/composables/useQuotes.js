import { reactive } from 'vue'
import { getCoreQuotes } from '../api/client'

export function useQuotes() {
  const markets = reactive([
    { name: '人民币/美元', price: 0, chg: 0, pct_chg: 0 },
    { name: '现货黄金', price: 0, chg: 0, pct_chg: 0 },
    { name: 'WTI原油', price: 0, chg: 0, pct_chg: 0 },
    { name: '上证指数', price: 0, chg: 0, pct_chg: 0 },
    { name: '深证成指', price: 0, chg: 0, pct_chg: 0 },
    { name: '创业板指', price: 0, chg: 0, pct_chg: 0 },
  ])

  let timer = null

  async function refreshQuotes() {
    try {
      const json = await getCoreQuotes()
      if (json.code !== 200) return
      const quotes = json.data?.quotes || []
      const map = new Map(quotes.map((q) => [q.name, q]))
      for (const m of markets) {
        let q = map.get(m.name)
        // 兼容旧版接口名「COMEX黄金」
        if (!q && m.name === '现货黄金') q = map.get('COMEX黄金')
        if (!q) continue
        m.price = q.price
        m.chg = q.chg ?? 0
        m.pct_chg = q.pct_chg ?? 0
      }
    } catch (e) {
      console.error('刷新行情失败：', e)
    }
  }

  function start() {
    void refreshQuotes()
    timer = setInterval(() => void refreshQuotes(), 1000)
  }
  function stop() {
    if (timer) clearInterval(timer)
  }

  return { markets, refreshQuotes, start, stop }
}

