import { computed, ref } from 'vue'
import { getHotTopics } from '../api/client'

export function useHotTopics() {
  const hotTopics = ref([])
  const hotTopicsMore = ref([])
  let timer = null

  async function refreshTop10() {
    try {
      const json = await getHotTopics({ limit: 10 })
      if (json.code !== 200) return
      hotTopics.value = (json.data?.items || []).slice(0, 10)
    } catch (e) {
      console.error('刷新热门榜失败：', e)
    }
  }

  async function loadMore(limit = 50) {
    try {
      const json = await getHotTopics({ limit })
      if (json.code !== 200) return
      hotTopicsMore.value = json.data?.items || []
    } catch (e) {
      console.error('加载更多涨幅榜失败：', e)
    }
  }

  const hotTopicsAnalysis = computed(() => {
    const arr = (hotTopicsMore.value || []).filter((x) => Number.isFinite(Number(x?.pct_chg)))
    if (!arr.length) return { title: '盘面综述', bullets: ['暂无可分析数据，稍后自动刷新。'] }
    const pcts = arr.map((x) => Number(x.pct_chg))
    const avg = pcts.reduce((a, b) => a + b, 0) / pcts.length
    const top3 = pcts.slice(0, 3).reduce((a, b) => a + b, 0) / 3
    const strongCnt = pcts.filter((v) => v >= 7).length
    const weakCnt = pcts.filter((v) => v < 4).length
    const spread = pcts[0] - pcts[pcts.length - 1]
    const leader = arr[0]?.name || '龙头'
    const heatText = avg >= 6 ? '情绪偏强，短线追高需控制仓位' : (avg >= 4.5 ? '强势扩散中，优先看量价配合' : '分化明显，建议聚焦前排')
    return {
      title: '盘面综述',
      bullets: [
        `榜首为「${leader}」，前3平均涨幅 ${top3.toFixed(2)}%。`,
        `全榜平均涨幅 ${avg.toFixed(2)}%，强势股（>=7%）${strongCnt} 只，偏弱股（<4%）${weakCnt} 只。`,
        `首尾涨幅差 ${spread.toFixed(2)}%，${heatText}。`,
      ],
    }
  })

  function start() {
    void refreshTop10()
    timer = setInterval(() => void refreshTop10(), 30000)
  }
  function stop() { if (timer) clearInterval(timer) }

  return { hotTopics, hotTopicsMore, hotTopicsAnalysis, refreshTop10, loadMore, start, stop }
}

